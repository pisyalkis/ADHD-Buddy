import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_nightly_scan_pool_bugs.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.edited = []
        self.sent = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def seed_evening_plan(uid, for_date):
    bot.save_diary(uid, "evening", {
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_a": "Поправить переменные на кампейне",
        "e_b1": "Заполнить таблицу по ретро биржи", "e_b2": "Побегать",
        "e_c1": "Залогировать время", "e_c2": "Пожарить сердечки", "e_c3": "Стирка светлое",
        "e_selfcare": [], "e_energy": 0, "e_tasks_done": [],
    }, for_date=for_date)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug 1 (nightly scan 2026-09-01): setting ONE task via free text
    # (handle_set_task_intent -> apply_task_edit) on an otherwise empty day
    # silently materialized ALL SIX slots from yesterday's evening plan --
    # apply_task_edit called apply_yesterday_plan_if_empty itself, which
    # belongs only on "show me my whole day" screens (show_tasks/
    # morning_start/morning_task_offer_yes/walk_finish_callback), not on a
    # single-slot edit.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()
    yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    seed_evening_plan(uid, yesterday)
    assert not bot.get_diary(uid, "morning", today), "sanity: today starts empty"

    ctx = FakeCtx()
    msg = FakeMsg(uid)
    await bot.handle_set_task_intent(msg, ctx, uid, "позвонить врачу")
    morning = bot.get_diary(uid, "morning", today)
    set_fields = [k for k, _ in bot.TASK_FIELDS if morning.get(k)]
    assert set_fields == ["focus"], \
        f"only the one requested task must be set, got: {[(k, morning.get(k)) for k in set_fields]}"
    assert morning["focus"] == "позвонить врачу", morning
    print("1. handle_set_task_intent (free text, first task of the day) sets ONLY the requested task")

    # The auto-apply behavior itself is untouched on the actual "whole day"
    # screens -- sanity check show_tasks still auto-applies as before.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    seed_evening_plan(uid2, yesterday)
    upd2 = FakeUpdate(uid2)
    await bot.show_tasks(upd2, FakeCtx())
    morning2 = bot.get_diary(uid2, "morning", today)
    assert morning2.get("focus") == "Поправить переменные на кампейне", morning2
    assert morning2.get("c3") == "Стирка светлое", morning2
    print("2. show_tasks (whole-day screen) still auto-applies yesterday's full plan as before")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2 (nightly scan 2026-09-01, regression from #223): a pool item
    # could be picked for TWO different task slots at once, since the pool
    # no longer deletes the item immediately (only on ✅) and the
    # suggestions list didn't filter out items already linked elsewhere.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid3, "Купить молоко")
    item = bot.get_pool_tasks(uid3)[0]

    ctx3 = FakeCtx()
    upd3 = FakeUpdate(uid3, data=f"pooluse_b1_{item['id']}")
    await bot.pool_use_item(upd3, ctx3)
    morning3 = bot.get_diary(uid3, "morning", today)
    assert morning3.get("b1") == "Купить молоко", morning3
    assert morning3.get("_pool_link_b1") == item["id"], morning3

    # Now open suggestions for a DIFFERENT slot (c1) -- the already-linked
    # item must not be offered again.
    upd_c1 = FakeUpdate(uid3)
    ctx_c1 = FakeCtx()
    await bot._offer_task_input(upd_c1.callback_query.message, ctx_c1, uid3, "c1")
    text_c1, kb_c1 = upd_c1.callback_query.message.edited[-1] if upd_c1.callback_query.message.edited else upd_c1.callback_query.message.sent[-1]
    if kb_c1 is not None:
        flat = [b.callback_data for row in kb_c1.inline_keyboard for b in row]
        assert f"pooluse_c1_{item['id']}" not in flat, \
            f"an item already linked to another slot (b1) must not be offered for c1: {flat}"
    else:
        # No pool items left to suggest at all -- also an acceptable
        # correct outcome (falls straight to ask_task_text).
        pass
    print("3. A pool item already linked to another slot is not offered again for a different slot")

    # Editing the SAME slot again (b1) must still show it as an option --
    # not a duplicate concern, it's the same slot re-opened.
    ctx_b1 = FakeCtx()
    upd_b1 = FakeUpdate(uid3)
    await bot._offer_task_input(upd_b1.callback_query.message, ctx_b1, uid3, "b1")
    text_b1, kb_b1 = upd_b1.callback_query.message.edited[-1] if upd_b1.callback_query.message.edited else upd_b1.callback_query.message.sent[-1]
    assert kb_b1 is not None, "re-opening the same slot must still offer pool suggestions"
    flat_b1 = [b.callback_data for row in kb_b1.inline_keyboard for b in row]
    assert f"pooluse_b1_{item['id']}" in flat_b1, \
        f"re-opening the SAME slot must still offer its own already-linked item: {flat_b1}"
    print("4. Re-opening the same slot still offers its own linked item (not treated as a foreign duplicate)")

    print("\nALL NIGHTLY-SCAN-POOL-BUGS TESTS PASSED")


asyncio.run(main())
