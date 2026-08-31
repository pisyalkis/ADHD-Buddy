import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_walk_start_first_empty.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = 1
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


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


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real report: "он всегда начинает с А и нужно пропускать до нужной
    # задачи" -- A and B1 already set, only B2 onwards is actually empty.
    # walk_tasks_start must jump straight to B2, not force a "Пропустить"
    # tap through A and B1 first.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Сделать отчёт", "b1": "Позвонить маме"}, for_date=today)

    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="walk_tasks")
    await bot.walk_tasks_start(upd, ctx)

    sent_text = upd.callback_query.message.sent[0][0]
    assert "B2" in sent_text, sent_text
    assert "Введи текст задачи" in sent_text, \
        f"must go straight to asking for B2's text (first empty slot), got: {sent_text}"
    print("1. walk_tasks_start jumps straight to the first EMPTY slot (B2), skipping already-filled A/B1")

    # Sanity: no pool exists, so this went through ask_task_text directly
    # rather than offering pool suggestions -- either is fine, just confirm
    # it's not the "Пропустить/Поменять/Убрать/Готово" review screen for A.
    assert not any("Пропустить" in (t or "") for t, _ in upd.callback_query.message.sent), \
        "must not show the already-filled A's review screen first"
    print("2. Does not show A's review/skip screen at all")

    # ══════════════════════════════════════════════════════════════════════
    # Regression: all six slots already filled -- nothing left to jump to,
    # so the walk still starts from A for a full review, same as before.
    # ══════════════════════════════════════════════════════════════════════
    full = {k: f"дело {k}" for k, _ in bot.TASK_FIELDS}
    bot.save_diary(uid, "morning", full, for_date=today)

    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid, data="walk_tasks")
    await bot.walk_tasks_start(upd2, ctx2)
    sent_text2 = upd2.callback_query.message.sent[0][0]
    assert "A" in sent_text2 and "дело focus" in sent_text2, sent_text2
    kb2 = upd2.callback_query.message.sent[0][1]
    assert ("➡️ Пропустить", "walk_skip_focus") in buttons_of(kb2), buttons_of(kb2)
    print("3. When all six slots are already filled, the walk still starts from A for a full review (unchanged)")

    print("\nALL WALK-START-FIRST-EMPTY TESTS PASSED")


asyncio.run(main())
