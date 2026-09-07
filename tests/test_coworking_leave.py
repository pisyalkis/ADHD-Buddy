import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_leave.db")
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
    def __init__(self, uid, data=None, message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 901
        return M()


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def create_session(creator_uid, minutes_from_now=30, duration=45):
    start = (datetime.now(bot.pytz.utc) + timedelta(minutes=minutes_from_now)).isoformat()
    end = (datetime.now(bot.pytz.utc) + timedelta(minutes=minutes_from_now + duration)).isoformat()
    conn = sqlite3.connect(bot.DB_PATH)
    cur = conn.execute(
        "INSERT INTO coworking_sessions(creator_id, start_at, end_at, duration_minutes, started_notified, finished_notified) "
        "VALUES (?, ?, ?, ?, 0, 0)",
        (creator_uid, start, end, duration)
    )
    session_id = cur.lastrowid
    conn.commit(); conn.close()
    bot.join_coworking_session(session_id, creator_uid)
    return session_id


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-06): coworking had a "Присоединиться"
    # button but no symmetric way to back out -- once joined (or after
    # creating your own session), the only way to stop being counted in
    # was to just not show up, silently skewing the participant count that
    # everyone else sees.
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1
    make_user(uid1, "Артем")
    uid2 = 2
    make_user(uid2, "Вика")
    uid3 = 3
    make_user(uid3, "Игорь")
    session_id = create_session(uid1)
    bot.join_coworking_session(session_id, uid2)
    bot.join_coworking_session(session_id, uid3)
    assert set(bot.get_coworking_participants(session_id)) == {uid1, uid2, uid3}

    # 1. leave_coworking_session removes exactly the requested participant
    #    and reports True (a real removal).
    removed1 = bot.leave_coworking_session(session_id, uid3)
    assert removed1 is True
    assert set(bot.get_coworking_participants(session_id)) == {uid1, uid2}
    print("1. leave_coworking_session removes the participant and reports True")

    # 2. leave_coworking_session on someone already not in the session
    #    (double tap, or never joined) reports False and changes nothing.
    removed2 = bot.leave_coworking_session(session_id, uid3)
    assert removed2 is False
    assert set(bot.get_coworking_participants(session_id)) == {uid1, uid2}
    print("2. leave_coworking_session on a non-participant reports False, no change (double-tap safe)")

    # re-add uid3 for the callback-level tests below
    bot.join_coworking_session(session_id, uid3)

    # 3. coworking_leave_callback: a real leave edits the leaver's own
    #    message to a confirmation, and broadcasts the DECREMENTED count to
    #    everyone still in the session (but not to the leaver).
    fake_bot = FakeBot()
    leave_msg = FakeMsg(uid3)
    upd_leave = FakeUpdate(uid3, data=f"coworking_leave_{session_id}", message=leave_msg)
    await bot.coworking_leave_callback(upd_leave, FakeCtx(fake_bot))
    assert set(bot.get_coworking_participants(session_id)) == {uid1, uid2}
    assert upd_leave.callback_query.answers[0] == "Ты вышел(ла) из сессии."
    assert leave_msg.texts and "вышел" in leave_msg.texts[-1][0]
    assert len(fake_bot.sent) == 2, f"must broadcast the new count to exactly the 2 remaining participants: {fake_bot.sent}"
    broadcast_targets = {c[0] for c in fake_bot.sent}
    assert broadcast_targets == {uid1, uid2}, broadcast_targets
    for _, text, _ in fake_bot.sent:
        assert "Участников: *2*" in text, text
    print("3. coworking_leave_callback removes the leaver, confirms to them, broadcasts the new count to the rest")

    # 4. A repeat leave (double tap, already gone) answers gracefully and
    #    does NOT re-broadcast (count hasn't changed).
    fake_bot2 = FakeBot()
    upd_leave_again = FakeUpdate(uid3, data=f"coworking_leave_{session_id}", message=FakeMsg(uid3))
    await bot.coworking_leave_callback(upd_leave_again, FakeCtx(fake_bot2))
    assert upd_leave_again.callback_query.answers[0] == "Ты уже не в этой сессии."
    assert not fake_bot2.sent, f"a repeat leave must not re-broadcast an unchanged count: {fake_bot2.sent}"
    print("4. A repeat leave (double tap) is answered gracefully without re-broadcasting")

    # 5. coworking_leave_callback clears an open awaiting_*-flag from
    #    another screen -- same pattern already fixed for the join callback.
    ctx5 = FakeCtx(FakeBot())
    ctx5.user_data["awaiting_name"] = True
    upd_leave5 = FakeUpdate(uid2, data=f"coworking_leave_{session_id}", message=FakeMsg(uid2))
    await bot.coworking_leave_callback(upd_leave5, ctx5)
    assert not ctx5.user_data.get("awaiting_name"), \
        "coworking_leave_callback must clear an open awaiting_*-flag from another screen"
    print("5. coworking_leave_callback clears an open awaiting_*-flag from another screen")

    # 6. The creator leaving is handled exactly like any other participant
    #    (creator_id has no special-case anywhere in the business logic) --
    #    the session simply continues with whoever remains.
    session_id2 = create_session(uid1, minutes_from_now=40)
    bot.join_coworking_session(session_id2, uid2)
    fake_bot6 = FakeBot()
    upd_leave6 = FakeUpdate(uid1, data=f"coworking_leave_{session_id2}", message=FakeMsg(uid1))
    await bot.coworking_leave_callback(upd_leave6, FakeCtx(fake_bot6))
    assert set(bot.get_coworking_participants(session_id2)) == {uid2}, \
        "the creator must be able to leave their own session just like any other participant"
    print("6. The creator can leave their own session the same way any participant can")

    # 7. Both the creator's own confirmation (coworking_set_duration) and
    #    the join broadcast (coworking_join_callback) now offer the
    #    "🚪 Не смогу" leave button, not just the bare menu button.
    uid7 = 7
    make_user(uid7, "Соня")
    ctx7 = FakeCtx(FakeBot())
    ctx7.user_data["coworking_pending_start_utc"] = (datetime.now(bot.pytz.utc) + timedelta(minutes=30)).isoformat()
    upd_dur7 = FakeUpdate(uid7, data="coworking_dur_25", message=FakeMsg(uid7))
    await bot.coworking_set_duration(upd_dur7, ctx7)
    # Since PR "уведомление о новой коворкинг-сессии" (IDEAS.md 2026-09-07),
    # coworking_set_duration may also broadcast to alumni after the
    # creator's own confirmation -- pick out the creator's own message by
    # chat_id rather than assuming it's the last one sent.
    _, _, kb7 = next(m for m in ctx7.bot.sent if m[0] == uid7)
    leave_buttons7 = [b.callback_data for row in kb7.inline_keyboard for b in row if "coworking_leave_" in (b.callback_data or "")]
    assert leave_buttons7, "the session-creation confirmation must offer a leave button"
    print("7. The session-creation confirmation offers a '🚪 Не смогу' leave button")

    uid8 = 8
    make_user(uid8, "Дима")
    ctx8 = FakeCtx(FakeBot())
    upd_join8 = FakeUpdate(uid8, data=f"coworking_join_{session_id2}", message=FakeMsg(uid8))
    await bot.coworking_join_callback(upd_join8, ctx8)
    _, _, kb8 = ctx8.bot.sent[-1]
    leave_buttons8 = [b.callback_data for row in kb8.inline_keyboard for b in row if "coworking_leave_" in (b.callback_data or "")]
    assert leave_buttons8, "the join broadcast must also offer a leave button"
    print("8. The join broadcast also offers a '🚪 Не смогу' leave button")

    print("\nALL COWORKING-LEAVE TESTS PASSED")


asyncio.run(main())
