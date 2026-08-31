import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_phase0_analytics.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))
        return self


class FakeUpdate:
    def __init__(self, uid, text=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)
        self.message.text = text


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg(uid)
    async def answer(self): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeCbUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    admin_uid = 999  # matches NOTIFY_USER_ID
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Админ', 'M')")
    conn.commit(); conn.close()
    bot.update_user(admin_uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Phase 0: сколько людей реально доходят до оплаты (а не только платят)
    # и какая настоящая когортная кривая удержания (день 1/7/30 от
    # регистрации) -- ни то ни другое раньше не было видно в /admin.
    # ══════════════════════════════════════════════════════════════════════

    # 1. events table exists and log_event writes rows.
    bot.log_event(1, "subscribe_opened")
    bot.log_event(1, "subscribe_pay_started")
    bot.log_event(2, "subscribe_opened")
    conn = sqlite3.connect(bot.DB_PATH)
    rows = conn.execute("SELECT user_id, event FROM events ORDER BY id").fetchall()
    conn.close()
    assert rows == [(1, "subscribe_opened"), (1, "subscribe_pay_started"), (2, "subscribe_opened")], rows
    print("1. log_event writes rows into the new events table")

    # 2. go_subscribe / subscribe_command / go_subscribe_pay log events.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("DELETE FROM events")
    conn.commit(); conn.close()

    uid_a = 10
    bot.update_user(uid_a, name="Тест", timezone="Asia/Tbilisi")
    upd = FakeCbUpdate(uid_a, data="go_subscribe")
    await bot.go_subscribe(upd, FakeCtx())
    conn = sqlite3.connect(bot.DB_PATH)
    ev = conn.execute("SELECT event FROM events WHERE user_id=?", (uid_a,)).fetchall()
    conn.close()
    assert ("subscribe_opened",) in ev, ev
    print("2a. go_subscribe logs subscribe_opened")

    upd2 = FakeUpdate(uid_a)
    await bot.subscribe_command(upd2, FakeCtx())
    conn = sqlite3.connect(bot.DB_PATH)
    cnt = conn.execute("SELECT COUNT(*) FROM events WHERE user_id=? AND event='subscribe_opened'", (uid_a,)).fetchone()[0]
    conn.close()
    assert cnt == 2, cnt
    print("2b. subscribe_command also logs subscribe_opened")

    class FakeBotForInvoice:
        async def send_invoice(self, **kw): pass
    class FakeCtxWithBot(FakeCtx):
        def __init__(self):
            super().__init__()
            self.bot = FakeBotForInvoice()
    upd3 = FakeCbUpdate(uid_a, data="go_subscribe_pay")
    await bot.go_subscribe_pay(upd3, FakeCtxWithBot())
    conn = sqlite3.connect(bot.DB_PATH)
    ev2 = conn.execute("SELECT event FROM events WHERE user_id=? AND event='subscribe_pay_started'", (uid_a,)).fetchall()
    conn.close()
    assert len(ev2) == 1, ev2
    print("2c. go_subscribe_pay logs subscribe_pay_started")

    # 3. admin_stats renders without error and includes the new sections,
    # with correct retention math for a synthetic cohort.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("DELETE FROM users WHERE user_id NOT IN (999)")
    conn.execute("DELETE FROM diary")
    conn.execute("DELETE FROM events")
    conn.commit(); conn.close()

    tz = bot.get_user_tz(bot.get_user(admin_uid))
    today = datetime.now(tz).date()
    day7_cohort_date = (today - timedelta(days=7)).isoformat()

    # 3 users registered exactly 7 days ago; 2 of them checked in today
    # (their "day 7"), 1 didn't -- expect 67% (2/3) day-7 retention.
    conn = sqlite3.connect(bot.DB_PATH)
    for i, uid in enumerate([101, 102, 103]):
        conn.execute(
            "INSERT INTO users(user_id, name, gender, created_at, timezone) VALUES (?, 'U', 'M', ?, 'Asia/Tbilisi')",
            (uid, day7_cohort_date)
        )
    conn.commit(); conn.close()
    bot.save_diary(101, "morning", {"focus": "x"}, for_date=today.isoformat())
    bot.save_diary(102, "evening", {"focus": "y"}, for_date=today.isoformat())
    # 103 does NOT check in today -- not retained.

    # Also 1 user registered today who has NOT finished onboarding (no name)
    # -- must count toward "начали", not toward "завершили".
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, created_at) VALUES (555, ?)", (today.isoformat(),))
    conn.commit(); conn.close()

    upd_admin = FakeUpdate(admin_uid)
    await bot.admin_stats(upd_admin, FakeCtx())
    assert upd_admin.message.sent, "admin_stats sent nothing"
    text = upd_admin.message.sent[-1][0]
    assert "Онбординг" in text and "Ретеншн" in text and "Воронка подписки" in text, text
    assert "67%" in text or "(2/3)" in text, f"expected day-7 retention 2/3 (67%) in text:\n{text}"
    print("3. admin_stats includes onboarding funnel + retention + subscribe funnel, with correct math")

    print("\nALL PHASE0-ANALYTICS TESTS PASSED")


asyncio.run(main())
