import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_plan_pool_dedup.db")
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
        self.edited = []
        self.sent = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def buttons_of(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "почему перенесённая задача не пропадает из списка
    # предлагаемых?" -- a pool item picked for one evening-plan slot (say
    # e_a) kept showing up as a suggestion for the NEXT slots (e_b1, e_c1,
    # ...) in the SAME wizard pass, since evening_plan_use_pool
    # deliberately doesn't delete the pool item on selection (mirrors
    # 📋 Задачи -- only removed once actually marked ✅ done).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    bot.add_pool_task(uid, "Купить молоко")
    bot.add_pool_task(uid, "Написать отчёт")
    item = next(t for t in bot.get_pool_tasks(uid) if t["text"] == "Купить молоко")

    ctx = FakeCtx()
    upd = FakeUpdate(uid, f"eplanuse_e_a_{item['id']}")
    await bot.evening_plan_use_pool(upd, ctx)
    assert ctx.user_data.get("e_a") == "Купить молоко", ctx.user_data

    # Now the NEXT step (e_b1) is offered -- the already-picked item must
    # not be suggested again.
    kb_b1 = bot.evening_plan_kb("e_b1", uid, ctx)
    flat_b1 = buttons_of(kb_b1)
    assert f"eplanuse_e_b1_{item['id']}" not in flat_b1, \
        f"a pool item already picked for e_a must not be offered again for e_b1: {flat_b1}"
    print("1. A pool item already picked for one evening-plan slot is not offered again for the next slot")

    # The OTHER, still-unpicked pool item must still be offered normally.
    other_item = next(t for t in bot.get_pool_tasks(uid) if t["text"] == "Написать отчёт")
    assert f"eplanuse_e_b1_{other_item['id']}" in flat_b1, \
        f"an untouched pool item must still be offered: {flat_b1}"
    print("2. An untouched pool item is still offered normally")

    # Sanity: without ctx (backward compat, e.g. some future caller), the
    # old behavior (no filtering) is preserved -- not a hard requirement
    # of the fix, just confirms the default doesn't crash.
    kb_no_ctx = bot.evening_plan_kb("e_b1", uid)
    flat_no_ctx = buttons_of(kb_no_ctx)
    assert f"eplanuse_e_b1_{item['id']}" in flat_no_ctx
    print("3. evening_plan_kb without ctx still works (backward compatible default)")

    print("\nALL EVENING-PLAN-POOL-DEDUP TESTS PASSED")


asyncio.run(main())
