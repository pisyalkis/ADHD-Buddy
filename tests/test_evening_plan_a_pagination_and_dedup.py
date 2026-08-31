import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_plan_a_pagination_and_dedup.db")
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
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (9th checkup): "Поставлю цели завтра ▸▸" only got attached
    # by ask_plan_a's own extra_rows -- evening_plan_show_more (pagination
    # via "Показать ещё") rebuilt the keyboard without it, silently
    # dropping the one-tap skip-all-goals shortcut on task A's screen.
    # ══════════════════════════════════════════════════════════════════════
    for i in range(5):
        bot.add_pool_task(uid, f"Дело {i}")
    msg = FakeMsg()
    await bot.ask_plan_a(msg, FakeCtx(), uid)
    buttons_initial = all_buttons(msg.last_kb)
    assert any(cb == "skip_all_goals" for _, cb in buttons_initial), buttons_initial
    print("1. ask_plan_a shows 'Поставлю цели завтра ▸▸' initially")

    upd_more = FakeUpdate(uid, data="eplanmore_e_a_3")
    ctx = FakeCtx()
    await bot.evening_plan_show_more(upd_more, ctx)
    buttons_after_more = all_buttons(upd_more.callback_query.message.last_kb)
    assert any(cb == "skip_all_goals" for _, cb in buttons_after_more), \
        f"'Поставлю цели завтра ▸▸' must survive pagination on the task-A screen, got {buttons_after_more}"
    print("2. 'Поставлю цели завтра ▸▸' survives 'Показать ещё' pagination on task A")

    # It must NOT appear on other steps (B1/B2/C1-C3), where it never did.
    upd_b1 = FakeUpdate(uid, data="eplanmore_e_b1_3")
    await bot.evening_plan_show_more(upd_b1, FakeCtx())
    buttons_b1 = all_buttons(upd_b1.callback_query.message.last_kb)
    assert not any(cb == "skip_all_goals" for _, cb in buttons_b1), buttons_b1
    print("3. 'Поставлю цели завтра ▸▸' correctly does NOT appear on the B1 step")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (9th checkup, low severity): pool carryover dedup was exact
    # case-sensitive match -- retyping the same task with different casing
    # produced a near-duplicate pool entry.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Аня', 'F')")
    conn.commit(); conn.close()
    uid2 = 2
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    bot.add_pool_task(uid2, "Позвонить маме")
    today_iso = datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat()
    bot.save_diary(uid2, "morning", {"focus": "позвонить маме"}, for_date=today_iso)
    ctx2 = FakeCtx()
    ctx2.user_data.update({
        "e_morning_date": today_iso,
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_selfcare": [], "e_energy": 3,
        "e_a": "", "e_b1": "", "e_b2": "", "e_c1": "", "e_c2": "", "e_c3": "",
        "e_tasks_done": [],  # not done
    })
    await bot.finish_evening(FakeMsg(), uid2, ctx2)
    pool2 = [t["text"] for t in bot.get_pool_tasks(uid2)]
    assert pool2.count("Позвонить маме") == 1 and "позвонить маме" not in pool2, \
        f"a case-different retyping of the same task must not create a duplicate pool entry, got {pool2}"
    print("4. Pool carryover dedup is now case-insensitive -- no near-duplicate entries")

    print("\nALL EVENING-PLAN-A-PAGINATION-AND-DEDUP TESTS PASSED")


asyncio.run(main())
