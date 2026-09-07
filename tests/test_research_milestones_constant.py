import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date, timezone as _timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_research_milestones_constant.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

_REAL_BOT_DATETIME = bot.datetime


class _FrozenDateTime(_REAL_BOT_DATETIME):
    # 11:00 in Asia/Tbilisi (UTC+4) -- inside the research send window
    # (10 <= now_dt.hour <= 12), and a fixed calendar date so "created_at
    # N days ago" is deterministic.
    _FROZEN_UTC = _REAL_BOT_DATETIME(2026, 1, 20, 7, 0, 0, tzinfo=_timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls._FROZEN_UTC.astimezone(tz) if tz is not None else cls._FROZEN_UTC.replace(tzinfo=None)


def freeze_bot_time():
    bot.datetime = _FrozenDateTime


def unfreeze_bot_time():
    bot.datetime = _REAL_BOT_DATETIME


def make_user(uid, name, created_days_ago, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    created = (bot.datetime.now(bot.pytz.utc).date() - timedelta(days=created_days_ago)).isoformat()
    bot.update_user(uid, timezone=tz_name, notif_enabled=1, created_at=created)


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        class M:
            message_id = 1
        return M()

    async def delete_message(self, chat_id, message_id):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (found investigating task #43 -- "unify the three days-since-
    # activity systems"): RESEARCH_MILESTONES = [3, 7, 14, 30, 60, 90] is
    # documented and used elsewhere (admin_research, tests) as THE list of
    # research checkpoints -- but _process_user_notifications' actual
    # scheduling loop read its own separate hardcoded copy of the same
    # literal, never the constant. Editing RESEARCH_MILESTONES would
    # silently do nothing to the real send schedule.
    # ══════════════════════════════════════════════════════════════════════
    freeze_bot_time()

    calls = []

    async def fake_send_research_question(app, uid, day):
        calls.append((uid, day))

    real_send_research_question = bot.send_research_question
    bot.send_research_question = fake_send_research_question

    real_milestones = bot.RESEARCH_MILESTONES
    try:
        # 1. A milestone value that exists ONLY in a custom RESEARCH_MILESTONES
        #    (not in the original hardcoded [3,7,14,30,60,90]) must now
        #    actually fire -- proving the loop reads the constant, not a
        #    frozen duplicate.
        bot.RESEARCH_MILESTONES = [5]
        uid1 = 1
        make_user(uid1, "Артем", created_days_ago=5)
        user1 = bot.get_user(uid1)
        await bot._process_user_notifications(FakeApp(), user1)
        assert (uid1, 5) in calls, \
            f"a milestone present only in RESEARCH_MILESTONES must be used by the scheduler (bug fix): {calls}"
        print("1. A custom RESEARCH_MILESTONES value (day 5) is now actually used by the scheduler (bug fix)")

        # 2. Regression: the original milestone set still fires exactly as
        #    before once restored.
        calls.clear()
        bot.RESEARCH_MILESTONES = real_milestones
        uid2 = 2
        make_user(uid2, "Вика", created_days_ago=3)
        user2 = bot.get_user(uid2)
        await bot._process_user_notifications(FakeApp(), user2)
        assert (uid2, 3) in calls, f"day 3 must still fire normally with the real milestone list: {calls}"
        print("2. The real RESEARCH_MILESTONES list still fires normally (no regression)")

        # 3. A day that hasn't reached ANY milestone yet must not fire at
        #    all -- sanity check that the loop is still milestone-gated,
        #    not firing unconditionally every tick.
        calls.clear()
        uid3 = 3
        make_user(uid3, "Игорь", created_days_ago=1)
        user3 = bot.get_user(uid3)
        await bot._process_user_notifications(FakeApp(), user3)
        assert not calls, f"day 1 hasn't reached any real milestone -- must not fire: {calls}"
        print("3. A day that hasn't reached any milestone yet does not fire (sanity check)")
    finally:
        bot.RESEARCH_MILESTONES = real_milestones
        bot.send_research_question = real_send_research_question
        unfreeze_bot_time()

    print("\nALL RESEARCH-MILESTONES-CONSTANT TESTS PASSED")


asyncio.run(main())
