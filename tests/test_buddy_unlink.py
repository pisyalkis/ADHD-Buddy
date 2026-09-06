import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_unlink.db")
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

    async def reply_text(self, text, **kw):
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
    def __init__(self, uid, data=None, message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = message


class FakeCtx:
    def __init__(self, bot_=None):
        self.user_data = {}
        self.bot = bot_


class FakeBot:
    def __init__(self):
        self.sent = []

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
    # Real request (product discussion, this session): buddy switching --
    # break the pair with NO cooldown (both sides immediately free to find
    # a new buddy again), and the other side gets a NEUTRAL notification --
    # explicitly NOT "больше не хочет быть твоим бадди" (would read as
    # rejection), just "решил(а) попробовать по-другому".
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1; uid2 = 2
    make_user(uid1, "Артем"); make_user(uid2, "Вика")
    bot.finalize_buddy_pairing(uid1, uid2)

    # 1. unlink_buddy_pair clears buddy_uid/buddy_paired_at on BOTH sides
    #    and returns the ex-partner's uid.
    partner = bot.unlink_buddy_pair(uid1)
    assert partner == uid2, partner
    u1 = bot.get_user(uid1); u2 = bot.get_user(uid2)
    assert not u1.get("buddy_uid") and not u1.get("buddy_paired_at")
    assert not u2.get("buddy_uid") and not u2.get("buddy_paired_at")
    print("1. unlink_buddy_pair clears the link symmetrically and returns the ex-partner's uid")

    # 2. unlink_buddy_pair on a user with no buddy is a harmless no-op.
    uid3 = 3
    make_user(uid3, "Соло")
    assert bot.unlink_buddy_pair(uid3) is None
    print("2. unlink_buddy_pair returns None for a user who has no buddy (no-op)")

    # 3. Both sides are IMMEDIATELY free to seek again -- no cooldown flag
    #    anywhere blocks a fresh pairing right after unlinking.
    uid4 = 4
    make_user(uid4, "Новый")
    ok = bot.finalize_buddy_pairing(uid1, uid4)
    assert ok is True, "no cooldown must block re-pairing right after an unlink"
    print("3. A user can immediately pair again right after unlinking -- no cooldown")

    # 4. buddy_unlink_menu shows a confirmation screen (doesn't unlink on
    #    its own) naming the partner, with a way to cancel.
    uid5 = 5; uid6 = 6
    make_user(uid5, "Игорь"); make_user(uid6, "Соня")
    bot.finalize_buddy_pairing(uid5, uid6)
    menu_msg = FakeMessage(uid5)
    upd_menu = FakeUpdate(uid5, data="buddy_unlink_menu", message=menu_msg)
    await bot.buddy_unlink_menu(upd_menu, FakeCtx(FakeBot()))
    assert "Соня" in menu_msg.text, menu_msg.text
    assert int(bot.get_user(uid5)["buddy_uid"]) == uid6, "the confirmation screen alone must not unlink anything"
    print("4. buddy_unlink_menu shows a confirmation naming the partner, without unlinking yet")

    # 5. buddy_unlink_confirm actually unlinks AND sends a NEUTRAL
    #    notification to the ex-partner -- not blaming, no "не хочет быть
    #    твоим бадди" framing.
    fbot5 = FakeBot()
    ctx5 = FakeCtx(fbot5)
    confirm_msg = FakeMessage(uid5)
    upd_confirm = FakeUpdate(uid5, data="buddy_unlink_confirm", message=confirm_msg)
    await bot.buddy_unlink_confirm(upd_confirm, ctx5)
    assert not bot.get_user(uid5).get("buddy_uid")
    assert not bot.get_user(uid6).get("buddy_uid")
    assert len(fbot5.sent) == 1, fbot5.sent
    notif_chat, notif_text, _ = fbot5.sent[0]
    assert notif_chat == uid6, "the notification must go to the EX-PARTNER, not the initiator"
    assert "не хочет быть" not in notif_text, "must not use blaming/rejection framing"
    assert "по-другому" in notif_text
    print("5. buddy_unlink_confirm unlinks both sides and sends a neutral (non-blaming) notification to the ex-partner")

    # 6. buddy_unlink_menu on a user with no buddy safely falls back to the
    #    normal buddy_menu instead of erroring (e.g. a stale/double tap
    #    after the pair already broke up).
    stale_msg = FakeMessage(uid5)
    upd_stale = FakeUpdate(uid5, data="buddy_unlink_menu", message=stale_msg)
    await bot.buddy_unlink_menu(upd_stale, FakeCtx(FakeBot()))
    assert "Бадди не задан" in stale_msg.text or "Твой бадди" not in stale_msg.text
    print("6. buddy_unlink_menu on an already-unlinked user falls back to the normal buddy menu, no crash")

    print("\nALL BUDDY UNLINK TESTS PASSED")


asyncio.run(main())
