import os, sys, asyncio, sqlite3, types
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coach_single_message.db")
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


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [31000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.reply_calls = []
        self.text = None

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m

    async def edit_text(self, text, **kw):
        self.text = text
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edits.append((chat_id, message_id, text))


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "маячки/уведомления/коуч" -- always one current message.
    # Applied to 🧠 Коуч: opening the coach menu, tapping a quick-prompt
    # button, and typing a free-text follow-up must all stay on the SAME
    # message instead of each producing a new one.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    menu_screen = FakeMsg(chat_id=uid)  # e.g. main menu, where "🧠 Коуч" lives

    upd = FakeUpdate(uid, data="go_coach", message=menu_screen)
    await bot.coach_menu(upd, ctx)

    tracked_id = ctx.user_data.get("coach_msg_id")
    assert tracked_id == menu_screen.message_id, \
        f"coach_menu must take over the tapped screen itself, not spawn a new message, got tracked={tracked_id} vs tapped={menu_screen.message_id}"
    assert not menu_screen.reply_calls
    print("1. coach_menu takes over the tapped screen in place (no new message)")

    # Tap a quick-prompt button ("🚫 Не могу начать" -> c_start).
    set_fake_reply("Начни с одного маленького шага на 5 минут.")
    prompt_screen = FakeMsg(chat_id=uid); prompt_screen.message_id = tracked_id
    upd2 = FakeUpdate(uid, data="c_start", message=prompt_screen)
    await bot.coach_quick(upd2, ctx)

    assert not prompt_screen.reply_calls, \
        f"coach_quick must not spawn a new message, got {prompt_screen.reply_calls}"
    assert all(mid == tracked_id for _, mid, _ in fbot.edits), \
        f"every edit must target the ONE tracked coach message, got {fbot.edits}"
    assert "5 минут" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("2. Tapping a quick-prompt button edits the SAME tracked message with the coach's reply")

    # A typed follow-up (free text) must ALSO edit the same tracked message,
    # not create a new one from the user's own message.
    set_fake_reply("Отлично, продолжай в том же духе.")
    user_text = FakeMsg(chat_id=uid)
    upd3 = FakeUpdate(uid, text_message=user_text)
    ctx.user_data["coach_mode"] = True
    await bot.send_coach(user_text, "Сделал(а) первый шаг", uid, ctx)

    assert not user_text.reply_calls, \
        f"a typed follow-up must not spawn a new message from the user's own message, got {user_text.reply_calls}"
    assert all(mid == tracked_id for _, mid, _ in fbot.edits)
    assert "продолжай" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("3. A typed follow-up also edits the SAME tracked message -- no new message across the whole conversation")

    # Leaving the coach (e.g. "◀️ Меню") clears the tracking, so a LATER,
    # unrelated coach session doesn't silently hijack this old message.
    go_menu_screen = FakeMsg(chat_id=uid); go_menu_screen.message_id = tracked_id
    upd4 = FakeUpdate(uid, data="go_menu", message=go_menu_screen)
    await bot.go_menu(upd4, ctx)
    assert ctx.user_data.get("coach_msg_id") is None
    assert ctx.user_data.get("coach_chat_id") is None
    print("4. Leaving the coach (go_menu) clears the tracked coach message id")

    print("\nALL COACH-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
