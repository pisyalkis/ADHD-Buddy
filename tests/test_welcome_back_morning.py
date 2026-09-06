import os, sys, asyncio, sqlite3, json
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_welcome_back_morning.db")
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


def make_user(uid, name, streak_days_ago=None):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    if streak_days_ago is not None:
        last_active = (bot.evening_day(TBILISI) - timedelta(days=streak_days_ago)).isoformat()
        bot.update_user(uid, streak=json.dumps([last_active]))


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-26): after a multi-day skip, the ADHD/
    # shame-prone audience this bot targets gets the exact same "☀️ Доброе
    # утро! Навык дня: ..." as any ordinary day -- no acknowledgement of the
    # gap, no permission to just start fresh. Swap in a softer greeting
    # (no streak mention, no reference to "yesterday") once the gap since
    # the last real activity (finish_morning/finish_evening -- streak dates,
    # not just opening the bot) crosses WELCOME_BACK_GAP_DAYS.
    # ══════════════════════════════════════════════════════════════════════

    # 1. _days_since_last_activity: empty streak -> None (new user, not "returning").
    uid0 = 0
    make_user(uid0, "Новичок")
    assert bot._days_since_last_activity(uid0) is None
    print("1. _days_since_last_activity is None for a brand-new user with no streak yet")

    # 2. _days_since_last_activity: correct gap computation.
    uid1 = 1
    make_user(uid1, "Артем", streak_days_ago=5)
    assert bot._days_since_last_activity(uid1) == 5, bot._days_since_last_activity(uid1)
    print("2. _days_since_last_activity correctly computes the gap from the streak's latest date")

    # 3. A 5-day gap (>= WELCOME_BACK_GAP_DAYS) -> soft welcome-back text,
    #    no streak/"yesterday" mentions.
    app = FakeApp()
    await bot.morning_notification(app, uid1)
    assert app.bot.sent, "sanity: morning_notification must send something"
    _chat, text, _kb = app.bot.sent[0]
    assert "С возвращением" in text, text
    assert "стрик" in text.lower()
    assert "Доброе утро" not in text, "the routine greeting must not also appear"
    assert "вчера" not in text.lower(), f"a soft welcome-back must not reference 'yesterday', got: {text}"
    print("3. A 5-day gap triggers the soft welcome-back greeting, without streak-shaming or 'yesterday' references")

    # 4. A fresh user (gap below threshold, e.g. yesterday) -> the ordinary
    #    routine greeting, unchanged.
    uid2 = 2
    make_user(uid2, "Вика", streak_days_ago=1)
    app2 = FakeApp()
    await bot.morning_notification(app2, uid2)
    _chat2, text2, _kb2 = app2.bot.sent[0]
    # Приветствие ротируется (см. MORNING_GREETINGS/_daily_text_variant) —
    # проверяем, что это ОДИН ИЗ обычных вариантов, а не жёстко один текст.
    assert any(g.format(name="Вика") in text2 for g in bot.MORNING_GREETINGS), text2
    assert "С возвращением" not in text2, text2
    print("4. A 1-day gap (ordinary case) still gets one of the normal rotating greetings (no regression)")

    # 5. Brand-new user (no streak at all yet) -> also the ordinary greeting,
    #    not treated as "returning".
    app3 = FakeApp()
    await bot.morning_notification(app3, uid0)
    _chat3, text3, _kb3 = app3.bot.sent[0]
    assert any(g.format(name="Новичок") in text3 for g in bot.MORNING_GREETINGS), text3
    print("5. A brand-new user (no streak yet) also gets one of the ordinary rotating greetings, not the welcome-back one")

    print("\nALL WELCOME-BACK-MORNING TESTS PASSED")


asyncio.run(main())
