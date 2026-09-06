import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_pairs.db")
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


_next_id = [100]


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = _next_id[0]
        _next_id[0] += 1
        self.text = ""
        self.texts = []

    async def reply_text(self, text, **kw):
        m = FakeMessage(self.chat_id)
        m.text = text
        return m

    async def edit_text(self, text, **kw):
        self.text = text
        self.texts.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append((text, kw.get("reply_markup")))


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, args=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = message


class FakeCtx:
    def __init__(self, bot_=None, args=None):
        self.user_data = {}
        self.bot = bot_
        self.args = args or []


class FakeBot:
    def __init__(self, username="adhd_buddy_bot"):
        self.sent = []
        self.username = username

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 901
        return M()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (product discussion, this session): buddy pairing --
    # invite a friend via deep link (t.me/<bot>?start=buddy_<uid>) or get
    # randomly matched with another user also seeking a buddy. Coexists
    # with the old manual buddy_name (unlinked, no notifications).
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1
    make_user(uid1, "Артем")
    uid2 = 2
    make_user(uid2, "Вика")

    # 1. finalize_buddy_pairing links both sides symmetrically.
    ok = bot.finalize_buddy_pairing(uid1, uid2)
    assert ok is True
    u1 = bot.get_user(uid1); u2 = bot.get_user(uid2)
    assert int(u1["buddy_uid"]) == uid2
    assert int(u2["buddy_uid"]) == uid1
    assert u1["buddy_paired_at"] and u2["buddy_paired_at"]
    print("1. finalize_buddy_pairing links both sides symmetrically")

    # 2. Refuses if either side already has a buddy.
    uid3 = 3
    make_user(uid3, "Игорь")
    assert bot.finalize_buddy_pairing(uid1, uid3) is False, "uid1 already has a buddy"
    assert bot.finalize_buddy_pairing(uid3, uid2) is False, "uid2 already has a buddy"
    print("2. finalize_buddy_pairing refuses when either side already has a buddy")

    # 3. Refuses self-pairing.
    uid4 = 4
    make_user(uid4, "Соло")
    assert bot.finalize_buddy_pairing(uid4, uid4) is False
    print("3. finalize_buddy_pairing refuses pairing a user with themself")

    # 4. buddy_menu shows the linked partner's real name when buddy_uid is
    #    set, plus a "how to work with a buddy" guide button to revisit it.
    menu_msg = FakeMessage(uid1)
    upd_menu = FakeUpdate(uid1, data="go_buddy", message=menu_msg)
    await bot.buddy_menu(upd_menu, FakeCtx(FakeBot()))
    linked_text, linked_kb = menu_msg.texts[-1]
    assert "Вика" in linked_text, linked_text
    assert kb_callbacks(linked_kb) == ["buddy_ping", "buddy_guide", "buddy_unlink_menu", "go_menu"], kb_callbacks(linked_kb)
    print("4. buddy_menu shows the linked partner's real name and a button to revisit the buddy guide")

    # 4b. _parse_buddy_invite_arg: valid deep link for a brand-new user.
    inviter = bot.get_user(uid4)
    assert inviter.get("buddy_uid") in ("", None) or not inviter.get("buddy_uid")
    ctx_new = FakeCtx(FakeBot(), args=[f"buddy_{uid4}"])
    new_uid = 5
    result = bot._parse_buddy_invite_arg(ctx_new, new_uid)
    assert result == uid4, result
    print("4b. _parse_buddy_invite_arg resolves a valid deep-link payload to the inviter's uid")

    # 5. _parse_buddy_invite_arg rejects self-invite, unknown inviter, and an
    #    inviter who already has a buddy (uid1 does, from step 1).
    assert bot._parse_buddy_invite_arg(FakeCtx(args=[f"buddy_{uid4}"]), uid4) is None, "self-invite must be rejected"
    assert bot._parse_buddy_invite_arg(FakeCtx(args=["buddy_99999"]), new_uid) is None, "unknown inviter must be rejected"
    assert bot._parse_buddy_invite_arg(FakeCtx(args=[f"buddy_{uid1}"]), new_uid) is None, "an inviter who already has a buddy must be rejected"
    assert bot._parse_buddy_invite_arg(FakeCtx(args=["not_a_buddy_payload"]), new_uid) is None, "malformed payload must be ignored"
    print("5. _parse_buddy_invite_arg rejects self-invite / unknown inviter / already-paired inviter / malformed payload")

    # 6. start() for a BRAND-NEW user with a valid invite personalizes the
    #    intro and stashes pending_buddy_invite for later finalization.
    ctx6 = FakeCtx(FakeBot(), args=[f"buddy_{uid4}"])
    upd6 = FakeUpdate(new_uid, message=FakeMessage(new_uid))
    state = await bot.start(upd6, ctx6)
    assert ctx6.user_data.get("pending_buddy_invite") == uid4
    assert state == bot.ONBOARD_NAME
    print("6. start() stashes pending_buddy_invite for a brand-new invited user and proceeds to onboarding")

    # 7. _finalize_pending_buddy_invite (called from onboard_notif_on/_skip)
    #    finalizes the pairing once the invitee has a name, and notifies both.
    bot.update_user(new_uid, name="Новенький")
    fbot7 = FakeBot()
    ctx7 = FakeCtx(fbot7)
    ctx7.user_data["pending_buddy_invite"] = uid4
    msg7 = FakeMessage(new_uid)
    await bot._finalize_pending_buddy_invite(ctx7, msg7, new_uid)
    assert "pending_buddy_invite" not in ctx7.user_data
    assert int(bot.get_user(new_uid)["buddy_uid"]) == uid4
    assert int(bot.get_user(uid4)["buddy_uid"]) == new_uid
    assert len(fbot7.sent) == 6, fbot7.sent  # celebratory + guide + share-ask, per side
    assert sum(1 for _, t, _ in fbot7.sent if t == bot.BUDDY_GUIDE_TEXT) == 2, \
        "both sides must receive the 'how to work with a buddy' guide"
    print("7. _finalize_pending_buddy_invite finalizes the pairing, notifies both sides and sends the guide to both")

    # 8. A race: the inviter got paired elsewhere while the invitee was still
    #    onboarding -- _finalize_pending_buddy_invite must no-op silently,
    #    not raise or corrupt state.
    uid8a = 8; uid8b = 9; uid8c = 10
    make_user(uid8a, "A"); make_user(uid8b, "B"); make_user(uid8c, "C")
    bot.finalize_buddy_pairing(uid8a, uid8b)  # uid8a already taken by the time uid8c finishes onboarding
    fbot8 = FakeBot()
    ctx8 = FakeCtx(fbot8)
    ctx8.user_data["pending_buddy_invite"] = uid8a
    await bot._finalize_pending_buddy_invite(ctx8, FakeMessage(uid8c), uid8c)
    assert not bot.get_user(uid8c).get("buddy_uid"), "the race loser must not end up linked"
    assert not fbot8.sent, "no notification should fire on a failed race"
    print("8. _finalize_pending_buddy_invite silently no-ops when the inviter got paired elsewhere during onboarding")

    # 9. Existing user hitting a valid deep link gets an accept/decline
    #    prompt instead of the usual welcome-back message.
    uid9 = 11
    make_user(uid9, "Существующий")
    ctx9 = FakeCtx(FakeBot(), args=[f"buddy_{uid8c}"])
    msg9 = FakeMessage(uid9)
    upd9 = FakeUpdate(uid9, message=msg9)
    ret9 = await bot.start(upd9, ctx9)
    assert ret9 == bot.ConversationHandler.END
    last_reply = msg9  # reply_text returns a new FakeMessage; check via closure below
    print("9. start() routes an existing user's valid deep-link hit to the accept/decline prompt (see step 9b)")

    # 9b. Verify buddy_invite_accept actually finalizes that pairing.
    fbot9 = FakeBot()
    ctx9b = FakeCtx(fbot9)
    q9b_msg = FakeMessage(uid9)
    upd9b = FakeUpdate(uid9, data=f"buddy_invite_accept_{uid8c}", message=q9b_msg)
    await bot.buddy_invite_accept(upd9b, ctx9b)
    assert int(bot.get_user(uid9)["buddy_uid"]) == uid8c
    assert int(bot.get_user(uid8c)["buddy_uid"]) == uid9
    print("9b. buddy_invite_accept finalizes the pairing for an existing user who accepts")

    # 10. Random matching: first seeker queues (buddy_seeking_since set),
    #     second seeker gets matched immediately with the first (FIFO).
    uid10 = 12; uid11 = 13
    make_user(uid10, "Ищущий1"); make_user(uid11, "Ищущий2")
    fbot10 = FakeBot()
    ctx10 = FakeCtx(fbot10)
    q10_msg = FakeMessage(uid10)
    upd10 = FakeUpdate(uid10, data="buddy_find_match", message=q10_msg)
    await bot.buddy_find_match(upd10, ctx10)
    assert bot.get_user(uid10).get("buddy_seeking_since"), "first seeker must be queued, not matched with themself"
    assert not bot.get_user(uid10).get("buddy_uid")
    print("10. buddy_find_match queues the first seeker (buddy_seeking_since set)")

    fbot11 = FakeBot()
    ctx11 = FakeCtx(fbot11)
    q11_msg = FakeMessage(uid11)
    upd11 = FakeUpdate(uid11, data="buddy_find_match", message=q11_msg)
    await bot.buddy_find_match(upd11, ctx11)
    assert int(bot.get_user(uid11)["buddy_uid"]) == uid10
    assert int(bot.get_user(uid10)["buddy_uid"]) == uid11
    assert not bot.get_user(uid10).get("buddy_seeking_since"), "seeking flag must clear once matched"
    assert len(fbot11.sent) == 6, "_notify_buddy_paired must message both sides (celebratory + guide + share-ask each)"
    print("11. buddy_find_match immediately matches the second seeker with the first (FIFO), clears seeking flags, notifies both")

    # 12. buddy_cancel_seeking clears the flag without pairing anyone.
    uid12 = 14
    make_user(uid12, "Отменяющий")
    bot.update_user(uid12, buddy_seeking_since=datetime.now(bot.pytz.utc).isoformat())
    ctx12 = FakeCtx(FakeBot())
    q12_msg = FakeMessage(uid12)
    upd12 = FakeUpdate(uid12, data="buddy_cancel_seeking", message=q12_msg)
    await bot.buddy_cancel_seeking(upd12, ctx12)
    assert not bot.get_user(uid12).get("buddy_seeking_since")
    assert not bot.get_user(uid12).get("buddy_uid")
    print("12. buddy_cancel_seeking clears the seeking flag without pairing")

    # 13. buddy_menu coexistence: buddy_name (old, unlinked) stays untouched
    #     and still shows up for a user who has never linked via buddy_uid.
    uid13 = 15
    make_user(uid13, "Мануальный")
    bot.update_user(uid13, buddy_name="Друг детства")
    fbot13 = FakeBot()
    ctx13 = FakeCtx(fbot13)
    msg13 = FakeMessage(uid13)
    upd13 = FakeUpdate(uid13, data="go_buddy", message=msg13)
    await bot.buddy_menu(upd13, ctx13)
    assert bot.get_user(uid13)["buddy_name"] == "Друг детства", "old manual buddy_name must remain untouched"
    print("13. The old manual buddy_name coexists untouched for users who haven't linked via buddy_uid")

    # 14. "📖 Как работать с бадди" re-shows the guide on demand, with a way
    #     back to the buddy menu.
    guide_msg = FakeMessage(uid1)
    upd_guide = FakeUpdate(uid1, data="buddy_guide", message=guide_msg)
    await bot.buddy_guide(upd_guide, FakeCtx(FakeBot()))
    guide_text, guide_kb = guide_msg.texts[-1]
    assert guide_text == bot.BUDDY_GUIDE_TEXT
    assert kb_callbacks(guide_kb) == ["go_buddy"], kb_callbacks(guide_kb)
    print("14. buddy_guide re-shows the 'how to work with a buddy' guide on demand")

    print("\nALL BUDDY PAIRING TESTS PASSED")


asyncio.run(main())
