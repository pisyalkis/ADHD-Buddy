import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_all_screens_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


_next_mid = [5000]

class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = _next_mid[0]
        _next_mid[0] += 1
        self.sent = []
        self.edited = []
        self.edit_should_fail = False
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return FakeMsg(self.chat_id)
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message too old to edit")
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def edit_reply_markup(self, **kw):
        pass


class FakeBot:
    def __init__(self):
        self.edit_calls = []
        self._by_id = {}  # (chat_id, message_id) -> FakeMsg, for edit_message_text to mutate
    def register(self, msg):
        self._by_id[(msg.chat_id, msg.message_id)] = msg
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        msg = self._by_id.get((chat_id, message_id))
        if msg is None or msg.edit_should_fail:
            raise Exception("can't edit")
        msg.edited.append((text, kw.get("reply_markup")))
        self.edit_calls.append((chat_id, message_id, text))
    async def send_message(self, *a, **kw): pass
    async def delete_message(self, **kw): pass


class FakeQuery:
    def __init__(self, uid, msg, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = msg
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, msg, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, msg, data)
        self.message = None


class FakeTextMsg:
    def __init__(self, text):
        self.text = text
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))


class FakeTextUpdate:
    def __init__(self, uid, text):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = None
        self.message = FakeTextMsg(text)


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def _fake_parse_reminder(text, now_dt):
    return ("2026-01-01T10:00:00", text, "")

bot.parse_reminder_request = _fake_parse_reminder


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "чтобы меню всегда было одним сообщением, которое через
    # некоторое время удаляется" — extended from ⚙️ Общие to the rest of the
    # bot's screens: ◀️ Меню, правка задачи, 📥 Список дел, ⏰ Напоминания,
    # 💬 Обратная связь. Each must edit the same message in place across its
    # whole "open screen -> answer with free text -> confirmation" flow.
    # ══════════════════════════════════════════════════════════════════════

    # ---- 1. ◀️ Меню -------------------------------------------------------
    fbot = FakeBot()
    msg = FakeMsg(uid); fbot.register(msg)
    ctx = FakeCtx(bot=fbot)
    upd = FakeUpdate(uid, msg, data="go_menu")
    await bot.go_menu(upd, ctx)
    assert msg.sent == [], "go_menu must edit in place, not send a new message (real bug found: it always did before)"
    assert ctx.user_data.get("menu_msg_id") == msg.message_id
    print("1. go_menu now edits the same message in place instead of always sending a new one")

    upd2 = FakeUpdate(uid, msg, data="go_tab_tools")
    await bot.go_tab(upd2, ctx)
    assert msg.sent == []
    print("2. go_tab keeps using the same tracked message")

    # ---- 2. ✏️ Задача (single edit, NOT the six-step walk) ----------------
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=today)
    msg2 = FakeMsg(uid); fbot.register(msg2)
    ctx2 = FakeCtx(bot=fbot)
    upd3 = FakeUpdate(uid, msg2, data="edit_task_focus")
    await bot.edit_task_callback(upd3, ctx2)
    assert msg2.sent == [], "opening the single-slot edit prompt must edit in place"
    assert ctx2.user_data.get("task_edit_msg_id") == msg2.message_id

    text_upd = FakeTextUpdate(uid, "Позвонить маме")
    await bot.handle_text(text_upd, ctx2)
    assert text_upd.message.sent == [], "typing the new task text must edit the tracked prompt, not reply with a new message"
    assert fbot.edit_calls and fbot.edit_calls[-1][1] == msg2.message_id
    assert "Позвонить маме" in msg2.edited[-1][0]
    print("3. Single-slot task edit (✏️ on one row) stays on one message end-to-end")

    # Walk mode (✏️ Поставить/изменить задачи, all six slots) must be
    # UNCHANGED -- its own multi-step wizard with a separate message per
    # step is a bigger, separate piece of work, deliberately left alone.
    msg3 = FakeMsg(uid); fbot.register(msg3)
    ctx3 = FakeCtx(bot=fbot)
    upd4 = FakeUpdate(uid, msg3, data="walk_tasks_start")
    await bot.walk_tasks_start(upd4, ctx3)
    assert "task_edit_msg_id" not in ctx3.user_data, "walk mode must not engage single-message tracking"
    assert msg3.sent or msg3.edited  # first step rendered somehow
    print("4. Walk-mode task setting (all six slots) is untouched -- no tracking engaged there")

    # ---- 3. 📥 Список дел --------------------------------------------------
    msg4 = FakeMsg(uid); fbot.register(msg4)
    ctx4 = FakeCtx(bot=fbot)
    upd5 = FakeUpdate(uid, msg4, data="go_task_pool")
    await bot.show_task_pool(upd5, ctx4)
    assert msg4.sent == []
    assert ctx4.user_data.get("task_pool_msg_id") == msg4.message_id
    print("5. show_task_pool edits in place and tracks its message")

    upd6 = FakeUpdate(uid, msg4, data="pool_add")
    await bot.pool_add_start(upd6, ctx4)
    assert msg4.sent == []

    text_upd2 = FakeTextUpdate(uid, "Купить молоко\nЗабрать посылку")
    await bot.handle_text(text_upd2, ctx4)
    assert text_upd2.message.sent == [], "adding pool items via the explicit screen must edit the tracked message"
    assert "Купить молоко" in msg4.edited[-1][0] or "2 дел" in msg4.edited[-1][0]
    print("6. 📥 Список дел: добавить edits the same message for the whole add flow")

    # Free-text AI-router path (no preceding screen opened) must NOT touch
    # any tracked message -- there's nothing to safely return to.
    text_upd3 = FakeTextUpdate(uid, "прямой текст без экрана")
    await bot.add_pool_and_reply(text_upd3.message, uid, ["Дело из роутера"])
    assert text_upd3.message.sent, "the free-text router path (no ctx) must still just reply normally"
    print("7. add_pool_and_reply without ctx (free-text router) still replies normally, no stale-message risk")

    # ---- 4. ⏰ Напоминания --------------------------------------------------
    msg5 = FakeMsg(uid); fbot.register(msg5)
    ctx5 = FakeCtx(bot=fbot)
    upd7 = FakeUpdate(uid, msg5, data="go_reminders")
    await bot.show_reminders(upd7, ctx5)
    assert msg5.sent == []
    assert ctx5.user_data.get("reminders_msg_id") == msg5.message_id

    # reminder_add_start needs ANTHROPIC_KEY truthy to proceed past its guard.
    bot.ANTHROPIC_KEY = "fake-key-for-test"
    try:
        upd8 = FakeUpdate(uid, msg5, data="rem_add")
        await bot.reminder_add_start(upd8, ctx5)
        assert msg5.sent == []

        text_upd4 = FakeTextUpdate(uid, "через 20 минут проверить почту")
        await bot.handle_text(text_upd4, ctx5)
        assert text_upd4.message.sent == [], "adding a reminder via the explicit screen must edit the tracked message"
        assert "Напомню" in msg5.edited[-1][0]
        print("8. ⏰ Напоминания: добавить edits the same message for the whole add flow")
    finally:
        bot.ANTHROPIC_KEY = ""

    # Free-text AI-router reminder creation (no ctx) must still just reply.
    text_upd5 = FakeTextUpdate(uid, "прямой текст напоминания")
    await bot.create_reminder_and_reply(text_upd5.message, uid, "2026-01-01T10:00:00", "тест")
    assert text_upd5.message.sent
    print("9. create_reminder_and_reply without ctx (free-text router) still replies normally")

    # ---- 5. 💬 Обратная связь -----------------------------------------------
    msg6 = FakeMsg(uid); fbot.register(msg6)
    ctx6 = FakeCtx(bot=fbot)
    upd9 = FakeUpdate(uid, msg6, data="go_feedback")
    await bot.go_feedback(upd9, ctx6)
    assert msg6.sent == []
    assert ctx6.user_data.get("feedback_msg_id") == msg6.message_id

    text_upd6 = FakeTextUpdate(uid, "Было бы круто добавить тёмную тему")
    await bot.handle_text(text_upd6, ctx6)
    assert text_upd6.message.sent == [], "submitting feedback must edit the tracked prompt, not reply with a new message"
    assert "Спасибо" in msg6.edited[-1][0]
    print("10. 💬 Обратная связь edits the same message for prompt + confirmation")

    # ══════════════════════════════════════════════════════════════════════
    # Every tracked screen actually schedules a self-deletion row (reusing
    # scheduled_deletions) -- spot-check one, since the mechanism itself is
    # already proven end-to-end for ⚙️ Общие in test_settings_single_message.py.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT COUNT(*) FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (msg6.chat_id, msg6.message_id)
    ).fetchone()
    conn.close()
    assert row[0] == 1, row
    print("11. The feedback screen's message is scheduled for self-deletion too (reused scheduled_deletions queue)")

    print("\nALL ALL-SCREENS-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
