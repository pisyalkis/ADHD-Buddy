import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_payment_dedup.db")
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
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.bot = FakeBot()
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = None
        self.message = FakeMsg()
        self.pre_checkout_query = None


class FakeCtxBot:
    def __init__(self):
        self.sent = []
    async def send_invoice(self, **kw):
        pass
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        class _M:
            message_id = 999999
        return _M()
    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeCtxBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def payments_for(uid):
    conn = sqlite3.connect(bot.DB_PATH)
    rows = conn.execute("SELECT charge_id FROM payments WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def make_payment_update(uid, charge_id, amount=100):
    upd = FakeUpdate(uid)
    upd.message.successful_payment = type("P", (), {
        "total_amount": amount, "currency": "XTR",
        "invoice_payload": f"subscription_{uid}",
        "telegram_payment_charge_id": charge_id,
    })()
    return upd


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (ночной скан 2026-09-09): Telegram can redeliver the
    # successful_payment update (retry after a process restart, when the
    # in-memory _seen_update_ids from dedupe_updates has already been reset)
    # -- successful_payment_callback previously had no idempotency check at
    # all, so a redelivered update extended subscription_until AGAIN and
    # logged a second payments row, for a single real charge. Fixed via
    # payment_already_processed(charge_id) -- telegram_payment_charge_id is
    # unique per actual payment -- plus a defensive unique index on
    # payments.charge_id.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")

    # 1. A fresh payment extends the subscription by STARS_SUBSCRIPTION_DAYS
    #    and logs exactly one payments row.
    today = datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date()
    ctx1 = FakeCtx()
    upd1 = make_payment_update(uid, "charge_A", amount=100)
    await bot.successful_payment_callback(upd1, ctx1)
    until_after_1 = date.fromisoformat(bot.get_user(uid)["subscription_until"][:10])
    assert until_after_1 == today + timedelta(days=bot.STARS_SUBSCRIPTION_DAYS), until_after_1
    assert payments_for(uid) == ["charge_A"], payments_for(uid)
    assert len(upd1.message.sent) == 1, "the user must get exactly one 'thank you' reply"
    print("1. A fresh payment extends the subscription once and logs one payments row")

    # 2. The SAME update (same charge_id) redelivered -- e.g. after a
    #    process restart -- must NOT extend the subscription again, must
    #    NOT log a second payments row, and must NOT re-notify anyone.
    ctx2 = FakeCtx()
    upd2 = make_payment_update(uid, "charge_A", amount=100)
    await bot.successful_payment_callback(upd2, ctx2)
    until_after_2 = date.fromisoformat(bot.get_user(uid)["subscription_until"][:10])
    assert until_after_2 == until_after_1, \
        f"a redelivered payment with the same charge_id must NOT extend the subscription again: {until_after_1} -> {until_after_2}"
    assert payments_for(uid) == ["charge_A"], \
        f"a redelivered payment must NOT log a second payments row: {payments_for(uid)}"
    assert not upd2.message.sent, "a redelivered payment must not re-send the 'thank you' reply"
    assert not ctx2.bot.sent, "a redelivered payment must not re-notify the admin"
    print("2. A redelivered update with the SAME charge_id is a no-op (no double-charge, no duplicate log)")

    # 3. A GENUINE second payment (different charge_id) still extends the
    #    subscription normally -- the fix must not block real repeat
    #    payments (e.g. renewing next month).
    ctx3 = FakeCtx()
    upd3 = make_payment_update(uid, "charge_B", amount=100)
    await bot.successful_payment_callback(upd3, ctx3)
    until_after_3 = date.fromisoformat(bot.get_user(uid)["subscription_until"][:10])
    assert until_after_3 == until_after_1 + timedelta(days=bot.STARS_SUBSCRIPTION_DAYS), \
        f"a genuinely new payment (different charge_id) must still extend the subscription: {until_after_1} -> {until_after_3}"
    assert sorted(payments_for(uid)) == ["charge_A", "charge_B"], payments_for(uid)
    print("3. A genuinely new payment (different charge_id) still extends the subscription normally")

    print("\nALL PAYMENT-DEDUP TESTS PASSED")


asyncio.run(main())
