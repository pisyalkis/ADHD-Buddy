import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking.db")
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
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edited = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 901
        return M()
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append((chat_id, text, kw.get("reply_markup")))


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


class FakeApp:
    def __init__(self, bot_):
        self.bot = bot_


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (product discussion): open co-working sessions -- anyone
    # can post "silent work at 18:00 for 45 min", others join without any
    # identity exposure, the bot just synchronizes start/end and shows a
    # live participant count.
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1
    make_user(uid1, "Артем")
    uid2 = 2
    make_user(uid2, "Вика")

    # 1. Creating a session: enter a valid future HH:MM, pick a duration --
    #    session gets created with the creator as its first participant.
    fake_bot1 = FakeBot()
    ctx1 = FakeCtx(fake_bot1)
    ctx1.user_data["awaiting_coworking_time"] = True
    now_tbilisi = datetime.now(TBILISI)
    # The coworking time-entry flow only supports "later today" (HH:MM,
    # no date) -- a naive "+1 hour" wraps past midnight when the sandbox's
    # real clock is late evening, which strftime silently turns into an
    # EARLIER time on the same calendar day (looks like the past to
    # handle_text). Cap the offset so it always stays before midnight.
    minutes_left_today = (24 * 60 - 1) - (now_tbilisi.hour * 60 + now_tbilisi.minute)
    offset_minutes = max(1, min(60, minutes_left_today))
    future_time = (now_tbilisi + timedelta(minutes=offset_minutes)).strftime("%H:%M")
    class FakeTextMsg:
        def __init__(self, uid_, text):
            self.chat_id = uid_
            self.text = text
        async def reply_text(self, text, **kw):
            return self
    upd_time = FakeUpdate(uid1, text_message=FakeTextMsg(uid1, future_time))
    await bot.handle_text(upd_time, ctx1)
    assert ctx1.user_data.get("coworking_pending_start_utc") is not None, "a valid future time must stage the pending start"
    print("1. Entering a valid future HH:MM stages the session's start time")

    dur_msg = FakeMsg(uid1)
    upd_dur = FakeUpdate(uid1, data="coworking_dur_45", message=dur_msg)
    await bot.coworking_set_duration(upd_dur, ctx1)
    sessions = bot.get_open_coworking_sessions()
    assert len(sessions) == 1, sessions
    session = sessions[0]
    assert session["duration_minutes"] == 45
    assert session["creator_id"] == uid1
    participants = bot.get_coworking_participants(session["id"])
    assert participants == [uid1], "the creator must be auto-joined as the first participant"
    print("2. Picking a duration creates the session with the creator already joined")

    # 3. A second user joins -- both the joiner AND the original creator get
    #    an updated participant count (creator's tracked message refreshes
    #    even though THEY didn't tap anything just now).
    join_msg = FakeMsg(uid2)
    upd_join = FakeUpdate(uid2, data=f"coworking_join_{session['id']}", message=join_msg)
    await bot.coworking_join_callback(upd_join, FakeCtx(fake_bot1))
    participants2 = bot.get_coworking_participants(session["id"])
    assert set(participants2) == {uid1, uid2}, participants2
    sent_texts = [t for _, t, _ in fake_bot1.sent]
    creator_texts = [t for t in sent_texts if "2" in t]
    assert creator_texts, \
        f"the creator's tracked message must be refreshed with the new count of 2, got {sent_texts}"
    print("3. A second user joining updates the participant count for BOTH the joiner and the original creator")

    # 4. Joining twice is a harmless no-op (doesn't duplicate the participant).
    upd_join_again = FakeUpdate(uid2, data=f"coworking_join_{session['id']}", message=join_msg)
    await bot.coworking_join_callback(upd_join_again, FakeCtx(fake_bot1))
    assert len(bot.get_coworking_participants(session["id"])) == 2, "joining twice must not duplicate the participant"
    print("4. Joining the same session twice does not duplicate the participant")

    # 5. check_coworking_sessions fires the start ping once start_at has
    #    passed, to every participant, with the live count -- and marks the
    #    session so it doesn't fire again.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("UPDATE coworking_sessions SET start_at=? WHERE id=?",
                 ((datetime.now(bot.pytz.utc) - timedelta(minutes=1)).isoformat(), session["id"]))
    conn.commit(); conn.close()
    app = FakeApp(FakeBot())
    await bot.check_coworking_sessions(app)
    assert len(app.bot.sent) == 2, app.bot.sent
    assert all("началась" in t for _, t, _ in app.bot.sent)
    assert all("2" in t for _, t, _ in app.bot.sent)
    started_session = bot.get_coworking_session(session["id"])
    assert started_session["started_notified"] == 1

    app_repeat = FakeApp(FakeBot())
    await bot.check_coworking_sessions(app_repeat)
    assert not app_repeat.bot.sent, "an already-notified start must not fire again on the next tick"
    print("5. check_coworking_sessions pings all participants exactly once when the session starts")

    # 6. check_coworking_sessions fires the end ping once end_at has passed.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("UPDATE coworking_sessions SET end_at=? WHERE id=?",
                 ((datetime.now(bot.pytz.utc) - timedelta(minutes=1)).isoformat(), session["id"]))
    conn.commit(); conn.close()
    app2 = FakeApp(FakeBot())
    await bot.check_coworking_sessions(app2)
    assert len(app2.bot.sent) == 2, app2.bot.sent
    assert all("Готово" in t for _, t, _ in app2.bot.sent)
    finished_session = bot.get_coworking_session(session["id"])
    assert finished_session["finished_notified"] == 1
    print("6. check_coworking_sessions pings all participants exactly once when the session ends")

    # 7. A past/started session no longer accepts new joins.
    uid3 = 3
    make_user(uid3, "Игорь")
    late_msg = FakeMsg(uid3)
    upd_late = FakeUpdate(uid3, data=f"coworking_join_{session['id']}", message=late_msg)
    await bot.coworking_join_callback(upd_late, FakeCtx(FakeBot()))
    assert uid3 not in bot.get_coworking_participants(session["id"]), \
        "joining an already-started session must be rejected"
    assert "уже недоступна" in upd_late.callback_query.answers[0]
    print("7. Joining an already-started session is rejected")

    print("\nALL COWORKING TESTS PASSED")


asyncio.run(main())
