import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_day_card_evening_day.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # Нужна таймзона, реально находящаяся сейчас в окне 00:00-04:00 --
    # именно там evening_day(tz) расходится с календарной датой.
    midnight_tz = None
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            cand = pytz.timezone(candidate)
            if datetime.now(cand).hour < 4:
                midnight_tz = candidate
                break
        except Exception:
            continue

    if not midnight_tz:
        print("SKIPPED (no timezone currently in the 00:00-04:00 window -- harmless, rare)")
        return

    bot.update_user(uid, timezone=midnight_tz)
    tz = bot.get_user_tz(bot.get_user(uid))
    now = datetime.now(tz)
    real_today = now.date().isoformat()
    ev_day = bot.evening_day(tz).isoformat()
    assert ev_day != real_today, "sanity: evening_day must resolve to yesterday in this window"

    # ══════════════════════════════════════════════════════════════════════
    # Bug: closing the evening ritual just after midnight saves everything
    # under evening_day's date, but the Day Card screen used to default to
    # the plain calendar date -- showing "Пока пусто" right after the user
    # just finished their evening, instead of what they just wrote.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Сделать отчёт"}, for_date=ev_day)
    bot.save_diary(uid, "evening", {"e_a": "план на завтра"}, for_date=ev_day)

    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="go_daycard")
    await bot.show_day_card(upd, ctx)

    text = upd.callback_query.message.last_text
    assert "Пока пусто" not in text, \
        f"Day Card must show the evening_day entry just closed, not 'Пока пусто', got: {text}"
    assert "Сделать отчёт" in text and "план на завтра" in text, text
    print("1. Day Card defaults to evening_day's date right after closing the evening ritual past midnight")

    print("\nALL DAY-CARD-EVENING-DAY TESTS PASSED")


asyncio.run(main())
