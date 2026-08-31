import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup19_batch.db")
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


class FakeCtxBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class _M:
            message_id = 999999
        return _M()
    async def delete_message(self, chat_id, message_id):
        pass


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
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup): "N дней" hardcoded in /blogger's copy-paste
    # text and in _grant_and_notify, regardless of the actual day count.
    # ══════════════════════════════════════════════════════════════════════
    ctx_blog = FakeCtx()
    upd_blog = FakeUpdate(999, text="/blogger Имя 21")
    bot.NOTIFY_USER_ID = 999
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Admin', 'M')")
    conn.commit(); conn.close()
    ctx_blog.args = ["Имя", "21"]
    await bot.blogger_command(upd_blog, ctx_blog)
    blog_text = upd_blog.message.sent[0][0]
    assert "21 день" in blog_text, blog_text
    assert "21 дней" not in blog_text, blog_text
    print("1a. /blogger's promo text correctly says '21 день', not '21 дней'")

    app_grant = FakeApp()
    ctx_grant = FakeCtx()
    ctx_grant.bot = app_grant.bot
    await bot._grant_and_notify(ctx_grant, uid, 21)
    grant_text = app_grant.bot.sent[-1][1]
    assert "21 день" in grant_text, grant_text
    assert "21 дней" not in grant_text, grant_text
    print("1b. _grant_and_notify correctly says '21 день', not '21 дней'")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup): PROBLEM_TO_SKILLS was missing the whole
    # "self-esteem" onboarding group (self_esteem/self_talk/
    # unfinished_shame/memory_yesterday) -- picking only these struggles
    # silently degraded to the unfiltered, non-personalized skill pool.
    # ══════════════════════════════════════════════════════════════════════
    for struggle in ("self_esteem", "self_talk", "unfinished_shame", "memory_yesterday"):
        assert struggle in bot.PROBLEM_TO_SKILLS and bot.PROBLEM_TO_SKILLS[struggle], \
            f"{struggle} must have a real skill mapping"
        bot.update_user(uid, struggles=struggle)
        indices = bot._daily_skill_indices(bot.get_user(uid))
        assert len(indices) < len(bot.SKILLS), \
            f"struggle={struggle!r} must still narrow the skill pool (personalization must not silently degrade to the full unfiltered pool), got {len(indices)} of {len(bot.SKILLS)}"
    print("2. PROBLEM_TO_SKILLS now covers the self-esteem onboarding group -- personalization no longer silently degrades")
    bot.update_user(uid, struggles="")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup, same class as round 18's morning_notification
    # fix but in the DIFFERENT, interactive morning_start handler): showed
    # the full B1/B2 plan right next to "only task A matters" on a
    # low-energy day.
    # ══════════════════════════════════════════════════════════════════════
    yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    bot.save_diary(uid, "evening", {
        "e_a": "Задача A", "e_b1": "Задача B1", "e_b2": "Задача B2", "e_energy": 1,
    }, for_date=yesterday)
    ctx_ms = FakeCtx()
    upd_ms = FakeUpdate(uid, data="morning_start")
    await bot.morning_start(upd_ms, ctx_ms)
    ms_text = "\n".join(t for t, _ in upd_ms.callback_query.message.sent)
    assert "Задача B1" not in ms_text, ms_text
    assert "Задача B2" not in ms_text, ms_text
    assert "Задача A" in ms_text, ms_text
    assert "одна задача A" in ms_text, ms_text
    print("3. morning_start no longer shows a full B1/B2 plan alongside 'only task A matters' on a low-energy day")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup): enabling skill-beacon reminders (either the
    # pinned-card quick toggle or the settings screen) while beacon_types
    # was empty gave a confident "included!" confirmation, but
    # next_beacon_slot/_beacon_rotation_pool silently returned None forever
    # -- the feature would never actually fire.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, skill_beacon_enabled=0, beacon_types="")
    ctx_qts = FakeCtx()
    upd_qts = FakeUpdate(uid, data="quick_toggle_skill")
    await bot.quick_toggle_skill(upd_qts, ctx_qts)
    after_qts = bot.get_user(uid)
    assert int(after_qts.get("skill_beacon_enabled") or 0) == 1
    assert (after_qts.get("beacon_types") or "").strip() != "", \
        "enabling skill-beacon with no types selected must auto-populate beacon_types, not leave it silently empty"
    assert bot._beacon_rotation_pool(after_qts), "the rotation pool must be non-empty after auto-populating"
    print("4a. quick_toggle_skill auto-populates beacon_types when enabling with none selected")

    bot.update_user(uid, skill_beacon_enabled=0, beacon_types="")
    ctx_tsb = FakeCtx()
    upd_tsb = FakeUpdate(uid, data="toggle_skill_beacon")
    await bot.toggle_skill_beacon(upd_tsb, ctx_tsb)
    after_tsb = bot.get_user(uid)
    assert int(after_tsb.get("skill_beacon_enabled") or 0) == 1
    assert (after_tsb.get("beacon_types") or "").strip() != ""
    print("4b. toggle_skill_beacon auto-populates beacon_types when enabling with none selected")

    # Sanity: disabling doesn't touch beacon_types, and enabling with types
    # already chosen doesn't override the user's own selection.
    bot.update_user(uid, skill_beacon_enabled=0, beacon_types="stop")
    ctx_keep = FakeCtx()
    upd_keep = FakeUpdate(uid, data="quick_toggle_skill")
    await bot.quick_toggle_skill(upd_keep, ctx_keep)
    assert bot.get_user(uid).get("beacon_types") == "stop", \
        "enabling with an existing non-empty selection must not overwrite it"
    print("4c. quick_toggle_skill leaves an existing non-empty beacon_types selection untouched")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup): handle_delete_reminder_intent claimed "вот
    # похожие" (here are similar ones) even when _match_by_text found ZERO
    # matches and it fell back to arbitrary, unrelated items.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_reminder(uid, "Купить молоко", (datetime.now(tz) + timedelta(hours=1)).replace(tzinfo=None).isoformat())
    bot.add_reminder(uid, "Позвонить маме", (datetime.now(tz) + timedelta(hours=2)).replace(tzinfo=None).isoformat())
    msg_del = FakeMsg()
    await bot.handle_delete_reminder_intent(msg_del, uid, "погулять на луне")
    del_text = msg_del.last_text
    assert "похожие" not in del_text, del_text
    print("5. handle_delete_reminder_intent no longer falsely claims 'похожие' when there were zero real matches")

    for r in bot.get_reminders(uid):
        bot.cancel_reminder(uid, r["id"])

    bot.add_reminder(uid, "Купить молоко", (datetime.now(tz) + timedelta(hours=1)).replace(tzinfo=None).isoformat())
    bot.add_reminder(uid, "Купить хлеб", (datetime.now(tz) + timedelta(hours=2)).replace(tzinfo=None).isoformat())
    msg_del2 = FakeMsg()
    await bot.handle_delete_reminder_intent(msg_del2, uid, "купить")
    assert "похожие" in msg_del2.last_text, msg_del2.last_text
    print("5b. handle_delete_reminder_intent still says 'похожие' normally when there ARE real partial matches")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup): research_callback's day==7 branch sent a
    # "closure" message with a "◀️ Меню" button BEFORE the actual open-text
    # follow-up question -- tapping it routed through go_menu ->
    # clear_awaiting_flags, silently and permanently losing the pending
    # day-7 open question (day 3/14 don't offer an early exit like this).
    # Since the single-actual-message work, both texts are folded into ONE
    # message sent via ctx.bot (send_tracked_notification), not q.message.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, research_awaiting="0", research_done="")
    upd_r7 = FakeUpdate(uid, data="research_7_yes")
    ctx_r7 = FakeCtx()
    await bot.research_callback(upd_r7, ctx_r7)
    sent_kb = ctx_r7.bot.sent[-1][2]
    sent_buttons = [b.callback_data for row in (sent_kb.inline_keyboard if sent_kb else []) for b in row]
    assert "go_menu" not in sent_buttons, \
        f"the day-7 message must not offer an early 'Меню' exit before the open question, got buttons: {sent_buttons}"
    assert str(bot.get_user(uid).get("research_awaiting") or "0") != "0"
    print("6. research_callback's day-7 message no longer offers an early 'Меню' exit before the open question")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup): finish_morning ALWAYS writes a non-empty
    # morning diary row (focus/b1/b2/c1/c2/c3 keys present, even if all
    # empty) as soon as the morning ritual is touched at all -- so the "+2h,
    # morning still not closed" reminder's `not get_diary(...)` check never
    # fired for a user who did the ritual but set zero real tasks (exactly
    # the users who need the nudge most).
    # ══════════════════════════════════════════════════════════════════════
    uid8 = 8
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (8, 'Восьмой', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid8, timezone=tz_name)
    tz8 = bot.get_user_tz(bot.get_user(uid8))
    now8 = datetime.now(tz8)
    if now8.hour < 3:
        print("7. SKIPPED (too close to midnight to construct a reliable 'notif_morning 2h ago' scenario) -- harmless, rare")
    else:
        past_morning = (now8 - timedelta(hours=3)).strftime("%H:%M")
        day_key8 = now8.strftime("%Y-%m-%d")
        bot.save_diary(uid8, "morning", {k: "" for k in bot.TASK_KEYS} | {"writing": "", "gratitude": "", "child": ""}, for_date=day_key8)
        bot.update_user(
            uid8, notif_enabled=1, notif_morning_on=1, notif_morning=past_morning,
            morning_sent_date=day_key8, notif_midday_on=0, notif_evening_on=0,
            beacon_enabled=0, skill_beacon_enabled=0, weekly_report_sent_date=day_key8,
            resume_check_due="", focus_active=0, morning_reminder_sent_date="",
        )
        app8 = FakeApp()
        await bot.check_notifications(app8)
        assert bot.get_user(uid8).get("morning_reminder_sent_date") == day_key8, \
            "the +2h reminder must fire for a user who touched the morning ritual but set zero real tasks"
        assert any("не поставлены" in t for _, t, _ in app8.bot.sent), app8.bot.sent
        print("7. The +2h 'morning still not closed' reminder now fires even when the morning diary row exists but has zero real tasks")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (19th checkup, same root cause as #7): midday_callback's
    # `next_undone_task(...) or "все задачи дня уже сделаны"` fallback
    # wrongly claimed completion when no tasks were ever set at all --
    # nonsensical inside the "😬 Прокрастинирую" flow ("I can't start" met
    # with "everything is already done, relax").
    # ══════════════════════════════════════════════════════════════════════
    uid9 = 9
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (9, 'Девятый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid9, timezone=tz_name)
    tz9 = bot.get_user_tz(bot.get_user(uid9))
    today9 = datetime.now(tz9).date().isoformat()
    bot.save_diary(uid9, "morning", {k: "" for k in bot.TASK_KEYS}, for_date=today9)
    ctx_mid = FakeCtx()
    upd_mid = FakeUpdate(uid9, data="mid_nostart")
    await bot.midday_callback(upd_mid, ctx_mid)
    mid_text = upd_mid.callback_query.message.last_text
    assert "уже сделаны" not in mid_text, mid_text
    assert "не поставлены" in mid_text, mid_text
    print("8a. midday_callback no longer claims 'all tasks already done' when no tasks were ever set")

    bot.save_diary(uid9, "morning", {"focus": "Реальная задача"}, for_date=today9)
    ctx_mid2 = FakeCtx()
    upd_mid2 = FakeUpdate(uid9, data="mid_nostart")
    await bot.midday_callback(upd_mid2, ctx_mid2)
    mid_text2 = upd_mid2.callback_query.message.last_text
    assert "Реальная задача" in mid_text2, mid_text2
    print("8b. midday_callback still shows the real undone task normally when tasks exist")

    print("\nALL CHECKUP19-BATCH TESTS PASSED")


asyncio.run(main())
