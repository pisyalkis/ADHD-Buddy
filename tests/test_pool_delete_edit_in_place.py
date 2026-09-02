import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pool_delete_edit_in_place.db")
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
        self.edited = []
        self.sent = []
        self.edit_should_fail = False
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message too old to edit")
        self.edited.append((text, kw.get("reply_markup")))
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


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.add_pool_task(uid, "Купить молоко")
    bot.add_pool_task(uid, "Позвонить в банк")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: deleting an item from 📥 Список дел must not spam a new
    # message with the whole (updated) list every time -- it should edit
    # the same message in place, both for opening "Что удалить?" and after
    # each actual deletion.
    # ══════════════════════════════════════════════════════════════════════
    upd_open = FakeUpdate(uid, data="pool_del_menu")
    ctx = FakeCtx()
    await bot.show_task_pool_delete(upd_open, ctx)
    msg = upd_open.callback_query.message
    assert msg.edited and not msg.sent, \
        f"opening the delete menu must edit in place, got edited={msg.edited} sent={msg.sent}"
    print("1. Opening '🗑 Удалить дело' edits the existing message in place")

    pool = bot.get_pool_tasks(uid)
    target = next(t for t in pool if t["text"] == "Купить молоко")
    upd_del = FakeUpdate(uid, data=f"pooldel_{target['id']}")
    upd_del.callback_query.message = msg  # tapping a button on the SAME message
    await bot.pool_delete_item(upd_del, ctx)
    assert len(msg.edited) == 2 and not msg.sent, \
        f"deleting an item must edit the SAME message again, not send a new one, got edited={msg.edited} sent={msg.sent}"
    assert "Купить молоко" not in msg.edited[-1][0]
    print("2. Deleting an item edits the SAME message again with the updated list, no new message sent")

    # Falls back to a new message if editing fails (e.g. the screen expired).
    msg.edit_should_fail = True
    remaining = bot.get_pool_tasks(uid)
    upd_del2 = FakeUpdate(uid, data=f"pooldel_{remaining[0]['id']}")
    upd_del2.callback_query.message = msg
    await bot.pool_delete_item(upd_del2, ctx)
    assert msg.sent, "must fall back to a new message when editing fails"
    print("3. Falls back to sending a new message when editing the old one fails")

    print("\nALL POOL-DELETE-EDIT-IN-PLACE TESTS PASSED")


asyncio.run(main())
