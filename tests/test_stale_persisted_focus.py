import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_stale_persisted_focus.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = FakeQuery(uid, data) if data is not None else None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    bot._morning_conv = None
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (reported by Artem: "третий день подряд подтягиваются одни и
    # те же задачи на день из прошлого"): the bot uses PicklePersistence,
    # so ctx.user_data survives restarts indefinitely. Users who were around
    # before the M_FOCUS/M_B1/... step-by-step ritual was removed still have
    # ancient "m_focus"/"m_b1" etc. values sitting in their persisted
    # user_data from that old flow. _merged_task_fields used to read those
    # via `ctx.user_data.get(f"m_{key}") or existing.get(key, "")` -- since
    # nothing clears/overwrites them anymore, that stale truthy value won
    # over fresh DB content on every single finish_morning call, forever.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    # Simulate exactly that: leftover state from a years-old session, as if
    # loaded straight from the pickle persistence file.
    ctx.user_data["m_focus"] = "Накатить обновления. Посмотреть что с ботом и оплатами"
    ctx.user_data["m_b1"] = "Написать описание батончиков для продавцов"

    # Set today's REAL, fresh, different tasks the normal way (via 📋 Задачи).
    msg = FakeMsg()
    await bot.apply_task_edit(msg, ctx, uid, "focus", "Совсем другая задача на сегодня")

    # Now run the morning ritual (⚡ Быстро) -- this must NOT resurrect the
    # ancient ctx.user_data value over what was just freshly set.
    upd = FakeUpdate(uid, data="morning_quick")
    await bot.morning_quick(upd, ctx)
    morning = bot.get_diary(uid, "morning", today)
    assert morning.get("focus") == "Совсем другая задача на сегодня", \
        f"stale persisted ctx.user_data['m_focus'] must NOT override today's real task, got {morning}"
    print("1. finish_morning no longer lets ancient persisted ctx.user_data['m_focus'] override today's real task")

    # ══════════════════════════════════════════════════════════════════════
    # And on a day where NOTHING has been set yet via 📋 Задачи, the stale
    # ctx.user_data value must not resurrect itself as "today's task" either
    # -- it must show correctly as unset.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Виктория', 'F')")
    conn.commit(); conn.close()
    uid2 = 2
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    ctx2 = FakeCtx()
    ctx2.user_data["m_focus"] = "Древняя задача из давно снесённого шага ритуала"
    upd2 = FakeUpdate(uid2, data="morning_quick")
    await bot.morning_quick(upd2, ctx2)
    morning2 = bot.get_diary(uid2, "morning", today)
    assert morning2.get("focus", "") == "", \
        f"a genuinely empty day must stay empty, not resurrect an ancient stale value, got {morning2}"
    print("2. A genuinely empty day stays empty instead of resurrecting an ancient stale ctx.user_data value")

    # ══════════════════════════════════════════════════════════════════════
    # morning_start's fresh-day reset now proactively purges these legacy
    # keys too, so they don't linger indefinitely in persisted storage.
    # ══════════════════════════════════════════════════════════════════════
    ctx3 = FakeCtx()
    ctx3.user_data["m_focus"] = "Ещё один протухший обрывок"
    upd3 = FakeUpdate(uid2, data="go_morning")
    await bot.morning_start(upd3, ctx3)
    assert "m_focus" not in ctx3.user_data, ctx3.user_data
    print("3. morning_start purges legacy m_focus/m_b1/... keys from persisted user_data on a fresh day")

    print("\nALL STALE-PERSISTED-FOCUS TESTS PASSED")


asyncio.run(main())
