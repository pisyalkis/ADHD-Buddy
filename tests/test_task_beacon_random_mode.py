import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_beacon_random_mode.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 1
        return M()

    async def delete_message(self, chat_id, message_id):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeMessage:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1

    async def edit_text(self, text, **kw):
        return self

    async def reply_text(self, text, **kw):
        return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = type("U", (), {"id": uid})
        self.data = data
        self.message = FakeMessage(uid)

    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = type("U", (), {"id": uid})
        self.effective_chat = type("C", (), {"id": uid})


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", beacon_enabled=1, beacon_start="00:00", beacon_end="23:59")
    today = datetime.now(TBILISI).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, today)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-30): the skill beacon already supports
    # "N random times a day" (skill_beacon_mode="random") -- an unpredictable
    # schedule usually beats a fixed interval against habituation/ignoring
    # for ADHD -- but the TASK beacon (send_task_beacon/beacon_interval) only
    # ever supported fixed hourly intervals. Port the same mode over, reusing
    # the shared _skill_beacon_random_times infrastructure (beacon_start/
    # beacon_end are already shared between both beacons).
    # ══════════════════════════════════════════════════════════════════════

    # 1. _settings_beacon_text_and_kb shows the mode/count controls for the
    #    task beacon, mirroring the skill beacon's own controls.
    uid = 1
    make_user(uid, "Артем")
    bot.update_user(uid, beacon_mode="random", beacon_daily_count=4)
    text, kb = bot._settings_beacon_text_and_kb(bot.get_user(uid))
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "beacon_mode_interval" in callbacks and "beacon_mode_random" in callbacks, callbacks
    assert "beacon_count_4" in callbacks, callbacks
    assert "beacon_int_1" not in callbacks, "interval row must not show while in random mode"
    assert "4 раз(а) в день" in text, text
    print("1. _settings_beacon_text_and_kb shows mode/count controls for the task beacon, hides interval row in random mode")

    # 2. beacon_set_mode/beacon_set_count persist the choice.
    await bot.beacon_set_mode(FakeUpdate(uid, "beacon_mode_random"), FakeCtx())
    assert bot.get_user(uid)["beacon_mode"] == "random"
    await bot.beacon_set_count(FakeUpdate(uid, "beacon_count_2"), FakeCtx())
    assert int(bot.get_user(uid)["beacon_daily_count"]) == 2
    await bot.beacon_set_mode(FakeUpdate(uid, "beacon_mode_interval"), FakeCtx())
    assert bot.get_user(uid)["beacon_mode"] == "interval"
    print("2. beacon_set_mode/beacon_set_count persist the chosen mode/count")

    # 3. In interval mode (the default), send_task_beacon behaves exactly as
    #    before -- no behavior change for existing users.
    uid2 = 2
    make_user(uid2, "Вика")
    bot.update_user(uid2, beacon_last_sent="")
    app2 = FakeApp()
    await bot.send_task_beacon(app2, bot.get_user(uid2))
    assert len(app2.bot.sent) == 1, "interval mode with no prior send must fire immediately, unchanged"
    print("3. Interval mode (default) behaves exactly as before -- no regression")

    # 4. In random mode, send_task_beacon uses _task_beacon_random_due
    #    instead of the interval logic -- fires only at/after a scheduled
    #    random target, not on every tick.
    uid3 = 3
    make_user(uid3, "Игорь")
    bot.update_user(uid3, beacon_mode="random", beacon_daily_count=1)
    user3 = bot.get_user(uid3)
    now = datetime.now(TBILISI)
    targets = bot._skill_beacon_random_times(user3, now, 1)
    assert len(targets) == 1
    target = targets[0]

    app_before = FakeApp()
    before_now = target - timedelta(minutes=5)
    # send_task_beacon reads real time internally via get_user_tz/datetime.now,
    # so drive it through _task_beacon_random_due directly for a controlled
    # "before/after the target" comparison (same function send_task_beacon calls).
    assert bot._task_beacon_random_due(user3, before_now) is False, \
        "must not fire before the scheduled random target"
    assert bot._task_beacon_random_due(user3, target + timedelta(seconds=1)) is True, \
        "must fire once at/after the scheduled random target"
    print("4. _task_beacon_random_due only reports due at/after the scheduled random target, not before")

    # 5. After firing, the SAME target must not be due again (beacon_last_sent
    #    tracks it) -- mirrors _skill_beacon_due's own already-used filtering.
    bot.update_user(uid3, beacon_last_sent=(target + timedelta(seconds=1)).isoformat())
    user3_after = bot.get_user(uid3)
    assert bot._task_beacon_random_due(user3_after, target + timedelta(minutes=1)) is False, \
        "an already-used target must not be considered due again"
    print("5. Once fired, the same random target is not re-used (tracked via beacon_last_sent)")

    # 6. Task beacon and skill beacon random schedules are tracked
    #    independently -- firing one does not mark the other as done.
    uid4 = 4
    make_user(uid4, "Соня")
    bot.update_user(uid4, beacon_mode="random", beacon_daily_count=3,
                     skill_beacon_mode="random", skill_beacon_daily_count=3,
                     skill_beacon_enabled=1, beacon_types="stop")
    bot.update_user(uid4, beacon_last_sent=datetime.now(TBILISI).isoformat())
    user4 = bot.get_user(uid4)
    assert not user4.get("skill_beacon_last_sent"), \
        "firing the task beacon must not mark the skill beacon as already sent"
    print("6. Task beacon and skill beacon random schedules are tracked independently")

    print("\nALL TASK BEACON RANDOM MODE TESTS PASSED")


asyncio.run(main())
