import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_feedback_exempt_from_paywall.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
bot_module_env = os.environ
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.text = None
        self.successful_payment = None
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        raise Exception("can't edit a user's own message")


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, message=None, callback_query=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)
        self.message = message
        self.callback_query = callback_query
        self.pre_checkout_query = None
        self.effective_message = message if message else (callback_query.message if callback_query else None)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_expired_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(
        uid, timezone="Asia/Tbilisi",
        created_at=(datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date() - timedelta(days=bot.TRIAL_DAYS + 5)).isoformat()
    )


async def hits_paywall(update, ctx):
    try:
        await bot.access_gate(update, ctx)
        return False
    except bot.ApplicationHandlerStop:
        return True


async def main():
    bot.ACCESS_GATE_ENABLED = True

    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-30): access_gate blocked literally
    # everything except a couple of subscribe/promo/menu screens for an
    # expired user -- go_feedback ("Обратная связь") wasn't exempt, so a
    # user who wants to explain why they won't pay, or just ask a question,
    # had no channel at all: any action just replayed the same paywall text.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Tapping "💬 Обратная связь" must not hit the paywall.
    uid = 1
    make_expired_user(uid, "Артем")
    ctx = FakeCtx()
    cq = FakeQuery(uid, "go_feedback")
    upd = FakeUpdate(uid, callback_query=cq)
    assert not await hits_paywall(upd, ctx), "go_feedback must be reachable even with an expired trial"
    print("1. go_feedback callback is exempt from the paywall")

    # Actually open the screen for real, to get awaiting_feedback set as it
    # would be in production.
    await bot.go_feedback(upd, ctx)
    assert ctx.user_data.get("awaiting_feedback") is True

    # 2. Typing the actual feedback text afterwards must ALSO not hit the
    #    paywall -- it's a plain message, not a callback_query, and without
    #    this the screen would open but the reply would bounce off the gate.
    msg = FakeMsg(uid)
    msg.text = "Бот классный, но не готов платить прямо сейчас"
    upd2 = FakeUpdate(uid, message=msg)
    assert not await hits_paywall(upd2, ctx), \
        "typing the feedback text (awaiting_feedback) must not hit the paywall either"
    print("2. The follow-up feedback text message is also exempt (awaiting_feedback)")

    # End-to-end: it must actually reach handle_text and get saved.
    await bot.handle_text(upd2, ctx)
    conn = sqlite3.connect(bot.DB_PATH)
    saved = conn.execute("SELECT text FROM feedback WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    assert any("не готов платить" in t for (t,) in saved), \
        f"the feedback text must actually be saved end-to-end, got: {saved}"
    print("3. The feedback text is actually saved end-to-end for an expired user")

    # 4. Sanity/regression: a non-exempt action (e.g. 🍅 Фокус-режим) for the
    #    same expired user must still hit the paywall as before.
    ctx2 = FakeCtx()
    cq2 = FakeQuery(uid, "go_focus")
    upd3 = FakeUpdate(uid, callback_query=cq2)
    assert await hits_paywall(upd3, ctx2), \
        "a non-exempt action must still hit the paywall for an expired user (no over-broad exemption)"
    print("4. A non-exempt action (go_focus) still hits the paywall as before (no regression)")

    print("\nALL FEEDBACK-EXEMPT-FROM-PAYWALL TESTS PASSED")


asyncio.run(main())
