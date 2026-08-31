import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_redundant_task_offer.db")
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


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (live report, screenshot): after "Взять как задачи на
    # сегодня" (or manually setting tasks) followed by finishing the
    # morning ritual, the task offer still unconditionally asked "Поставить
    # задачи на сегодня?" -- confusing right below a summary that already
    # showed A/B1/B2 set.
    #
    # send_morning_task_offer itself was later merged into
    # _finish_ritual_cleanup (see test_merge_morning_finish_offer.py) --
    # renamed to _morning_task_offer_text_and_kb, now returning (text, kb)
    # instead of sending directly, so this exact suppression logic can
    # still be exercised on its own.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Разобраться со списком дел", "b1": "Структура канала"}, for_date=today)
    text, kb = bot._morning_task_offer_text_and_kb(uid)
    assert text is None and kb is None, \
        f"the task offer must not fire when today's tasks are already set, got {text!r}"
    print("1. _morning_task_offer_text_and_kb stays silent when today's tasks are already set")

    # Sanity: with no tasks set yet, the offer still shows normally.
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone=tz_name)
    text2, kb2 = bot._morning_task_offer_text_and_kb(uid2)
    assert text2 and "Поставить задачи на сегодня?" in text2
    assert kb2 is not None
    print("2. _morning_task_offer_text_and_kb still offers normally when no tasks are set yet")

    print("\nALL REDUNDANT-TASK-OFFER TESTS PASSED")


asyncio.run(main())
