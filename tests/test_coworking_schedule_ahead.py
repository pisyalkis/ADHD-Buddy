import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_schedule_ahead.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 900
        self.texts = []

    async def edit_text(self, text, **kw):
        self.texts.append((text, kw.get("reply_markup")))
        return self

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.texts.append((text, kw.get("reply_markup")))
        return m


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeTextMsg:
    def __init__(self, uid_, text):
        self.chat_id = uid_
        self.text = text

    async def reply_text(self, text, **kw):
        return self


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 901
        return M()


class FakeCtx:
    def __init__(self, bot_=None):
        self.user_data = {}
        self.bot = bot_ or FakeBot()


def make_user(uid, name, tz_name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def find_tz_with_local_hour(target_hour):
    """Same Etc/GMT-offset trick used elsewhere in this test suite (e.g.
    test_weekly_report_monday.py's Monday-finder) -- pick a fixed-offset
    timezone where the CURRENT real time's local hour matches target_hour,
    so "is this time already past today?" is deterministic regardless of
    when the test actually runs."""
    for offset in range(-11, 13):
        candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
        try:
            tz = bot.pytz.timezone(candidate)
            if datetime.now(tz).hour == target_hour:
                return candidate
        except Exception:
            continue
    return None


async def start_and_enter_time(uid, tz_name, text):
    ctx = FakeCtx()
    ctx.user_data["awaiting_coworking_time"] = True
    ctx.user_data["awaiting_coworking_time_set_at"] = datetime.now().isoformat()
    upd = FakeUpdate(uid, text_message=FakeTextMsg(uid, text))
    await bot.handle_text(upd, ctx)
    return ctx


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-06): coworking sessions could only be
    # created for "today" -- body-doubling is exactly the kind of thing
    # that's natural to plan ahead, "tonight, for tomorrow at 9am", but the
    # feature had no way to do that at all (unlike reminders/evening plan).
    # ══════════════════════════════════════════════════════════════════════

    # 1. A plain "HH:MM" that is still in the FUTURE today schedules for
    #    TODAY, unchanged from before (no day note, no regression).
    morning_tz = find_tz_with_local_hour(10)
    if morning_tz is None:
        print("1. SKIPPED (no timezone currently at local hour 10)")
    else:
        uid1 = 1
        make_user(uid1, "Артем", morning_tz)
        ctx1 = await start_and_enter_time(uid1, morning_tz, "18:00")
        assert ctx1.user_data.get("coworking_pending_start_utc") is not None
        start_local1 = datetime.fromisoformat(ctx1.user_data["coworking_pending_start_utc"]).astimezone(bot.pytz.timezone(morning_tz))
        assert start_local1.date() == datetime.now(bot.pytz.timezone(morning_tz)).date(), \
            f"a future time today must stay today, got {start_local1}"
        print("1. A plain HH:MM still in the future today schedules for TODAY (no regression)")

    # 2. A plain "HH:MM" that has ALREADY PASSED today now auto-rolls to
    #    TOMORROW instead of being rejected -- the core fix.
    evening_tz = find_tz_with_local_hour(20)
    if evening_tz is None:
        print("2/3. SKIPPED (no timezone currently at local hour 20)")
    else:
        uid2 = 2
        make_user(uid2, "Вика", evening_tz)
        tz2 = bot.pytz.timezone(evening_tz)
        ctx2 = await start_and_enter_time(uid2, evening_tz, "09:00")  # 9am already passed at local hour 20
        pending2 = ctx2.user_data.get("coworking_pending_start_utc")
        assert pending2 is not None, "a past-today time must now be auto-scheduled for tomorrow, not rejected"
        start_local2 = datetime.fromisoformat(pending2).astimezone(tz2)
        tomorrow2 = (datetime.now(tz2).date() + timedelta(days=1))
        assert start_local2.date() == tomorrow2, f"expected tomorrow ({tomorrow2}), got {start_local2.date()}"
        assert start_local2.hour == 9 and start_local2.minute == 0
        print("2. A plain HH:MM already past today auto-rolls to TOMORROW instead of being rejected (bug fix)")

        # 3. Explicit "завтра HH:MM" schedules for tomorrow even when that
        #    time HASN'T passed today -- an intentional advance booking.
        uid3 = 3
        make_user(uid3, "Игорь", evening_tz)
        ctx3 = await start_and_enter_time(uid3, evening_tz, "завтра 21:30")  # 21:30 hasn't happened yet today (it's 20:xx)
        pending3 = ctx3.user_data.get("coworking_pending_start_utc")
        assert pending3 is not None
        start_local3 = datetime.fromisoformat(pending3).astimezone(tz2)
        tomorrow3 = (datetime.now(tz2).date() + timedelta(days=1))
        assert start_local3.date() == tomorrow3, \
            f"explicit 'завтра' must schedule for tomorrow even if the time hasn't passed today: {start_local3}"
        assert start_local3.hour == 21 and start_local3.minute == 30
        print("3. Explicit 'завтра HH:MM' schedules for tomorrow even when the time hasn't passed today")

    # 4. Invalid format is still rejected, with the updated hint mentioning
    #    the 'завтра' option.
    uid4 = 4
    make_user(uid4, "Соня", "Asia/Tbilisi")
    ctx4 = await start_and_enter_time(uid4, "Asia/Tbilisi", "не время")
    assert ctx4.user_data.get("awaiting_coworking_time") is True, "an unparseable reply must re-arm the flag for a retry"
    assert ctx4.user_data.get("coworking_pending_start_utc") is None
    print("4. An invalid format is still rejected and re-prompts for a retry")

    # 5. The open-sessions list and the session-creation confirmation mark a
    #    tomorrow session with "(завтра)" so it's not ambiguous next to a
    #    same-day one.
    if evening_tz is not None:
        tz2 = bot.pytz.timezone(evening_tz)
        uid5 = 5
        make_user(uid5, "Лена", evening_tz)
        ctx5 = await start_and_enter_time(uid5, evening_tz, "10:00")  # already past at local hour 20 -> tomorrow
        dur_msg = FakeMsg(uid5)
        upd_dur = FakeUpdate(uid5, data="coworking_dur_25", message=dur_msg)
        await bot.coworking_set_duration(upd_dur, ctx5)
        # coworking_set_duration confirms via send_tracked_notification (a
        # fresh bot.send_message), not by editing the button's own message.
        created_text = ctx5.bot.sent[-1][1] if ctx5.bot.sent else ""
        assert "завтра" in created_text, f"the creation confirmation must note it's for tomorrow: {created_text}"

        sessions = bot.get_open_coworking_sessions()
        tomorrow_session = next(s for s in sessions if s["creator_id"] == uid5)
        listing_text = bot._coworking_session_text(tomorrow_session, uid5, 1)
        assert "завтра" in listing_text, f"the session listing must note it's for tomorrow: {listing_text}"
        print("5. Both the creation confirmation and the session listing mark a tomorrow session with '(завтра)'")

    print("\nALL COWORKING-SCHEDULE-AHEAD TESTS PASSED")


asyncio.run(main())
