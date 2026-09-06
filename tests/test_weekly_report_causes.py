import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_weekly_report_causes.db")
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


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-28): the daily midday checkin asks "what's
    # going on?" (mid_nostart/mid_scary/mid_phone/... -- see MIDDAY_LABELS/
    # midday_callback) and saves the answer to the "midday" diary block's
    # "state" field every day, but weekly_report never aggregated it -- the
    # report showed WHETHER the week went well, never WHY it didn't.
    # ══════════════════════════════════════════════════════════════════════
    today = datetime.now(TBILISI).date()

    # 1. The week's most common non-"all good" causes are surfaced, ranked
    #    by frequency, capped at the top 3, each with a day count.
    uid = 1
    make_user(uid, "Артем")
    causes_by_day_offset = {
        1: "mid_phone", 2: "mid_phone", 3: "mid_phone",   # 3x -- most common
        4: "mid_scary", 5: "mid_scary",                    # 2x
        6: "mid_time",                                     # 1x
        7: "mid_ok",                                        # not a cause -- must be excluded
    }
    for offset, key in causes_by_day_offset.items():
        d = (today - timedelta(days=offset)).isoformat()
        bot.save_diary(uid, "midday", {"state": bot.MIDDAY_LABELS[key]}, for_date=d)
    app = FakeApp()
    ok = await bot.weekly_report(app, uid)
    assert ok
    report = app.bot.sent[0][1]
    assert "Что чаще всего мешало" in report, report
    phone_label = bot.MIDDAY_LABELS["mid_phone"]
    scary_label = bot.MIDDAY_LABELS["mid_scary"]
    time_label = bot.MIDDAY_LABELS["mid_time"]
    ok_label = bot.MIDDAY_LABELS["mid_ok"]
    # Order: phone (3 days) must be listed before scary (2 days) before time (1 day).
    assert report.index(phone_label) < report.index(scary_label) < report.index(time_label), report
    assert f"{phone_label} — 3 дня" in report, report
    assert f"{scary_label} — 2 дня" in report, report
    assert f"{time_label} — 1 день" in report, report
    assert ok_label not in report.split("Что чаще всего мешало")[1], \
        "'Всё по плану' must not be listed as a procrastination cause"
    print("1. weekly_report ranks the week's midday causes by frequency, excludes 'Всё по плану', shows day counts")

    # 2. A week with only "mid_ok" (or no midday checkins at all) shows no
    #    causes section -- nothing to report, so don't show an empty one.
    uid2 = 2
    make_user(uid2, "Вика")
    for offset in range(1, 8):
        d = (today - timedelta(days=offset)).isoformat()
        bot.save_diary(uid2, "midday", {"state": bot.MIDDAY_LABELS["mid_ok"]}, for_date=d)
    app2 = FakeApp()
    await bot.weekly_report(app2, uid2)
    report2 = app2.bot.sent[0][1]
    assert "Что чаще всего мешало" not in report2, report2
    print("2. A week with only 'Всё по плану' (or no midday data) shows no causes section")

    # 3. Only the top 3 causes are shown even if more than 3 distinct causes
    #    were reported during the week.
    uid3 = 3
    make_user(uid3, "Игорь")
    four_causes = ["mid_nostart", "mid_scary", "mid_resist", "mid_energy"]
    for offset, key in zip(range(1, 5), four_causes):
        d = (today - timedelta(days=offset)).isoformat()
        bot.save_diary(uid3, "midday", {"state": bot.MIDDAY_LABELS[key]}, for_date=d)
    app3 = FakeApp()
    await bot.weekly_report(app3, uid3)
    report3 = app3.bot.sent[0][1]
    shown_count = sum(1 for key in four_causes if bot.MIDDAY_LABELS[key] in report3)
    assert shown_count == 3, f"expected exactly top 3 causes shown, got {shown_count}: {report3}"
    print("3. At most the top 3 causes are shown, even with more distinct causes reported")

    print("\nALL WEEKLY-REPORT-CAUSES TESTS PASSED")


asyncio.run(main())
