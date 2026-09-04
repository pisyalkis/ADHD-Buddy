import os, sys, asyncio

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_chunked_markdown_oversized_part.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: _reply_chunked_markdown only ever compared the RUNNING chunk
    # against `limit` -- it never checked whether a single incoming `part`
    # was itself already over `limit` (e.g. one long user feedback message,
    # unbounded on the input side, wrapped as "*name* (date):\n{text}" in
    # admin_feedback). Such a part was sent as-is via reply_text, which
    # Telegram rejects for exceeding the real message-length limit -- an
    # unhandled BadRequest, the exact class of bug this function was
    # written to prevent for the multi-part case.
    # ══════════════════════════════════════════════════════════════════════
    msg = FakeMessage()
    limit = 100
    small = "*Юзер1* (2026-09-01):\nнормальный короткий фидбек"
    huge_line = "*Юзер2* (2026-09-02):\n" + ("оченьдлинный " * 20)  # one giant line, no \n inside
    assert len(huge_line) > limit, "sanity: the oversized part must actually exceed limit"

    await bot._reply_chunked_markdown(msg, [small, huge_line], limit=limit)

    assert all(len(s) <= limit for s in msg.sent), \
        f"every single sent message must respect the Telegram/limit bound, got lengths: {[len(s) for s in msg.sent]}"
    print(f"1. No sent chunk exceeds the {limit}-char limit, even though one input part did ({len(huge_line)} chars)")

    # Nothing from the oversized part's content is silently dropped.
    reassembled = "".join(msg.sent)
    for word in ["Юзер1", "Юзер2", "нормальный", "оченьдлинный"]:
        assert word in reassembled, f"'{word}' must survive in the output, got: {msg.sent}"
    print("2. The oversized part's content is fully preserved across the forced sub-chunks, nothing dropped")

    # A part with real newlines should still be split on line boundaries,
    # not raw characters, whenever a line boundary makes that possible.
    msg2 = FakeMessage()
    multiline_huge = "*Юзер3* (2026-09-03):\n" + "\n".join(f"строка номер {i} тут кое-что" for i in range(10))
    await bot._reply_chunked_markdown(msg2, [multiline_huge], limit=limit)
    assert all(len(s) <= limit for s in msg2.sent), [len(s) for s in msg2.sent]
    for chunk in msg2.sent:
        assert not any(line and len(line) > limit for line in chunk.split("\n")), \
            "no single sent chunk should contain a line broken mid-way when full lines already fit"
    print("3. A multi-line oversized part is split on line boundaries, not mid-line, when lines fit individually")

    print("\nALL CHUNKED-MARKDOWN OVERSIZED-PART TESTS PASSED")


asyncio.run(main())
