import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_promo_code_integrity.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
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
        self.sent.append((text, kw.get("parse_mode")))
        return self


class FakeUpdate:
    def __init__(self, uid, args):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg(uid)


class FakeCtx:
    def __init__(self, args):
        self.args = args


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug 1: create_promo_code did INSERT OR REPLACE with hardcoded uses=0,
    # silently wiping the redemption limit whenever an admin recreates an
    # existing code (e.g. to fix a label typo).
    # ══════════════════════════════════════════════════════════════════════
    bot.create_promo_code("SUMMER", 30, 5, "лето")
    bot.redeem_promo_code(1, "SUMMER")
    bot.redeem_promo_code(2, "SUMMER")
    rows = bot.list_promo_codes()
    row = next(r for r in rows if r[0] == "SUMMER")
    assert row[3] == 2, f"sanity: uses=2 after two redemptions, got {row}"

    # Admin recreates the code (fixing the label) -- uses must survive.
    bot.create_promo_code("SUMMER", 30, 5, "летняя акция")
    rows2 = bot.list_promo_codes()
    row2 = next(r for r in rows2 if r[0] == "SUMMER")
    assert row2[3] == 2, f"recreating an existing code must NOT reset uses, got {row2}"
    assert row2[1] == "летняя акция", f"label must still update, got {row2}"
    print("1. create_promo_code preserves uses when recreating an existing code")

    # A genuinely new code must still start at uses=0.
    bot.create_promo_code("WINTER", 14, 1, "")
    rows3 = bot.list_promo_codes()
    row3 = next(r for r in rows3 if r[0] == "WINTER")
    assert row3[3] == 0, f"a brand new code must start at uses=0, got {row3}"
    print("2. create_promo_code still starts a brand new code at uses=0")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2: newpromo_command interpolated the label into a Markdown message
    # without md_escape, unlike the sibling blogger_command.
    # ══════════════════════════════════════════════════════════════════════
    uid = 999  # matches NOTIFY_USER_ID
    upd = FakeUpdate(uid, [])
    label_parts = ["Метка", "с", "*звёздочкой*"]
    ctx = FakeCtx(["TESTCODE", "10", "1"] + label_parts)
    await bot.newpromo_command(upd, ctx)
    assert upd.message.sent, "newpromo_command must reply"
    text, parse_mode = upd.message.sent[-1]
    expected_escaped = bot.md_escape(" ".join(label_parts))
    assert expected_escaped in text, \
        f"the label must be escaped via md_escape before interpolating, got: {text!r}"
    assert "*звёздочкой*" not in text, \
        f"the raw unescaped label must not appear (would break Markdown parsing), got: {text!r}"
    print("3. newpromo_command escapes the label before interpolating into Markdown")

    print("\nALL PROMO-CODE-INTEGRITY TESTS PASSED")


asyncio.run(main())
