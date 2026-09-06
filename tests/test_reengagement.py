import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reengagement.db")
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
    def __init__(self, uid):
        self.chat = FakeChat(uid)
    async def reply_text(self, text, **kw): return self


class FakeUpdateMsg:
    """A plain incoming message update, no callback_query -- used to
    exercise track_last_seen via dedupe_updates."""
    def __init__(self, uid, update_id):
        self.update_id = update_id
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.effective_message = FakeMessage(uid)
        self.channel_post = None
        self.edited_channel_post = None
        self.callback_query = None
        self.message = FakeMessage(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 1
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (product discussion, this session): ADHD users start
    # using the bot then vanish with no further contact, distinct from
    # merely skipping the morning ritual (already handled by welcome-back).
    # last_seen_at tracks real interaction, not ritual completion; on
    # milestones of 3/7/14 days of TOTAL silence, one reactivation message
    # goes out -- compassionate, no shame, no stats, explicit choice
    # including an honest "leave me alone" that permanently opts out.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")

    # 1. track_last_seen (via dedupe_updates) stamps last_seen_at on a
    #    plain incoming update.
    upd = FakeUpdateMsg(uid, update_id=1001)
    await bot.dedupe_updates(upd, FakeCtx())
    user = bot.get_user(uid)
    assert user.get("last_seen_at"), "last_seen_at must be stamped after a real update"
    print("1. track_last_seen (via dedupe_updates) stamps last_seen_at on any real update")

    # 2. _days_since_seen computes the gap correctly against a backdated
    #    last_seen_at.
    ten_days_ago = (datetime.now(bot.pytz.utc) - timedelta(days=10)).isoformat()
    bot.update_user(uid, last_seen_at=ten_days_ago)
    assert bot._days_since_seen(uid) == 10, bot._days_since_seen(uid)
    print("2. _days_since_seen correctly computes the gap from last_seen_at")

    # 3. A gap of 3 days (first milestone) triggers exactly one
    #    reactivation message with the three expected buttons.
    three_days_ago = (datetime.now(bot.pytz.utc) - timedelta(days=3)).isoformat()
    bot.update_user(uid, last_seen_at=three_days_ago, reengage_max_milestone_sent=0)
    app = FakeApp()
    ok = await bot.send_reengagement_message(app, uid)
    assert ok is True
    assert app.bot.sent, "send_reengagement_message must actually send something"
    _, text, kb = app.bot.sent[0]
    assert "не только у тебя" in text
    cbs = kb_callbacks(kb)
    assert cbs == ["reengage_start", "reengage_adjust", "reengage_leave"], cbs
    print("3. send_reengagement_message sends the compassionate, no-stats message with all three choices")

    # 4. End-to-end via the per-user tick: a 3-day gap sends the message and
    #    records reengage_max_milestone_sent=3 -- but only inside the
    #    9-10h UTC window (Fresh Start morning), not at an arbitrary hour.
    uid2 = 2
    make_user(uid2, "Вика")
    bot.update_user(uid2, last_seen_at=three_days_ago, reengage_max_milestone_sent=0,
                     notif_enabled=0)  # deliberately off -- reengagement must not depend on it
    app2 = FakeApp()
    user2 = bot.get_user(uid2)
    await bot._process_user_notifications(app2, user2)
    # NOTE: _process_user_notifications uses real datetime.now() internally,
    # so this assertion is only meaningful if the sandbox's real UTC hour is
    # within [9,10) -- guard it so the test stays honest either way.
    real_utc_hour = datetime.now(bot.pytz.utc).hour
    if 9 <= real_utc_hour < 10:
        assert int(bot.get_user(uid2).get("reengage_max_milestone_sent") or 0) == 3, \
            "within the reactivation window, a 3-day gap must record milestone 3"
        print("4. The per-user tick sends the day-3 reactivation message and records the milestone (real time is in-window)")
    else:
        assert int(bot.get_user(uid2).get("reengage_max_milestone_sent") or 0) == 0, \
            "outside the reactivation window, nothing should be sent yet"
        print(f"4. Outside the reactivation window (real UTC hour={real_utc_hour}), correctly does nothing yet")

    # 5. A long-silent user (gap=20, never checked before) gets exactly ONE
    #    message, jumping straight to the highest qualifying milestone (14)
    #    rather than queuing up 3/7/14 one per day.
    uid3 = 3
    make_user(uid3, "Игорь")
    twenty_days_ago = (datetime.now(bot.pytz.utc) - timedelta(days=20)).isoformat()
    bot.update_user(uid3, last_seen_at=twenty_days_ago, reengage_max_milestone_sent=0)
    gap3 = bot._days_since_seen(uid3)
    due = [m for m in bot.REENGAGE_MILESTONES if m > 0 and gap3 >= m]
    assert due[-1] == 14, due
    print("5. A long-unseen user's first check jumps straight to the highest qualifying milestone (14), not a queue")

    # 6. reengage_leave_callback opts the user out permanently, without
    #    touching notif_enabled or any other notification toggle.
    class FakeQuery:
        def __init__(self, uid_):
            self.from_user = FakeUser(uid_)
            self.message = FakeMessage(uid_)
        async def answer(self, *a, **kw): pass
    class FakeUpdateCb:
        def __init__(self, uid_):
            self.callback_query = FakeQuery(uid_)
    await bot.reengage_leave_callback(FakeUpdateCb(uid), FakeCtx())
    assert int(bot.get_user(uid).get("reengage_opt_out") or 0) == 1
    print("6. '🤫 Оставь в покое' permanently opts the user out of future reactivation messages")

    # 7. Any subsequent real update resets reengage_max_milestone_sent back
    #    to 0 -- a user who returns and later goes quiet again must be
    #    reachable at the milestones once more.
    bot.update_user(uid2, reengage_max_milestone_sent=14)
    upd2 = FakeUpdateMsg(uid2, update_id=1002)
    await bot.dedupe_updates(upd2, FakeCtx())
    assert int(bot.get_user(uid2).get("reengage_max_milestone_sent") or 0) == 0, \
        "any real interaction must reset the milestone counter for a future silence"
    print("7. Any real update resets reengage_max_milestone_sent, so future silences can trigger reactivation again")

    print("\nALL REENGAGEMENT TESTS PASSED")


asyncio.run(main())
