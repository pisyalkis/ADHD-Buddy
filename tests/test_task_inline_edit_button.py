import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_inline_edit_button.db")
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


def buttons_of(kb):
    return [[(b.text, b.callback_data) for b in row] for row in kb.inline_keyboard]


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "неудобно, что не могу отредактировать задачу сразу
    # текстом" при создании списка задач -- each task row on 📋 Задачи now
    # carries its own "✏️" button that jumps straight into editing just
    # that slot, instead of forcing a walk through all six via
    # "✏️ Поставить/изменить задачи".
    # ══════════════════════════════════════════════════════════════════════
    morning = {"focus": "Написать отчёт", "b1": "Позвонить маме"}
    text, kb = bot._tasks_text_and_kb(morning, set(), "M")
    rows = buttons_of(kb)
    # Реальный фидбек (по скриншоту): чекбокс и "✏️" в одном ряду из двух
    # кнопок Telegram делит пополам независимо от длины текста -- короткая
    # "✏️" занимала половину экрана рядом с длинным текстом задачи. Каждый
    # чекбокс теперь на всю ширину отдельной строкой, а все "✏️ <метка>" --
    # в одном общем компактном ряду, который делится между несколькими
    # короткими кнопками, а не с длинным текстом задачи.
    assert rows[0] == [("▫️ A: Написать отчёт", "task_done_focus")], rows
    assert rows[1] == [("▫️ B1: Позвонить маме", "task_done_b1")], rows
    assert rows[2] == [("✏️ A", "edit_task_focus"), ("✏️ B1", "edit_task_b1")], rows
    print("1. Each task gets a full-width checkbox row; all '✏️ <label>' edit buttons share one compact row")

    # The bulk walk-through entry point is still there too, for setting up
    # NEW empty slots -- must not be lost.
    flat = [cb for row in rows for _, cb in row]
    assert "walk_tasks" in flat, rows
    print("2. The 'walk_tasks' bulk entry point is still present alongside the per-task edit buttons")

    # Tapping '✏️' on a specific task jumps straight to editing THAT slot
    # (reuses the existing edit_task_callback -- offers pool suggestions or
    # free text), skipping the other five slots entirely.
    bot.add_pool_task(uid, "Купить молоко")
    bot.save_diary(uid, "morning", morning, for_date=bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat())
    upd = FakeUpdate(uid, data="edit_task_b1")
    ctx = FakeCtx()
    ctx.user_data["awaiting_name"] = True  # stale flag from elsewhere
    await bot.edit_task_callback(upd, ctx)
    sent_text, sent_kb = upd.callback_query.message.sent[0]
    assert "B1" in sent_text or "b1" in sent_text.lower() or "🅱️" in sent_text or ctx.user_data.get("awaiting_task_edit") == "b1"
    assert ctx.user_data.get("awaiting_task_edit") == "b1", \
        "tapping the b1 edit button must arm the editor for exactly that slot, not any other"
    assert ctx.user_data.get("awaiting_name") in (False, None), "must still clear stale awaiting flags like before"
    print("3. Tapping '✏️' on a specific task (b1) arms direct editing for that exact slot and clears stale flags")

    # Sanity: an empty (never-set) slot has no row at all -- nothing to edit.
    morning_partial = {"focus": "Написать отчёт"}
    text2, kb2 = bot._tasks_text_and_kb(morning_partial, set(), "M")
    rows2 = buttons_of(kb2)
    flat2 = [cb for row in rows2 for _, cb in row]
    assert "edit_task_b1" not in flat2, rows2
    print("4. Empty task slots don't get a stray edit button")

    print("\nALL TASK-INLINE-EDIT-BUTTON TESTS PASSED")


asyncio.run(main())
