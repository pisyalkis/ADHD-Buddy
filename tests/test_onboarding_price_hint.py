import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_onboarding_price_hint.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.deleted = []

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeMessage:
    _next_id = [100]

    def __init__(self, chat_id=1, bot=None):
        self.chat_id = chat_id
        self.message_id = FakeMessage._next_id[0]
        FakeMessage._next_id[0] += 1
        self._bot = bot
        self.text = ""

    async def reply_text(self, text, **kw):
        m = FakeMessage(self.chat_id, self._bot)
        m.text = text
        return m


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, cid): self.id = cid


class FakeUpdate:
    def __init__(self, uid, message):
        self.message = message
        self.callback_query = None
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(1)
        self.args = []


class FakeCtx:
    def __init__(self, fbot):
        self.user_data = {}
        self.bot = fbot


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-27): the subscription price/trial length
    # (TRIAL_INFO_TIP) only appeared at the very END of onboarding -- an
    # external, unfamiliar user already gave their name and gender before
    # learning anything about money, only finding out at the tail end.
    # ══════════════════════════════════════════════════════════════════════

    # 1. A brand-new user's very first /start message already mentions the
    #    trial length and the monthly price -- not the full TRIAL_INFO_TIP
    #    (too much detail this early), just a short one-line hint. Capture
    #    the actual sent text via a message wrapper that records it.
    class RecordingMessage(FakeMessage):
        def __init__(self, chat_id=1, bot=None):
            super().__init__(chat_id, bot)
            self.sent_texts = []

        async def reply_text(self, text, **kw):
            self.sent_texts.append(text)
            return await super().reply_text(text, **kw)

    uid2 = 2
    fbot2 = FakeBot()
    ctx2 = FakeCtx(fbot2)
    incoming = RecordingMessage(chat_id=2, bot=fbot2)
    upd2 = FakeUpdate(uid2, incoming)
    await bot.start(upd2, ctx2)
    assert len(incoming.sent_texts) == 1, incoming.sent_texts
    welcome_text = incoming.sent_texts[0]
    assert str(bot.TRIAL_DAYS) in welcome_text, welcome_text
    assert str(bot.STARS_PRICE_MONTHLY) in welcome_text, welcome_text
    assert "⭐" in welcome_text, welcome_text
    assert "Как тебя зовут?" in welcome_text, welcome_text
    print("1. The very first /start message mentions the trial length and monthly Stars price")

    # 3. The price hint is short -- must NOT duplicate the full detailed
    #    TRIAL_INFO_TIP explanation (still shown later, at the end of
    #    onboarding, in full).
    assert "оплата прямо в Telegram" not in welcome_text, \
        "the first message should carry a short hint, not the full TRIAL_INFO_TIP explanation"
    print("2. The first-message hint stays short -- the detailed TRIAL_INFO_TIP explanation is not duplicated here")

    # 4. The buddy-invite branch (referral onboarding) also carries the price
    #    hint -- the two branches share the same reply_text call, but verify
    #    explicitly since the intro prefix differs.
    inviter_uid = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, 'Игорь', 'M')", (inviter_uid,))
    conn.commit(); conn.close()
    uid3 = 4
    fbot3 = FakeBot()
    ctx3 = FakeCtx(fbot3)
    upd3 = FakeUpdate(uid3, RecordingMessage(chat_id=4, bot=fbot3))
    ctx3.args = [f"buddy_{inviter_uid}"]
    await bot.start(upd3, ctx3)
    invite_text = upd3.message.sent_texts[0]
    assert "Игорь" in invite_text, invite_text
    assert str(bot.STARS_PRICE_MONTHLY) in invite_text, invite_text
    print("3. The buddy-invite (referral) onboarding branch also carries the price hint")

    print("\nALL ONBOARDING-PRICE-HINT TESTS PASSED")


asyncio.run(main())
