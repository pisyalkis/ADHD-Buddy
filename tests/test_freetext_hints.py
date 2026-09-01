import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_freetext_hints.db")
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
        self.edited = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
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


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "в описании навыка список дел нет информации о свободном
    # внесении через чат" -- and the same gap exists for tasks (set_task
    # intent). The ONLY place that documented any of this was ℹ️ О боте,
    # which most people never open. Every relevant skill entry and on-screen
    # text should mention it directly.
    # ══════════════════════════════════════════════════════════════════════
    pool_skill = next(s for s in bot.SKILLS if s["name"] == "📋 Список дел и календарь")
    assert "добавь в список дел" in pool_skill["instructions"], pool_skill["instructions"]
    print("1. The '📋 Список дел и календарь' skill now mentions adding items via free text in chat")

    abc_skill = next(s for s in bot.SKILLS if s["name"] == "🔤 Приоритеты A, B, C")
    assert "📋 Задачи" in abc_skill["instructions"], abc_skill["instructions"]
    assert "поставь задачу" in abc_skill["instructions"] or "задача B1" in abc_skill["instructions"], abc_skill["instructions"]
    print("2. The '🔤 Приоритеты A, B, C' skill now mentions 📋 Задачи and setting a task via free text")

    # ---- 📥 Список дел screen itself ---------------------------------------
    empty_text = bot.task_pool_text([])
    assert "добавь в список дел" in empty_text, empty_text
    print("3. task_pool_text (empty) shows the free-text hint")

    bot.add_pool_task(uid, "Купить молоко")
    pool = bot.get_pool_tasks(uid)
    nonempty_text = bot.task_pool_text(pool)
    assert "добавь в список дел" in nonempty_text, nonempty_text
    print("4. task_pool_text (non-empty) also shows the free-text hint")

    # ---- 📋 Задачи screen itself --------------------------------------------
    text_empty, kb_empty = bot._tasks_text_and_kb({}, set(), "M", uid)
    assert "поставь задачу" in text_empty or "задача B1" in text_empty, text_empty
    print("5. _tasks_text_and_kb (no tasks set) shows the free-text set_task hint")

    morning = {"focus": "Написать отчёт"}
    text_full, kb_full = bot._tasks_text_and_kb(morning, set(), "M", uid)
    assert "поставь задачу" in text_full or "задача B1" in text_full, text_full
    print("6. _tasks_text_and_kb (tasks already set) still shows the hint")

    # ---- ℹ️ О боте already had a general hint, but was missing the set_task
    # example specifically -- found during this same audit. The hint now
    # lives on the "tools" page (О боте is split into pages, same principle
    # as 📖 О СДВГ).
    about_msg = FakeMsg()
    await bot.send_about_section(about_msg, "tools", "M")
    about_text = about_msg.edited[0][0] if about_msg.edited else about_msg.sent[0][0]
    assert "поставь задачу" in about_text, about_text
    print("7. ℹ️ О боте's 'necязательно через меню' line now includes a поставь-задачу example too")

    print("\nALL FREETEXT-HINTS TESTS PASSED")


asyncio.run(main())
