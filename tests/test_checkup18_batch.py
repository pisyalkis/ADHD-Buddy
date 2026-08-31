import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup18_batch.db")
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
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtxBot:
    async def send_message(self, chat_id, text, **kw):
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
    # Real bug (18th checkup): toggle_field_callback's reset_skip_streak was
    # wired to the DISABLE branch instead of the RE-ENABLE branch (its own
    # comment says "turned back on manually").
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, disabled_fields="m_gratitude", skip_streaks="m_gratitude:2")
    upd = FakeUpdate(uid, data="toggle_field_m_gratitude")  # currently disabled -> this re-enables it
    await bot.toggle_field_callback(upd, FakeCtx())
    after = bot.get_user(uid)
    assert "m_gratitude" not in (after.get("disabled_fields") or "").split(","), after.get("disabled_fields")
    assert "m_gratitude" not in (after.get("skip_streaks") or ""), \
        f"re-enabling a field manually must reset its stale skip streak, got skip_streaks={after.get('skip_streaks')!r}"
    print("1. toggle_field_callback now resets skip_streak on RE-ENABLE, not on disable")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup): _daily_skill_indices collapsed the skill pool
    # to exactly 1 item for several struggle categories, because
    # DAILY_SKILL_EXCLUDE strips "Список дел"/"Приоритеты" out of pools that
    # PROBLEM_TO_SKILLS built mostly from those two names.
    # ══════════════════════════════════════════════════════════════════════
    for struggle in ("notasks", "overload", "unfinished", "nostructure", "memory"):
        bot.update_user(uid, struggles=struggle)
        indices = bot._daily_skill_indices(bot.get_user(uid))
        assert len(indices) >= 2, \
            f"struggle={struggle!r} must keep at least 2 skills in rotation, got {len(indices)}: {[bot.SKILLS[i]['name'] for i in indices]}"
    print("2. _daily_skill_indices no longer collapses to a single permanently-fixed skill")
    bot.update_user(uid, struggles="")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup): midday_kb offered "🎉 Все задачи сделаны" even
    # when there were zero tasks at all (existing_keys empty).
    # ══════════════════════════════════════════════════════════════════════
    kb_empty = bot.midday_kb(morning={}, done_set=set())
    labels_empty = [b.text for row in kb_empty.inline_keyboard for b in row]
    assert "🎉 Все задачи сделаны" not in labels_empty, labels_empty
    print("3a. midday_kb no longer offers 'all tasks done' when there are no tasks")

    kb_with_tasks = bot.midday_kb(morning={"focus": "Тест"}, done_set=set())
    labels_with = [b.text for row in kb_with_tasks.inline_keyboard for b in row]
    assert "🎉 Все задачи сделаны" in labels_with, labels_with
    print("3b. midday_kb still offers 'all tasks done' when real tasks exist and aren't all done")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup): redeem_promo_code always claimed "trial
    # extended" even for a user who already has a paid subscription, where
    # promo_extra_days has no real effect (get_access_status ignores trial
    # math entirely once subscribed).
    # ══════════════════════════════════════════════════════════════════════
    bot.create_promo_code("TESTCODE18", 5, 0, "test")
    future = (datetime.now(tz).date() + timedelta(days=30)).isoformat()
    bot.update_user(uid, subscription_until=future)
    ok, msg = bot.redeem_promo_code(uid, "TESTCODE18")
    assert ok, msg
    assert "уже есть полный доступ" in msg, msg
    assert "пробный период продлён" not in msg, msg
    print("4a. redeem_promo_code no longer falsely claims 'trial extended' for an already-subscribed user")

    bot.create_promo_code("TESTCODE18B", 5, 0, "test")
    bot.update_user(uid, subscription_until="")
    ok2, msg2 = bot.redeem_promo_code(uid, "TESTCODE18B")
    assert ok2, msg2
    assert "пробный период продлён на 5 дн" in msg2, msg2
    print("4b. redeem_promo_code still reports 'trial extended' normally for a non-subscribed user")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup): send_research_question set research_awaiting
    # (day 3 and day 14) the moment the rating-buttons notification was
    # sent -- BEFORE any button click -- hijacking any ordinary free text
    # sent in between as a research answer.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, research_awaiting="0", research_done="")
    app = FakeApp()
    await bot.send_research_question(app, uid, 3)
    assert str(bot.get_user(uid).get("research_awaiting") or "0") == "0", \
        f"research_awaiting must stay unset right after sending the day-3 rating buttons, got {bot.get_user(uid).get('research_awaiting')!r}"
    print("5a. send_research_question(day=3) no longer sets research_awaiting before any button click")

    bot.update_user(uid, research_awaiting="0", research_done="")
    await bot.send_research_question(app, uid, 14)
    assert str(bot.get_user(uid).get("research_awaiting") or "0") == "0", \
        f"research_awaiting must stay unset right after sending the day-14 rating buttons, got {bot.get_user(uid).get('research_awaiting')!r}"
    print("5b. send_research_question(day=14) no longer sets research_awaiting before any button click")

    # sanity: the button click itself (research_callback) still correctly
    # arms research_awaiting for the open follow-up question afterwards.
    upd_r = FakeUpdate(uid, data="research_3_4")
    await bot.research_callback(upd_r, FakeCtx())
    assert str(bot.get_user(uid).get("research_awaiting") or "0") != "0", \
        "research_callback must still arm research_awaiting after the actual rating click"
    print("5c. research_callback still correctly arms research_awaiting after a real button click")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup, 5 sites): Russian day/streak pluralization
    # checked raw magnitude (==1 / <5 / else) instead of last-digit rules --
    # correct by coincidence for 1-4 and 11-14, but wrong for 21-24, 31-34...
    # ══════════════════════════════════════════════════════════════════════
    orig_calc_streak = bot.calc_streak
    bot.calc_streak = lambda uid_: 21
    try:
        # evening_start
        bot.save_diary(uid, "morning", {"focus": "Т"}, for_date=datetime.now(tz).date().isoformat())
        ctx_es = FakeCtx()
        upd_es = FakeUpdate(uid, data="go_evening")
        await bot.evening_start(upd_es, ctx_es)
        es_text = upd_es.callback_query.message.sent[0][0]
        assert "21 день" in es_text, es_text
        assert "21 дней" not in es_text, es_text
        print("6a. evening_start's streak line correctly says '21 день', not '21 дней'")

        # finish_evening
        ctx_fe = FakeCtx()
        ctx_fe.user_data.update({
            "e_morning_date": datetime.now(tz).date().isoformat(),
            "e_ach": "", "e_praise": "", "e_highlights": "",
            "e_selfcare": [], "e_energy": 3,
            "e_a": "", "e_b1": "", "e_b2": "", "e_c1": "", "e_c2": "", "e_c3": "",
            "e_tasks_done": [],
        })
        msg_fe = FakeMsg()
        await bot.finish_evening(msg_fe, uid, ctx_fe)
        assert "21 день" in msg_fe.last_text, msg_fe.last_text
        assert "21 дней" not in msg_fe.last_text, msg_fe.last_text
        print("6b. finish_evening's streak line correctly says '21 день', not '21 дней'")

        # show_streak
        upd_ss = FakeUpdate(uid, data="show_streak")
        await bot.show_streak(upd_ss, FakeCtx())
        ss_text = upd_ss.callback_query.message.sent[0][0]
        assert "21 день" in ss_text, ss_text
        assert "21 дней" not in ss_text, ss_text
        print("6c. show_streak correctly says '21 день', not '21 дней'")

        # weekly_report
        bot.update_user(uid, streak_hidden=0)
        app_wr = FakeApp()
        await bot.weekly_report(app_wr, uid)
        wr_text = app_wr.bot.sent[-1][1]
        assert "21 день" in wr_text, wr_text
        assert "21 дней" not in wr_text, wr_text
        print("6d. weekly_report's streak line correctly says '21 день', not '21 дней'")
    finally:
        bot.calc_streak = orig_calc_streak

    # _subscribe_text_and_kb (trial days left, not streak -- 22 to also
    # exercise the "дня" branch, distinct from the "день" branch above)
    bot.update_user(uid, subscription_until="", promo_extra_days=(22 - bot.TRIAL_DAYS), created_at=datetime.now(tz).date().isoformat())
    text_sub, _ = bot._subscribe_text_and_kb(bot.get_user(uid))
    assert "22 дня" in text_sub, text_sub
    assert "22 дней" not in text_sub, text_sub
    print("6e. _subscribe_text_and_kb's trial-days-left line correctly says '22 дня', not '22 дней'")
    bot.update_user(uid, promo_extra_days=0)

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup): resuming an interrupted evening at the e_ach
    # step always showed the generic "Чего достиг(-ла)?" wording, even when
    # the user DID have and complete today's task checklist (which normally
    # produces the "Помимо запланированного..." wording via
    # tasks_done_finish's had_checklist=True) -- because RESUME_FIELDS_EVENING
    # never passed had_checklist through.
    # ══════════════════════════════════════════════════════════════════════
    # evening_start computes "today" via evening_day(tz), not a plain
    # calendar date -- before 4am local it's still "yesterday" (see
    # bot.evening_day's docstring). Using plain datetime.now(tz).date()
    # here made this test flaky specifically in that early-morning window,
    # since it wouldn't match what evening_start itself looks up.
    today_iso = bot.evening_day(tz).isoformat()
    bot.save_diary(uid, "morning", {"focus": "Задача A"}, for_date=today_iso)
    ctx_resume = FakeCtx()
    ctx_resume.user_data["e_progress_date"] = today_iso
    ctx_resume.user_data["e_morning_date"] = today_iso
    # A later step already has data (marks "resuming" as True) while e_ach
    # itself is absent -> resume picks e_ach as the first unanswered step.
    ctx_resume.user_data["e_c3"] = "placeholder"
    msg_resume = FakeMsg()
    upd_resume = FakeUpdate(uid, data="go_evening")
    upd_resume.callback_query.message = msg_resume
    await bot.evening_start(upd_resume, ctx_resume)
    all_resume_text = "\n".join(t for t, _ in msg_resume.sent)
    assert "Помимо запланированного" in all_resume_text, all_resume_text
    print("7. Resuming an interrupted evening at e_ach now uses the checklist-aware wording when today had real tasks")

    # Sanity: a user with NO tasks today resuming at e_ach still gets the
    # generic wording (there was no checklist to reference).
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone=tz_name)
    today_iso2 = bot.evening_day(bot.get_user_tz(bot.get_user(uid2))).isoformat()
    ctx_resume2 = FakeCtx()
    ctx_resume2.user_data["e_progress_date"] = today_iso2
    ctx_resume2.user_data["e_morning_date"] = today_iso2
    ctx_resume2.user_data["e_c3"] = "placeholder"
    msg_resume2 = FakeMsg()
    upd_resume2 = FakeUpdate(uid2, data="go_evening")
    upd_resume2.callback_query.message = msg_resume2
    await bot.evening_start(upd_resume2, ctx_resume2)
    all_resume_text2 = "\n".join(t for t, _ in msg_resume2.sent)
    assert "Чего достиг" in all_resume_text2, all_resume_text2
    assert "Помимо запланированного" not in all_resume_text2, all_resume_text2
    print("7b. Resuming at e_ach with no tasks today correctly keeps the generic wording")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (18th checkup): morning_notification showed the FULL A/B1/B2
    # carry-over plan and then, right below it, "Сегодня — только одна
    # задача A. Этого достаточно." -- contradictory when B1/B2 were also set
    # on a low-energy evening.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone=tz_name)
    tz3 = bot.get_user_tz(bot.get_user(uid3))
    yesterday3 = (datetime.now(tz3).date() - timedelta(days=1)).isoformat()
    bot.save_diary(uid3, "evening", {
        "e_a": "Задача A", "e_b1": "Задача B1", "e_b2": "Задача B2", "e_energy": 1,
    }, for_date=yesterday3)
    app3 = FakeApp()
    await bot.morning_notification(app3, uid3)
    mn_text = app3.bot.sent[-1][1]
    assert "Задача B1" not in mn_text, mn_text
    assert "Задача B2" not in mn_text, mn_text
    assert "Задача A" in mn_text, mn_text
    assert "только одна задача A" in mn_text, mn_text
    print("8. morning_notification no longer shows a full B1/B2 plan alongside 'only task A matters' on a low-energy day")

    print("\nALL CHECKUP18-BATCH TESTS PASSED")


asyncio.run(main())
