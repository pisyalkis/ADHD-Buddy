import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_edit_in_place_sections.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.edit_should_fail = False
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message too old to edit")
        self.edited.append((text, kw.get("reply_markup")))
    async def reply_animation(self, **kw):
        class _A:
            animation = None
        return _A()


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


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeTrackedBot()


class FakeTrackedMsg:
    _next_id = [71000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeTrackedMsg._next_id[0]
        FakeTrackedMsg._next_id[0] += 1


class FakeTrackedBot:
    def __init__(self):
        self.sent = []
        self.deleted = []
    async def send_message(self, chat_id, text, **kw):
        m = FakeTrackedMsg(chat_id)
        self.sent.append((chat_id, text, kw.get("reply_markup"), m.message_id))
        return m
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeCtxWithBot:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def run_edits(uid, handler, data=""):
    """Runs handler twice: once where edit_text succeeds (must edit, not
    send), once where edit_text fails (must fall back to reply_text)."""
    upd_ok = FakeUpdate(uid, data=data)
    await handler(upd_ok, FakeCtx())
    assert len(upd_ok.callback_query.message.edited) >= 1, \
        f"{handler.__name__} did not edit the existing message"
    assert len(upd_ok.callback_query.message.sent) == 0, \
        f"{handler.__name__} sent a new message even though editing succeeded"

    upd_fail = FakeUpdate(uid, data=data)
    upd_fail.callback_query.message.edit_should_fail = True
    await handler(upd_fail, FakeCtx())
    assert len(upd_fail.callback_query.message.sent) >= 1, \
        f"{handler.__name__} did not fall back to a new message when editing failed"


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: after the menu got its "tabs edit in place" mechanic,
    # the actual sections you drill into from those tabs still sent a fresh
    # message every time. Extended the same _edit_or_send mechanic to every
    # top-level section reachable from the tab bar.
    # ══════════════════════════════════════════════════════════════════════
    await run_edits(uid, bot.coach_menu, "go_coach")
    print("1. coach_menu edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.show_skill, "go_skill")
    print("2. show_skill edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.show_streak, "go_streak")
    print("3. show_streak (normal branch) edits in place, falls back on failure")

    # streak_hidden branch is a separate code path -- must also edit in place.
    bot.update_user(uid, streak_hidden=1)
    await run_edits(uid, bot.show_streak, "go_streak")
    bot.update_user(uid, streak_hidden=0)
    print("4. show_streak (streak_hidden branch) edits in place, falls back on failure")

    await run_edits(uid, bot.show_tasks, "go_tasks")
    print("5. show_tasks edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.show_reminders, "go_reminders")
    print("6. show_reminders edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.show_day_card, "go_daycard")
    print("7. show_day_card edits in place, falls back to a new message on failure")

    # Since the single-actual-message work extended to the focus timer
    # (its own notif_msg_ids channel "focus_timer", shared across
    # go_focus/focus_start/focus_stop/send_focus_end so the whole
    # lifecycle stays on one message) -- go_focus no longer edits q.message
    # directly, it sends via ctx.bot through send_tracked_notification.
    fbot = FakeTrackedBot()
    ctx_focus = FakeCtxWithBot(fbot)
    upd_focus = FakeUpdate(uid, data="go_focus")
    await bot.go_focus(upd_focus, ctx_focus)
    assert len(fbot.sent) == 1 and "На сколько минут" in fbot.sent[0][1], fbot.sent
    print("8. go_focus (no active timer) sends via the tracked focus_timer channel")

    # focus_active branch is a separate code path -- must also go through
    # the same tracked channel (replacing whatever was sent above).
    tz = bot.get_user_tz(bot.get_user(uid))
    end_dt = datetime.now(tz) + timedelta(minutes=20)
    bot.update_user(uid, focus_active=1, focus_end_time=end_dt.isoformat())
    upd_focus2 = FakeUpdate(uid, data="go_focus")
    await bot.go_focus(upd_focus2, ctx_focus)
    assert len(fbot.sent) == 2 and "Таймер уже идёт" in fbot.sent[1][1], fbot.sent
    assert (uid, fbot.sent[0][3]) in fbot.deleted, \
        "the previous focus_timer message must be deleted before sending the new one"
    bot.update_user(uid, focus_active=0)
    print("9. go_focus (timer already running) replaces the previous tracked focus_timer message")

    await run_edits(uid, bot.go_about, "go_about")
    print("10. go_about edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.show_whats_new, "go_whats_new")
    print("11. show_whats_new (with changelog) edits in place, falls back on failure")

    # Empty-CHANGELOG branch is a separate code path -- must also edit in place.
    real_changelog = bot.CHANGELOG
    bot.CHANGELOG = []
    await run_edits(uid, bot.show_whats_new, "go_whats_new")
    bot.CHANGELOG = real_changelog
    print("12. show_whats_new (empty changelog) edits in place, falls back on failure")

    await run_edits(uid, bot.go_feedback, "go_feedback")
    print("13. go_feedback edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.go_subscribe, "go_subscribe")
    print("14. go_subscribe edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.buddy_menu, "go_buddy")
    print("15. buddy_menu edits in place, falls back to a new message on failure")

    # Real gap from the audit: reroll_skill_callback/show_skill_detail/
    # buddy_ping used to send a brand new message instead of editing the
    # screen the person was already looking at.
    await run_edits(uid, bot.reroll_skill_callback, "reroll_skill")
    print("16. reroll_skill_callback edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.show_skill_detail, "skill_0")
    print("17. show_skill_detail edits in place, falls back to a new message on failure")

    bot.update_user(uid, buddy_name="Маша")
    await run_edits(uid, bot.buddy_ping, "buddy_ping")
    print("18. buddy_ping edits in place, falls back to a new message on failure")

    # Real request: 📖 О СДВГ paged through brand new messages per section
    # instead of editing the screen the person was already looking at.
    await run_edits(uid, bot.guide_start, "go_guide")
    print("19. guide_start (📖 О СДВГ entry) edits in place, falls back to a new message on failure")

    await run_edits(uid, bot.guide_section, "guide_why")
    print("20. guide_section (paging between sections) edits in place, falls back on failure")

    # Real request: "А что с приватностью?" should open in the same window
    # it was opened from, not send a new message.
    await run_edits(uid, bot.go_privacy, "go_privacy")
    print("21. go_privacy edits in place, falls back to a new message on failure")

    print("\nALL EDIT-IN-PLACE SECTION TESTS PASSED")


asyncio.run(main())
