import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup11_batch.db")
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


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data="go_evening"):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.effective_message = None
        self.callback_query = FakeQuery(uid, data)
        self.message = None
        self.pre_checkout_query = None


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
    # Real bug (11th checkup): e_tasks_done was set ONLY inside ask_tasks_done,
    # which is only called when today's morning HAS tasks. On a day with no
    # morning tasks, a stale done-list from a PREVIOUS day survived in
    # ctx.user_data and finish_evening wrote it into today's tasks_done DB
    # record -- a brand-new task typed into that slot afterwards would show
    # up as already done.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    bot.update_user(uid, timezone=tz_name)
    user = bot.get_user(uid)
    day1 = (datetime.now(bot.get_user_tz(user)).date() - timedelta(days=2)).isoformat()
    day2 = datetime.now(bot.get_user_tz(user)).date().isoformat()

    bot.save_diary(uid, "morning", {"focus": "Сделать X"}, for_date=day1)
    bot.save_diary(uid, "tasks_done", {"done": ["focus"]}, for_date=day1)
    bot.save_diary(uid, "morning", {"gratitude": "Погода хорошая"}, for_date=day2)  # no tasks today

    ctx = FakeCtx()
    ctx.user_data["e_tasks_done"] = ["focus"]  # stale snapshot carried from day1's evening review

    orig_evening_day = bot.evening_day
    bot.evening_day = lambda tz: datetime.now(tz).replace(
        year=int(day2[:4]), month=int(day2[5:7]), day=int(day2[8:10])
    ).date()
    try:
        upd = FakeUpdate(uid, data="go_evening")
        await bot.evening_start(upd, ctx)
    finally:
        bot.evening_day = orig_evening_day

    assert ctx.user_data.get("e_tasks_done") == [], \
        f"evening_start must refresh e_tasks_done to TODAY's real done-list when today has no tasks, got {ctx.user_data.get('e_tasks_done')!r}"
    print("1. evening_start no longer leaves a stale e_tasks_done when today's morning has no tasks")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (11th checkup): get_latest_evening_plan judged "is today's
    # evening entry fresh enough" by checking only e_a -- if the user
    # explicitly skipped task A during a late-evening session (after the
    # evening_day 4am cutoff, so the record lands in the "today" bucket),
    # the whole fresh record was discarded in favor of a stale two-day-old
    # entry, corrupting both the "remember your plan" greeting and the
    # low-energy adaptive greeting.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    bot.update_user(uid2, timezone=tz_name)
    user2 = bot.get_user(uid2)
    today2 = datetime.now(bot.get_user_tz(user2)).date().isoformat()
    stale2 = (datetime.now(bot.get_user_tz(user2)).date() - timedelta(days=1)).isoformat()
    # Stale (2 days back from "today"): has a plan + energy.
    bot.save_diary(uid2, "evening", {"e_a": "Старая задача", "e_energy": 1}, for_date=stale2)
    # Fresh "today" bucket: task A explicitly skipped, but energy IS set --
    # this is a real, complete evening session, just without a task A.
    bot.save_diary(uid2, "evening", {"e_a": "", "e_energy": 4}, for_date=today2)

    ev = bot.get_latest_evening_plan(uid2)
    assert ev.get("e_energy") == 4, \
        f"get_latest_evening_plan must prefer today's real (if skipped-task-A) record over a stale older one, got e_energy={ev.get('e_energy')!r}"
    assert ev.get("e_a") == "", ev
    print("2. get_latest_evening_plan now correctly treats a present-but-skipped-task-A record as fresh")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (11th checkup): send_focus_end cleared focus_active/wrote the
    # accumulated minutes to the DB BEFORE attempting the Telegram send --
    # if the send failed, the timer state was already marked "done" and
    # check_notifications would never retry, so the user never learned
    # their focus timer had ended.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    bot.update_user(uid3, timezone=tz_name)
    user3 = bot.get_user(uid3)
    end_time = datetime.now(bot.get_user_tz(user3)).isoformat()
    bot.update_user(uid3, focus_active=1, focus_end_time=end_time, focus_minutes_today=0, focus_date="")
    app = FakeApp()
    app.bot.fail_send = True
    await bot.send_focus_end(app, uid3, 25, end_time)
    still_active = bot.get_user(uid3)
    assert str(still_active.get("focus_active")) == "1", \
        f"focus_active must NOT be cleared when the Telegram send fails, got {still_active.get('focus_active')!r}"
    print("3a. send_focus_end keeps focus_active=1 when the Telegram send fails (so it can be retried)")

    app2 = FakeApp()
    await bot.send_focus_end(app2, uid3, 25, end_time)
    after_success = bot.get_user(uid3)
    assert str(after_success.get("focus_active")) == "0", after_success
    assert int(after_success.get("focus_minutes_today")) == 25, after_success
    assert len(app2.bot.sent) == 1
    print("3b. send_focus_end still clears focus_active and records minutes on the normal success path")

    print("\nALL CHECKUP11-BATCH TESTS PASSED")


asyncio.run(main())
