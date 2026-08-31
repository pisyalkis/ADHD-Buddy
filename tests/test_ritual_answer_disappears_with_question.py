import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_ritual_answer_disappears.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [21000]
    def __init__(self, chat_id, text="ответ пользователя"):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.reply_calls = []
        self.text = text

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self):
        self.edits = []
        self.deleted = []
        self.sent = []

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edits.append((chat_id, message_id, text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return FakeMsg(chat_id)


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


def ritual_msg_ids_in_db(chat_id):
    """Peeks (without popping) at what's still queued in ritual_msg_ids for
    this chat -- read-only, so it doesn't disturb the real flow."""
    conn = sqlite3.connect(bot.DB_PATH)
    rows = conn.execute("SELECT message_id FROM ritual_msg_ids WHERE chat_id=?", (chat_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


async def main():
    uid = 42
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (42, 'Аня', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "заполняешь утро и вечер — твой ответ должен исчезать
    # ВМЕСТЕ С ВОПРОСОМ", i.e. the moment the ritual advances to the next
    # question, not just "eventually, once the whole ritual is done" (that
    # was the OLD behavior -- ritual_msg_ids accumulated the answer and it
    # only got swept at _finish_ritual_cleanup, at the very end).
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    menu_screen = FakeMsg(chat_id=uid)

    await bot.morning_start(FakeUpdate(uid, data="go_morning", message=menu_screen), ctx)
    tracked_id = ctx.user_data.get("ritual_step_msg_id")

    warmup_screen = FakeMsg(chat_id=uid); warmup_screen.message_id = tracked_id
    await bot.skip_warmup(FakeUpdate(uid, data="skip_warmup", message=warmup_screen), ctx)
    # Now on the "writing" question.

    user_writing = FakeMsg(chat_id=uid, text="сегодня было много мыслей")
    upd_writing = FakeUpdate(uid, text_message=user_writing)
    await bot.got_writing(upd_writing, ctx)

    # The ritual is still MID-FLOW here (next question is "gratitude",
    # finish_morning has not run) -- the user's own answer must already be
    # gone, right now, not queued for later.
    assert (uid, user_writing.message_id) in fbot.deleted, \
        f"the typed answer must be deleted immediately when the next question appears, got deleted={fbot.deleted}"
    assert "Благодарность" in fbot.edits[-1][2], \
        "the question message itself must have moved on to the next question at the same moment"
    print("1. Typed morning answer (writing) is deleted the moment the NEXT question appears, mid-ritual")

    # It must never have been queued in the old bulk-cleanup table either --
    # this is a genuine behavior change, not just an earlier delete of the
    # same deferred mechanism.
    assert user_writing.message_id not in ritual_msg_ids_in_db(uid), \
        "the answer must be deleted directly, not routed through ritual_msg_ids for a later sweep"
    print("2. The answer never passes through the deferred ritual_msg_ids bulk-delete table at all")

    # Skip gratitude via button, then answer "child" by typed text too.
    gratitude_screen = FakeMsg(chat_id=uid); gratitude_screen.message_id = tracked_id
    await bot.skip_m_gratitude(FakeUpdate(uid, data="skip_m_gratitude", message=gratitude_screen), ctx)

    user_child = FakeMsg(chat_id=uid, text="ты молодец, что стараешься")
    await bot.got_child(FakeUpdate(uid, text_message=user_child), ctx)
    assert (uid, user_child.message_id) in fbot.deleted
    print("3. Same holds for the last morning field (child) -- deleted immediately, not deferred")

    # ══════════════════════════════════════════════════════════════════════
    # Evening ritual: walk into a free-text field (e_ach, reached once the
    # checklist branch is skipped by having no task fields filled) and
    # confirm the same immediate-delete behavior there.
    # ══════════════════════════════════════════════════════════════════════
    fbot2 = FakeBot()
    ctx2 = FakeCtx(fbot2)
    evening_menu = FakeMsg(chat_id=uid)
    await bot.evening_start(FakeUpdate(uid, data="go_evening", message=evening_menu), ctx2)
    # No task fields were set today -> lands straight on "e_ach".
    ev_tracked = ctx2.user_data.get("ritual_step_msg_id")
    assert ev_tracked is not None, "evening ritual must be tracking its own step message"

    user_ach = FakeMsg(chat_id=uid, text="закончил(а) важный отчёт")
    await bot.got_e_ach(FakeUpdate(uid, text_message=user_ach), ctx2)
    assert (uid, user_ach.message_id) in fbot2.deleted, \
        f"evening free-text answers must also disappear immediately, got deleted={fbot2.deleted}"
    assert user_ach.message_id not in ritual_msg_ids_in_db(uid)
    print("4. Evening ritual (e_ach) deletes the typed answer immediately too, same as morning")

    print("\nALL RITUAL-ANSWER-DISAPPEARS-WITH-QUESTION TESTS PASSED")


asyncio.run(main())
