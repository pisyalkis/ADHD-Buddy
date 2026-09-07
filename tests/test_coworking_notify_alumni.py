import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_notify_alumni.db")
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
        self.texts = []

    async def edit_text(self, text, **kw):
        self.texts.append((text, kw.get("reply_markup")))
        return self

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.texts.append((text, kw.get("reply_markup")))
        return m


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


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
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


def make_user(uid, name, tz_name="Asia/Tbilisi"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone=tz_name)


def create_past_session_with_participant(uid):
    """Gives uid coworking history (alumni status) via a PAST (already
    started) session -- get_coworking_alumni looks at coworking_participants
    regardless of whether the session is still open."""
    start = (datetime.now(bot.pytz.utc) - timedelta(hours=5)).isoformat()
    end = (datetime.now(bot.pytz.utc) - timedelta(hours=4)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, started_notified, finished_notified) "
        "VALUES (?, ?, ?, 30, 1, 1)",
        (uid, start, end)
    )
    session_id = cur.lastrowid
    conn.commit(); conn.close()
    bot.join_coworking_session(session_id, uid)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-07, live conversation): creating a
    # session notified only the creator -- everyone else found out only by
    # opening 🧘 Коворкинг themselves. Now notify past coworking
    # participants ("alumni") -- not every bot user, that would be spam for
    # people who never touched the feature.
    # ══════════════════════════════════════════════════════════════════════
    creator = 1
    make_user(creator, "Артем")

    alumnus = 2
    make_user(alumnus, "Вика")
    create_past_session_with_participant(alumnus)

    never_participated = 3
    make_user(never_participated, "Игорь")

    opted_out_alumnus = 4
    make_user(opted_out_alumnus, "Соня")
    create_past_session_with_participant(opted_out_alumnus)
    bot.update_user(opted_out_alumnus, coworking_notif_on=0)

    fake_bot = FakeBot()
    ctx = FakeCtx(fake_bot)
    ctx.user_data["coworking_pending_start_utc"] = (datetime.now(bot.pytz.utc) + timedelta(minutes=30)).isoformat()
    upd = FakeUpdate(creator, data="coworking_dur_25", message=FakeMsg(creator))
    await bot.coworking_set_duration(upd, ctx)

    targets = {c[0] for c in fake_bot.sent}

    # 1. The creator still gets their own confirmation, as before.
    assert creator in targets, fake_bot.sent
    print("1. The creator still gets their own creation confirmation (no regression)")

    # 2. A past coworking participant ("alumnus") gets notified about the
    #    new session.
    assert alumnus in targets, f"an alumnus must be notified about a new session: {fake_bot.sent}"
    alumnus_text = next(t for c, t, _ in fake_bot.sent if c == alumnus)
    assert "Новая коворкинг-сессия" in alumnus_text, alumnus_text
    print("2. A past participant ('alumnus') is notified about the new session (the feature)")

    # 3. Someone who never touched coworking is NOT notified -- avoids
    #    spamming everyone about an unfamiliar feature.
    assert never_participated not in targets, \
        f"must not spam someone who never used coworking: {fake_bot.sent}"
    print("3. Someone who never participated in coworking is not notified (avoids spam)")

    # 4. An alumnus who opted out (coworking_notif_on=0) is not notified.
    assert opted_out_alumnus not in targets, \
        f"an opted-out alumnus must not be notified: {fake_bot.sent}"
    print("4. An alumnus who opted out via coworking_notif_on=0 is not notified")

    # 5. Tapping "🔕 Не присылать такие" on the invite sets coworking_notif_on=0
    #    for that user going forward.
    assert bot.get_user(alumnus).get("coworking_notif_on") in (None, "1", 1), \
        "sanity: alumnus starts opted IN"
    off_msg = FakeMsg(alumnus)
    upd_off = FakeUpdate(alumnus, data="coworking_notif_off", message=off_msg)
    await bot.coworking_notif_off(upd_off, FakeCtx(FakeBot()))
    assert str(bot.get_user(alumnus).get("coworking_notif_on")) == "0"
    print("5. Tapping '🔕 Не присылать такие' opts the user out going forward")

    # 6. A now-opted-out alumnus (from check 5) does not get notified about
    #    a LATER new session either.
    fake_bot2 = FakeBot()
    ctx2 = FakeCtx(fake_bot2)
    ctx2.user_data["coworking_pending_start_utc"] = (datetime.now(bot.pytz.utc) + timedelta(minutes=45)).isoformat()
    upd2 = FakeUpdate(creator, data="coworking_dur_45", message=FakeMsg(creator))
    await bot.coworking_set_duration(upd2, ctx2)
    targets2 = {c[0] for c in fake_bot2.sent}
    assert alumnus not in targets2, \
        f"the just-opted-out alumnus must not be notified about a later session: {fake_bot2.sent}"
    print("6. The just-opted-out alumnus stays excluded from a later session's notification too")

    print("\nALL COWORKING-NOTIFY-ALUMNI TESTS PASSED")


asyncio.run(main())
