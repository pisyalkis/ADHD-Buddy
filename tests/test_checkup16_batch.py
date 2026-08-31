import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup16_batch.db")
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
    def __init__(self, fail_send=False):
        self.sent = []
        self.bot = FakeBot()
        self.fail_send = fail_send
    async def reply_text(self, text, **kw):
        if self.fail_send:
            raise RuntimeError("simulated Telegram send failure")
        self.sent.append((text, kw.get("reply_markup")))
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
        self.callback_query = FakeQuery(uid, data)
        self.message = None
        if text is not None:
            self.message = FakeMsg()
            self.message.text = text


class FakeCtxBot:
    def __init__(self):
        self.fail_send = False
    async def send_message(self, chat_id, text, **kw):
        if self.fail_send:
            raise RuntimeError("simulated Telegram send failure")
        class _M:
            message_id = 999999
        return _M()
    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self, args=None):
        self.args = args or []
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
    # Real bug (16th checkup): with_privacy_hint marked privacy_hint_shown
    # in the DB BEFORE the message was actually sent.
    # ══════════════════════════════════════════════════════════════════════
    msg_fail = FakeMsg(fail_send=True)
    try:
        await bot.ask_writing(msg_fail, FakeCtx(), uid)
    except RuntimeError:
        pass
    still_unshown = bot.get_user(uid).get("privacy_hint_shown") or ""
    assert "m_writing" not in still_unshown.split(","), \
        f"privacy_hint_shown must NOT be marked when the send fails, got {still_unshown!r}"
    print("1a. send_with_privacy_hint does not mark the hint shown when the send fails")

    msg_ok = FakeMsg(fail_send=False)
    await bot.ask_writing(msg_ok, FakeCtx(), uid)
    assert "🔒" in msg_ok.last_text, msg_ok.last_text
    shown_now = bot.get_user(uid).get("privacy_hint_shown") or ""
    assert "m_writing" in shown_now.split(","), shown_now
    print("1b. send_with_privacy_hint marks the hint shown after a successful send")

    msg_second = FakeMsg(fail_send=False)
    await bot.ask_writing(msg_second, FakeCtx(), uid)
    assert "🔒" not in msg_second.last_text, msg_second.last_text
    print("1c. send_with_privacy_hint does not repeat the hint on subsequent calls")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup): quick_toggle_beacon/quick_toggle_skill live on
    # the pinned daily-summary message and never cleared awaiting flags.
    # ══════════════════════════════════════════════════════════════════════
    await check_clears(bot.quick_toggle_beacon, uid, "quick_toggle_beacon")
    print("2a. quick_toggle_beacon now clears stale awaiting flags")
    await check_clears(bot.quick_toggle_skill, uid, "quick_toggle_skill")
    print("2b. quick_toggle_skill now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup): promo_command's /promo CODE branch (the way
    # /blogger tells users to redeem) never cleared awaiting flags, unlike
    # its own no-args branch.
    # ══════════════════════════════════════════════════════════════════════
    ctx_promo = FakeCtx(args=["NOSUCHCODE"])
    ctx_promo.user_data["awaiting_feedback"] = True
    upd_promo = FakeUpdate(uid, text="/promo NOSUCHCODE")
    upd_promo.message = FakeMsg()
    upd_promo.message.text = "/promo NOSUCHCODE"
    await bot.promo_command(upd_promo, ctx_promo)
    assert ctx_promo.user_data.get("awaiting_feedback") in (False, None), \
        f"promo_command's /promo CODE branch must clear a stale awaiting_feedback flag, still set: {ctx_promo.user_data.get('awaiting_feedback')}"
    print("3. promo_command (/promo CODE branch) now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup): research_callback wrote research_awaiting to
    # the DB BEFORE the open-text follow-up question was confirmed sent, for
    # all three day3/day7/day14 branches.
    # ══════════════════════════════════════════════════════════════════════
    for data, day_label in [("research_3_5", "day3"), ("research_7_yes", "day7"), ("research_14_9", "day14")]:
        bot.update_user(uid, research_awaiting="0", research_done="")
        upd_r = FakeUpdate(uid, data=data)
        ctx_r = FakeCtx()
        ctx_r.bot.fail_send = True
        try:
            await bot.research_callback(upd_r, ctx_r)
        except RuntimeError:
            pass
        still0 = bot.get_user(uid).get("research_awaiting")
        assert str(still0) in ("0", "", "None") or still0 in (0, None), \
            f"research_awaiting ({day_label}) must not be set when the open-question send fails, got {still0!r}"
    print("4. research_callback no longer sets research_awaiting before the open question actually sends (day3/7/14)")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup): beacon_technique_done never cleared awaiting
    # flags (arrives from a background-scheduled beacon message).
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Test"}, for_date=datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat())
    await check_clears(bot.beacon_technique_done, uid, "beacon_technique_done")
    print("5. beacon_technique_done now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup): walk_skip_callback relied only on
    # _walk_to_step's partial clear_awaiting_flags(ctx) (no `update`), so
    # research_awaiting (DB) and an active conversation weren't cleared.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, research_awaiting="3_open:test")
    ctx_walk = FakeCtx()
    upd_walk = FakeUpdate(uid, data="walk_skip_focus")
    await bot.walk_skip_callback(upd_walk, ctx_walk)
    after_walk = bot.get_user(uid).get("research_awaiting")
    assert str(after_walk) in ("0", "", "None") or after_walk in (0, None), \
        f"walk_skip_callback must clear the DB research_awaiting flag too (full clear, not just ctx.user_data), got {after_walk!r}"
    print("6. walk_skip_callback now does a full clear_awaiting_flags (DB research_awaiting included)")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup): pool_write_own / pool_use_item set
    # awaiting_task_edit without a prior full clear_awaiting_flags.
    # ══════════════════════════════════════════════════════════════════════
    await check_clears(bot.pool_write_own, uid, "poolwrite_focus")
    print("7a. pool_write_own now clears stale awaiting flags")

    bot.add_pool_task(uid, "Купить молоко")
    pool_item = bot.get_pool_tasks(uid)[0]
    await check_clears(bot.pool_use_item, uid, f"pooluse_focus_{pool_item['id']}")
    print("7b. pool_use_item now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (16th checkup, broader than round 15's fix): notif_master_on
    # was read from the per-tick snapshot taken once at the very start of
    # check_notifications (get_all_notif_users()), before ANY awaits for
    # ANY user -- so if the tick takes real wall-clock time processing many
    # users (or even just this same user's own earlier sends), a user who
    # disabled notifications after that snapshot was taken could still get
    # their midday/weekly/evening/+2h-reminder notification. Uses
    # notif_midday="00:00" to make the "is it midday time yet" gate always
    # true, avoiding real-clock dependency.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Ник', 'M')")
    conn.commit(); conn.close()
    bot.update_user(
        uid2, timezone=tz_name, notif_enabled=1,
        notif_midday="00:00", notif_midday_on=1, midday_sent_date="",
        notif_morning="23:59", notif_morning_on=0, morning_sent_date=datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat(),
        notif_evening_on=0, weekly_report_sent_date=datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat(),
        morning_reminder_sent_date=datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat(),
        beacon_enabled=0, skill_beacon_enabled=0, work_start_date="",
        resume_check_due="", focus_active=0, research_done="3,7,14,30",
    )
    stale_row = dict(bot.get_user(uid2))
    stale_row["notif_enabled"] = 1  # the stale in-memory snapshot check_notifications would have used
    orig_get_all = bot.get_all_notif_users
    bot.get_all_notif_users = lambda: [stale_row]
    bot.update_user(uid2, notif_enabled=0)  # DB already has it disabled by the time the tick reaches this user
    try:
        app = FakeApp()
        await bot.check_notifications(app)
    finally:
        bot.get_all_notif_users = orig_get_all
    sent_to_uid2 = [(cid, t) for cid, t, _ in app.bot.sent if cid == uid2]
    assert not sent_to_uid2, \
        f"check_notifications must not send the midday notification once notif_enabled was disabled before this user's own iteration started, got {sent_to_uid2}"
    print("8. check_notifications now re-reads notif_enabled fresh at the start of each user's own iteration")

    print("\nALL CHECKUP16-BATCH TESTS PASSED")


asyncio.run(main())
