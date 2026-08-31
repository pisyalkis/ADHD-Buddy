import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_plan_pool_pagination.db")
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
        self.edited_markup = None
    async def edit_reply_markup(self, reply_markup=None, **kw):
        self.edited_markup = reply_markup


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "почему список дел показывает по 3 дела? мы же это
    # фиксили" -- the pagination fix (bigger page size + ◀️ N/M ▶️ counter
    # instead of a bare "Показать ещё" with no way back) landed in
    # pool_suggestions_kb (📋 Задачи, PR #140) but evening_plan_kb -- the
    # parallel screen used when picking a pool item for TOMORROW's plan in
    # the evening ritual -- is a separate implementation that never got the
    # same fix, and was still hardcoded to limit=3.
    # ══════════════════════════════════════════════════════════════════════
    for i in range(10):
        bot.add_pool_task(uid, f"Дело {i+1}")
    pool = bot.get_pool_tasks(uid)
    assert len(pool) == 10

    kb1 = bot.evening_plan_kb("e_a", uid)
    labels1 = buttons_of(kb1)
    item_labels1 = [t for t, cb in labels1 if cb.startswith("eplanuse_")]
    assert len(item_labels1) == 8, labels1
    assert ("1/2", "noop") in labels1, labels1
    assert any(cb.startswith("eplanmore_e_a_8") for _, cb in labels1), labels1
    assert not any(t == "◀️" for t, _ in labels1), "no back button on the first page"
    print("1. evening_plan_kb shows 8 items per page and a '1/2' indicator with a forward button on page 1")

    # Forward navigation via evening_plan_show_more (same handler as before,
    # now driven by the ◀️/▶️ scheme instead of a bare "Показать ещё").
    upd = FakeUpdate(uid, data="eplanmore_e_a_8")
    await bot.evening_plan_show_more(upd, None)
    kb2 = upd.callback_query.message.edited_markup
    labels2 = buttons_of(kb2)
    item_labels2 = [t for t, cb in labels2 if cb.startswith("eplanuse_")]
    assert len(item_labels2) == 2, labels2
    assert ("2/2", "noop") in labels2, labels2
    assert any(t == "◀️" for t, _ in labels2), "page 2 must offer a back button"
    assert not any(cb.startswith("eplanmore_") and t == "▶️" for t, cb in labels2), "no forward button on the last page"
    print("2. evening_plan_show_more moves to page 2/2 with a back button and no forward button (last page)")

    # Back navigation.
    upd2 = FakeUpdate(uid, data="eplanmore_e_a_0")
    await bot.evening_plan_show_more(upd2, None)
    kb3 = upd2.callback_query.message.edited_markup
    labels3 = buttons_of(kb3)
    assert ("1/2", "noop") in labels3, labels3
    assert not any(t == "◀️" for t, _ in labels3), "back on page 1 must not show a back button"
    print("3. evening_plan_show_more navigates back to page 1/2 correctly")

    # Small pool (fits on one page) -> no page indicator at all, same
    # convention as pool_suggestions_kb.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.add_pool_task(uid2, "Одно дело")
    kb4 = bot.evening_plan_kb("e_a", uid2)
    labels4 = buttons_of(kb4)
    assert not any(cb == "noop" for _, cb in labels4), "no page indicator needed for a single-page pool"
    print("4. evening_plan_kb shows no page indicator at all when everything fits on one page")

    # "Поставлю цели завтра ▸▸" must still be present only on e_a, on every page.
    assert ("Поставлю цели завтра ▸▸", "skip_all_goals") in labels1
    assert ("Поставлю цели завтра ▸▸", "skip_all_goals") in labels2
    kb_b1 = bot.evening_plan_kb("e_b1", uid)
    assert not any(cb == "skip_all_goals" for _, cb in buttons_of(kb_b1)), \
        "skip_all_goals must stay exclusive to e_a"
    print("5. 'Поставлю цели завтра' stays on every page of e_a and does not leak to other steps")

    print("\nALL EVENING-PLAN-POOL-PAGINATION TESTS PASSED")


asyncio.run(main())
