import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_carryover_conversation_hang.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeConversationHandler:
    """Минимальная замена python-telegram-bot's ConversationHandler --
    только то, что использует clear_awaiting_flags/use_yesterday_plan_callback:
    словарь активных диалогов, ключ (chat_id, uid)."""
    def __init__(self):
        self._conversations = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Real bug: use_yesterday_plan_callback ("✅ Взять как задачи на
    # сегодня") is reachable from the SAME message as the morning warmup
    # prompt -- i.e. while the user is still mid-conversation in the
    # morning ritual (M_EXERCISE state). It called clear_awaiting_flags
    # with `update`, whose documented side effect is popping the active
    # morning/evening ConversationHandler entry entirely. That orphaned
    # every subsequent ritual button ("Уже сделал", "Начать разминку",
    # etc.) -- python-telegram-bot's ConversationHandler no longer tracks
    # a conversation for this user, so those state-bound callbacks never
    # fire, and Telegram shows an endless "loading" spinner on tap (the
    # callback query is never answered by anything).
    # ══════════════════════════════════════════════════════════════════════
    yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    bot.save_diary(uid, "evening", {"e_a": "Реальный план"}, for_date=yesterday)

    fake_morning_conv = FakeConversationHandler()
    conv_key = (uid, uid)  # (chat_id, uid) -- FakeChat(uid).id == uid here
    fake_morning_conv._conversations[conv_key] = "M_EXERCISE"  # simulates an active mid-ritual conversation
    orig_morning_conv = bot._morning_conv
    bot._morning_conv = fake_morning_conv
    try:
        ctx = FakeCtx()
        upd = FakeUpdate(uid, data="use_yesterday_plan")
        await bot.use_yesterday_plan_callback(upd, ctx)
        assert conv_key in fake_morning_conv._conversations, \
            "use_yesterday_plan_callback must NOT cancel the active morning conversation -- doing so orphans every subsequent ritual button (the exact hang reported live: tapping 'Уже сделал' after this button did nothing)"
        print("1. use_yesterday_plan_callback no longer cancels the active mid-ritual morning conversation")
    finally:
        bot._morning_conv = orig_morning_conv

    # Sanity: the button still does its actual job (writes today's tasks).
    today = datetime.now(tz).date().isoformat()
    morning_today = bot.get_diary(uid, "morning", today)
    assert morning_today.get("focus") == "Реальный план", morning_today
    print("2. use_yesterday_plan_callback still correctly writes today's task fields")

    print("\nALL CARRYOVER-CONVERSATION-HANG TESTS PASSED")


asyncio.run(main())
