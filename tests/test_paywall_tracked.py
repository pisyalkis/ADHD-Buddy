import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_paywall_tracked.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edited = []
        self._next_id = 100

    async def send_message(self, chat_id, text, **kw):
        return None

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append((chat_id, message_id, text))
        return FakeSentMsg(chat_id, message_id)


class FakeSentMsg:
    def __init__(self, chat_id, mid):
        self.chat_id = chat_id
        self.message_id = mid


class FakeMsg:
    """A real incoming USER text message -- cannot be edited by the bot,
    matching Telegram's actual behavior (edit_text only works on messages
    the bot itself sent)."""
    def __init__(self, chat_id, ctx_bot, next_id_holder):
        self.chat_id = chat_id
        self.message_id = next_id_holder[0]
        next_id_holder[0] += 1
        self.text = "привет"
        self._bot = ctx_bot
        self.successful_payment = None

    async def edit_text(self, text, **kw):
        raise Exception("Message can't be edited")  # bot can't edit a user's own message

    async def reply_text(self, text, **kw):
        mid = self._bot._next_id
        self._bot._next_id += 1
        sent = FakeSentMsg(self.chat_id, mid)
        self._bot.sent.append((self.chat_id, mid, text))
        return sent


class FakeUpdate:
    def __init__(self, uid, msg):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)
        self.effective_message = msg
        self.message = msg
        self.callback_query = None
        self.pre_checkout_query = None


class FakeCtx:
    def __init__(self, fake_bot):
        self.user_data = {}
        self.bot = fake_bot


async def main():
    bot.ACCESS_GATE_ENABLED = True
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(
        uid, timezone="Asia/Tbilisi",
        created_at=(datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date() - timedelta(days=bot.TRIAL_DAYS + 5)).isoformat()
    )

    # ══════════════════════════════════════════════════════════════════════
    # Bug: access_gate's paywall was sent via a raw target.reply_text on
    # EVERY blocked action, with no tracking -- unlike virtually every
    # other screen in the bot. A user with expired access who repeatedly
    # types something (a common, ordinary reaction to being blocked, not
    # understanding what happened) got a brand new "Пробный период
    # закончился" message each time, spamming the chat.
    # ══════════════════════════════════════════════════════════════════════
    fake_bot = FakeBot()
    ctx = FakeCtx(fake_bot)
    next_id = [500]

    msg1 = FakeMsg(uid, fake_bot, next_id)
    upd1 = FakeUpdate(uid, msg1)
    try:
        await bot.access_gate(upd1, ctx)
        raised1 = False
    except bot.ApplicationHandlerStop:
        raised1 = True
    assert raised1, "sanity: an expired user's message must actually hit the paywall"
    assert len(fake_bot.sent) == 1, f"sanity: the first blocked message must send exactly one paywall message, got: {fake_bot.sent}"
    print("1. First blocked message sends exactly one paywall message")

    msg2 = FakeMsg(uid, fake_bot, next_id)
    upd2 = FakeUpdate(uid, msg2)
    try:
        await bot.access_gate(upd2, ctx)
    except bot.ApplicationHandlerStop:
        pass

    assert len(fake_bot.sent) == 1, \
        f"a second blocked message must NOT send a duplicate paywall message, got sent: {fake_bot.sent}"
    assert len(fake_bot.edited) == 1, \
        f"a second blocked message must edit the already-shown paywall in place instead, got edited: {fake_bot.edited}"
    print("2. A second blocked message edits the existing paywall in place instead of spamming a duplicate")

    print("\nALL PAYWALL-TRACKED TESTS PASSED")


asyncio.run(main())
