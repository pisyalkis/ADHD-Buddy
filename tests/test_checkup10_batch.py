import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup10_batch.db")
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
        self.edited = []
        self.unpinned = []
        self.unpin_should_fail = False
    async def edit_message_text(self, **kw):
        self.edited.append(kw)
    async def unpin_chat_message(self, **kw):
        if self.unpin_should_fail:
            raise RuntimeError("simulated Telegram API failure")
        self.unpinned.append(kw)
    async def pin_chat_message(self, **kw):
        pass


class FakeAppCtx:
    def __init__(self):
        self.bot = FakeBot()
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'M')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (10th checkup): e_morning_date was set ONLY inside
    # ask_tasks_done -- if a day's morning ritual had NO tasks set at all,
    # evening_start never touched e_morning_date, so a stale value from a
    # PREVIOUS day (when tasks WERE set) survived in ctx.user_data (via
    # PicklePersistence) and finish_evening blindly trusted it -- pulling
    # yesterday's morning/tasks into today's evening summary.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    bot.update_user(uid, timezone=tz_name)
    user = bot.get_user(uid)
    day1 = (datetime.now(bot.get_user_tz(user)).date() - timedelta(days=2)).isoformat()
    day2 = datetime.now(bot.get_user_tz(user)).date().isoformat()

    # Day 1: morning WITH tasks -- evening_start's ask_tasks_done branch
    # would normally set e_morning_date = day1 correctly. Note: "focus" IS
    # the task-A field (see TASK_FIELDS), so setting it counts as a task.
    bot.save_diary(uid, "morning", {"focus": "Сделать X"}, for_date=day1)

    # Day 2 (today): morning WITHOUT any tasks at all (no TASK_FIELDS set),
    # only a non-task field (gratitude) so the diary entry isn't empty and
    # the "morning not found -> fall back to calendar date" branch doesn't
    # kick in and mask the bug.
    bot.save_diary(uid, "morning", {"gratitude": "Погода сегодня хорошая"}, for_date=day2)

    # Simulate the stale ctx.user_data a user would carry across restarts:
    # yesterday's evening ritual set e_morning_date = day1 and it was never
    # cleared (RESUME_FIELDS_EVENING doesn't include this key).
    ctx = FakeCtx()
    ctx.user_data["e_morning_date"] = day1

    # Force evening_day(tz) to resolve to day2 regardless of current wall
    # clock, by monkeypatching just for this call -- avoids test flakiness
    # near midnight while still exercising the real evening_start code path.
    orig_evening_day = bot.evening_day
    bot.evening_day = lambda tz: datetime.now(tz).replace(
        year=int(day2[:4]), month=int(day2[5:7]), day=int(day2[8:10])
    ).date()
    try:
        upd = FakeUpdate(uid, data="go_evening")
        state = await bot.evening_start(upd, ctx)
    finally:
        bot.evening_day = orig_evening_day

    assert ctx.user_data.get("e_morning_date") == day2, \
        f"evening_start must refresh e_morning_date to TODAY's morning even when today has no tasks, got {ctx.user_data.get('e_morning_date')!r}"
    print("1. evening_start no longer leaves a stale e_morning_date when today's morning has no tasks")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (10th checkup): unpin_today_tasks cleared pinned_msg_id even
    # when unpin_chat_message itself failed (network/rate-limit) -- the
    # message stayed actually pinned in the chat, but the DB thought there
    # was nothing to unpin, so the next pin_today_tasks left it orphaned
    # forever with no path to clean it up.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, pinned_msg_id="555")
    fctx = FakeAppCtx()
    fctx.bot.unpin_should_fail = True
    await bot.unpin_today_tasks(fctx, uid)
    still_there = bot.get_user(uid).get("pinned_msg_id")
    assert still_there == "555", \
        f"pinned_msg_id must NOT be cleared when unpin_chat_message fails, got {still_there!r}"
    print("2a. unpin_today_tasks keeps pinned_msg_id when the Telegram unpin call fails")

    fctx2 = FakeAppCtx()
    await bot.unpin_today_tasks(fctx2, uid)
    cleared = bot.get_user(uid).get("pinned_msg_id")
    assert cleared == "", f"pinned_msg_id must be cleared once unpin actually succeeds, got {cleared!r}"
    print("2b. unpin_today_tasks still clears pinned_msg_id on the normal success path")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (10th checkup): access_gate crashed with an unhandled
    # IndexError on a lone "/" message (text[1:].split()[0] on an empty
    # list) -- an expired user sending just "/" slipped past the paywall
    # check entirely instead of being blocked.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    bot.update_user(uid2, timezone=tz_name)
    orig_status = bot.get_access_status
    bot.get_access_status = lambda u: "expired"
    try:
        upd2 = FakeUpdate(uid2, data="")
        upd2.callback_query = None
        upd2.message = type("M", (), {"text": "/", "successful_payment": None})()
        ctx2 = FakeCtx()
        was_stopped = False
        try:
            await bot.access_gate(upd2, ctx2)
        except bot.ApplicationHandlerStop:
            was_stopped = True
        assert was_stopped, "access_gate must not crash and must still block an expired user sending a lone '/'"
    finally:
        bot.get_access_status = orig_status
    print("3. access_gate no longer crashes on a lone '/' message, still blocks the expired user")

    print("\nALL CHECKUP10-BATCH TESTS PASSED")


asyncio.run(main())
