import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_done_from_notif.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [333000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.edited_text = []
        self.edited_markup = []
        self.reply_calls = []

    async def edit_text(self, text, **kw):
        self.edited_text.append((text, kw.get("reply_markup")))

    async def edit_reply_markup(self, **kw):
        self.edited_markup.append(kw.get("reply_markup"))

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m


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


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт", "b1": "", "b2": "", "c1": "", "c2": "", "c3": ""}, for_date=today)

    # ══════════════════════════════════════════════════════════════════════
    # Real bug: tapping the ▫️/✅ checkbox on the task-beacon message (or
    # midday/resume-check) rewrote the WHOLE message into the "📋 Задачи"
    # edit menu (with ✏️ buttons, "Список дел", etc.) -- a totally
    # different, confusing screen -- instead of just reflecting the check
    # mark on the same beacon/checkin message.
    # ══════════════════════════════════════════════════════════════════════
    beacon_msg = FakeMsg(chat_id=uid)
    bot._set_notif_msg_id(uid, "task_beacon", beacon_msg.message_id)
    ctx = FakeCtx()
    upd = FakeUpdate(uid, "task_done_focus", beacon_msg)
    await bot.task_done_callback(upd, ctx)
    assert not beacon_msg.edited_text, \
        f"tapping the checkbox on a task-beacon message must NOT rewrite its text into the task-edit menu, got {beacon_msg.edited_text}"
    assert beacon_msg.edited_markup, "the checkbox state must still be refreshed on the same message"
    print("1. Checking off a task from the task-beacon message keeps its own text, only refreshes the checkbox")

    # Tapping again (unchecking) must not suddenly switch it into the edit
    # menu either -- same code path both directions.
    await bot.task_done_callback(FakeUpdate(uid, "task_done_focus", beacon_msg), ctx)
    assert not beacon_msg.edited_text
    print("2. Unchecking the same task from the task-beacon message also stays on the same screen")

    # ══════════════════════════════════════════════════════════════════════
    # midday channel -- same fix applies.
    # ══════════════════════════════════════════════════════════════════════
    midday_msg = FakeMsg(chat_id=uid)
    bot._set_notif_msg_id(uid, "midday", midday_msg.message_id)
    await bot.task_done_callback(FakeUpdate(uid, "task_done_focus", midday_msg), ctx)
    assert not midday_msg.edited_text
    assert midday_msg.edited_markup
    print("3. Checking off a task from the midday check-in message also keeps its own text")

    # ══════════════════════════════════════════════════════════════════════
    # Untracked message (e.g. the real 📋 Задачи screen) -- unaffected,
    # keeps rewriting into the full task-edit menu as before.
    # ══════════════════════════════════════════════════════════════════════
    tasks_screen = FakeMsg(chat_id=uid)
    await bot.task_done_callback(FakeUpdate(uid, "task_done_focus", tasks_screen), ctx)
    assert tasks_screen.edited_text and "📋" in tasks_screen.edited_text[-1][0], tasks_screen.edited_text
    print("4. Checking off a task from the actual 📋 Задачи screen still rebuilds the edit menu, unchanged")

    # ══════════════════════════════════════════════════════════════════════
    # beacon_technique_done's own follow-up ("✅ Сделал(а)" after a technique)
    # must now be tracked under "task_beacon" too, so the SAME fix covers it.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx2 = FakeCtx(fbot)
    upd2 = FakeUpdate(uid, "beacon_technique_done", FakeMsg(chat_id=uid))
    await bot.beacon_technique_done(upd2, ctx2)
    assert len(fbot.sent) == 1
    tracked_mid = fbot.sent[0][2]
    assert bot._get_notif_msg_id(uid, "task_beacon") == tracked_mid, \
        "beacon_technique_done's follow-up beacon message must be tracked under 'task_beacon'"
    print("5. beacon_technique_done's follow-up message is now tracked under 'task_beacon'")

    print("\nALL TASK-DONE-FROM-NOTIF TESTS PASSED")


asyncio.run(main())
