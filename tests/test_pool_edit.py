import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pool_edit.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.sent = []
        self.edited = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self

    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = FakeMsg(uid)

    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, text="", data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)
        self.message.text = text
        self.callback_query = FakeQuery(uid, data) if data is not None else None


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-28): "Список дел" only supported
    # delete/add -- fixing a typo or refining a pool item meant deleting it
    # and re-adding it, losing its "created" timestamp (and so its position
    # relative to the POOL_STALE_DAYS "age" hint).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    bot.add_pool_task(uid, "Купить малако")
    item = bot.get_pool_tasks(uid)[0]
    task_id = item["id"]
    original_created = item["created"]

    # 1. task_pool_kb shows "Изменить дело" only when the pool is non-empty.
    kb_empty = bot.task_pool_kb([])
    kb_full = bot.task_pool_kb([item])
    callbacks_empty = [b.callback_data for row in kb_empty.inline_keyboard for b in row]
    callbacks_full = [b.callback_data for row in kb_full.inline_keyboard for b in row]
    assert "pool_edit_menu" not in callbacks_empty
    assert "pool_edit_menu" in callbacks_full
    print("1. task_pool_kb shows 'Изменить дело' only when the pool has items")

    # 2. show_task_pool_edit lists every pool item with a pooledit_{id} callback.
    upd_menu = FakeUpdate(uid, data="pool_edit_menu")
    ctx = FakeCtx()
    await bot.show_task_pool_edit(upd_menu, ctx)
    kb = upd_menu.callback_query.message.edited[-1][1]
    edit_callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"pooledit_{task_id}" in edit_callbacks, edit_callbacks
    print("2. show_task_pool_edit lists the pool item with a pooledit_{id} callback")

    # 3. Tapping the item sets awaiting_pool_edit and shows the current text.
    upd_start = FakeUpdate(uid, data=f"pooledit_{task_id}")
    ctx2 = FakeCtx()
    await bot.pool_edit_item_start(upd_start, ctx2)
    assert ctx2.user_data.get("awaiting_pool_edit") == task_id
    shown_text = upd_start.callback_query.message.edited[-1][0]
    assert "Купить малако" in shown_text, shown_text
    print("3. pool_edit_item_start sets awaiting_pool_edit and shows the current text")

    # 4. Replying with new text updates the pool item's TEXT but keeps its
    #    original "created" timestamp (the whole point -- a plain
    #    delete+re-add would reset it and make the item look freshly added).
    upd_reply = FakeUpdate(uid, text="Купить молоко")
    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_pool_edit"] = task_id
    ctx3.user_data["awaiting_pool_edit_set_at"] = datetime.now().isoformat()
    await bot.handle_text(upd_reply, ctx3)
    updated = bot.get_pool_tasks(uid)[0]
    assert updated["text"] == "Купить молоко", updated
    assert updated["created"] == original_created, \
        "editing text must not reset the pool item's created timestamp"
    assert "awaiting_pool_edit" not in ctx3.user_data, "awaiting flag must be cleared after a successful edit"
    print("4. Replying with new text updates the item's text, keeps its original created timestamp, clears the flag")

    # 5. An empty reply is rejected and the awaiting flag stays live for a retry.
    bot.add_pool_task(uid, "Второе дело")
    item2 = [t for t in bot.get_pool_tasks(uid) if t["text"] == "Второе дело"][0]
    upd_empty = FakeUpdate(uid, text="   ")
    ctx4 = FakeCtx()
    ctx4.user_data["awaiting_pool_edit"] = item2["id"]
    ctx4.user_data["awaiting_pool_edit_set_at"] = datetime.now().isoformat()
    await bot.handle_text(upd_empty, ctx4)
    assert ctx4.user_data.get("awaiting_pool_edit") == item2["id"], \
        "an empty reply must not clear the awaiting flag -- must allow retry"
    still = [t for t in bot.get_pool_tasks(uid) if t["id"] == item2["id"]][0]
    assert still["text"] == "Второе дело", "an empty reply must not overwrite the item's text"
    print("5. An empty reply is rejected, keeps the item unchanged, and allows a retry")

    print("\nALL POOL-EDIT TESTS PASSED")


asyncio.run(main())
