import os, sys, asyncio, sqlite3, types
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coach_mode_reminder.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-tests"

_fake_reply = {"text": ""}

class FakeContent:
    def __init__(self, text): self.text = text

class FakeResp:
    def __init__(self, text): self.content = [FakeContent(text)]

class FakeMessages:
    def create(self, **kw):
        return FakeResp(_fake_reply["text"])

class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()

fake_module = types.ModuleType("anthropic")
fake_module.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake_module

def set_fake_reply(text):
    _fake_reply["text"] = text

import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = None
        self.message = FakeMsg()
        self.message.text = text


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Bug (Artem, with screenshot): once coach_mode is stuck on from an
    # earlier ambiguous message, EVERY subsequent free-text message -- even
    # a perfectly well-formed reminder request -- used to be swallowed by
    # the coach's own conversational reply ("Хорошо, напомню через минуту")
    # WITHOUT ever creating a real reminder, because coach_mode short-
    # circuited straight to send_coach before classify_free_text ever ran.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["coach_mode"] = True  # already stuck on from an earlier message

    now_dt = datetime.now(bot.get_user_tz(bot.get_user(uid)))
    remind_at = (now_dt + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    set_fake_reply(
        '{"intent": "reminder", "remind_at": "%s", "text": "написать Марике", "recur": ""}' % remind_at
    )
    upd = FakeUpdate(uid, text="Напомни написать Марике через минуту")
    await bot.handle_text(upd, ctx)

    reminders = bot.get_reminders(uid)
    assert len(reminders) == 1, \
        f"a clear reminder request must create a real reminder even while coach_mode is on, got {reminders}"
    assert reminders[0]["text"] == "написать Марике"
    print("1. A reminder request while coach_mode is stuck on now creates a real reminder")

    assert "напомню" in upd.message.last_text.lower() or "Марике" in upd.message.last_text
    print("2. The reply confirms the real reminder (create_reminder_and_reply), not a coach chat reply")

    # ── A genuinely ambiguous message while coach_mode is on still goes to
    #    the coach, as before ────────────────────────────────────────────────
    set_fake_reply('{"intent": "other"}')
    ctx2 = FakeCtx()
    ctx2.user_data["coach_mode"] = True
    upd2 = FakeUpdate(uid, text="мне тяжело сегодня, ничего не хочется делать")
    await bot.handle_text(upd2, ctx2)
    assert len(bot.get_reminders(uid)) == 1, "an ambiguous message must not create a spurious reminder"
    assert ctx2.user_data.get("coach_mode") is True
    print("3. A genuinely ambiguous message while coach_mode is on still reaches the coach, unaffected")

    print("\nALL COACH-MODE-REMINDER TESTS PASSED")


asyncio.run(main())
