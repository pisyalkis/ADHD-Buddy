import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_dedupe_updates.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, update_id, uid, data=None):
        self.update_id = update_id
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.effective_message = FakeMsg()
        self.callback_query = FakeQuery(uid, data) if data is not None else None
        self.message = None
        self.pre_checkout_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Тест', 'M')")
    conn.commit(); conn.close()
    bot._seen_update_ids.clear()

    # ══════════════════════════════════════════════════════════════════════
    # Bug (reported by Artem, with screenshot): pressing "☕ Отдыхаю 10-15 мин"
    # once seemed to do nothing, then a second press produced THREE replies --
    # a redelivered update (bot restart / Telegram retry) processed twice on
    # top of the real second tap. dedupe_updates must swallow the redelivery.
    # ══════════════════════════════════════════════════════════════════════
    upd1 = FakeUpdate(1001, 1, data="mid_resting")
    await bot.dedupe_updates(upd1, FakeCtx())
    print("1. A fresh update passes through dedupe_updates untouched")

    redelivered = FakeUpdate(1001, 1, data="mid_resting")
    try:
        await bot.dedupe_updates(redelivered, FakeCtx())
        raised = False
    except bot.ApplicationHandlerStop:
        raised = True
    assert raised, "the exact same update_id delivered again must be stopped, not reprocessed"
    print("2. The same update_id delivered a second time is stopped (ApplicationHandlerStop)")

    # ── A genuinely different update (real second tap) still goes through ──
    upd2 = FakeUpdate(1002, 1, data="mid_resting")
    await bot.dedupe_updates(upd2, FakeCtx())
    print("3. A different update_id (a real second tap) is not blocked")

    # ── Old entries are pruned so the dict doesn't grow forever ─────────────
    bot._seen_update_ids[9999] = bot.time.monotonic() - bot._SEEN_UPDATE_TTL - 5
    upd3 = FakeUpdate(1003, 1, data="mid_resting")
    await bot.dedupe_updates(upd3, FakeCtx())
    assert 9999 not in bot._seen_update_ids, "entries older than the TTL must be pruned"
    print("4. Stale entries older than the TTL are pruned on each check")

    print("\nALL DEDUPE-UPDATES TESTS PASSED")


asyncio.run(main())
