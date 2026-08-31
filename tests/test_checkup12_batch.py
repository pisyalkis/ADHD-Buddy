import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup12_batch.db")
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
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg()
        self.message.text = text
        self.callback_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeBot:
    def __init__(self):
        self.sent = []
        self.fail_send = False
    async def send_message(self, chat_id, text, **kw):
        if self.fail_send:
            raise RuntimeError("simulated Telegram send failure")
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Аня', 'F')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (12th checkup): PROBLEM_TO_SKILLS was missing entries for the
    # whole "🪞 Отношение к себе" struggle group (self_esteem/self_talk/
    # unfinished_shame/memory_yesterday, added in PR #117) -- a user who only
    # ticked those got an empty personalization pool and silently fell back
    # to the ENTIRE unfiltered skill catalogue, contradicting the mechanism's
    # own documented purpose.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    bot.update_user(uid, timezone=tz_name, struggles="self_esteem")
    user = bot.get_user(uid)
    pool = bot._daily_skill_indices(user)
    pool_names = [bot.SKILLS[i]["name"] for i in pool]
    assert any("Подкрепление" in n for n in pool_names), \
        f"self_esteem's pool should include the self-praise/reinforcement skill, got {pool_names}"
    assert not any("Навык СТОП" in n for n in pool_names), \
        f"a user with ONLY 'self_esteem' struggles must get a FILTERED pool (unrelated skills like Навык СТОП excluded), got {pool_names}"
    print("1. PROBLEM_TO_SKILLS now covers the self-esteem struggle group -- personalization pool is filtered")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (12th checkup): checkpoint_evening_progress merged live
    # tasks_done under `for_date` (the evening_day of the interrupted
    # session) instead of e_morning_date (where the morning's tasks
    # actually live) -- these dates diverge in the 00:00-04:00 edge case,
    # same as finish_evening's own already-fixed bug.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    bot.update_user(uid2, timezone=tz_name)
    stale_evening_date = "2026-01-10"     # the interrupted session's evening_day/for_date
    real_morning_date = "2026-01-11"      # where the morning (and its tasks_done) actually live
    bot.save_diary(uid2, "tasks_done", {"done": ["focus", "b1"]}, for_date=real_morning_date)
    bot.save_diary(uid2, "tasks_done", {"done": ["WRONG_DAY_MARKER"]}, for_date=stale_evening_date)

    ctx2 = FakeCtx()
    ctx2.user_data["e_morning_date"] = real_morning_date
    ctx2.user_data["e_tasks_done"] = []
    bot.checkpoint_evening_progress(ctx2, uid2, stale_evening_date)
    saved = bot.get_diary(uid2, "evening", stale_evening_date)
    assert set(saved.get("e_tasks_done", [])) == {"focus", "b1"}, \
        f"checkpoint_evening_progress must merge tasks_done from e_morning_date, not the stale evening_day, got {saved.get('e_tasks_done')}"
    print("2. checkpoint_evening_progress now merges tasks_done from the correct (e_morning_date) day")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (12th checkup): next_beacon_slot advanced beacon_rotation_idx
    # in the DB BEFORE send_skill_beacon actually attempted the send -- a
    # failed send silently skipped that technique from the rotation forever
    # instead of retrying it next tick.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    bot.update_user(
        uid3, timezone=tz_name,
        skill_beacon_enabled=1, beacon_types="stop,breathing",
        beacon_start="00:00", beacon_end="23:59",
        skill_beacon_last_sent="", beacon_rotation_idx="0",
    )
    app = FakeApp()
    app.bot.fail_send = True
    user3 = bot.get_user(uid3)
    await bot.send_skill_beacon(app, user3)
    still0 = bot.get_user(uid3)
    assert still0.get("beacon_rotation_idx") == "0", \
        f"beacon_rotation_idx must NOT advance when the send fails (so the same technique retries), got {still0.get('beacon_rotation_idx')!r}"
    assert still0.get("skill_beacon_last_sent") == "", still0
    print("3a. next_beacon_slot/send_skill_beacon keep the rotation index unchanged when the send fails")

    app2 = FakeApp()
    user3b = bot.get_user(uid3)
    await bot.send_skill_beacon(app2, user3b)
    after = bot.get_user(uid3)
    assert after.get("beacon_rotation_idx") == "1", after
    assert after.get("skill_beacon_last_sent"), after
    assert len(app2.bot.sent) == 1
    print("3b. next_beacon_slot/send_skill_beacon still advance the rotation on the normal success path")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (12th checkup, same class as the already-fixed coach_mode
    # bug): research_awaiting is a DB-level flag that persists indefinitely
    # (set by a background research notification, not a same-turn prompt)
    # and was checked BEFORE classify_free_text -- so a completely unrelated
    # message (e.g. a reminder request) sent while research_awaiting was set
    # got silently swallowed as a "research answer" instead of being routed
    # to its real intent.
    # ══════════════════════════════════════════════════════════════════════
    uid4 = 1  # reuse uid 1, give it a fresh identity for this scenario
    bot.update_user(uid4, timezone=tz_name, research_awaiting="7_open:Что мешало?")

    orig_classify = bot.classify_free_text
    now_dt = datetime.now(bot.get_user_tz(bot.get_user(uid4)))
    remind_at = (now_dt + timedelta(hours=1)).replace(microsecond=0).isoformat()

    async def fake_classify_reminder(text, now_dt):
        return {"intent": "reminder", "remind_at": remind_at, "text": "выключить чайник", "recur": ""}

    bot.classify_free_text = fake_classify_reminder
    try:
        upd = FakeUpdate(uid4, text="напомни выключить чайник через час")
        ctx4 = FakeCtx()
        await bot.handle_text(upd, ctx4)
    finally:
        bot.classify_free_text = orig_classify

    reminders_after = bot.get_reminders(uid4)
    assert any("чайник" in r["text"] for r in reminders_after), \
        f"a reminder request must NOT be swallowed as a research answer just because research_awaiting is set, got reminders={reminders_after}"
    still_awaiting = bot.get_user(uid4).get("research_awaiting")
    assert still_awaiting == "7_open:Что мешало?", \
        f"research_awaiting must be left untouched when the message was actually a different intent, got {still_awaiting!r}"
    reply_text = upd.message.last_text
    assert "Напомню" in reply_text, reply_text
    print("4a. research_awaiting no longer swallows a message that classify_free_text recognizes as a different intent")

    # And a genuine free-text research answer (no other intent detected)
    # must still be captured correctly, exactly as before.
    upd2 = FakeUpdate(uid4, text="Было неудобно, что не сохранялись напоминания")
    ctx5 = FakeCtx()
    await bot.handle_text(upd2, ctx5)  # ANTHROPIC_KEY="" -> classify_free_text returns intent "other"
    thanked = upd2.message.last_text
    assert "важен" in thanked, thanked
    assert bot.get_user(uid4).get("research_awaiting") in (0, "0", None), bot.get_user(uid4).get("research_awaiting")
    print("4b. A genuine free-text research answer (no clearer intent) is still captured and thanked")

    print("\nALL CHECKUP12-BATCH TESTS PASSED")


asyncio.run(main())
