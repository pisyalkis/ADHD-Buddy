import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_carried_task_marker.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = 900

    async def reply_text(self, text, **kw):
        return self


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-01): apply_yesterday_plan_if_empty
    # auto-carries yesterday's evening plan into today's empty task slots,
    # but nothing distinguished a silently-carried task from one the user
    # actually typed/chose today. Mark carried slots with _carried_{key},
    # surface it as "(↩️ из вчерашнего плана)" in the task listings, and
    # clear it the moment the user actually touches that slot.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    yesterday = (datetime.now(TBILISI).date() - timedelta(days=1)).isoformat()
    today = datetime.now(TBILISI).date().isoformat()
    bot.save_diary(uid, "evening", {"e_a": "Позвонить врачу", "e_b1": "Купить молоко"}, for_date=yesterday)

    # 1. apply_yesterday_plan_if_empty marks each carried-over slot.
    morning = bot.apply_yesterday_plan_if_empty(uid, today, bot.get_diary(uid, "morning", today))
    assert morning.get("focus") == "Позвонить врачу"
    assert morning.get("_carried_focus") == 1, morning
    assert morning.get("_carried_b1") == 1, morning
    print("1. apply_yesterday_plan_if_empty marks each auto-carried slot with _carried_{key}")

    # 2. _tasks_text_and_kb shows the "из вчерашнего плана" note for carried
    #    slots, and NOT for a manually-added one.
    morning["c1"] = "Задача, поставленная сегодня вручную"
    text, kb = bot._tasks_text_and_kb(morning, set(), "M")
    assert "Позвонить врачу _(↩️ из вчерашнего плана)_" in text, text
    assert "Купить молоко _(↩️ из вчерашнего плана)_" in text, text
    assert "Задача, поставленная сегодня вручную _(↩️ из вчерашнего плана)_" not in text, text
    assert "Задача, поставленная сегодня вручную" in text
    print("2. _tasks_text_and_kb marks carried slots, leaves manually-added ones unmarked")

    # 3. _walk_progress_text shows the same marker.
    bot.save_diary(uid, "morning", morning, for_date=today)
    walk_text = bot._walk_progress_text(uid, today)
    assert "Позвонить врачу _(↩️ из вчерашнего плана)_" in walk_text, walk_text
    assert "Задача, поставленная сегодня вручную _(↩️ из вчерашнего плана)_" not in walk_text, walk_text
    print("3. _walk_progress_text shows the same marker for carried slots")

    # 4. Editing a carried slot (apply_task_edit) clears the marker -- it's
    #    now a conscious decision, not a silent carry-over.
    await bot.apply_task_edit(FakeMessage(uid), FakeCtx(), uid, "focus", "Позвонить врачу")
    morning_after_edit = bot.get_diary(uid, "morning", today)
    assert not morning_after_edit.get("_carried_focus"), \
        "editing a carried slot (even re-confirming the same text) must clear the carried marker"
    assert morning_after_edit.get("_carried_b1") == 1, "editing ONE slot must not clear the marker on OTHER slots"
    print("4. apply_task_edit clears the carried marker for the slot it touches, leaves other slots' markers intact")

    # 5. The now-edited slot no longer shows the marker on the tasks screen.
    text2, kb2 = bot._tasks_text_and_kb(morning_after_edit, set(), "M")
    assert "Позвонить врачу _(↩️ из вчерашнего плана)_" not in text2, text2
    assert "Позвонить врачу" in text2
    assert "Купить молоко _(↩️ из вчерашнего плана)_" in text2, "the untouched slot must still show the marker"
    print("5. Once edited, the slot's marker is gone from the tasks screen; untouched slots keep theirs")

    print("\nALL CARRIED-TASK-MARKER TESTS PASSED")


asyncio.run(main())
