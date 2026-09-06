import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_focus_calibration.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = 900
        self.text = ""
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        m = FakeMessage(self.chat_id)
        m.text = text
        return m

    async def edit_text(self, text, **kw):
        self.text = text
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = message


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        m = FakeMessage(chat_id)
        m.text = text
        return m


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-26): the focus-timer skill explicitly
    # explains ADHD brains have a weak internal sense of time, but the
    # timer itself never compares the chosen duration ("думал") against how
    # long it actually took to finish the task it was tracking ("ушло").
    # The FIRST focus round started for a given task text records an
    # estimate + start time; marking that SAME task done later shows the
    # comparison once, then resets.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = datetime.now(TBILISI).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Разобрать почту"}, for_date=today)

    # 1. Starting a focus round for the current (undone) task records the
    #    estimate/text/start-time on the user.
    msg1 = FakeMessage(uid)
    upd1 = FakeUpdate(uid, "focus_start_25", msg1)
    await bot.focus_start_callback(upd1, FakeCtx())
    user = bot.get_user(uid)
    assert user["focus_task_text"] == "Разобрать почту", user["focus_task_text"]
    assert int(user["focus_task_estimate_minutes"]) == 25
    assert user["focus_task_started_at"], "start time must be recorded"
    print("1. Starting a focus round for the current task records estimate/text/start-time")

    # 2. A SECOND round on the SAME task must NOT reset the original
    #    estimate/start-time (otherwise "actual" would always trivially
    #    equal the last chosen duration).
    first_started_at = user["focus_task_started_at"]
    bot.update_user(uid, focus_active=0, focus_end_time="")  # simulate the first round having ended
    msg1b = FakeMessage(uid)
    upd1b = FakeUpdate(uid, "focus_start_10", msg1b)
    await bot.focus_start_callback(upd1b, FakeCtx())
    user2 = bot.get_user(uid)
    assert int(user2["focus_task_estimate_minutes"]) == 25, "the ORIGINAL estimate must survive a second round on the same task"
    assert user2["focus_task_started_at"] == first_started_at, "the ORIGINAL start time must survive a second round on the same task"
    print("2. A second round on the same task does not reset the original estimate/start-time")

    # 3. Marking that SAME task done shows the "думал X — ушло Y" comparison
    #    and resets the tracked fields (only once).
    bot.update_user(uid, focus_task_started_at=(datetime.now(bot.pytz.utc) - timedelta(minutes=52)).isoformat())
    done_msg = FakeMessage(uid)
    done_upd = FakeUpdate(uid, "task_done_focus", done_msg)
    await bot.task_done_callback(done_upd, FakeCtx())
    calib_replies = [r for r in done_msg.replies if "Думал" in r]
    assert len(calib_replies) == 1, done_msg.replies
    assert "25 мин" in calib_replies[0], calib_replies[0]
    assert "52 мин" in calib_replies[0] or "51 мин" in calib_replies[0] or "53 мин" in calib_replies[0], calib_replies[0]
    assert "Разобрать почту" in calib_replies[0], calib_replies[0]
    user3 = bot.get_user(uid)
    assert not user3["focus_task_text"], "tracking must reset after showing the comparison once"
    assert not user3["focus_task_started_at"]
    print("3. Marking the tracked task done shows the calibration comparison exactly once, then resets tracking")

    # 4. Un-completing and re-completing the SAME task again does not
    #    re-show the comparison (tracking already reset).
    done_msg2 = FakeMessage(uid)
    await bot.task_done_callback(FakeUpdate(uid, "task_done_focus", done_msg2), FakeCtx())  # un-check
    done_msg3 = FakeMessage(uid)
    await bot.task_done_callback(FakeUpdate(uid, "task_done_focus", done_msg3), FakeCtx())  # re-check
    assert not any("Думал" in r for r in done_msg3.replies), done_msg3.replies
    print("4. Re-completing the same task again does not re-show a stale calibration comparison")

    # 5. Completing a DIFFERENT task (never tracked by a focus round) shows
    #    no calibration note at all.
    uid2 = 2
    make_user(uid2, "Вика")
    bot.save_diary(uid2, "morning", {"focus": "Позвонить врачу"}, for_date=today)
    done_msg4 = FakeMessage(uid2)
    await bot.task_done_callback(FakeUpdate(uid2, "task_done_focus", done_msg4), FakeCtx())
    assert not any("Думал" in r for r in done_msg4.replies), done_msg4.replies
    print("5. Completing a task that was never tracked by a focus round shows no calibration note")

    print("\nALL FOCUS CALIBRATION TESTS PASSED")


asyncio.run(main())
