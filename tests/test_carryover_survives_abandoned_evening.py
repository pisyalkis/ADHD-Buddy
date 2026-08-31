import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_carryover_survives_abandoned_evening.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQueryMsg:
    async def reply_text(self, text, **kw):
        return self
    async def edit_reply_markup(self, **kw):
        pass


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data
        self.message = FakeQueryMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    tz = bot.get_user_tz(bot.get_user(uid))
    today_iso = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "если задача из плана на день не выполнена — она должна
    # попадать в список дел". Before this fix the carryover only happened
    # in finish_evening, at the very END of the evening ritual (five-six
    # steps after reviewing which tasks got done) -- if the person closed
    # the chat right after confirming "Что получилось?" without finishing
    # achievements/praise/highlights/selfcare/energy/tomorrow's plan, the
    # unfinished task was never carried over at all.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {
        "focus": "Сделать отчёт",   # done
        "b1": "Убраться дома",      # NOT done
    }, for_date=today_iso)

    ctx = FakeCtx()
    ctx.user_data["e_morning_date"] = today_iso
    ctx.user_data["e_tasks_done"] = ["focus"]

    # Simulates confirming the "Что получилось?" checklist and then
    # abandoning the rest of the evening ritual entirely -- finish_evening
    # is never called.
    await bot.tasks_done_finish(FakeUpdate(uid, data="td_done"), ctx)

    pool = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert "Убраться дома" in pool, \
        f"the unfinished task must already be in the pool, even though the rest of the evening ritual was never touched, got {pool}"
    assert "Сделать отчёт" not in pool
    print("1. The unfinished task lands in 📥 Список дел immediately after confirming 'Что получилось?', "
          "even if the rest of the evening ritual is abandoned")

    print("\nALL CARRYOVER-SURVIVES-ABANDONED-EVENING TESTS PASSED")


asyncio.run(main())
