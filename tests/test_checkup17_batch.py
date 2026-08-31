import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup17_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
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
        self.chat_id = 1
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_reply_markup(self, **kw):
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
        self.answers = []
    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data="", text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data) if text is None else None
        self.message = None
        if text is not None:
            self.message = FakeMsg()
            self.message.text = text


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def check_clears(handler, uid, data):
    ctx = FakeCtx()
    ctx.user_data["awaiting_feedback"] = True
    upd = FakeUpdate(uid, data=data)
    await handler(upd, ctx)
    assert ctx.user_data.get("awaiting_feedback") in (False, None), \
        f"{handler.__name__} must clear a stale awaiting_feedback flag, still set: {ctx.user_data.get('awaiting_feedback')}"


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (17th checkup, same class as rounds 14-16): 21 more handlers
    # reachable from persistent keyboards / notifications / commands never
    # cleared stale awaiting_* flags.
    # ══════════════════════════════════════════════════════════════════════
    await check_clears(bot.toggle_streak_visibility, uid, "toggle_streak_visibility")
    print("1. toggle_streak_visibility now clears stale awaiting flags")

    await check_clears(bot.edit_reports_menu, uid, "edit_reports")
    print("2. edit_reports_menu now clears stale awaiting flags")

    await check_clears(bot.toggle_field_callback, uid, "toggle_field_gratitude")
    print("3. toggle_field_callback now clears stale awaiting flags")

    await check_clears(bot.quickdisable_field_callback, uid, "quickdisable_gratitude")
    print("4. quickdisable_field_callback now clears stale awaiting flags")

    await check_clears(bot.dismiss_nudge_callback, uid, "dismiss_nudge")
    print("5. dismiss_nudge_callback now clears stale awaiting flags")

    await check_clears(bot.beacon_types_menu, uid, "beacon_types_menu")
    print("6. beacon_types_menu now clears stale awaiting flags")

    await check_clears(bot.toggle_beacon_type_callback, uid, "toggle_beacontype_stop")
    print("7. toggle_beacon_type_callback now clears stale awaiting flags")

    await check_clears(bot.toggle_notif, uid, "toggle_notif")
    print("8. toggle_notif now clears stale awaiting flags")

    await check_clears(bot.toggle_notif_block, uid, "toggle_morning")
    print("9. toggle_notif_block now clears stale awaiting flags")

    await check_clears(bot.toggle_beacon, uid, "toggle_beacon")
    print("10. toggle_beacon now clears stale awaiting flags")

    await check_clears(bot.beacon_set_interval, uid, "beacon_int_2")
    print("11. beacon_set_interval now clears stale awaiting flags")

    await check_clears(bot.toggle_skill_beacon, uid, "toggle_skill_beacon")
    print("12. toggle_skill_beacon now clears stale awaiting flags")

    await check_clears(bot.set_skill_beacon_mode, uid, "skill_mode_random")
    print("13. set_skill_beacon_mode now clears stale awaiting flags")

    await check_clears(bot.set_skill_beacon_interval, uid, "skill_int_15")
    print("14. set_skill_beacon_interval now clears stale awaiting flags")

    await check_clears(bot.set_skill_beacon_count, uid, "skill_count_3")
    print("15. set_skill_beacon_count now clears stale awaiting flags")

    await check_clears(bot.disable_notification_type, uid, "disable_notif_morning")
    print("16. disable_notification_type now clears stale awaiting flags")

    # pool_show_more was renamed to pool_change_page (task-pool pagination
    # redesign) and its callback_data prefix changed from "poolmore_" to
    # "poolpage_" -- same clear_awaiting_flags behavior, new name/prefix.
    await check_clears(bot.pool_change_page, uid, "poolpage_focus_3")
    print("17. pool_change_page (formerly pool_show_more) still clears stale awaiting flags")

    await check_clears(bot.buddy_menu, uid, "buddy_menu")
    print("18. buddy_menu now clears stale awaiting flags")

    await check_clears(bot.guide_start, uid, "guide_start")
    print("19. guide_start now clears stale awaiting flags")

    await check_clears(bot.guide_section, uid, "guide_what")
    print("20. guide_section now clears stale awaiting flags")

    # subscribe_command is a plain /subscribe command handler (no
    # callback_query) -- exercised via a text-style FakeUpdate instead.
    ctx_sub = FakeCtx()
    ctx_sub.user_data["awaiting_feedback"] = True
    upd_sub = FakeUpdate(uid, text="/subscribe")
    await bot.subscribe_command(upd_sub, ctx_sub)
    assert ctx_sub.user_data.get("awaiting_feedback") in (False, None), \
        f"subscribe_command must clear a stale awaiting_feedback flag, still set: {ctx_sub.user_data.get('awaiting_feedback')}"
    print("21. subscribe_command now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (17th checkup): g() is built for single WORDS -- its N-branch
    # naively appends "(а)" to the end of whatever `male` text is given. Used
    # with a full sentence (onboarding button) or identical male==female args
    # ("Вперёд"/"Вперёд"), it produced nonsense for gender="N" ("Другое").
    # Fixed by switching to personalize()/dropping the spurious gendering.
    # ══════════════════════════════════════════════════════════════════════
    ctx_gg = FakeCtx()
    ctx_gg.user_data["onboard_name"] = "Тест"
    upd_gg = FakeUpdate(uid, data="gender_N")
    await bot.got_gender(upd_gg, ctx_gg)
    gg_buttons = [b.text for row in upd_gg.callback_query.message.sent[-1][1].inline_keyboard for b in row]
    btn_text = next(t for t in gg_buttons if "проходил" in t)
    assert btn_text == "Да, проходил(а) — сразу к делу", btn_text
    assert "делу(а)" not in btn_text, btn_text
    print("22. Onboarding 'проходил(а)' button no longer mangles the sentence for gender=N (personalize, not g())")

    # finish_morning's closing line: "Вперёд" must not get a spurious "(а)"
    # appended just because gender="N" -- g(gender,'Вперёд','Вперёд') used to
    # do exactly that even though male==female (no real gender variation).
    ctx_fm = FakeCtx()
    msg_fm = FakeMsg()
    bot.save_diary(uid, "morning", {"focus": "Тест"}, for_date=datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat())
    await bot.finish_morning(msg_fm, uid, ctx_fm)
    assert "Вперёд(а)" not in msg_fm.last_text, msg_fm.last_text
    assert "Вперёд" in msg_fm.last_text, msg_fm.last_text
    print("23. finish_morning's 'Вперёд' closing line is no longer mangled by g() for gender=N")

    bot.update_user(uid, gender="M")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (17th checkup, same class as the notif_morning/midday/evening
    # past-time guard): answering "во сколько начинаешь работать" with a time
    # that has ALREADY passed today (e.g. it's 14:00, but habitually typed
    # "09:00") used to leave work_start_sent_date empty, so check_notifications
    # would fire "Пора начинать!" within the next minute -- right after the
    # user just answered the question.
    # ══════════════════════════════════════════════════════════════════════
    tz = bot.get_user_tz(bot.get_user(uid))
    now_tz = datetime.now(tz)
    if now_tz.hour == 0 and now_tz.minute < 2:
        print("24. SKIPPED (current local time too close to midnight to construct a reliably-past HH:MM) -- harmless, rare")
    else:
        past_time = (now_tz - timedelta(minutes=1)).strftime("%H:%M")
        ctx_ws = FakeCtx()
        ctx_ws.user_data["awaiting_work_start"] = True
        upd_ws = FakeUpdate(uid, text=past_time)
        await bot.handle_text(upd_ws, ctx_ws)
        today_iso = now_tz.date().isoformat()
        assert bot.get_user(uid).get("work_start_sent_date") == today_iso, \
            f"work_start_sent_date must be backdated to today when the entered time ({past_time}) has already passed, got {bot.get_user(uid).get('work_start_sent_date')!r}"
        print("24. Entering an already-passed work-start time correctly backdates work_start_sent_date (suppresses an immediate spurious reminder)")

        future_time = (now_tz + timedelta(minutes=5)).strftime("%H:%M")
        ctx_ws2 = FakeCtx()
        ctx_ws2.user_data["awaiting_work_start"] = True
        upd_ws2 = FakeUpdate(uid, text=future_time)
        await bot.handle_text(upd_ws2, ctx_ws2)
        assert bot.get_user(uid).get("work_start_sent_date") == "", \
            f"work_start_sent_date must stay empty when the entered time is still in the future, got {bot.get_user(uid).get('work_start_sent_date')!r}"
        print("25. Entering a still-upcoming work-start time leaves work_start_sent_date empty (normal reminder still fires later)")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (17th checkup, same class as weekly_report -- but opposite
    # direction): admin_stats' "active in last 7/30 days" is a rolling
    # "as of now" metric, not a closed-week report, so it should INCLUDE
    # today. The old today-7/today-30 with ">=" counted 8/31 dates instead
    # of 7/30.
    # ══════════════════════════════════════════════════════════════════════
    admin_uid = 999
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Admin', 'M')")
    conn.commit(); conn.close()
    bot.update_user(admin_uid, timezone=tz_name)
    admin_today = datetime.now(bot.get_user_tz(bot.get_user(admin_uid))).date()

    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Граница', 'F')")
    conn.commit(); conn.close()
    uid4 = 4
    # Exactly 7 calendar dates back (today-7) -- must NOT count under the
    # fixed "today-6..today" (7-date) window, only under the old buggy one.
    old_boundary = (admin_today - timedelta(days=7)).isoformat()
    bot.save_diary(uid4, "morning", {"focus": "х"}, for_date=old_boundary)

    class FakeAdminMsg:
        def __init__(self):
            self.sent = []
        async def reply_text(self, text, **kw):
            self.sent.append(text)

    class FakeAdminUpdate:
        def __init__(self, uid):
            self.effective_user = FakeUser(uid)
            self.message = FakeAdminMsg()

    upd_admin = FakeAdminUpdate(admin_uid)
    await bot.admin_stats(upd_admin, None)
    text = upd_admin.message.sent[0]
    import re
    m = re.search(r"Активны за 7 дней: \*(\d+)\*", text)
    assert m, text
    active7 = int(m.group(1))

    conn = sqlite3.connect(bot.DB_PATH)
    expected7 = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM diary WHERE date >= ?",
        ((admin_today - timedelta(days=6)).isoformat(),)
    ).fetchone()[0]
    conn.close()
    assert active7 == expected7, \
        f"admin_stats' 7-day window must be today-6..today (7 dates inclusive), expected {expected7}, got {active7}"
    # The boundary user (dated exactly today-7) must NOT be counted under the fixed window.
    conn = sqlite3.connect(bot.DB_PATH)
    boundary_in_window = conn.execute(
        "SELECT COUNT(*) FROM diary WHERE user_id=? AND date >= ?",
        (uid4, (admin_today - timedelta(days=6)).isoformat())
    ).fetchone()[0]
    conn.close()
    assert boundary_in_window == 0, "sanity: today-7 boundary user must fall outside the fixed today-6 window"
    print("26. admin_stats' 'active 7 days' window is today-6..today (7 dates inclusive of today), not an off-by-one 8-date window")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (17th checkup, direct analogue of the already-fixed
    # finish_evening C2/C3 gap): morning_start's "yesterday's plan" reminder
    # only showed A/B1/B2 and was gated on field A alone -- so a user who
    # explicitly skipped A but set B1/C1/C2/C3 saw NOTHING carried over.
    # ══════════════════════════════════════════════════════════════════════
    uid5 = 5
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (5, 'Пятый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid5, timezone=tz_name)
    tz5 = bot.get_user_tz(bot.get_user(uid5))
    yesterday_iso = (datetime.now(tz5).date() - timedelta(days=1)).isoformat()
    bot.save_diary(uid5, "evening", {
        "e_a": "", "skip_e_a": True,
        "e_b1": "", "e_b2": "Помыть окна",
        "e_c1": "Позвонить маме", "e_c2": "Полить цветы", "e_c3": "Прочитать главу",
    }, for_date=yesterday_iso)

    ctx5 = FakeCtx()
    upd5 = FakeUpdate(uid5, data="morning_start")
    await bot.morning_start(upd5, ctx5)
    all_sent5 = "\n".join(t for t, _ in upd5.callback_query.message.sent)
    assert "Помыть окна" in all_sent5, all_sent5
    assert "Позвонить маме" in all_sent5, all_sent5
    assert "Полить цветы" in all_sent5, all_sent5
    assert "Прочитать главу" in all_sent5, all_sent5
    print("27. morning_start now shows the full B1/B2/C1/C2/C3 carry-over even when A was explicitly skipped")

    # Sanity: when NOTHING was set yesterday at all, no carry-over block appears.
    uid6 = 6
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (6, 'Шестой', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid6, timezone=tz_name)
    ctx6 = FakeCtx()
    upd6 = FakeUpdate(uid6, data="morning_start")
    await bot.morning_start(upd6, ctx6)
    all_sent6 = "\n".join(t for t, _ in upd6.callback_query.message.sent)
    assert "Помни" not in all_sent6, all_sent6
    print("28a. morning_start shows no carry-over block when yesterday's evening plan is entirely empty")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (17th checkup): has_any_diary_ever checked ANY diary block,
    # but finish_morning already saves a "morning" row before the evening
    # selfcare checklist is ever reached -- so on a brand-new user's very
    # first day (morning then evening, same day), the "skip checklist for
    # genuine first-timers" branch never actually triggered. Renamed to
    # has_any_evening_diary_ever and filtered to block='evening'.
    # ══════════════════════════════════════════════════════════════════════
    uid7 = 7
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (7, 'Седьмой', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid7, timezone=tz_name)
    today7 = datetime.now(bot.get_user_tz(bot.get_user(uid7))).date().isoformat()
    # Brand-new user's first morning already saved -- but no EVENING diary yet.
    bot.save_diary(uid7, "morning", {"focus": "Первый день"}, for_date=today7)
    assert bot.has_any_evening_diary_ever(uid7) is False, \
        "a user with only a morning diary entry must not count as having any evening diary yet"
    print("28b. has_any_evening_diary_ever correctly ignores morning-only diary history (genuine evening first-timer)")

    bot.save_diary(uid7, "evening", {"e_energy": 3}, for_date=today7)
    assert bot.has_any_evening_diary_ever(uid7) is True, \
        "after an evening diary entry exists, has_any_evening_diary_ever must return True"
    print("28c. has_any_evening_diary_ever correctly returns True once a real evening diary entry exists")

    print("\nALL CHECKUP17-BATCH TESTS PASSED")


asyncio.run(main())
