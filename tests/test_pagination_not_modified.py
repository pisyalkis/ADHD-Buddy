import os, sys, asyncio, sqlite3
from datetime import datetime
from telegram.error import BadRequest

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pagination_not_modified.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    """First edit_reply_markup call actually 'changes' the keyboard (so it
    succeeds); every following call with an IDENTICAL markup raises the
    real python-telegram-bot exception Telegram sends for a no-op edit --
    exactly what a same-button double-tap produces in production."""
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self._last_markup_repr = None

    async def edit_reply_markup(self, reply_markup=None):
        repr_ = str(reply_markup)
        if repr_ == self._last_markup_repr:
            raise BadRequest("Message is not modified: message to edit is exactly the same")
        self._last_markup_repr = repr_
        return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: pool_change_page/evening_plan_show_more encode callback_data with
    # an ABSOLUTE target page/offset, not a relative step. A same-button
    # double-tap (common ADHD-audience behavior, already fixed once for
    # day_card_nav's edit_text) sends the identical callback_data twice --
    # the second edit_reply_markup targets the exact same, already-shown
    # keyboard and raises BadRequest("Message is not modified"), unhandled,
    # surfacing as a visible error via on_error.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=today)
    for i in range(10):
        bot.add_pool_task(uid, f"Задача пула {i}")

    ctx = FakeCtx()
    # Same callback_data twice in a row -- simulates the double-tap.
    upd1 = FakeUpdate(uid, "poolpage_focus_8")
    upd2 = FakeUpdate(uid, "poolpage_focus_8")
    upd2.callback_query.message = upd1.callback_query.message  # same message both times

    await bot.pool_change_page(upd1, ctx)  # first tap: real page change, succeeds
    await bot.pool_change_page(upd2, ctx)  # double-tap: identical target page
    print("1. pool_change_page survives a same-button double-tap (identical target page) without raising")

    # ══════════════════════════════════════════════════════════════════════
    # Same scenario for evening_plan_show_more.
    # ══════════════════════════════════════════════════════════════════════
    for i in range(10):
        bot.add_pool_task(uid, f"Дело пула {i}")
    ctx2 = FakeCtx()
    upd3 = FakeUpdate(uid, "eplanmore_e_a_8")
    upd4 = FakeUpdate(uid, "eplanmore_e_a_8")
    upd4.callback_query.message = upd3.callback_query.message

    await bot.evening_plan_show_more(upd3, ctx2)
    await bot.evening_plan_show_more(upd4, ctx2)
    print("2. evening_plan_show_more survives a same-button double-tap without raising")

    print("\nALL PAGINATION-NOT-MODIFIED TESTS PASSED")


asyncio.run(main())
