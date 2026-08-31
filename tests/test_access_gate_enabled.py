import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_access_gate_enabled.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()

assert bot.ACCESS_GATE_ENABLED is True, "gate must be ON for this test to be meaningful"


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, text=None, data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.effective_message = FakeMsg()
        self.message = self.effective_message
        self.message.text = text
        self.message.successful_payment = None
        self.callback_query = FakeQuery(uid, data) if data is not None else None
        self.pre_checkout_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Owner', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Trial', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Expired', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Subscribed', 'M')")
    conn.commit(); conn.close()

    bot.update_user(1, timezone="Asia/Tbilisi")  # this is NOTIFY_USER_ID (999) in reality; test id=1 isn't the owner here
    bot.update_user(2, timezone="Asia/Tbilisi", created_at=date.today().isoformat())
    bot.update_user(3, timezone="Asia/Tbilisi",
                     created_at=(date.today() - timedelta(days=bot.TRIAL_DAYS + 5)).isoformat())
    bot.update_user(4, timezone="Asia/Tbilisi",
                     created_at=(date.today() - timedelta(days=bot.TRIAL_DAYS + 5)).isoformat(),
                     subscription_until=(date.today() + timedelta(days=10)).isoformat())

    # ── Owner (NOTIFY_USER_ID) is never blocked ─────────────────────────────
    owner_upd = FakeUpdate(bot.NOTIFY_USER_ID, text="привет")
    owner_ctx = FakeCtx()
    await bot.access_gate(owner_upd, owner_ctx)
    assert owner_upd.message.sent == [], "owner must never see the paywall"
    print("1. Owner (NOTIFY_USER_ID) is exempt from the gate")

    # ── Fresh user still inside the 7-day trial passes through ──────────────
    trial_upd = FakeUpdate(2, text="привет")
    await bot.access_gate(trial_upd, FakeCtx())
    assert trial_upd.message.sent == []
    print("2. A user still inside the trial window passes through untouched")

    # ── Expired trial, no subscription -> blocked with the paywall message ─
    expired_upd = FakeUpdate(3, text="привет")
    try:
        await bot.access_gate(expired_upd, FakeCtx())
        raised = False
    except bot.ApplicationHandlerStop:
        raised = True
    assert raised, "an expired user's free-text message must be stopped by the gate"
    assert len(expired_upd.message.sent) == 1
    assert "Пробный период закончился" in expired_upd.message.sent[0][0]
    print("3. An expired, unsubscribed user is shown the paywall and blocked")

    # ── Active subscription overrides an expired trial -> passes through ───
    sub_upd = FakeUpdate(4, text="привет")
    await bot.access_gate(sub_upd, FakeCtx())
    assert sub_upd.message.sent == []
    print("4. An active paid subscription overrides an expired trial")

    # ── Exempt commands/callbacks still reach an expired user ───────────────
    expired_cmd_upd = FakeUpdate(3, text="/subscribe")
    await bot.access_gate(expired_cmd_upd, FakeCtx())
    assert expired_cmd_upd.message.sent == []
    print("5a. /subscribe still reaches an expired user (must be able to pay)")

    expired_cb_upd = FakeUpdate(3, data="go_subscribe_pay")
    await bot.access_gate(expired_cb_upd, FakeCtx())
    assert expired_cb_upd.callback_query.message.sent == []
    print("5b. go_subscribe_pay callback still reaches an expired user")

    # ── An expired user mid-promo-code-entry is not interrupted ─────────────
    expired_promo_ctx = FakeCtx()
    expired_promo_ctx.user_data["awaiting_promo_code"] = True
    expired_promo_upd = FakeUpdate(3, text="MYPROMO")
    await bot.access_gate(expired_promo_upd, expired_promo_ctx)
    assert expired_promo_upd.message.sent == []
    print("5c. An expired user typing a promo code is not interrupted mid-entry")

    print("\nALL ACCESS-GATE-ENABLED TESTS PASSED")


asyncio.run(main())
