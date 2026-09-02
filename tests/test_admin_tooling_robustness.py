import os, sys, asyncio, sqlite3
from datetime import datetime as real_datetime, timedelta
import pytz

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_admin_tooling_robustness.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("parse_mode")))
        return self
    async def edit_reply_markup(self, **kw):
        pass


class FakeUpdate:
    def __init__(self, uid):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)


class FakeCtx:
    def __init__(self):
        self.args = []


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = message
        self.answers = []
    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class FakeCbUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data, FakeMsg(uid))
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)


class FakeCbCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    admin_uid = 999
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Админ', 'M')")
    conn.commit(); conn.close()
    bot.update_user(admin_uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 1: admin_feedback/admin_research sliced the joined Markdown
    # message by a raw char count, which could split a message mid-entity
    # (e.g. inside an unpaired "*"). _reply_chunked_markdown must only ever
    # split BETWEEN whole parts, never inside one.
    # ══════════════════════════════════════════════════════════════════════
    class FakeChunkMsg:
        def __init__(self):
            self.sent = []
        async def reply_text(self, text, **kw):
            self.sent.append(text)

    msg = FakeChunkMsg()
    part_a = "A" * 3990
    part_b = "B" * 3990
    part_c = "C" * 10
    await bot._reply_chunked_markdown(msg, [part_a, part_b, part_c])
    assert len(msg.sent) == 3, f"each oversized part must land in its own message, got {len(msg.sent)}"
    assert msg.sent[0] == part_a and msg.sent[1] == part_b and msg.sent[2] == part_c, \
        "no part may be split mid-string across two messages"
    print("1. _reply_chunked_markdown never splits a single part across two messages")

    msg2 = FakeChunkMsg()
    await bot._reply_chunked_markdown(msg2, ["short one", "short two", "short three"])
    assert len(msg2.sent) == 1, "small parts must still be merged into one message as before"
    assert "short one" in msg2.sent[0] and "short three" in msg2.sent[0]
    print("2. _reply_chunked_markdown still merges small parts into one message")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2: toggle_beacon_type_callback let every technique type be
    # unchecked while the master beacon toggle stayed on -- next_beacon_slot
    # then silently returns (None, None) forever, with no signal at all.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi", skill_beacon_enabled=1, beacon_types="breathing")

    upd2 = FakeCbUpdate(uid2, "toggle_beacontype_breathing")
    await bot.toggle_beacon_type_callback(upd2, FakeCbCtx())
    assert bot.get_user(uid2).get("beacon_types", "") == "", "sanity: the only enabled type got unchecked"
    assert upd2.callback_query.answers, "must answer the callback"
    text, show_alert = upd2.callback_query.answers[-1]
    assert show_alert is True and text, \
        f"unchecking the LAST enabled technique type must warn the user (show_alert), got: {upd2.callback_query.answers}"
    print("3. toggle_beacon_type_callback warns when the last technique type is unchecked")

    # Sanity: toggling one back on (now non-empty) must not warn.
    upd2b = FakeCbUpdate(uid2, "toggle_beacontype_breathing")
    await bot.toggle_beacon_type_callback(upd2b, FakeCbCtx())
    text2, show_alert2 = upd2b.callback_query.answers[-1]
    assert show_alert2 is False, "re-enabling a type must not show the empty-set warning"
    print("4. toggle_beacon_type_callback does not warn once at least one type stays enabled")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 3: grant30_callback had no try/except around _grant_and_notify,
    # unlike grant_command -- a failure looked like the button did nothing.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Олег', 'M')")
    conn.commit(); conn.close()

    async def failing_grant(ctx, target_uid, days):
        raise RuntimeError("boom")
    orig_grant = bot._grant_and_notify
    bot._grant_and_notify = failing_grant
    try:
        upd3 = FakeCbUpdate(admin_uid, f"grant30_{uid3}")
        await bot.grant30_callback(upd3, FakeCbCtx())
        assert upd3.callback_query.message.sent, \
            "grant30_callback must reply with an error instead of silently doing nothing"
        assert "Ошибка" in upd3.callback_query.message.sent[-1][0], upd3.callback_query.message.sent
        print("5. grant30_callback reports a visible error instead of silently failing")
    finally:
        bot._grant_and_notify = orig_grant

    # ══════════════════════════════════════════════════════════════════════
    # Bug 4: log_event("subscribe_pay_started") was written BEFORE
    # send_invoice -- a send_invoice failure still left the funnel metric
    # showing "started payment", hiding the real failure.
    # ══════════════════════════════════════════════════════════════════════
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Вика', 'F')")
    conn.commit(); conn.close()

    class FailingInvoiceBot:
        async def send_invoice(self, **kw):
            raise RuntimeError("Stars limit hit")

    upd4 = FakeCbUpdate(uid4, "go_subscribe_pay")
    ctx4 = FakeCbCtx()
    ctx4.bot = FailingInvoiceBot()
    try:
        await bot.go_subscribe_pay(upd4, ctx4)
        assert False, "expected the simulated send_invoice failure to propagate"
    except RuntimeError:
        pass
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute("SELECT COUNT(*) FROM events WHERE user_id=? AND event='subscribe_pay_started'", (uid4,)).fetchone()
    conn.close()
    assert row[0] == 0, \
        f"a failed send_invoice must NOT record subscribe_pay_started (funnel would lie), got {row[0]} rows"
    print("6. go_subscribe_pay does not log subscribe_pay_started when send_invoice fails")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 5: _retention's cohort_date (inside admin_stats) was computed from
    # admin_today (the ADMIN's personal timezone) but compared against
    # users.created_at, which is always written in the bot's default
    # USER_TIMEZONE -- a mismatch when the admin's tz differs from it.
    # ══════════════════════════════════════════════════════════════════════
    class FakeDatetime(real_datetime):
        _fixed = {}
        @classmethod
        def now(cls, tz=None):
            key = getattr(tz, "zone", str(tz))
            if key in cls._fixed:
                return cls._fixed[key]
            return real_datetime.now(tz)

    orig_user_timezone = bot.USER_TIMEZONE
    bot.USER_TIMEZONE = "UTC"  # simulate the bot's default deploy timezone
    bot.update_user(admin_uid, timezone="Pacific/Kiritimati")  # UTC+14

    # Same real instant, 14h apart in wall-clock terms -- crosses midnight.
    FakeDatetime._fixed["UTC"] = pytz.UTC.localize(real_datetime(2026, 9, 2, 23, 30, 0))
    kiritimati = pytz.timezone("Pacific/Kiritimati")
    FakeDatetime._fixed[kiritimati.zone] = kiritimati.localize(real_datetime(2026, 9, 3, 13, 30, 0))

    # A real user whose created_at matches "bot_today - 1" (UTC-based,
    # 2026-09-01) -- NOT "admin_today - 1" (Kiritimati-based, 2026-09-02).
    uid5 = 5
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute(
        "INSERT INTO users(user_id, name, gender, created_at) VALUES (5, 'Когорта', 'M', '2026-09-01')"
    )
    conn.commit(); conn.close()

    orig_datetime = bot.datetime
    bot.datetime = FakeDatetime
    try:
        upd5 = FakeUpdate(admin_uid)
        await bot.admin_stats(upd5, FakeCtx())
    finally:
        bot.datetime = orig_datetime
        bot.USER_TIMEZONE = orig_user_timezone

    assert upd5.message.sent, "admin_stats must reply"
    stats_text = upd5.message.sent[-1][0]
    assert "1 день: — (когорта пуста)" not in stats_text, \
        (f"the day-1 retention cohort must be found using the bot's own timezone "
         f"(matching created_at's timezone), not the admin's personal timezone, got:\n{stats_text}")
    print("7. _retention (admin_stats) finds the cohort using the bot's timezone, not the admin's")

    print("\nALL ADMIN-TOOLING-ROBUSTNESS TESTS PASSED")


asyncio.run(main())
