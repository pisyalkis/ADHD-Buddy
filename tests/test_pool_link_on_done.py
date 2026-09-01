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
    # Product decision reversed again: "нет, только при выполнении" -- and
    # crucially, the reason it was flipped away from this before ("нажимал,
    # что оно выполнено, а дело оставалось в списке дел") must actually be
    # fixed this time, not just silently reintroduced. Picking a pool item
    # for a task slot must NOT delete it right away -- only when the task
    # is actually marked ✅ done (via the quick checkbox OR the evening
    # ritual's checklist), through the _pool_link_{key} deferred link.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Купить хлеб")
    pool_item = bot.get_pool_tasks(uid)[0]
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data=f"pooluse_focus_{pool_item['id']}")
    await bot.pool_use_item(upd, ctx)
    assert [t["text"] for t in bot.get_pool_tasks(uid)] == ["Купить хлеб"], \
        "picking a pool item for a task slot must NOT remove it from the pool yet"
    print("1. Picking a pool item for a task slot leaves it in the pool")

    morning = bot.get_diary(uid, "morning", today)
    assert morning.get("focus") == "Купить хлеб", morning
    assert morning.get("_pool_link_focus") == pool_item["id"], \
        "a deferred link to the pool item must be recorded on the slot"
    print("2. The task slot records a deferred link to the pool item")

    # Marking that task done (quick checkbox path, task_done_callback) must
    # now actually remove it from the pool -- this is the exact scenario
    # that was reported as broken ("marked done, stayed in the list").
    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid, data="task_done_focus")
    await bot.task_done_callback(upd2, ctx2)
    assert bot.get_pool_tasks(uid) == [], \
        "marking the task done must remove the linked pool item"
    morning_after_done = bot.get_diary(uid, "morning", today)
    assert "_pool_link_focus" not in morning_after_done, morning_after_done
    print("3. Marking the task done (task_done_callback) removes the linked pool item")

    # ══════════════════════════════════════════════════════════════════════
    # Same lifecycle through the EVENING ritual's checklist (finish_evening)
    # -- a separate code path from task_done_callback that must mirror the
    # same cleanup, not just the quick-checkbox one.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Полить цветы")
    pool_item2 = bot.get_pool_tasks(uid)[0]
    ctx3 = FakeCtx()
    upd3 = FakeUpdate(uid, data=f"pooluse_b1_{pool_item2['id']}")
    await bot.pool_use_item(upd3, ctx3)
    assert [t["text"] for t in bot.get_pool_tasks(uid)] == ["Полить цветы"], \
        "sanity: still in the pool right after picking"

    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вечер', 'F')")
    conn.commit(); conn.close()
    uid_eve = 2
    bot.update_user(uid_eve, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid_eve, "Вечерний пункт")
    eve_item = bot.get_pool_tasks(uid_eve)[0]
    ctx_eve = FakeCtx()
    upd_eve = FakeUpdate(uid_eve, data=f"pooluse_c1_{eve_item['id']}")
    await bot.pool_use_item(upd_eve, ctx_eve)
    ctx_eve2 = FakeCtx()
    ctx_eve2.user_data["e_tasks_done"] = ["c1"]
    ctx_eve2.user_data["e_morning_date"] = today
    await bot.finish_evening(FakeMsg(), uid_eve, ctx_eve2)
    assert bot.get_pool_tasks(uid_eve) == [], \
        "finish_evening (the evening ritual's checklist) must also remove the linked pool item on ✅"
    print("4. Marking the task done through the evening ritual (finish_evening) also removes the linked pool item")

    # ══════════════════════════════════════════════════════════════════════
    # Clearing a slot ("🗑 Убрать") or overwriting it must NOT delete the
    # pool item -- the task was never completed, so the item stays put.
    # ══════════════════════════════════════════════════════════════════════
    ctx4 = FakeCtx()
    upd4 = FakeUpdate(uid, data="walk_clear_b1")
    await bot.walk_clear_callback(upd4, ctx4)
    assert [t["text"] for t in bot.get_pool_tasks(uid)] == ["Полить цветы"], \
        "clearing a linked slot must NOT delete the still-unfinished pool item"
    morning_cleared = bot.get_diary(uid, "morning", today)
    assert "_pool_link_b1" not in morning_cleared, morning_cleared
    print("5. Clearing a linked slot leaves the pool item untouched, just drops the link")

    # Retyping a linked slot manually clears the link (doesn't silently
    # keep pointing at an item that's no longer this slot's task).
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Ретайп', 'M')")
    conn.commit(); conn.close()
    uid3 = 3
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid3, "Сходить в магазин")
    item3 = bot.get_pool_tasks(uid3)[0]
    ctx5 = FakeCtx()
    upd5 = FakeUpdate(uid3, data=f"pooluse_c1_{item3['id']}")
    await bot.pool_use_item(upd5, ctx5)

    ctx6 = FakeCtx()
    await bot.apply_task_edit(FakeMsg(), ctx6, uid3, "c1", "Другая задача")
    morning_retyped = bot.get_diary(uid3, "morning", today)
    assert "_pool_link_c1" not in morning_retyped, morning_retyped
    assert morning_retyped["c1"] == "Другая задача"

    ctx7 = FakeCtx()
    upd7 = FakeUpdate(uid3, data="task_done_c1")
    await bot.task_done_callback(upd7, ctx7)
    assert [t["text"] for t in bot.get_pool_tasks(uid3)] == ["Сходить в магазин"], \
        "retyping must clear the link, so the unrelated (never-completed) pool item survives"
    print("6. Retyping a linked slot clears the link, so the original pool item survives")

    print("\nALL POOL-LINK-ON-DONE TESTS PASSED")


asyncio.run(main())
