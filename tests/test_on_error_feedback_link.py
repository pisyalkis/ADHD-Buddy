import os, sys, asyncio

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_on_error_feedback_link.db")
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


class FakeQuery:
    def __init__(self):
        self.answered = False
        self.message = FakeMsg()
    async def answer(self):
        self.answered = True


class FakeUpdate:
    def __init__(self):
        self.callback_query = FakeQuery()
        self.effective_message = self.callback_query.message


class FakeCtx:
    def __init__(self, error):
        self.error = error


def callbacks(reply_markup):
    return [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-31): the generic error message always
    # said the same "попробуй ещё раз или открой меню" whether the failure
    # was a one-off network blip or something stably broken for this user
    # -- with no path to actually report it. Add a feedback button/link
    # alongside "◀️ Меню".
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate()
    await bot.on_error(upd, FakeCtx(Exception("boom")))
    assert upd.callback_query.message.sent
    text, kb = upd.callback_query.message.sent[-1]
    cbs = callbacks(kb)
    assert "go_menu" in cbs, "the Menu button must still be there (no regression)"
    assert "go_feedback" in cbs, f"on_error's message must offer a way to report the problem, got {cbs}"
    print("1. on_error's message offers both '◀️ Меню' and '💬 Обратная связь' buttons")

    # 2. go_feedback is already access-gate-exempt -- a user whose access
    #    just expired can still reach feedback from this error screen.
    assert "go_feedback" in bot.ACCESS_GATE_EXEMPT_CALLBACKS
    print("2. go_feedback stays reachable even with expired access (already exempt)")

    print("\nALL ON-ERROR-FEEDBACK-LINK TESTS PASSED")


asyncio.run(main())
