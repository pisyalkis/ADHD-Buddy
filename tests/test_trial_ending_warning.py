import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_trial_ending_warning.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 1
            chat_id = 0
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name, days_ago):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    created = (datetime.now(TBILISI).date() - timedelta(days=days_ago)).isoformat()
    bot.update_user(uid, timezone="Asia/Tbilisi", created_at=created)


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-30): no advance warning before the
    # trial's hard paywall hits -- the first thing a user sees is
    # access_gate's block, right at the moment access expires. This adds a
    # one-time warning at "2 days or fewer left", with subscribe + promo
    # buttons right there, sent well before the paywall.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Exactly 2 days left -> warning fires, includes both action buttons.
    uid = 1
    make_user(uid, "Артем", bot.TRIAL_DAYS - 2)
    app = FakeApp()
    await bot.send_trial_ending_warning(app, uid)
    assert app.bot.sent, "a user with 2 trial days left must get the warning"
    _chat_id, text, kb = app.bot.sent[0]
    assert "2 дня" in text or "2 дн" in text, text
    flat = buttons_of(kb)
    assert any(cb == "go_subscribe_pay" for _, cb in flat), flat
    assert any(cb == "go_promo" for _, cb in flat), flat
    assert int(bot.get_user(uid).get("trial_warning_sent")) == 1, \
        "trial_warning_sent must be set to 1 after actually sending"
    print("1. With 2 trial days left, the warning fires once with both subscribe/promo buttons")

    # 2. Already sent -> must not fire again, even if called repeatedly.
    app2 = FakeApp()
    await bot.send_trial_ending_warning(app2, uid)
    assert not app2.bot.sent, "already-warned user must not be warned again"
    print("2. A user already warned is not warned again")

    # 3. Plenty of days left (e.g. day 3 of 14) -> must NOT fire, and --
    #    critically -- must NOT prematurely set trial_warning_sent (a
    #    one-time-ever flag, unlike the daily _sent_date fields), or the
    #    real warning would never fire later when it's actually due.
    uid2 = 2
    make_user(uid2, "Вика", 3)
    app3 = FakeApp()
    await bot.send_trial_ending_warning(app3, uid2)
    assert not app3.bot.sent, "a user with plenty of trial days left must not be warned yet"
    assert int(bot.get_user(uid2).get("trial_warning_sent") or 0) == 0, \
        "trial_warning_sent must stay 0 until the real 2-days-left window actually arrives"
    print("3. A user far from trial's end is not warned, and the flag isn't prematurely set")

    # Advance uid2 to 1 day left -- the warning must still be reachable
    # (flag wasn't burned prematurely).
    bot.update_user(uid2, created_at=(datetime.now(TBILISI).date() - timedelta(days=bot.TRIAL_DAYS - 1)).isoformat())
    app4 = FakeApp()
    await bot.send_trial_ending_warning(app4, uid2)
    assert app4.bot.sent, "once the user actually reaches <=2 days left, the warning must fire"
    print("4. Once the real window arrives, the warning still fires (not burned early)")

    # 5. Expired user -> must not get this warning (that's access_gate's job).
    uid3 = 3
    make_user(uid3, "Олег", bot.TRIAL_DAYS + 5)
    app5 = FakeApp()
    await bot.send_trial_ending_warning(app5, uid3)
    assert not app5.bot.sent, "an already-expired user must not get the 'ending soon' warning"
    print("5. An already-expired user does not get the ending-soon warning")

    print("\nALL TRIAL-ENDING-WARNING TESTS PASSED")


asyncio.run(main())
