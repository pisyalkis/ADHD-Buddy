import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_on_error_notifies_user.db")
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
    def __init__(self, with_callback=True, with_message=True):
        self.callback_query = FakeQuery() if with_callback else None
        self.effective_message = self.callback_query.message if with_callback else (FakeMsg() if with_message else None)


class FakeCtx:
    def __init__(self, error):
        self.error = error


def has_menu_button(reply_markup):
    if reply_markup is None:
        return False
    return any(btn.callback_data == "go_menu" for row in reply_markup.inline_keyboard for btn in row)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug report: "нажимаю на кнопку — вообще никакой реакции". An
    # unhandled exception deep inside a handler (e.g. evening_start after
    # q.answer() already fired) used to be COMPLETELY invisible to the user
    # -- on_error only printed to the server log. Now it must also notify
    # the user with a visible message and a way back to the menu.
    # ══════════════════════════════════════════════════════════════════════

    upd = FakeUpdate(with_callback=True)
    await bot.on_error(upd, FakeCtx(Exception("boom")))
    assert upd.callback_query.answered, "on_error must clear the button spinner"
    assert upd.callback_query.message.sent, "on_error must notify the user, not just log"
    text, kb = upd.callback_query.message.sent[-1]
    assert "не так" in text or "ошиб" in text.lower(), text
    assert has_menu_button(kb), f"on_error's message should offer a way back to the menu, got {kb}"
    print("1. on_error notifies the user (with a Menu button) on a callback-query update")

    upd2 = FakeUpdate(with_callback=False, with_message=True)
    await bot.on_error(upd2, FakeCtx(Exception("boom")))
    assert upd2.effective_message.sent, "on_error must also notify on a plain message update (no callback_query)"
    print("2. on_error notifies the user on a plain message update too")

    # Must never raise itself, regardless of how little information `update` carries.
    await bot.on_error(None, FakeCtx(Exception("boom")))
    print("3. on_error(update=None, ...) does not raise")

    upd3 = FakeUpdate(with_callback=False, with_message=False)
    await bot.on_error(upd3, FakeCtx(Exception("boom")))
    print("4. on_error with no effective_message at all does not raise")

    print("\nALL ON-ERROR-NOTIFIES-USER TESTS PASSED")


asyncio.run(main())
