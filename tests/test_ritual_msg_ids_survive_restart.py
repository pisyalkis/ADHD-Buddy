import os, sys, asyncio, sqlite3, importlib

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_ritual_msg_ids_survive_restart.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    _next_id = [3000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        return m


class FakeBot:
    def __init__(self):
        self.deleted = []
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
    async def send_message(self, chat_id, text, **kw):
        return FakeMsg(chat_id)


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 42

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (live report): "после заполнения утра удалилось только
    # последнее сообщение, а не весь чат вопрос-ответ" -- traced to
    # _RITUAL_MSG_IDS being a plain in-memory dict. This bot gets
    # redeployed many times per hour during an active session, and a
    # process restart between two ritual messages silently dropped
    # everything tracked before it. Simulate exactly that: track some
    # messages, then act as if the process restarted (fresh module import,
    # same DB file) before the ritual finishes.
    # ══════════════════════════════════════════════════════════════════════
    msg1 = FakeMsg(uid)
    msg2 = FakeMsg(uid)
    bot._track_ritual_msg(msg1)
    bot._track_ritual_msg(msg2)

    conn = sqlite3.connect(bot.DB_PATH)
    count_before = conn.execute("SELECT COUNT(*) FROM ritual_msg_ids WHERE chat_id=?", (uid,)).fetchone()[0]
    conn.close()
    assert count_before == 2, count_before
    print("1. Two ritual messages tracked before the simulated restart")

    # Simulate a process restart: reload the module fresh (a real restart
    # would re-run init_db() against the same DB_PATH and start with no
    # in-memory state at all -- reload approximates that for this test).
    bot2 = importlib.reload(bot)
    bot2.init_db()

    msg3 = FakeMsg(uid)
    bot2._track_ritual_msg(msg3)

    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    await bot2._finish_ritual_cleanup(ctx, msg3, uid)

    deleted_ids = {mid for _, mid in fbot.deleted}
    assert msg1.message_id in deleted_ids, \
        f"a message tracked BEFORE the simulated restart must still be cleaned up, got {fbot.deleted}"
    assert msg2.message_id in deleted_ids
    assert msg3.message_id in deleted_ids
    print("2. All three messages -- including the two tracked before the restart -- get deleted at ritual finish")

    conn = sqlite3.connect(bot2.DB_PATH)
    remaining = conn.execute("SELECT COUNT(*) FROM ritual_msg_ids WHERE chat_id=?", (uid,)).fetchone()[0]
    conn.close()
    assert remaining == 0
    print("3. The ritual_msg_ids table is fully cleared after cleanup")

    print("\nALL RITUAL-MSG-IDS-SURVIVE-RESTART TESTS PASSED")


asyncio.run(main())
