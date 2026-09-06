import os, sys, asyncio, sqlite3, glob

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_db_backup.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
for leftover in glob.glob(os.environ["DB_PATH"] + ".backup_*"):
    os.remove(leftover)
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    async def reply_text(self, text, **kw):
        return self


class FakeUpdate:
    def __init__(self, uid):
        class U:
            id = uid
        self.effective_user = U()
        self.message = FakeMsg()


class FakeApplication:
    def __init__(self, bot_):
        self.bot = bot_


class FakeCtx:
    def __init__(self, bot_):
        self.application = FakeApplication(bot_)


class FakeBot:
    def __init__(self, fail_send=False):
        self.sent_documents = []
        self.sent_messages = []
        self.fail_send = fail_send

    async def send_document(self, chat_id, document, filename, caption=None):
        if self.fail_send:
            raise RuntimeError("Telegram недоступен")
        # Читаем содержимое, как реальный Bot прочитал бы файловый объект,
        # чтобы проверить, что это настоящий, консистентный снимок БД.
        data = document.read()
        self.sent_documents.append((chat_id, filename, data))

    async def send_message(self, chat_id, text, **kw):
        self.sent_messages.append((chat_id, text))


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-02): no DB backup mechanism existed at
    # all. backup_database uses sqlite3's own backup API (safe under live
    # WAL writes, unlike a raw file copy) and ships the snapshot to the
    # admin via Telegram -- no new cloud infrastructure needed.
    # ══════════════════════════════════════════════════════════════════════
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()

    # 1. backup_database produces a real, readable snapshot sent as a
    #    Telegram document to the admin (BACKUP_TARGET_UID / NOTIFY_USER_ID).
    fake_bot = FakeBot()
    app = FakeApplication(fake_bot)
    ok = await bot.backup_database(app)
    assert ok is True
    assert len(fake_bot.sent_documents) == 1, fake_bot.sent_documents
    chat_id, filename, data = fake_bot.sent_documents[0]
    assert chat_id == bot.BACKUP_TARGET_UID
    assert filename.startswith("adhd_backup_") and filename.endswith(".db")
    print("1. backup_database sends a document to the admin (BACKUP_TARGET_UID)")

    # 2. The sent snapshot is a genuine, independently-readable SQLite DB
    #    containing the same data as the live DB at backup time -- not an
    #    empty or corrupt stub.
    snapshot_path = os.path.join(SCRATCH, "recovered_snapshot.db")
    if os.path.exists(snapshot_path):
        os.remove(snapshot_path)
    with open(snapshot_path, "wb") as f:
        f.write(data)
    snap_conn = sqlite3.connect(snapshot_path)
    row = snap_conn.execute("SELECT name FROM users WHERE user_id=1").fetchone()
    snap_conn.close()
    os.remove(snapshot_path)
    assert row == ("Артем",), row
    print("2. The backup snapshot is a real, independently-readable copy of the live DB")

    # 3. No temp file is left behind next to DB_PATH after a successful backup.
    leftovers = glob.glob(bot.DB_PATH + ".backup_*")
    assert leftovers == [], f"temp backup file(s) not cleaned up: {leftovers}"
    print("3. No temporary backup file is left on disk after a successful run")

    # 4. If sending fails (Telegram down), backup_database returns False,
    #    still cleans up its temp file, AND tells the admin via a plain
    #    message (so a failed backup isn't silently swallowed).
    fail_bot = FakeBot(fail_send=True)
    app_fail = FakeApplication(fail_bot)
    ok2 = await bot.backup_database(app_fail)
    assert ok2 is False
    assert glob.glob(bot.DB_PATH + ".backup_*") == []
    assert fail_bot.sent_messages, "a failed backup must notify the admin, not fail silently"
    print("4. A failed send returns False, still cleans up, and notifies the admin")

    # 5. /backup is admin-only, exactly like the other admin_* commands.
    fake_bot2 = FakeBot()
    ctx = FakeCtx(fake_bot2)
    stranger_update = FakeUpdate(uid=42)
    await bot.admin_backup(stranger_update, ctx)
    assert not fake_bot2.sent_documents, "a non-admin must not be able to trigger /backup"
    print("5. /backup is gated to NOTIFY_USER_ID, same as the other admin commands")

    print("\nALL DB-BACKUP TESTS PASSED")


asyncio.run(main())
