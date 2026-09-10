import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_referral_farming.db")
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


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = 900
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

    async def answer(self, text=None, **kw): pass


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


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan 2026-09-09, financial): unlink_buddy_pair tears
    # a pair apart with NO cooldown -- finalize_buddy_pairing only checked
    # "neither side currently has a buddy", never any history. Two accounts
    # (or one person controlling two) could pair via deep-link invite (+7/+7
    # days), immediately unlink, re-invite via the SAME deep link, pair
    # again (+7/+7 again) -- indefinitely, no new accounts needed each
    # cycle. Fixed via buddy_referral_rewards: the reward for a given PAIR
    # of people is granted at most once, ever, regardless of how many times
    # they unlink and re-pair.
    # ══════════════════════════════════════════════════════════════════════
    uid_a = 1; uid_b = 2
    make_user(uid_a, "Артем"); make_user(uid_b, "Вика")
    today = datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date()
    expected_after_one_reward = (today + timedelta(days=bot.BUDDY_REFERRAL_REWARD_DAYS)).isoformat()

    # 1. First-time pairing via deep-link invite rewards both sides normally.
    fbot1 = FakeBot()
    ctx1 = FakeCtx(fbot1)
    upd1 = FakeUpdate(uid_b, data=f"buddy_invite_accept_{uid_a}", message=FakeMessage(uid_b))
    await bot.buddy_invite_accept(upd1, ctx1)
    assert bot.get_user(uid_a)["subscription_until"][:10] == expected_after_one_reward
    assert bot.get_user(uid_b)["subscription_until"][:10] == expected_after_one_reward
    print("1. First-time deep-link pairing rewards both sides normally")

    # 2. Unlink -- no cooldown, both immediately free again.
    bot.unlink_buddy_pair(uid_a)
    assert not bot.get_user(uid_a).get("buddy_uid")
    assert not bot.get_user(uid_b).get("buddy_uid")
    print("2. Unlinking frees both sides immediately (no cooldown, by design)")

    # 3. Re-inviting via the SAME deep link and pairing AGAIN must NOT grant
    #    a second +7/+7 -- subscription_until stays exactly where it was
    #    after check 1, not extended further.
    fbot2 = FakeBot()
    ctx2 = FakeCtx(fbot2)
    upd2 = FakeUpdate(uid_b, data=f"buddy_invite_accept_{uid_a}", message=FakeMessage(uid_b))
    await bot.buddy_invite_accept(upd2, ctx2)
    # The pair DOES form again (that's legitimate -- reconnecting with the
    # same person is fine), just without a repeat reward.
    assert int(bot.get_user(uid_a)["buddy_uid"]) == uid_b
    assert bot.get_user(uid_a)["subscription_until"][:10] == expected_after_one_reward, \
        f"a second reward for the SAME pair must NOT be granted: {bot.get_user(uid_a)['subscription_until']}"
    assert bot.get_user(uid_b)["subscription_until"][:10] == expected_after_one_reward, \
        f"a second reward for the SAME pair must NOT be granted: {bot.get_user(uid_b)['subscription_until']}"
    print("3. Re-pairing the SAME two people again does NOT grant a second referral reward")

    # 4. The re-pairing notification must not falsely claim a bonus was
    #    granted when it wasn't (accurate messaging, not just no double-pay).
    assert not any("бонус за приглашение друга" in t for _, t, _ in fbot2.sent), \
        f"must not claim a bonus was granted when the reward was actually skipped: {fbot2.sent}"
    print("4. The re-pairing notification does not falsely claim a bonus was granted")

    # 5. Repeating unlink -> re-pair a THIRD time still grants nothing extra
    #    -- confirms it's not just "blocked once", but permanently for this
    #    pair.
    bot.unlink_buddy_pair(uid_a)
    fbot3 = FakeBot()
    ctx3 = FakeCtx(fbot3)
    upd3 = FakeUpdate(uid_b, data=f"buddy_invite_accept_{uid_a}", message=FakeMessage(uid_b))
    await bot.buddy_invite_accept(upd3, ctx3)
    assert bot.get_user(uid_a)["subscription_until"][:10] == expected_after_one_reward
    assert bot.get_user(uid_b)["subscription_until"][:10] == expected_after_one_reward
    print("5. A third unlink/re-pair cycle for the same pair still grants nothing extra (permanent, not one-shot)")

    # 6. Sanity/regression: a GENUINELY new pair (different people) is still
    #    rewarded normally -- the fix must not block legitimate new
    #    referrals.
    uid_c = 3; uid_d = 4
    make_user(uid_c, "Игорь"); make_user(uid_d, "Соня")
    fbot4 = FakeBot()
    ctx4 = FakeCtx(fbot4)
    upd4 = FakeUpdate(uid_d, data=f"buddy_invite_accept_{uid_c}", message=FakeMessage(uid_d))
    await bot.buddy_invite_accept(upd4, ctx4)
    assert bot.get_user(uid_c)["subscription_until"][:10] == expected_after_one_reward
    assert bot.get_user(uid_d)["subscription_until"][:10] == expected_after_one_reward
    assert any("бонус за приглашение друга" in t for _, t, _ in fbot4.sent), \
        "a genuinely new pair must still see the bonus message"
    print("6. A genuinely different, new pair is still rewarded normally (fix doesn't block real referrals)")

    print("\nALL BUDDY-REFERRAL-FARMING TESTS PASSED")


asyncio.run(main())
