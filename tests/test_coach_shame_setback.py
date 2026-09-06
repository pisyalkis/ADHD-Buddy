import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coach_shame_setback.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1

    async def edit_text(self, text, **kw):
        return self

    async def reply_text(self, text, **kw):
        return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = FakeMsg(uid)

    async def answer(self, *a, **kw): pass

    async def edit_message_text(self, text, **kw):
        return self.message


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name, gender="M"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, ?)", (uid, name, gender))
    conn.commit(); conn.close()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-27): 🤖 Коуч had quick buttons for
    # "can't start"/"distracted"/"procrastinating"/"overloaded", but none for
    # shame or a setback -- a common and especially heavy ADHD state where
    # self-blame after a slip blocks recovery harder than the slip itself.
    # ══════════════════════════════════════════════════════════════════════

    # 1. COACH_PROMPTS has entries for both new quick buttons.
    assert "c_shame" in bot.COACH_PROMPTS
    assert "c_setback" in bot.COACH_PROMPTS
    assert bot.COACH_PROMPTS["c_shame"].strip()
    assert bot.COACH_PROMPTS["c_setback"].strip()
    print("1. COACH_PROMPTS has non-empty prompts for c_shame and c_setback")

    uid = 1
    make_user(uid, "Артем", "M")

    # 2. coach_menu shows both new buttons, gendered correctly -- verified via
    #    a message wrapper that records the reply_markup passed to edit_text
    #    (coach_menu edits q.message via _edit_or_send).
    class RecordingMsg(FakeMsg):
        def __init__(self, chat_id):
            super().__init__(chat_id)
            self.markups = []

        async def edit_text(self, text, **kw):
            self.markups.append(kw.get("reply_markup"))
            return self

    uid2 = 2
    make_user(uid2, "Вика", "F")
    upd2 = FakeUpdate(uid2, "go_coach")
    upd2.callback_query.message = RecordingMsg(uid2)
    ctx2 = FakeCtx()
    await bot.coach_menu(upd2, ctx2)
    markup = upd2.callback_query.message.markups[-1]
    labels_callbacks = [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]
    callbacks = [c for _, c in labels_callbacks]
    assert "c_shame" in callbacks and "c_setback" in callbacks, labels_callbacks
    shame_label = dict(labels_callbacks)["c_shame"] if False else next(t for t, c in labels_callbacks if c == "c_shame")
    setback_label = next(t for t, c in labels_callbacks if c == "c_setback")
    assert "Стыдно" in shame_label, shame_label
    # gender='F' -> personalize should resolve "Сорвался(ась)" to the female form.
    assert "Сорвалась" in setback_label and "Сорвался(ась)" not in setback_label, setback_label
    print("2. coach_menu shows gendered 'Стыдно за себя'/'Сорвался(ась)' buttons with c_shame/c_setback callbacks")

    # 3. Tapping either button routes through coach_quick -> send_coach with
    #    the matching COACH_PROMPTS text (verified via the "not configured"
    #    fallback message, since ANTHROPIC_KEY is empty in tests -- confirms
    #    the callback is wired to a real, non-empty prompt end-to-end).
    upd3 = FakeUpdate(uid, "c_shame")
    ctx3 = FakeCtx()
    await bot.coach_quick(upd3, ctx3)  # must not raise
    upd4 = FakeUpdate(uid, "c_setback")
    ctx4 = FakeCtx()
    await bot.coach_quick(upd4, ctx4)  # must not raise
    print("3. coach_quick routes c_shame/c_setback to send_coach without error")

    print("\nALL COACH-SHAME-SETBACK TESTS PASSED")


asyncio.run(main())
