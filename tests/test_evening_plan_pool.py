import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_plan_pool.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_reply_markup(self, **kw):
        self.sent.append((None, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]
    @property
    def last_kb(self):
        return self.sent[-1][1]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def all_buttons(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "почему вечером не предлагают задачи из списка дел?" --
    # evening plan-setting (e_a/e_b1/e_b2/e_c1/e_c2/e_c3) was pure free-text
    # entry, no pool suggestions, unlike 📋 Задачи. Especially relevant now
    # that PR #120 pushes unfinished tasks into the pool at evening close.
    # ══════════════════════════════════════════════════════════════════════
    bot.add_pool_task(uid, "Купить лампочки")
    bot.add_pool_task(uid, "Позвонить маме")
    msg = FakeMsg()
    await bot.ask_plan_a(msg, FakeCtx(), uid)
    kb = msg.last_kb
    buttons = all_buttons(kb)
    assert ("Купить лампочки", f"eplanuse_e_a_1") in buttons or any(cb.startswith("eplanuse_e_a_") for _, cb in buttons), buttons
    assert any(cb == "skip_e_a" for _, cb in buttons), buttons
    assert any(cb == "skip_all_goals" for _, cb in buttons), \
        "the e_a-specific 'Поставлю цели завтра' shortcut must survive alongside pool suggestions"
    print("1. ask_plan_a (task A) now shows pool suggestions, keeps skip + skip-all-goals buttons")

    ctx = FakeCtx()
    msg2 = FakeMsg()
    await bot.ask_evening_plan_step(msg2, ctx, uid, "e_b1")
    buttons2 = all_buttons(msg2.last_kb)
    assert any(cb.startswith("eplanuse_e_b1_") for _, cb in buttons2), buttons2
    assert any(cb == "skip_e_b1" for _, cb in buttons2), buttons2
    print("2. ask_evening_plan_step (e_b1) also shows pool suggestions")

    # ══════════════════════════════════════════════════════════════════════
    # Picking a pool item fills the field and advances to the next real
    # step (same as typing text would) -- and does NOT delete the pool
    # item (same principle as pool_use_item in 📋 Задачи).
    # ══════════════════════════════════════════════════════════════════════
    pool = bot.get_pool_tasks(uid)
    lamp_item = next(t for t in pool if t["text"] == "Купить лампочки")
    upd = FakeUpdate(uid, data=f"eplanuse_e_a_{lamp_item['id']}")
    ctx2 = FakeCtx()
    next_state = await bot.evening_plan_use_pool(upd, ctx2)
    assert ctx2.user_data["e_a"] == "Купить лампочки", ctx2.user_data
    assert next_state == bot.E_B1
    text_after = upd.callback_query.message.last_text
    assert "Задача B1" in text_after, text_after
    pool_after = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert "Купить лампочки" in pool_after, \
        "picking a pool item for tomorrow's plan must NOT remove it from the pool"
    print("3. Picking a pool item fills e_a, advances to the B1 step, and leaves the pool item intact")

    # ══════════════════════════════════════════════════════════════════════
    # A stale pool id (item deleted meanwhile) must not crash and must
    # stay on the same step.
    # ══════════════════════════════════════════════════════════════════════
    upd_stale = FakeUpdate(uid, data="eplanuse_e_b2_999999")
    ctx3 = FakeCtx()
    state_stale = await bot.evening_plan_use_pool(upd_stale, ctx3)
    assert state_stale == bot.E_B2
    assert "e_b2" not in ctx3.user_data
    print("4. A stale/missing pool id is handled gracefully, staying on the same step")

    # ══════════════════════════════════════════════════════════════════════
    # "Показать ещё" pagination works and stays on the same step.
    # ══════════════════════════════════════════════════════════════════════
    for i in range(5):
        bot.add_pool_task(uid, f"Дело {i}")
    upd_more = FakeUpdate(uid, data="eplanmore_e_c1_3")
    ctx4 = FakeCtx()
    state_more = await bot.evening_plan_show_more(upd_more, ctx4)
    assert state_more == bot.E_C1
    buttons_more = all_buttons(upd_more.callback_query.message.last_kb)
    assert any(cb.startswith("eplanuse_e_c1_") for _, cb in buttons_more), buttons_more
    print("5. 'Показать ещё' pagination works and stays on the same step")

    # ══════════════════════════════════════════════════════════════════════
    # An empty pool must not show phantom buttons -- just the plain skip.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Аня', 'F')")
    conn.commit(); conn.close()
    uid2 = 2
    msg3 = FakeMsg()
    await bot.ask_evening_plan_step(msg3, FakeCtx(), uid2, "e_c2")
    buttons3 = all_buttons(msg3.last_kb)
    assert not any(cb.startswith("eplanuse_") for _, cb in buttons3), buttons3
    assert buttons3 == [("Пропустить задачи C →", "skip_e_c_all")], buttons3
    print("6. An empty pool shows only the plain skip button, no phantom suggestions")

    print("\nALL EVENING-PLAN-POOL TESTS PASSED")


asyncio.run(main())
