import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_midday_checkboxes.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


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


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Сделать план", "b1": "Купить хлеб", "c1": "Позвонить маме"}, for_date=today)

    # ══════════════════════════════════════════════════════════════════════
    # Feedback (Victoria via Artem): the midday/beacon check-in ("Стоп на
    # секунду") only offered sequential progress shortcuts (A -> A+B -> ...),
    # not a way to mark a SPECIFIC task done out of order. midday_kb must now
    # expose the same per-task ▫️/✅ checkboxes as 📋 Задачи.
    # ══════════════════════════════════════════════════════════════════════
    morning = bot.get_diary(uid, "morning", today)

    # Real request ("разгрузим визуально"): by default the per-task
    # checkboxes are collapsed into one "☑️ Отметить то, что сделано"
    # button -- not shown individually up front.
    kb_collapsed = bot.midday_kb(morning, set())
    callbacks_collapsed = [row[0].callback_data for row in kb_collapsed.inline_keyboard]
    assert not any(cb.startswith("task_done_") for cb in callbacks_collapsed), callbacks_collapsed
    assert "mid_mark_done" in callbacks_collapsed, callbacks_collapsed
    assert not any(cb in ("mid_a_done_b", "mid_ab_done_c") for cb in callbacks_collapsed), \
        f"the old sequential-only progress shortcuts must be gone from the new keyboard, got {callbacks_collapsed}"
    print("1. midday_kb collapses per-task checkboxes into a single 'Отметить то, что сделано' button by default")

    # Real request: no neutral "just working, all fine" option existed --
    # only "all done"/"resting"/"procrastinating". mid_ok is a distinct,
    # already-existing handler (used elsewhere) reused here, not one of the
    # sequential shortcuts above -- it must be present.
    assert any(cb == "mid_ok" for cb in callbacks_collapsed), callbacks_collapsed
    print("1b. midday_kb offers the neutral 'Норм, работаю' option (mid_ok), distinct from the sequential shortcuts")

    # Expanding (expanded=True, as done by mid_mark_done_callback) reveals
    # the same per-task checkboxes as before, plus a way to collapse back.
    kb = bot.midday_kb(morning, set(), expanded=True)
    labels = [row[0].text for row in kb.inline_keyboard]
    callbacks = [row[0].callback_data for row in kb.inline_keyboard]
    assert any(cb == "task_done_focus" for cb in callbacks), callbacks
    assert any(cb == "task_done_b1" for cb in callbacks), callbacks
    assert any(cb == "task_done_c1" for cb in callbacks), callbacks
    assert "mid_mark_collapse" in callbacks, callbacks
    print("1c. expanded=True reveals a per-task checkbox for every set task, plus a way to collapse back")

    assert any(l.startswith("▫️ A: Сделать план") for l in labels), labels
    print("2. The checkbox button shows the task letter + text, same format as 📋 Задачи")

    assert any(cb == "mid_all_done" for cb in callbacks)
    assert any(cb == "mid_resting" for cb in callbacks)
    assert any(cb == "mid_procr" for cb in callbacks)
    print("3. The status shortcuts ('Всё сделано' / 'Отдыхаю' / 'Прокрастинирую') are still present")

    # ── Tapping a checkbox from the beacon screen goes through the SAME
    #    task_done_callback as 📋 Задачи -- no parallel logic to drift ────────
    ctx = FakeCtx()
    upd = FakeUpdate(uid, data="task_done_b1")
    await bot.task_done_callback(upd, ctx)
    done = bot.get_diary(uid, "tasks_done", today).get("done", [])
    assert "b1" in done, done
    print("4. Tapping the beacon's checkbox for B1 marks it done via the shared handler")

    # ── all_done gating: once every set task is checked, the bulk shortcut
    #    disappears (same behavior 📋 Задачи already had) ───────────────────
    done_set_all = {"focus", "b1", "c1"}
    kb_all_done = bot.midday_kb(morning, done_set_all)
    callbacks_all = [row[0].callback_data for row in kb_all_done.inline_keyboard]
    assert "mid_all_done" not in callbacks_all, callbacks_all
    print("5. Once every set task is checked, the 'Все задачи сделаны' shortcut is hidden")

    print("\nALL MIDDAY-CHECKBOXES TESTS PASSED")


asyncio.run(main())
