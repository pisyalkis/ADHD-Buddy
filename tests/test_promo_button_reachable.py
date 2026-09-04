import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_promo_button_reachable.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
os.environ["ACCESS_GATE_ENABLED"] = "1"
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.text = None
        self.sent = []
        self.successful_payment = None
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeUpdate:
    def __init__(self, uid, message=None, callback_query=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)
        self.message = message
        self.callback_query = callback_query
        self.pre_checkout_query = None
        self.effective_message = message


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: go_promo (enter a promo code) was registered as a callback
    # handler and even exempted from the paywall (ACCESS_GATE_EXEMPT_CALLBACKS),
    # but NO button anywhere in the UI actually emitted callback_data="go_promo" --
    # the only way in was the blind /promo command, which an expired user
    # (or a blogger's audience who only knows their promo code, not that a
    # slash command exists) would never discover.
    # ══════════════════════════════════════════════════════════════════════
    bot.ACCESS_GATE_ENABLED = True

    # 1. The paywall screen shown to an expired user (access_gate) -- the
    #    one and only screen such a user can actually see -- must offer a
    #    way in via promo code.
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", created_at=(datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date() - timedelta(days=bot.TRIAL_DAYS + 5)).isoformat())

    msg = FakeMsg(uid)
    msg.text = "привет"
    upd = FakeUpdate(uid, message=msg)
    ctx = FakeCtx()
    try:
        await bot.access_gate(upd, ctx)
        raised = False
    except bot.ApplicationHandlerStop:
        raised = True
    assert raised, "sanity: an expired user's plain message must actually hit the paywall"
    assert msg.sent, "sanity: the paywall message must have been sent"
    _, kb = msg.sent[-1]
    flat = buttons_of(kb)
    assert ("🎁 Промокод", "go_promo") in flat, \
        f"the paywall screen (the only thing an expired user can see) must offer a way to enter a promo code, got: {flat}"
    print("1. access_gate's paywall screen offers a '🎁 Промокод' button wired to go_promo")

    # 2. The 💎 Подписка screen (reachable from the main menu) for a trial
    #    user must also offer the same button.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    user2 = bot.get_user(uid2)
    text2, kb2 = bot._subscribe_text_and_kb(user2)
    flat2 = buttons_of(kb2)
    assert ("🎁 Промокод", "go_promo") in flat2, \
        f"the 💎 Подписка screen for a trial user must also offer a promo-code button, got: {flat2}"
    print("2. 💎 Подписка screen (trial user) also offers the '🎁 Промокод' button")

    # 3. Sanity: an already-subscribed user must NOT see it (promo code is
    #    meaningless once already paying) -- this branch was already fixed
    #    once for the price/promo prompt, must stay that way.
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Олег', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi", subscription_until=(datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date() + timedelta(days=10)).isoformat())
    user3 = bot.get_user(uid3)
    text3, kb3 = bot._subscribe_text_and_kb(user3)
    flat3 = buttons_of(kb3)
    assert ("🎁 Промокод", "go_promo") not in flat3, \
        f"an already-subscribed user must not be offered a promo-code button, got: {flat3}"
    print("3. An already-subscribed user's screen still has no promo-code button (unchanged)")

    print("\nALL PROMO-BUTTON-REACHABLE TESTS PASSED")


asyncio.run(main())
