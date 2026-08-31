import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_focus_timer_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [81000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1

    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []

    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, m.message_id))
        return m

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: extend "always one current message" to the focus/
    # pomodoro timer -- start -> stop/end used to leave a 3-message chain
    # (picker/status, "запущен", "время вышло"/"остановлен") behind.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    menu_screen = FakeMsg(chat_id=uid)

    upd = FakeUpdate(uid, "go_focus", menu_screen)
    await bot.go_focus(upd, ctx)
    assert len(fbot.sent) == 1
    picker_mid = fbot.sent[-1][2]
    assert bot._get_notif_msg_id(uid, "focus_timer") == picker_mid
    print("1. go_focus sends the picker as a new tracked 'focus_timer' message")

    # Starting a timer replaces the picker.
    picker_screen = FakeMsg(chat_id=uid); picker_screen.message_id = picker_mid
    upd2 = FakeUpdate(uid, "focus_start_25", picker_screen)
    await bot.focus_start_callback(upd2, ctx)
    started_mid = bot._get_notif_msg_id(uid, "focus_timer")
    assert (uid, picker_mid) in fbot.deleted, "starting a timer must delete the picker message"
    assert started_mid != picker_mid
    assert "Таймер запущен" in fbot.sent[-1][1], fbot.sent[-1]
    print("2. Starting a 25-min timer deletes the picker and tracks the 'started' confirmation")

    # Re-opening go_focus while the timer is running replaces "started" with the status view.
    started_screen = FakeMsg(chat_id=uid); started_screen.message_id = started_mid
    upd3 = FakeUpdate(uid, "go_focus", started_screen)
    await bot.go_focus(upd3, ctx)
    status_mid = bot._get_notif_msg_id(uid, "focus_timer")
    assert (uid, started_mid) in fbot.deleted
    assert "Таймер уже идёт" in fbot.sent[-1][1], fbot.sent[-1]
    print("3. Re-opening 🍅 Фокус mid-timer replaces the old message with a fresh status view")

    # Stopping the timer replaces the status view with the stop summary.
    status_screen = FakeMsg(chat_id=uid); status_screen.message_id = status_mid
    upd4 = FakeUpdate(uid, "focus_stop", status_screen)
    await bot.focus_stop_callback(upd4, ctx)
    stop_mid = bot._get_notif_msg_id(uid, "focus_timer")
    assert (uid, status_mid) in fbot.deleted
    assert "Таймер остановлен" in fbot.sent[-1][1], fbot.sent[-1]
    print("4. Stopping the timer replaces the status view with the stop summary")

    # Tapping "◀️ Меню" from the stop summary deletes it AND clears the
    # focus_timer channel -- otherwise a later timer would try to delete
    # whatever the main menu has since become.
    stop_screen = FakeMsg(chat_id=uid); stop_screen.message_id = stop_mid
    upd5 = FakeUpdate(uid, "focus_end_menu", stop_screen)
    await bot.focus_menu_callback(upd5, ctx)
    assert bot._get_notif_msg_id(uid, "focus_timer") is None
    print("5. '◀️ Меню' from the stop summary clears the focus_timer tracking (no stale collision later)")

    # ══════════════════════════════════════════════════════════════════════
    # send_focus_end (scheduler-fired, "⏰ Время вышло!") -- same channel.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    ctx2 = FakeCtx(app.bot)
    upd6 = FakeUpdate(uid, "go_focus", FakeMsg(chat_id=uid))
    await bot.go_focus(upd6, ctx2)
    running_mid = bot._get_notif_msg_id(uid, "focus_timer")
    running_screen = FakeMsg(chat_id=uid); running_screen.message_id = running_mid
    upd7 = FakeUpdate(uid, "focus_start_5", running_screen)
    await bot.focus_start_callback(upd7, ctx2)
    started_mid2 = bot._get_notif_msg_id(uid, "focus_timer")

    user_now = bot.get_user(uid)
    await bot.send_focus_end(app, uid, 5, user_now["focus_end_time"])
    assert (uid, started_mid2) in app.bot.deleted, \
        "send_focus_end must delete the 'started' message before sending 'время вышло'"
    assert "Время вышло" in app.bot.sent[-1][1], app.bot.sent[-1]
    print("6. send_focus_end (scheduler) replaces the 'started' message with 'Время вышло!' on the same channel")

    print("\nALL FOCUS-TIMER-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
