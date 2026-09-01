import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_walk_progress_summary.db")
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


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request: "в процессе постановки задач можно ли сделать так,
    # чтобы поставленные задачи появлялись в верхушке сообщения?" -- each
    # step of the sequential task-setting walk only showed the CURRENT
    # slot, with no way to see what was already decided a few steps back
    # without leaving the walk. Now every walk step (empty-slot prompt,
    # pool-suggestions prompt, and an already-filled slot's own screen)
    # prefixes a short "📋 Уже поставлено" summary of the other set slots.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Отправить письмо", "b1": "Смета для темплейта"}, for_date=today)

    ctx = FakeCtx()
    ctx.user_data["task_walk"] = True
    msg = FakeMsg(uid)

    # 1. Walking onto an EMPTY slot (b2) shows the progress summary (A, B1)
    # above the "введи текст"/pool-suggestions prompt.
    await bot._walk_to_step(msg, ctx, uid, "b2")
    text, kb = msg.edited[-1]
    assert "📋 Уже поставлено" in text, text
    assert "✅ A: Отправить письмо" in text, text
    assert "✅ B1: Смета для темплейта" in text, text
    print("1. Walking onto an empty slot shows a progress summary of already-set tasks")

    # 2. Walking onto an ALREADY-FILLED slot (focus/A) shows the OTHER set
    # tasks (B1) in the summary, but does not duplicate A itself (A is
    # already the main content of this screen).
    await bot._walk_to_step(msg, ctx, uid, "focus")
    text2, kb2 = msg.edited[-1]
    assert "📋 Уже поставлено" in text2, text2
    assert "✅ B1: Смета для темплейта" in text2, text2
    assert text2.count("Отправить письмо") == 1, \
        f"the current slot's own text must appear once (as the main content), not duplicated in the summary: {text2}"
    print("2. Walking onto an already-filled slot shows other tasks, without duplicating itself")

    # 3. No tasks set at all -> no summary header at all (nothing to show).
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Новый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    ctx2 = FakeCtx()
    ctx2.user_data["task_walk"] = True
    msg2 = FakeMsg(uid2)
    await bot._walk_to_step(msg2, ctx2, uid2, "focus")
    text3, kb3 = msg2.edited[-1]
    assert "Уже поставлено" not in text3, text3
    print("3. No summary header appears when nothing is set yet")

    # 4. Outside the walk (single-slot edit), no summary is shown -- keeps
    # that screen minimal, unchanged from before.
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Одиночный', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    today3 = datetime.now(bot.get_user_tz(bot.get_user(uid3))).date().isoformat()
    bot.save_diary(uid3, "morning", {"focus": "Задача A"}, for_date=today3)
    ctx3 = FakeCtx()  # no task_walk flag -- single-slot edit path
    upd3 = FakeUpdate(uid3, data="edit_task_b1")
    await bot.edit_task_callback(upd3, ctx3)
    text4, kb4 = upd3.callback_query.message.edited[-1] if upd3.callback_query.message.edited else upd3.callback_query.message.sent[-1]
    assert "Уже поставлено" not in text4, text4
    print("4. Outside the walk (single-slot edit), no summary is shown")

    print("\nALL WALK-PROGRESS-SUMMARY TESTS PASSED")


asyncio.run(main())
