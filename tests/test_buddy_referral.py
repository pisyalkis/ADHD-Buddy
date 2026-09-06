import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_referral.db")
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


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (product discussion, this session): referral reward --
    # reuse the EXISTING promo/grant machinery (grant_access_days, the same
    # one used for real Stars payments and admin /grant) rather than build
    # a new economy. Reward BOTH sides, but only for a deep-link invite --
    # random matching isn't a referral, nobody "brought" anyone in.
    # ══════════════════════════════════════════════════════════════════════

    # 1. finalize_buddy_pairing(reward_referral=False) -- the default, used
    #    by random matching -- must NOT touch subscription_until.
    uid1 = 1; uid2 = 2
    make_user(uid1, "Артем"); make_user(uid2, "Вика")
    ok = bot.finalize_buddy_pairing(uid1, uid2, reward_referral=False)
    assert ok is True
    assert not bot.get_user(uid1).get("subscription_until")
    assert not bot.get_user(uid2).get("subscription_until")
    print("1. finalize_buddy_pairing without reward_referral grants no bonus (random matching)")

    # 2. finalize_buddy_pairing(reward_referral=True) -- used by deep-link
    #    invites -- grants BUDDY_REFERRAL_REWARD_DAYS to BOTH sides via the
    #    same grant_access_days() used for real payments.
    uid3 = 3; uid4 = 4
    make_user(uid3, "Игорь"); make_user(uid4, "Соня")
    ok2 = bot.finalize_buddy_pairing(uid3, uid4, reward_referral=True)
    assert ok2 is True
    # grant_access_days computes "today" via the user's own tz (Tbilisi,
    # UTC+4) -- date.today() uses the SYSTEM tz instead, which can be a
    # different calendar day near midnight Tbilisi time. Match the bot's
    # own reference point to avoid a real-clock-dependent flake.
    today = datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date()
    expected = (today + timedelta(days=bot.BUDDY_REFERRAL_REWARD_DAYS)).isoformat()
    assert bot.get_user(uid3)["subscription_until"][:10] == expected, bot.get_user(uid3)["subscription_until"]
    assert bot.get_user(uid4)["subscription_until"][:10] == expected, bot.get_user(uid4)["subscription_until"]
    print(f"2. finalize_buddy_pairing(reward_referral=True) grants {bot.BUDDY_REFERRAL_REWARD_DAYS} days of access to both sides")

    # 3. A user who ALREADY has an active subscription gets it extended
    #    further (grant_access_days stacks from the later of today/current
    #    subscription_until -- same rule as a real Stars payment), not
    #    overwritten with a shorter date.
    uid5 = 5; uid6 = 6
    make_user(uid5, "Существующий"); make_user(uid6, "Новый")
    far_future = (today + timedelta(days=100)).isoformat()
    bot.update_user(uid5, subscription_until=far_future)
    bot.finalize_buddy_pairing(uid5, uid6, reward_referral=True)
    expected_stacked = (today + timedelta(days=100 + bot.BUDDY_REFERRAL_REWARD_DAYS)).isoformat()
    assert bot.get_user(uid5)["subscription_until"][:10] == expected_stacked, bot.get_user(uid5)["subscription_until"]
    print("3. The referral bonus stacks on top of an already-active subscription, doesn't overwrite it")

    # 4. End-to-end: _finalize_pending_buddy_invite (new-user-invited-by-
    #    deep-link path) rewards both sides AND mentions the bonus in the
    #    notification text sent to both.
    uid7 = 7  # inviter
    make_user(uid7, "Пригласивший")
    uid8 = 8  # brand-new invitee
    make_user(uid8, "Приглашённый")
    fbot4 = FakeBot()
    ctx4 = FakeCtx(fbot4)
    ctx4.user_data["pending_buddy_invite"] = uid7
    await bot._finalize_pending_buddy_invite(ctx4, FakeMessage(uid8), uid8)
    assert bot.get_user(uid7)["subscription_until"][:10] == expected
    assert bot.get_user(uid8)["subscription_until"][:10] == expected
    bonus_texts = [t for _, t, _ in fbot4.sent if "бонус за приглашение друга" in t]
    assert len(bonus_texts) == 2, "both sides must see the bonus mentioned in their pairing notification"
    print("4. _finalize_pending_buddy_invite rewards both sides via the deep-link path and mentions the bonus to both")

    # 5. End-to-end: buddy_invite_accept (existing-user-accepts-deep-link
    #    path) also rewards both sides.
    uid9 = 9  # inviter
    make_user(uid9, "Пригласивший2")
    uid10 = 10  # existing user accepting
    make_user(uid10, "Принимающий")
    fbot5 = FakeBot()
    ctx5 = FakeCtx(fbot5)
    upd5 = FakeUpdate(uid10, data=f"buddy_invite_accept_{uid9}", message=FakeMessage(uid10))
    await bot.buddy_invite_accept(upd5, ctx5)
    assert bot.get_user(uid9)["subscription_until"][:10] == expected
    assert bot.get_user(uid10)["subscription_until"][:10] == expected
    print("5. buddy_invite_accept rewards both sides via the deep-link accept path")

    # 6. Random matching (buddy_find_match) must NOT reward -- confirms the
    #    real handler wiring, not just the underlying finalize function.
    uid11 = 11; uid12 = 12
    make_user(uid11, "Ищущий1"); make_user(uid12, "Ищущий2")
    await bot.buddy_find_match(FakeUpdate(uid11, data="buddy_find_match", message=FakeMessage(uid11)), FakeCtx(FakeBot()))
    await bot.buddy_find_match(FakeUpdate(uid12, data="buddy_find_match", message=FakeMessage(uid12)), FakeCtx(FakeBot()))
    assert int(bot.get_user(uid12)["buddy_uid"]) == uid11
    assert not bot.get_user(uid11).get("subscription_until"), "random matching must not grant a referral bonus"
    assert not bot.get_user(uid12).get("subscription_until"), "random matching must not grant a referral bonus"
    print("6. buddy_find_match (random matching) does not grant any referral bonus")

    # 7. The invite-link screen itself mentions the bonus upfront, so the
    #    inviter knows what's in it for them before sharing the link.
    uid13 = 13
    make_user(uid13, "Показывающий")
    msg13 = FakeMessage(uid13)
    upd13 = FakeUpdate(uid13, data="buddy_invite_link", message=msg13)
    await bot.buddy_invite_link(upd13, FakeCtx(FakeBot()))
    assert str(bot.BUDDY_REFERRAL_REWARD_DAYS) in msg13.text, msg13.text
    print("7. The invite-link screen mentions the referral bonus upfront")

    print("\nALL BUDDY REFERRAL TESTS PASSED")


asyncio.run(main())
