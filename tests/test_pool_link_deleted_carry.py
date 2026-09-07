import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pool_link_deleted_carry.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeMsg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self

    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
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


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan, BUGS.md 2026-09-06): _carry_unfinished_tasks_to_pool
    # skipped carrying an unfinished task back to the pool whenever it still
    # had a _pool_link_{key} -- assuming the linked pool item was still there
    # untouched. But pool_delete_item (🗑 in 📥 Список дел) deletes any pool
    # item by id unconditionally, with no awareness of active task links. If
    # a user picked a pool item for a task, then manually deleted that same
    # pool item (thinking it a duplicate) without ever finishing the task,
    # the task vanished permanently at day-close -- exactly the loss this
    # function exists to prevent. Same bug, same fix, in TWO places: the
    # evening carry-over AND the "🎯 Оставить только А" midday action.
    # ══════════════════════════════════════════════════════════════════════
    today = datetime.now(TBILISI).date().isoformat()

    # 1. _carry_unfinished_tasks_to_pool: pool link still points to a LIVE
    #    pool item -- must NOT duplicate it (existing, correct behavior).
    uid = 1
    make_user(uid, "Артем")
    bot.add_pool_task(uid, "Позвонить врачу")
    live_item = bot.get_pool_tasks(uid)[0]
    bot.save_diary(uid, "morning", {
        "focus": "Главное", "b1": "Позвонить врачу", "_pool_link_b1": live_item["id"],
    }, for_date=today)
    bot._carry_unfinished_tasks_to_pool(uid, today, set())
    pool_after_live = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert pool_after_live.count("Позвонить врачу") == 1, \
        f"a task still linked to a LIVE pool item must not be duplicated: {pool_after_live}"
    print("1. _carry_unfinished_tasks_to_pool: a task linked to a still-live pool item is not duplicated")

    # 2. _carry_unfinished_tasks_to_pool: pool link points to a DELETED pool
    #    item (user removed it manually without finishing the task) -- the
    #    task must be carried back into the pool, not lost.
    uid2 = 2
    make_user(uid2, "Вика")
    bot.add_pool_task(uid2, "Забрать посылку")
    deleted_item = bot.get_pool_tasks(uid2)[0]
    bot.save_diary(uid2, "morning", {
        "focus": "Главное", "b1": "Забрать посылку", "_pool_link_b1": deleted_item["id"],
    }, for_date=today)
    bot.delete_pool_task(uid2, deleted_item["id"])
    assert bot.get_pool_tasks(uid2) == [], "sanity: pool item must actually be gone before the carry"
    bot._carry_unfinished_tasks_to_pool(uid2, today, set())
    pool_after_deleted = [t["text"] for t in bot.get_pool_tasks(uid2)]
    assert "Забрать посылку" in pool_after_deleted, \
        f"an unfinished task whose linked pool item was deleted must be carried back, not lost: {pool_after_deleted}"
    print("2. _carry_unfinished_tasks_to_pool: a task whose linked pool item was deleted IS carried back (bug fix)")

    # 3. The SAME class of fix in mid_energy_only_a (🔋 Мало энергии → 🎯
    #    Оставить только А): a B/C task linked to a deleted pool item must
    #    also be carried back, not lost, when trimmed off today.
    uid3 = 3
    make_user(uid3, "Игорь")
    bot.add_pool_task(uid3, "Купить корм коту")
    deleted_item3 = bot.get_pool_tasks(uid3)[0]
    bot.save_diary(uid3, "morning", {
        "focus": "Сделать план", "b1": "Купить корм коту", "_pool_link_b1": deleted_item3["id"],
    }, for_date=today)
    bot.delete_pool_task(uid3, deleted_item3["id"])
    await bot.midday_callback(FakeUpdate(uid3, "mid_energy_only_a"), FakeCtx())
    pool_texts3 = [t["text"] for t in bot.get_pool_tasks(uid3)]
    assert "Купить корм коту" in pool_texts3, \
        f"mid_energy_only_a must carry back a task whose linked pool item was deleted: {pool_texts3}"
    print("3. mid_energy_only_a: a B/C task whose linked pool item was deleted is also carried back (bug fix)")

    # 4. mid_energy_only_a: pool link still LIVE -- must not duplicate.
    uid4 = 4
    make_user(uid4, "Соня")
    bot.add_pool_task(uid4, "Сходить в аптеку")
    live_item4 = bot.get_pool_tasks(uid4)[0]
    bot.save_diary(uid4, "morning", {
        "focus": "Сделать план", "b1": "Сходить в аптеку", "_pool_link_b1": live_item4["id"],
    }, for_date=today)
    await bot.midday_callback(FakeUpdate(uid4, "mid_energy_only_a"), FakeCtx())
    pool_texts4 = [t["text"] for t in bot.get_pool_tasks(uid4)]
    assert pool_texts4.count("Сходить в аптеку") == 1, \
        f"mid_energy_only_a must not duplicate a task still linked to a live pool item: {pool_texts4}"
    print("4. mid_energy_only_a: a task still linked to a live pool item is not duplicated")

    print("\nALL POOL-LINK-DELETED-CARRY TESTS PASSED")


asyncio.run(main())
