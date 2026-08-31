import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_pool_ux.db")
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
        self.edited_markup = None
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_reply_markup(self, reply_markup=None, **kw):
        self.edited_markup = reply_markup


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
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: the pool-suggestions screen (picking a ready-made item
    # for A/B/C) showed only 3 at a time with a bare "Показать ещё" button
    # -- no count of how many items remain, and no way to go back. New:
    # bigger page size (8) plus a proper "N/M" page indicator with
    # forward/back navigation once the pool spans more than one page.
    # ══════════════════════════════════════════════════════════════════════
    for i in range(10):
        bot.add_pool_task(uid, f"Дело {i+1}")
    pool = bot.get_pool_tasks(uid)
    assert len(pool) == 10

    kb1 = bot.pool_suggestions_kb("focus", pool)
    labels1 = buttons_of(kb1)
    item_labels1 = [t for t, cb in labels1 if cb.startswith("pooluse_")]
    assert len(item_labels1) == 8, labels1
    assert ("1/2", "noop") in labels1, labels1
    assert any(cb.startswith("poolpage_focus_8") for _, cb in labels1), labels1
    assert not any(t == "◀️" for t, _ in labels1), "no back button on the first page"
    print("1. pool_suggestions_kb shows 8 items per page and a '1/2' indicator with a forward button on page 1")

    # Simulate tapping the forward nav button via pool_change_page.
    upd = FakeUpdate(uid, data="poolpage_focus_8")
    await bot.pool_change_page(upd, FakeCtx())
    kb2 = upd.callback_query.message.edited_markup
    labels2 = buttons_of(kb2)
    item_labels2 = [t for t, cb in labels2 if cb.startswith("pooluse_")]
    assert len(item_labels2) == 2, labels2
    assert ("2/2", "noop") in labels2, labels2
    assert any(t == "◀️" for t, _ in labels2), "page 2 must offer a back button"
    assert not any(cb.startswith("poolpage_") and t == "▶️" for t, cb in labels2), "no forward button on the last page"
    print("2. pool_change_page moves to page 2/2 with a back button and no forward button (last page)")

    # Small pool (fits on one page) -> no page indicator at all, same as before.
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.add_pool_task(2, "Одно дело")
    kb3 = bot.pool_suggestions_kb("focus", bot.get_pool_tasks(2))
    labels3 = buttons_of(kb3)
    assert not any(cb == "noop" for _, cb in labels3), "no page indicator needed for a single-page pool"
    print("3. pool_suggestions_kb shows no page indicator at all when everything fits on one page")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "у меня сейчас в списке дела, которые я уже выполнил"
    # -- a task set WITHOUT going through the pool picker (typed manually,
    # or carried over via "Взять как задачи на сегодня") left its matching
    # pool entry behind forever, even after being marked done, because the
    # _pool_link_ auto-cleanup only fires for tasks that were explicitly
    # selected from the pool.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone=tz_name)
    bot.add_pool_task(uid3, "Позвонить маме")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid3))).date().isoformat()
    # Set today's task manually (NOT via pool_use_item -- no _pool_link_).
    bot.save_diary(uid3, "morning", {"focus": "Позвонить маме"}, for_date=today)
    upd_done = FakeUpdate(uid3, data="task_done_focus")
    await bot.task_done_callback(upd_done, FakeCtx())
    remaining = [t["text"] for t in bot.get_pool_tasks(uid3)]
    assert "Позвонить маме" not in remaining, \
        f"a completed task must clean up its matching pool entry even without an explicit pool link, got {remaining}"
    print("4. task_done_callback auto-removes a text-matching pool entry even when the task wasn't picked from the pool")

    # Sanity: unmarking the task back (undo) doesn't crash and doesn't try
    # to re-match/re-delete anything (already gone).
    upd_undo = FakeUpdate(uid3, data="task_done_focus")
    await bot.task_done_callback(upd_undo, FakeCtx())
    print("5. Un-marking the task back does not crash")

    # Sanity: a pool item with DIFFERENT text is untouched.
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Четвёртый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid4, timezone=tz_name)
    bot.add_pool_task(uid4, "Другое дело")
    today4 = datetime.now(bot.get_user_tz(bot.get_user(uid4))).date().isoformat()
    bot.save_diary(uid4, "morning", {"focus": "Совсем другая задача"}, for_date=today4)
    upd_done4 = FakeUpdate(uid4, data="task_done_focus")
    await bot.task_done_callback(upd_done4, FakeCtx())
    remaining4 = [t["text"] for t in bot.get_pool_tasks(uid4)]
    assert "Другое дело" in remaining4, remaining4
    print("6. task_done_callback does not touch unrelated pool entries with different text")

    print("\nALL TASK-POOL-UX TESTS PASSED")


asyncio.run(main())
