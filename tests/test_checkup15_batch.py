import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup15_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
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
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtxBot:
    async def send_invoice(self, **kw): pass
    async def send_message(self, chat_id, text, **kw):
        class _M:
            message_id = 999999
        return _M()
    async def delete_message(self, chat_id, message_id): pass


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeCtxBot()


class FakeAppBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
    async def send_animation(self, **kw):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeAppBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"
    uid = 1
    bot.update_user(uid, timezone=tz_name)

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (15th checkup, same class as round 14's go_about/go_privacy/
    # go_subscribe*/successful_payment_callback fixes): research_callback,
    # focus_start_callback, focus_stop_callback, and midday_callback all
    # arrive via a notification's own inline keyboard (not the persistent
    # menu) and never cleared a stale awaiting_* flag left over from before
    # the notification arrived.
    # ══════════════════════════════════════════════════════════════════════
    async def check_clears(handler, data, extra_setup=None):
        ctx = FakeCtx()
        ctx.user_data["awaiting_feedback"] = True
        if extra_setup:
            extra_setup()
        upd = FakeUpdate(uid, data=data)
        await handler(upd, ctx)
        assert ctx.user_data.get("awaiting_feedback") in (False, None), \
            f"{handler.__name__} must clear a stale awaiting_feedback flag, still set: {ctx.user_data.get('awaiting_feedback')}"

    await check_clears(bot.research_callback, "research_3_3")
    print("1a. research_callback now clears stale awaiting flags")

    bot.update_user(uid, focus_active=0, focus_end_time="")
    await check_clears(bot.focus_start_callback, "focus_start_25")
    print("1b. focus_start_callback now clears stale awaiting flags")

    bot.update_user(uid, focus_active=1,
                     focus_end_time=datetime.now(bot.get_user_tz(bot.get_user(uid))).isoformat(),
                     focus_duration=25)
    await check_clears(bot.focus_stop_callback, "focus_stop")
    print("1c. focus_stop_callback now clears stale awaiting flags")

    await check_clears(bot.midday_callback, "mid_resting")
    print("1d. midday_callback now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (15th checkup): grant30_callback (the "🎁 +30" button in
    # /users, admin-only) never cleared admin_msg_target -- if the admin
    # had just tapped a user's name (arming admin_msg_target to forward the
    # next message verbatim) and tapped "🎁 +30" instead, the flag stayed
    # armed and silently hijacked the admin's next ordinary message.
    # ══════════════════════════════════════════════════════════════════════
    bot.NOTIFY_USER_ID = uid  # make this uid the admin for this check
    ctx_admin = FakeCtx()
    ctx_admin.user_data["admin_msg_target"] = 12345
    ctx_admin.user_data["admin_msg_name"] = "Кто-то другой"
    upd_admin = FakeUpdate(uid, data=f"grant30_{uid}")
    await bot.grant30_callback(upd_admin, ctx_admin)
    assert "admin_msg_target" not in ctx_admin.user_data, \
        f"grant30_callback must clear a stale admin_msg_target, still set: {ctx_admin.user_data.get('admin_msg_target')}"
    print("1e. grant30_callback now clears a stale admin_msg_target")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (15th checkup, direct sibling of round 14's overnight-window
    # fix): _skill_beacon_due's "already used this target" filter compared
    # last_dt.date() to now.date() using raw CALENDAR dates -- but for an
    # overnight window, _skill_beacon_random_times deliberately returns the
    # SAME target list on both sides of midnight (seeded by the window's
    # start date). If the beacon fired before midnight (last_dt = yesterday)
    # and the next tick lands after midnight (now.date() = today), the
    # dates don't match, the filter is skipped, and the already-used
    # evening target is treated as still due -- an immediate duplicate fire
    # right after midnight.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, beacon_start="22:00", beacon_end="06:00",
                     skill_beacon_mode="random", skill_beacon_daily_count=3)
    user = bot.get_user(uid)
    tz = bot.get_user_tz(user)
    # Fixed, deterministic target list spanning midnight -- monkeypatched so
    # this test isolates _skill_beacon_due's OWN date-comparison logic from
    # _skill_beacon_random_times' separate (already-fixed-elsewhere, round
    # 14 / PR #130) window-anchoring behavior.
    day = datetime.now(tz).date()
    base = tz.localize(datetime.combine(day, datetime.min.time()).replace(hour=23, minute=47))
    fixed_targets = [base, base + timedelta(hours=2, minutes=22), base + timedelta(hours=5, minutes=17)]
    first_target = fixed_targets[0]
    orig_random_times = bot._skill_beacon_random_times
    bot._skill_beacon_random_times = lambda user, now, count: fixed_targets
    try:
        # Simulate: the beacon fired at exactly the first (evening) target.
        bot.update_user(uid, skill_beacon_last_sent=first_target.isoformat())
        user_after = bot.get_user(uid)
        after_midnight = first_target + timedelta(hours=2)  # e.g. 01:47, still before target #2 (02:09)
        due = bot._skill_beacon_due(user_after, after_midnight)
    finally:
        bot._skill_beacon_random_times = orig_random_times
    assert not due, \
        f"_skill_beacon_due must not re-fire for an already-used target just because the calendar date rolled over, but returned True at {after_midnight} (last_dt={first_target})"
    print("2. _skill_beacon_due no longer re-fires an already-used overnight-window target right after midnight")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (15th checkup): Russian day-count pluralization used the
    # simplified "1 -> день, 2-4 -> дня, else -> дней" formula, wrong for
    # 11-14 (and any number ending in 11-14, e.g. 21 vs 11): "11 дня"
    # instead of "11 дней", "21 дней" instead of "21 день".
    # ══════════════════════════════════════════════════════════════════════
    assert bot.ru_days(1) == "день", bot.ru_days(1)
    assert bot.ru_days(2) == "дня", bot.ru_days(2)
    assert bot.ru_days(4) == "дня", bot.ru_days(4)
    assert bot.ru_days(5) == "дней", bot.ru_days(5)
    assert bot.ru_days(11) == "дней", bot.ru_days(11)
    assert bot.ru_days(12) == "дней", bot.ru_days(12)
    assert bot.ru_days(14) == "дней", bot.ru_days(14)
    assert bot.ru_days(21) == "день", bot.ru_days(21)
    assert bot.ru_days(22) == "дня", bot.ru_days(22)
    assert bot.ru_days(25) == "дней", bot.ru_days(25)
    assert bot.ru_days(111) == "дней", bot.ru_days(111)
    print("3. ru_days() now correctly handles the 11-14 Russian pluralization exception")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (15th checkup, same class as the round-9 stale-snapshot
    # duplicate-beacon bug): check_notifications computed notif_master_on
    # ONCE from the tick-start user snapshot, then used that same stale
    # value to gate the research-question send AFTER already re-fetching a
    # fresh `user` for the beacon calls. If the user disabled notifications
    # during one of the earlier awaits in the same tick, the stale
    # notif_master_on still let the research question through.
    # ══════════════════════════════════════════════════════════════════════
    import pytz as _pytz
    found_tz = None
    for off in range(-12, 13):
        name = f"Etc/GMT{-off:+d}" if off != 0 else "Etc/GMT"
        try:
            tzc = _pytz.timezone(name)
        except Exception:
            continue
        if 10 <= datetime.now(tzc).hour <= 12:
            found_tz = name
            break

    if found_tz is None:
        print("4. SKIPPED notif_master_on staleness test -- no Etc/GMT zone currently in the 10-12h window")
    else:
        conn = sqlite3.connect(bot.DB_PATH)
        conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Ник', 'M')")
        conn.commit(); conn.close()
        uid2 = 2
        tz2 = _pytz.timezone(found_tz)
        created = (datetime.now(tz2) - timedelta(days=3)).date().isoformat()
        bot.update_user(
            uid2, timezone=found_tz, notif_enabled=1, created_at=created, research_done="",
            notif_morning="23:59", notif_midday="23:59", notif_evening="23:59",
            notif_morning_on=0, notif_midday_on=0, notif_evening_on=0,
            beacon_enabled=0, skill_beacon_enabled=0,
            work_start_date="", resume_check_due="", focus_active=0,
            weekly_report_sent_date=datetime.now(tz2).date().isoformat(),
        )

        orig_send_task_beacon = bot.send_task_beacon
        async def fake_send_task_beacon(app, user):
            # Simulate the user disabling notifications via a concurrent
            # action while this tick is mid-flight on an earlier await.
            bot.update_user(uid2, notif_enabled=0)
            return await orig_send_task_beacon(app, user)
        bot.send_task_beacon = fake_send_task_beacon

        research_calls = []
        orig_send_research_question = bot.send_research_question
        async def fake_send_research_question(app, uid_, milestone):
            research_calls.append(milestone)
        bot.send_research_question = fake_send_research_question

        try:
            app2 = FakeApp()
            await bot.check_notifications(app2)
        finally:
            bot.send_task_beacon = orig_send_task_beacon
            bot.send_research_question = orig_send_research_question

        assert research_calls == [], \
            f"the research question must NOT be sent once notif_enabled was turned off mid-tick, but it fired for milestone(s) {research_calls}"
        print("4. check_notifications no longer sends the research question with a stale notif_master_on after mid-tick notif_enabled changes")

    print("\nALL CHECKUP15-BATCH TESTS PASSED")


asyncio.run(main())
