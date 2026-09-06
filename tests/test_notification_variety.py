import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_notification_variety.db")
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
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.user_data = {}


def make_user(uid, name, gender="M"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, ?)", (uid, name, gender))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (this session): the 3x/day ritual notifications (morning/
    # midday/evening) send the exact same fixed header every single day,
    # forever -- unlike MOTIVATIONS (already varied). Rotate the opening/
    # closing wrapper phrases via the same stable, per-day hash mechanism
    # already used by get_daily_skill (not naive random -- must survive a
    # process restart mid-day and stay consistent within the same day).
    # ══════════════════════════════════════════════════════════════════════

    # 1. _daily_text_variant is stable for the same (uid, today, salt) --
    #    calling it twice gives the same answer (survives a "restart").
    pool = ["A", "B", "C", "D", "E"]
    v1 = bot._daily_text_variant(1, "2026-01-01", "salt", pool)
    v2 = bot._daily_text_variant(1, "2026-01-01", "salt", pool)
    assert v1 == v2
    print("1. _daily_text_variant is stable across repeated calls for the same day/uid/salt")

    # 2. Different salts for the SAME (uid, today) can diverge -- independent
    #    pools don't collapse onto the same hash.
    diverged = any(
        bot._daily_text_variant(1, "2026-01-01", f"salt{i}", pool) != bot._daily_text_variant(1, "2026-01-01", "salt0", pool)
        for i in range(1, 20)
    )
    assert diverged, "different salts must be able to pick different variants"
    print("2. Different salts (independent pools) can diverge for the same uid/day")

    # 3. Across many different days, the variant actually varies -- this is
    #    not secretly always the same element regardless of date.
    seen = {bot._daily_text_variant(1, f"2026-01-{d:02d}", "salt", pool) for d in range(1, 29)}
    assert len(seen) > 1, "the variant must actually rotate across different days"
    print("3. The variant rotates across different calendar days (not stuck on one)")

    # 4. Different uids on the SAME day can get different variants (not
    #    globally synchronized across all users).
    seen_uids = {bot._daily_text_variant(u, "2026-01-01", "salt", pool) for u in range(1, 30)}
    assert len(seen_uids) > 1, "different users must not all be forced onto the same variant"
    print("4. Different users can land on different variants on the same day")

    # 5. morning_notification's ordinary-day text uses one of the rotating
    #    MORNING_GREETINGS/MORNING_CLOSERS, with {name} correctly substituted.
    uid1 = 1
    make_user(uid1, "Артем", "M")
    app1 = FakeApp()
    await bot.morning_notification(app1, uid1)
    _, text1, _ = app1.bot.sent[0]
    assert any(g.format(name="Артем") in text1 for g in bot.MORNING_GREETINGS), text1
    assert any(bot.personalize(c, "M") in text1 for c in bot.MORNING_CLOSERS), text1
    print("5. morning_notification uses one of the rotating greetings/closers, with the name substituted")

    # 6. midday_notification (morning diary filled) uses one of MIDDAY_OPENERS.
    uid2 = 2
    make_user(uid2, "Вика", "F")
    bot.save_diary(uid2, "morning", {"focus": "Позвонить врачу"}, for_date=datetime.now(TBILISI).date().isoformat())
    app2 = FakeApp()
    await bot.midday_notification(app2, uid2)
    _, text2, _ = app2.bot.sent[0]
    assert any(o.format(name="Вика") in text2 for o in bot.MIDDAY_OPENERS), text2
    print("6. midday_notification (morning filled) uses one of the rotating MIDDAY_OPENERS")

    # 7. midday_notification (morning NOT filled) uses one of
    #    MIDDAY_NO_MORNING_OPENERS instead -- a different pool for a
    #    genuinely different situation, not reused verbatim.
    uid3 = 3
    make_user(uid3, "Игорь", "M")
    app3 = FakeApp()
    await bot.midday_notification(app3, uid3)
    _, text3, _ = app3.bot.sent[0]
    assert any(o.format(name="Игорь") in text3 for o in bot.MIDDAY_NO_MORNING_OPENERS), text3
    print("7. midday_notification (morning not filled) uses one of the rotating MIDDAY_NO_MORNING_OPENERS")

    # 8. evening_notification uses one of the (opener, subline) EVENING_OPENERS
    #    pairs, coherently (not mixing an opener from one pair with a subline
    #    from another).
    uid4 = 4
    make_user(uid4, "Соня", "F")
    app4 = FakeApp()
    await bot.evening_notification(app4, uid4)
    _, text4, _ = app4.bot.sent[0]
    matched = [(o, s) for o, s in bot.EVENING_OPENERS if o.format(name="Соня") in text4 and s in text4]
    assert len(matched) == 1, (text4, bot.EVENING_OPENERS)
    print("8. evening_notification uses one coherent (opener, subline) pair from EVENING_OPENERS")

    print("\nALL NOTIFICATION VARIETY TESTS PASSED")


asyncio.run(main())
