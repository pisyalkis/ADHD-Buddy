import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pool_link_on_done.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return self
    async def edit_text(self, text, **kw):
        self.sent.append(text)
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = FakeQuery(uid, data)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real request (product decision reversed): picking a pool item for a
    # task slot must remove it from the pool IMMEDIATELY -- not wait until
    # the task is marked ✅ done.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Купить хлеб")
    pool_item = bot.get_pool_tasks(uid)[0]
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data=f"pooluse_focus_{pool_item['id']}")
    await bot.pool_use_item(upd, ctx)
    assert bot.get_pool_tasks(uid) == [], "the pool item must disappear immediately once picked"
    print("1. Picking a pool item for a task slot removes it from the pool right away")

    morning = bot.get_diary(uid, "morning", today)
    assert morning.get("focus") == "Купить хлеб"
    assert "_pool_link_focus" not in morning, \
        "no deferred link should be created -- the item is already gone from the pool"
    print("2. The task slot has no leftover deferred-delete link (nothing left to defer)")

    # Marking that task done later must not error out or touch anything --
    # there's nothing left in the pool to delete.
    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid, data="task_done_focus")
    await bot.task_done_callback(upd2, ctx2)
    assert bot.get_pool_tasks(uid) == []
    print("3. Marking the task done later is a harmless no-op for the (already empty) pool")

    # ══════════════════════════════════════════════════════════════════════
    # Backward compatibility: a diary row saved BEFORE this change may still
    # carry an old "_pool_link_{key}" pointing at a pool item that's still
    # there -- marking that task done must still clean it up correctly.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Позвонить маме")
    old_link_item = bot.get_pool_tasks(uid)[0]
    morning_legacy = bot.get_diary(uid, "morning", today)
    morning_legacy["b1"] = "Позвонить маме"
    morning_legacy["_pool_link_b1"] = old_link_item["id"]
    bot.save_diary(uid, "morning", morning_legacy, for_date=today)

    ctx3 = FakeCtx()
    upd3 = FakeUpdate(uid, data="task_done_b1")
    await bot.task_done_callback(upd3, ctx3)
    assert bot.get_pool_tasks(uid) == [], \
        "a legacy _pool_link_ from before this change must still be honored on done"
    morning_after = bot.get_diary(uid, "morning", today)
    assert "_pool_link_b1" not in morning_after, morning_after
    print("4. A legacy _pool_link_ (saved before this change) is still cleaned up correctly on done")

    # Retyping a task slot manually clears any stale legacy link too.
    bot.add_pool_task(uid, "Сходить в магазин")
    legacy_item2 = bot.get_pool_tasks(uid)[0]
    morning_legacy2 = bot.get_diary(uid, "morning", today)
    morning_legacy2["c1"] = "Сходить в магазин"
    morning_legacy2["_pool_link_c1"] = legacy_item2["id"]
    bot.save_diary(uid, "morning", morning_legacy2, for_date=today)

    ctx4 = FakeCtx()
    await bot.apply_task_edit(FakeMsg(), ctx4, uid, "c1", "Другая задача")
    morning_retyped = bot.get_diary(uid, "morning", today)
    assert "_pool_link_c1" not in morning_retyped, morning_retyped
    assert morning_retyped["c1"] == "Другая задача"

    ctx5 = FakeCtx()
    upd5 = FakeUpdate(uid, data="task_done_c1")
    await bot.task_done_callback(upd5, ctx5)
    assert [t["text"] for t in bot.get_pool_tasks(uid)] == ["Сходить в магазин"], \
        "retyping must clear the stale legacy link so the unrelated pool item survives"
    print("5. Retyping a slot clears a stale legacy link, so the unrelated pool item survives")

    print("\nALL POOL-LINK-ON-DONE TESTS PASSED")


asyncio.run(main())
