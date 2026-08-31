import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_plan_carryover.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (Artem): "поставил задачи вчера вечером, а сегодня их
    # нет" — the evening plan (e_a/e_b1/...) was only ever echoed as a
    # reminder LINE in the morning greeting; it never became today's real
    # task list (the one the beacon/midday/coach actually look at). New:
    # morning_start now offers "✅ Взять как задачи на сегодня", and a new
    # use_yesterday_plan_callback converts the plan into real TASK_FIELDS.
    # ══════════════════════════════════════════════════════════════════════
    yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    today = datetime.now(tz).date().isoformat()
    bot.save_diary(uid, "evening", {
        "e_a": "Написать отчёт", "e_b1": "Структура канала", "e_b2": "",
        "e_c1": "Полить цветы", "e_c2": "", "e_c3": "",
    }, for_date=yesterday)

    # 1. morning_start offers the button when a real evening plan exists.
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="morning_start")
    await bot.morning_start(upd, ctx)
    all_kb_data = [b.callback_data for row in upd.callback_query.message.sent[0][1].inline_keyboard for b in row]
    assert "use_yesterday_plan" in all_kb_data, all_kb_data
    print("1. morning_start offers 'Взять как задачи на сегодня' when yesterday's evening plan has real content")

    # 2. Tapping it actually creates today's real task fields.
    upd2 = FakeUpdate(uid, data="use_yesterday_plan")
    await bot.use_yesterday_plan_callback(upd2, FakeCtx())
    morning_today = bot.get_diary(uid, "morning", today)
    assert morning_today.get("focus") == "Написать отчёт", morning_today
    assert morning_today.get("b1") == "Структура канала", morning_today
    assert morning_today.get("c1") == "Полить цветы", morning_today
    assert "Написать отчёт" in upd2.callback_query.message.last_text
    print("2. use_yesterday_plan_callback writes the evening plan into today's real task fields")

    # 3. The beacon/coach now see real tasks instead of an empty list.
    assert any(morning_today.get(k) for k, _ in bot.TASK_FIELDS)
    print("3. Today's task fields are non-empty after carry-over -- beacon/midday/coach will see real tasks")

    # 4. Doesn't clobber a task the user already set manually today.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone=tz_name)
    tz2 = bot.get_user_tz(bot.get_user(uid2))
    yesterday2 = (datetime.now(tz2).date() - timedelta(days=1)).isoformat()
    today2 = datetime.now(tz2).date().isoformat()
    bot.save_diary(uid2, "evening", {"e_a": "План из вчера"}, for_date=yesterday2)
    bot.save_diary(uid2, "morning", {"focus": "Уже поставленная своя задача"}, for_date=today2)
    upd3 = FakeUpdate(uid2, data="use_yesterday_plan")
    await bot.use_yesterday_plan_callback(upd3, FakeCtx())
    morning2 = bot.get_diary(uid2, "morning", today2)
    assert morning2.get("focus") == "Уже поставленная своя задача", \
        f"must not overwrite a task already set today, got {morning2.get('focus')!r}"
    print("4. use_yesterday_plan_callback does not clobber a task field already set today")

    # 5. No plan at all -> graceful message, no crash.
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone=tz_name)
    upd4 = FakeUpdate(uid3, data="use_yesterday_plan")
    await bot.use_yesterday_plan_callback(upd4, FakeCtx())
    assert "Переносить нечего" in upd4.callback_query.message.last_text
    print("5. use_yesterday_plan_callback handles 'no plan at all' gracefully")

    # 6. morning_start does NOT offer the button when there's no real plan.
    ctx6 = FakeCtx()
    upd6 = FakeUpdate(uid3, data="morning_start")
    await bot.morning_start(upd6, ctx6)
    all_kb_data6 = [b.callback_data for row in upd6.callback_query.message.sent[0][1].inline_keyboard for b in row]
    assert "use_yesterday_plan" not in all_kb_data6, all_kb_data6
    print("6. morning_start does not offer the button when there's no real evening plan")

    # ══════════════════════════════════════════════════════════════════════
    # Sanity: the "все задачи дня уже сделаны" false-completion fix from the
    # just-merged PR #135 is live on main -- the exact bug Artem hit live.
    # ══════════════════════════════════════════════════════════════════════
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Четвёртый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid4, timezone=tz_name)
    today4 = datetime.now(bot.get_user_tz(bot.get_user(uid4))).date().isoformat()
    bot.save_diary(uid4, "morning", {k: "" for k in bot.TASK_KEYS}, for_date=today4)
    ctx_mid = FakeCtx()
    upd_mid = FakeUpdate(uid4, data="mid_nostart")
    await bot.midday_callback(upd_mid, ctx_mid)
    mid_text = upd_mid.callback_query.message.last_text
    assert "уже сделаны" not in mid_text, mid_text
    print("7. Sanity: the merged PR #135 fix (midday_callback false completion claim) is live on main")

    print("\nALL EVENING-PLAN-CARRYOVER TESTS PASSED")


asyncio.run(main())
