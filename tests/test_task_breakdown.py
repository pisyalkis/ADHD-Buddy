import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_breakdown.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = 900
        self.text = ""

    async def reply_text(self, text, **kw):
        m = FakeMessage(self.chat_id)
        m.text = text
        return m

    async def edit_text(self, text, **kw):
        self.text = text
        return self


class FakeQuery:
    def __init__(self, uid, message):
        self.from_user = FakeUser(uid); self.message = message
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, message)
        self.message = message


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-26): breaking a task into steps only
    # existed as a static article and a coach hint -- no button to hand the
    # ALREADY-TYPED task text straight to the coach. "🔧 Разбей на шаги" on
    # the tasks screen (only when there's something undone) does exactly
    # that via task_breakdown_callback, reusing send_coach.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = datetime.now(TBILISI).date().isoformat()

    # 1. _tasks_text_and_kb shows NO breakdown button when there are no
    #    tasks at all (nothing to break down).
    text0, kb0 = bot._tasks_text_and_kb({}, set(), "M")
    assert "task_breakdown" not in kb_callbacks(kb0), kb_callbacks(kb0)
    print("1. _tasks_text_and_kb shows no breakdown button when there are no tasks")

    # 2. Once a task is set, the breakdown button appears.
    bot.save_diary(uid, "morning", {"focus": "Разобрать почту"}, for_date=today)
    morning = bot.get_diary(uid, "morning", today)
    text1, kb1 = bot._tasks_text_and_kb(morning, set(), "M")
    assert "task_breakdown" in kb_callbacks(kb1), kb_callbacks(kb1)
    print("2. _tasks_text_and_kb shows the breakdown button once a task is set")

    # 3. Once that SAME task is marked done (and it's the only one), the
    #    button disappears again -- nothing left undone to break down.
    text2, kb2 = bot._tasks_text_and_kb(morning, {"focus"}, "M")
    assert "task_breakdown" not in kb_callbacks(kb2), kb_callbacks(kb2)
    print("3. The breakdown button disappears once the only task is marked done")

    # 4. task_breakdown_callback hands the undone task's text to send_coach
    #    verbatim inside the prompt -- monkeypatch send_coach to capture the
    #    call instead of hitting the (unconfigured-in-tests) Anthropic API.
    captured = {}
    async def fake_send_coach(message, text, uid_, ctx=None):
        captured["message"] = message
        captured["text"] = text
        captured["uid"] = uid_
    orig_send_coach = bot.send_coach
    bot.send_coach = fake_send_coach
    try:
        msg = FakeMessage(uid)
        upd = FakeUpdate(uid, msg)
        ctx = FakeCtx()
        await bot.task_breakdown_callback(upd, ctx)
        assert captured["uid"] == uid
        assert "Разобрать почту" in captured["text"], captured["text"]
        assert "маленькие" in captured["text"].lower() or "шаги" in captured["text"].lower(), captured["text"]
    finally:
        bot.send_coach = orig_send_coach
    print("4. task_breakdown_callback hands the undone task's text to send_coach")

    # 5. With nothing undone (all tasks done), task_breakdown_callback
    #    replies with a friendly message instead of calling send_coach.
    bot.save_diary(uid, "tasks_done", {"done": ["focus"]}, for_date=today)
    called = {"n": 0}
    async def counting_send_coach(*a, **kw):
        called["n"] += 1
    bot.send_coach = counting_send_coach
    try:
        msg2 = FakeMessage(uid)
        upd2 = FakeUpdate(uid, msg2)
        ctx2 = FakeCtx()
        await bot.task_breakdown_callback(upd2, ctx2)
        assert called["n"] == 0, "send_coach must not be called when nothing is undone"
        assert "сделаны" in msg2.text.lower() or "нечего" in msg2.text.lower(), msg2.text
    finally:
        bot.send_coach = orig_send_coach
    print("5. task_breakdown_callback replies with a friendly message instead of calling send_coach when nothing is undone")

    print("\nALL TASK BREAKDOWN TESTS PASSED")


asyncio.run(main())
