import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_alumni_invite_ttl.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 900

    async def edit_text(self, text, **kw):
        return self

    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message

    async def answer(self, text=None, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data=None, message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.sent = []
        self._next_id = 1000

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        self._next_id += 1
        class M:
            pass
        m = M(); m.message_id = self._next_id
        return m

    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self, bot_=None):
        self.user_data = {}
        self.bot = bot_ or FakeBot()


def make_user(uid, name, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def scheduled_deletion_for(chat_id):
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? ORDER BY id DESC LIMIT 1", (chat_id,)
    ).fetchone()
    conn.close()
    return datetime.fromisoformat(row[0]) if row else None


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan 2026-09-09, follow-up on #313): the alumni
    # "new session" invite went from no ttl_seconds (vanishes in the
    # default 15 min, same old bug) to ttl_seconds=0 in #313 ("for
    # consistency" with the other 3 coworking screens) -- but unlike those,
    # this one is NEVER overwritten for someone who doesn't respond (they
    # never join `participants`, so check_coworking_sessions never touches
    # their copy). ttl_seconds=0 meant a dead "Присоединиться" button
    # would sit in an inactive user's chat forever, accumulating with every
    # new session. The correct expiry is the session's own start time --
    # after that, joining is rejected anyway.
    # ══════════════════════════════════════════════════════════════════════
    creator = 1
    make_user(creator, "Артем")
    alumnus = 2
    make_user(alumnus, "Вика")
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("UPDATE users SET coworking_ever_joined='1' WHERE user_id=?", (alumnus,))
    conn.commit(); conn.close()

    minutes_ahead = 20 * 60  # "tomorrow" -- ~20 hours ahead
    fake_bot = FakeBot()
    ctx = FakeCtx(fake_bot)
    ctx.user_data["coworking_pending_start_utc"] = (
        datetime.now(bot.pytz.utc) + timedelta(minutes=minutes_ahead)
    ).isoformat()
    upd = FakeUpdate(creator, data="coworking_dur_25", message=FakeMsg(creator))
    await bot.coworking_set_duration(upd, ctx)

    # Find the alumnus's message id from the sent log (the second send()
    # call -- the first is the creator's own confirmation).
    alumnus_sent = [c for c in fake_bot.sent if c[0] == alumnus]
    assert len(alumnus_sent) == 1, alumnus_sent

    # 1. The alumnus invite IS scheduled for self-deletion (not ttl_seconds=0
    #    / "never" -- the dead-button-forever bug).
    deletion_time = scheduled_deletion_for(alumnus)
    assert deletion_time is not None, \
        "the alumni invite must schedule a self-deletion, not live forever (bug fix)"
    print("1. The alumni invite DOES schedule a self-deletion (not forever, unlike the #313 regression)")

    # 2. ...and it's scheduled for roughly the SESSION'S START TIME, not the
    #    generic 15-minute inactivity window.
    now = datetime.now(bot.pytz.utc)
    expected_start = now + timedelta(minutes=minutes_ahead)
    delta_from_expected = abs((deletion_time.replace(tzinfo=bot.pytz.utc) - expected_start).total_seconds())
    assert delta_from_expected < 30, \
        f"must self-delete around the session's start time, not a generic 15-min window: {deletion_time} vs expected ~{expected_start}"
    minutes_until_deletion = (deletion_time.replace(tzinfo=bot.pytz.utc) - now).total_seconds() / 60
    assert minutes_until_deletion > 60, \
        f"must NOT be the generic 15-minute INACTIVE_SCREEN_TTL_SEC window: {minutes_until_deletion} min"
    print("2. It's scheduled to self-delete around the SESSION'S START TIME, not after 15 minutes")

    # 3. Regression: the creator's own confirmation still uses ttl_seconds=0
    #    (never self-deletes) -- that one genuinely IS replaced later by
    #    join/leave broadcasts, so #313's fix for it is untouched.
    creator_deletion = scheduled_deletion_for(creator)
    assert creator_deletion is None, \
        f"the creator's own confirmation must still never self-delete (ttl_seconds=0, unaffected by this fix): {creator_deletion}"
    print("3. The creator's own confirmation is unaffected -- still ttl_seconds=0 as fixed in #313")

    print("\nALL COWORKING-ALUMNI-INVITE-TTL TESTS PASSED")


asyncio.run(main())
