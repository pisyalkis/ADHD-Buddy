import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_privacy_hint.db")
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
    @property
    def last_text(self):
        return self.sent[-1][0]
    @property
    def last_kb(self):
        return self.sent[-1][1]


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    ctx = FakeCtx()

    # ══════════════════════════════════════════════════════════════════════
    # Feedback (real tester): filling in the free-write field, worried
    # "someone might read this". The privacy screen already existed
    # (go_privacy, reachable from "О боте"), but nobody finds it at the
    # moment they hesitate. First time a user hits a "vulnerable" free-text
    # field, show a short reassurance line + a button straight to that
    # screen -- but ONLY the first time ever, not on every ritual.
    # ══════════════════════════════════════════════════════════════════════
    msg = FakeMsg()
    await bot.ask_writing(msg, ctx, uid)
    assert "🔒" in msg.last_text and "только у тебя" in msg.last_text, msg.last_text
    buttons = [b.text for row in msg.last_kb.inline_keyboard for b in row]
    assert "🔒 Приватность" in buttons, buttons
    assert any(b.callback_data == "go_privacy" for row in msg.last_kb.inline_keyboard for b in row)
    print("1. First-ever ask_writing shows the privacy hint + a button to the existing go_privacy screen")

    saved = bot.get_user(uid)
    assert "m_writing" in (saved.get("privacy_hint_shown") or "").split(","), saved
    print("2. privacy_hint_shown is recorded after the first showing")

    # Second time -- must NOT show the hint again (would feel naggy/paranoid).
    msg2 = FakeMsg()
    await bot.ask_writing(msg2, ctx, uid)
    assert "🔒" not in msg2.last_text, msg2.last_text
    buttons2 = [b.text for row in msg2.last_kb.inline_keyboard for b in row]
    assert "🔒 Приватность" not in buttons2, buttons2
    assert msg2.last_kb.inline_keyboard == bot.skip_kb("skip_m_writing").inline_keyboard
    print("3. Second time onward, ask_writing looks exactly as before -- no repeated nagging")

    # ══════════════════════════════════════════════════════════════════════
    # Fields that go through with_privacy_hint but ALSO already have a
    # "❓ Зачем это?" button (skip_why_kb) -- the privacy button must be
    # added as an extra row, not clobber the existing why/skip row.
    # ══════════════════════════════════════════════════════════════════════
    msg3 = FakeMsg()
    await bot.ask_gratitude(msg3, ctx, "M", uid)
    rows = msg3.last_kb.inline_keyboard
    assert len(rows) == 2, rows
    assert rows[0][0].text == "🔒 Приватность" and rows[0][0].callback_data == "go_privacy"
    assert [b.text for b in rows[1]] == ["❓ Зачем это?", "Пропустить →"]
    print("4. ask_gratitude keeps its existing 'why' row intact, privacy button added as its own row")

    # ══════════════════════════════════════════════════════════════════════
    # Honesty check: e_ach/e_highlights actually get sent to Claude for
    # ai_day_analysis -- their hint must say so (🤖), not falsely claim
    # "only you see this" (🔒) like the fields that never leave the DB.
    # ══════════════════════════════════════════════════════════════════════
    msg4 = FakeMsg()
    await bot.ask_achievements(msg4, ctx, "M", uid)
    assert "🤖" in msg4.last_text and "ИИ" in msg4.last_text, msg4.last_text
    assert "только у тебя" not in msg4.last_text, \
        "e_ach is actually sent to Claude for day analysis -- must not falsely claim it's local-only"
    print("5. ask_achievements (goes to Claude for AI day analysis) uses the honest AI-routed hint text, not the local-only one")

    msg5 = FakeMsg()
    await bot.ask_highlights(msg5, ctx, uid)
    assert "🤖" in msg5.last_text and "только у тебя" not in msg5.last_text, msg5.last_text
    print("6. ask_highlights (same reason) also uses the AI-routed hint text")

    # m_child and e_praise -- genuinely local-only fields -- keep the 🔒 wording.
    msg6 = FakeMsg()
    await bot.ask_child(msg6, ctx, "F", uid)
    assert "🔒" in msg6.last_text and "только у тебя" in msg6.last_text, msg6.last_text
    print("7. ask_child (never leaves the DB) uses the local-only hint text")

    msg7 = FakeMsg()
    await bot.ask_praise(msg7, ctx, uid)
    assert "🔒" in msg7.last_text and "только у тебя" in msg7.last_text, msg7.last_text
    print("8. ask_praise (never leaves the DB) uses the local-only hint text")

    print("\nALL PRIVACY-HINT TESTS PASSED")


asyncio.run(main())
