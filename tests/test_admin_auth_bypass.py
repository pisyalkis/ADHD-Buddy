import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_admin_auth_bypass.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
# Deliberately do NOT set NOTIFY_USER_ID -- simulates a deploy where the
# env var was forgotten (the exact scenario the bug report describes).
os.environ.pop("NOTIFY_USER_ID", None)
os.environ["ANTHROPIC_KEY"] = ""
import bot
assert bot.NOTIFY_USER_ID == 0, "sanity: NOTIFY_USER_ID defaults to 0 when unset"
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))
        return self


class FakeUpdate:
    def __init__(self, uid, args=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)


class FakeCtx:
    def __init__(self, args=None):
        self.args = args or []


async def main():
    # An ordinary, non-admin user (any uid != 0, since real Telegram ids
    # are never 0) -- with NOTIFY_USER_ID unset, this must NOT get admin
    # access to any of the gated commands.
    ordinary_uid = 123456789
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, 'Кто-то', 'M')", (ordinary_uid,))
    conn.commit(); conn.close()
    bot.update_user(ordinary_uid, timezone="Asia/Tbilisi")

    denied_calls = [
        ("newpromo_command", bot.newpromo_command, FakeUpdate(ordinary_uid, ["CODE"]), FakeCtx(["CODE"])),
        ("blogger_command", bot.blogger_command, FakeUpdate(ordinary_uid), FakeCtx(["Имя"])),
        ("promocodes_command", bot.promocodes_command, FakeUpdate(ordinary_uid), FakeCtx()),
        ("grant_command", bot.grant_command, FakeUpdate(ordinary_uid), FakeCtx(["1"])),
        ("admin_feedback", bot.admin_feedback, FakeUpdate(ordinary_uid), FakeCtx()),
        ("admin_send", bot.admin_send, FakeUpdate(ordinary_uid), FakeCtx()),
    ]
    for name, fn, upd, ctx in denied_calls:
        upd.message.sent.clear() if hasattr(upd.message, "sent") else None
        await fn(upd, ctx)
        assert upd.message.sent, f"{name} must reply (deny) even with NOTIFY_USER_ID unset"
        text = upd.message.sent[0][0]
        assert "Нет доступа" in text or "⛔" in text, \
            f"{name} must deny access to a non-admin user when NOTIFY_USER_ID is unset, got: {text!r}"

    print("1. All admin-gated commands deny access to an ordinary user when NOTIFY_USER_ID is unset (0)")

    # Sanity: create_promo_code (the underlying DB op) is untouched -- no
    # promo code should have been created by the denied newpromo_command call.
    assert not bot.promo_code_exists("CODE"), \
        "the denied newpromo_command call must not have created a promo code"
    print("2. The denied command had no side effect (no promo code created)")

    print("\nALL ADMIN-AUTH-BYPASS TESTS PASSED")


asyncio.run(main())
