import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, date

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup6_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = FakeQuery(uid, data) if data is not None else None


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        class _M:
            message_id = 999999
        return _M()
    async def delete_message(self, chat_id, message_id): pass


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: 5 top-level navigation entry points (reachable from the main menu
    # / "Ещё" submenu) didn't clear stale awaiting_* flags, unlike every
    # sibling navigation handler (go_menu, go_settings, etc.) -- a leftover
    # flag could hijack the user's next ordinary text message.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["awaiting_name"] = True
    await bot.go_menu_more(FakeUpdate(uid, data="go_menu_more"), ctx)
    assert ctx.user_data.get("awaiting_name") is False, ctx.user_data
    print("1. go_menu_more clears a stale awaiting_name")

    ctx2 = FakeCtx()
    ctx2.user_data["awaiting_city"] = True
    await bot.go_focus(FakeUpdate(uid, data="go_focus"), ctx2)
    assert ctx2.user_data.get("awaiting_city") is False, ctx2.user_data
    print("2. go_focus clears a stale awaiting_city")

    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_feedback"] = True
    await bot.show_skill(FakeUpdate(uid, data="go_skill"), ctx3)
    assert ctx3.user_data.get("awaiting_feedback") is False, ctx3.user_data
    print("3. show_skill clears a stale awaiting_feedback")

    ctx4 = FakeCtx()
    ctx4.user_data["awaiting_promo_code"] = True
    await bot.show_streak(FakeUpdate(uid, data="go_streak"), ctx4)
    assert ctx4.user_data.get("awaiting_promo_code") is False, ctx4.user_data
    print("4. show_streak clears a stale awaiting_promo_code")

    ctx5 = FakeCtx()
    ctx5.user_data["awaiting_reminder_add"] = True
    await bot.show_day_card(FakeUpdate(uid, data="go_daycard"), ctx5)
    assert ctx5.user_data.get("awaiting_reminder_add") is False, ctx5.user_data
    print("5a. show_day_card clears a stale awaiting_reminder_add")

    ctx6 = FakeCtx()
    ctx6.user_data["awaiting_pool_add"] = True
    today_iso = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    await bot.day_card_nav(FakeUpdate(uid, data=f"daycard_{today_iso}"), ctx6)
    assert ctx6.user_data.get("awaiting_pool_add") is False, ctx6.user_data
    print("5b. day_card_nav clears a stale awaiting_pool_add")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: admin_msg_start (the "write to this user" button in /users) didn't
    # clear stale awaiting_* flags -- the admin's own message meant for the
    # target user could get silently swallowed by an abandoned flow instead.
    # ══════════════════════════════════════════════════════════════════════
    ctx7 = FakeCtx()
    ctx7.user_data["awaiting_feedback"] = True
    await bot.admin_msg_start(FakeUpdate(bot.NOTIFY_USER_ID, data=f"admin_msg_{uid}"), ctx7)
    assert ctx7.user_data.get("awaiting_feedback") is False, ctx7.user_data
    assert ctx7.user_data.get("admin_msg_target") == uid
    print("6. admin_msg_start clears a stale awaiting_feedback")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: grant_access_days added to promo_extra_days, which is anchored to
    # the user's ORIGINAL signup date -- for anyone whose trial lapsed more
    # than `days` days ago, granting access silently did nothing even though
    # the bot claimed success.
    # ══════════════════════════════════════════════════════════════════════
    long_ago = (date.today() - timedelta(days=200)).isoformat()
    bot.update_user(uid, created_at=long_ago, promo_extra_days=0, subscription_until="")
    assert bot.get_access_status(bot.get_user(uid)) == "expired", "sanity: trial should already be long expired"

    bot.grant_access_days(uid, 30)
    status_after = bot.get_access_status(bot.get_user(uid))
    assert status_after == "subscribed", \
        f"granting 30 days to a long-expired account must restore access NOW, got status={status_after!r}"
    print("7a. grant_access_days restores access immediately for a long-expired account")

    # Granting again extends from the existing subscription_until, not from today
    until_1 = bot.get_user(uid)["subscription_until"]
    bot.grant_access_days(uid, 10)
    until_2 = bot.get_user(uid)["subscription_until"]
    expected = (date.fromisoformat(until_1[:10]) + timedelta(days=10)).isoformat()
    assert until_2[:10] == expected, f"expected {expected}, got {until_2[:10]}"
    print("7b. A second grant extends from the existing subscription_until, not from today")

    print("\nALL CHECKUP-6 BATCH TESTS PASSED")


asyncio.run(main())
