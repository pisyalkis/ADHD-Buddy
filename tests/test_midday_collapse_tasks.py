import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_midday_collapse_tasks.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 777
        self.markup_edits = []
    async def edit_reply_markup(self, **kw):
        self.markup_edits.append(kw.get("reply_markup"))
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.callback_query = FakeQuery(uid, data, message)


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Сделать план", "b1": "Купить хлеб"}, for_date=today)

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "разгрузим визуально. Заменим кнопки задач на «отметить
    # то, что сделано». Тогда выпадают задачи, которые можно отметить."
    # ══════════════════════════════════════════════════════════════════════
    msg = FakeMsg(chat_id=uid)
    await bot.mid_mark_done_callback(FakeUpdate(uid, "mid_mark_done", msg), None)
    assert len(msg.markup_edits) == 1
    expanded_kb = msg.markup_edits[0]
    callbacks = [row[0].callback_data for row in expanded_kb.inline_keyboard]
    assert "task_done_focus" in callbacks and "task_done_b1" in callbacks, callbacks
    assert "mid_mark_collapse" in callbacks, callbacks
    print("1. Tapping 'Отметить то, что сделано' expands the message's keyboard into per-task checkboxes")

    await bot.mid_mark_collapse_callback(FakeUpdate(uid, "mid_mark_collapse", msg), None)
    collapsed_kb = msg.markup_edits[1]
    callbacks2 = [row[0].callback_data for row in collapsed_kb.inline_keyboard]
    assert not any(cb.startswith("task_done_") for cb in callbacks2), callbacks2
    assert "mid_mark_done" in callbacks2, callbacks2
    print("2. '◀️ Свернуть' collapses it back to the single button")

    # The dedicated handlers must win over midday_callback's broad "^mid_"
    # pattern -- registration order matters (see main()'s add_handler calls).
    import inspect
    src = inspect.getsource(bot)
    idx_task_done = src.index('CallbackQueryHandler(mid_mark_done_callback')
    idx_midday = src.index('CallbackQueryHandler(midday_callback')
    assert idx_task_done < idx_midday, \
        "mid_mark_done_callback must be registered before midday_callback's '^mid_' catch-all"
    print("3. mid_mark_done_callback/mid_mark_collapse_callback are registered before midday_callback's broad '^mid_' pattern")

    print("\nALL MIDDAY-COLLAPSE-TASKS TESTS PASSED")


asyncio.run(main())
