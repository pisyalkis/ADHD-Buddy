import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_backup_email.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.sent_docs = []
        self.sent_msgs = []

    async def send_document(self, chat_id, document, filename, caption):
        self.sent_docs.append((chat_id, filename, caption))

    async def send_message(self, chat_id, text):
        self.sent_msgs.append((chat_id, text))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeSMTPServer:
    """Records login/send_message calls; used as both the class returned by
    smtplib.SMTP_SSL(...) and its own context manager."""
    instances = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logins = []
        self.sent = []
        FakeSMTPServer.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logins.append((user, password))

    def send_message(self, msg):
        self.sent.append(msg)


class FailingSMTPServer(FakeSMTPServer):
    def login(self, user, password):
        raise Exception("535 Authentication failed")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request: "пусть бэкап уходит мне на почту" -- dupe the existing
    # Telegram backup with an independent Gmail SMTP channel, kept optional
    # (skipped entirely when SMTP_USER/SMTP_APP_PASSWORD aren't configured)
    # so the feature doesn't break deployments that haven't set it up, and
    # doesn't fail the whole backup if only the email leg breaks.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Without SMTP creds configured (default/unset), backup_database
    #    behaves exactly as before -- Telegram only, no email attempt.
    real_smtp_ssl = bot.smtplib.SMTP_SSL
    bot.smtplib.SMTP_SSL = FakeSMTPServer
    FakeSMTPServer.instances.clear()
    bot.SMTP_USER = ""
    bot.SMTP_APP_PASSWORD = ""
    bot.BACKUP_EMAIL_TO = ""

    app1 = FakeApp()
    ok1 = await bot.backup_database(app1)
    assert ok1 is True
    assert len(app1.bot.sent_docs) == 1, app1.bot.sent_docs
    assert not FakeSMTPServer.instances, "must not attempt SMTP at all when creds aren't configured"
    assert not app1.bot.sent_msgs, "no email-failure notice either -- it was never attempted"
    print("1. Without SMTP creds configured, backup_database behaves exactly as before (Telegram only)")

    # 2. With SMTP creds configured, the backup is ALSO emailed -- correct
    #    From/To/attachment, alongside the still-successful Telegram send.
    bot.SMTP_USER = "pisyalkis@gmail.com"
    bot.SMTP_APP_PASSWORD = "fake-app-password"
    bot.BACKUP_EMAIL_TO = "pisyalkis@gmail.com"
    FakeSMTPServer.instances.clear()

    app2 = FakeApp()
    ok2 = await bot.backup_database(app2)
    assert ok2 is True
    assert len(app2.bot.sent_docs) == 1, "the Telegram copy must still be sent as before"
    assert len(FakeSMTPServer.instances) == 1, "must attempt exactly one SMTP session"
    server = FakeSMTPServer.instances[0]
    assert server.host == "smtp.gmail.com" and server.port == 465
    assert server.logins == [("pisyalkis@gmail.com", "fake-app-password")]
    assert len(server.sent) == 1
    sent_msg = server.sent[0]
    assert sent_msg["From"] == "pisyalkis@gmail.com"
    assert sent_msg["To"] == "pisyalkis@gmail.com"
    assert "бэкап" in sent_msg["Subject"].lower()
    # The attachment must actually be present (a real .db payload, not just headers).
    attachment_parts = [p for p in sent_msg.walk() if p.get_filename()]
    assert attachment_parts and attachment_parts[0].get_filename().endswith(".db"), sent_msg
    print("2. With SMTP creds configured, the backup is ALSO emailed with a correct attachment")

    # 3. If the email leg fails (e.g. bad app password), the Telegram copy
    #    must still have succeeded, backup_database must still report
    #    overall success, and the admin gets a SEPARATE notice about just
    #    the email failure (not a silent swallow, not a fatal error).
    bot.smtplib.SMTP_SSL = FailingSMTPServer
    app3 = FakeApp()
    ok3 = await bot.backup_database(app3)
    assert ok3 is True, "an email-only failure must not fail the whole backup (Telegram already succeeded)"
    assert len(app3.bot.sent_docs) == 1, "the Telegram copy must still succeed independently"
    assert any("почту" in t for _, t in app3.bot.sent_msgs), \
        f"the admin must be told specifically that the EMAIL leg failed: {app3.bot.sent_msgs}"
    print("3. An email-only failure doesn't break the Telegram backup, and is reported separately")

    bot.smtplib.SMTP_SSL = real_smtp_ssl
    bot.SMTP_USER = ""
    bot.SMTP_APP_PASSWORD = ""
    bot.BACKUP_EMAIL_TO = ""
    print("\nALL BACKUP-EMAIL TESTS PASSED")


asyncio.run(main())
