import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_ritual_cleanup.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


_next_msg_id = [1000]
OUTBOX = []  # (chat_id, text, reply_markup) for every message.reply_text() call


class FakeMsg:
    def __init__(self, chat_id, message_id=None):
        self.chat_id = chat_id
        self.message_id = message_id if message_id is not None else _next_msg_id[0]
        _next_msg_id[0] += 1
        self.text = None
    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        m.text = text
        OUTBOX.append((self.chat_id, text, kw.get("reply_markup")))
        return m
    async def edit_text(self, text, **kw):
        self.text = text
        return self
    async def edit_reply_markup(self, **kw):
        pass


class FakeBot:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.deleted = []
        self.sent = []
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        m.text = text
        self.sent.append((chat_id, text, m.message_id))
        return m
    async def pin_chat_message(self, **kw): pass
    async def unpin_chat_message(self, **kw): pass
    async def edit_message_text(self, **kw): pass


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = FakeMsg(uid)
    async def answer(self, *a, **kw): pass


class FakeCallbackUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeTextUpdate:
    def __init__(self, uid, text):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = None
        self.message = FakeMsg(uid)
        self.message.text = text


class FakeCtx:
    def __init__(self, uid):
        self.user_data = {}
        self.bot = FakeBot(uid)


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    ctx = FakeCtx(uid)

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: don't delete ritual questions AS THEY'RE ANSWERED (the
    # user's own reply would be left without context) -- instead the bot's
    # own side of the ritual edits ONE tracked message throughout
    # (_render_ritual_step), the user's own typed answers vanish immediately
    # alongside the next question (_delete_ritual_answer, see
    # test_ritual_answer_disappears_with_question.py), and once the ritual
    # is truly finished (finish_morning), any leftover tracked id (the
    # ritual_step message itself, plus rare stray messages) is swept in one
    # go. Nothing is lost: the pinned "Утро записано!" summary and 🗂
    # Карточка дня already show everything that was asked.
    # ══════════════════════════════════════════════════════════════════════
    await bot.morning_start(FakeCallbackUpdate(uid, "go_morning"), ctx)
    await bot.warmup_done(FakeCallbackUpdate(uid, "warmup_done"), ctx)
    await bot.got_writing(FakeTextUpdate(uid, "Сон про кота"), ctx)
    await bot.got_gratitude(FakeTextUpdate(uid, "Утреннему кофе"), ctx)
    await bot.got_child(FakeTextUpdate(uid, "Ты молодец"), ctx)

    # The bot's own side of the ritual (greeting -> warmup -> "Отлично" ->
    # writing/gratitude/child questions) all collapse into ONE
    # continuously-edited tracked message (track_key="ritual_step") instead
    # of a new message per step. The user's own 3 typed answers are each
    # deleted immediately as the ritual advances (not deferred). At cleanup,
    # only the final tracked ritual_step message is left to sweep -- so the
    # running total across the whole flow is 1 (ritual_step, at cleanup) + 3
    # (writing/gratitude/child answers, deleted immediately) = 4.
    assert len(ctx.bot.deleted) == 4, ctx.bot.deleted
    assert all(cid == uid for cid, _ in ctx.bot.deleted), ctx.bot.deleted
    print("1. Full morning ritual (warmup + writing/gratitude/child) deletes its one tracked ritual message plus the 3 typed answers")

    # Real bug (live report): _RITUAL_MSG_IDS used to be a plain in-memory
    # dict -- lost on every process restart, which happens often during a
    # session of continuous deploys, wiping mid-ritual tracking and leaving
    # only the messages sent AFTER the restart to be cleaned up. Now backed
    # by the ritual_msg_ids table (same durability as scheduled_deletions).
    conn = sqlite3.connect(bot.DB_PATH)
    remaining_ritual_ids = conn.execute("SELECT COUNT(*) FROM ritual_msg_ids WHERE chat_id=?", (uid,)).fetchone()[0]
    conn.close()
    assert remaining_ritual_ids == 0, remaining_ritual_ids
    print("2. ritual_msg_ids table is cleared for the chat after cleanup (durable, survives a restart)")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "Объединить сообщения утро записано и всё видно в
    # карточке дня" -- there is no longer a SEPARATE confirmation message at
    # all. The "🗂 Карточка дня" mention (and, when no tasks are set yet,
    # the "Поставить задачи на сегодня?" offer with its buttons) now lives
    # inside the ONE summary message finish_morning itself sends.
    # ══════════════════════════════════════════════════════════════════════
    assert ctx.bot.sent == [], \
        f"_finish_ritual_cleanup must no longer send its own confirmation message, got {ctx.bot.sent}"
    summary_calls = [c for c in OUTBOX if c[0] == uid]
    assert len(summary_calls) == 1, summary_calls
    _, summary_text, summary_kb = summary_calls[0]
    assert "Утро записано" in summary_text
    assert "Карточку дня" in summary_text
    assert "Поставить задачи на сегодня?" in summary_text
    assert any(b.callback_data == "morning_tasks_yes" for row in summary_kb.inline_keyboard for b in row), \
        "the task-offer buttons must be attached to this same summary message"
    print("3. The single summary message mentions the day card AND offers to set tasks, with real buttons attached")

    # ══════════════════════════════════════════════════════════════════════
    # When today's tasks are already set, there's no offer to merge in --
    # the pinned summary just mentions the day card, no task-offer buttons.
    # ══════════════════════════════════════════════════════════════════════
    uid_bare = 10
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (10, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid_bare, timezone="Asia/Tbilisi")
    today_bare = datetime.now(bot.get_user_tz(bot.get_user(uid_bare))).date().isoformat()
    bot.save_diary(uid_bare, "morning", {"focus": "Уже поставлено"}, for_date=today_bare)
    ctx_bare = FakeCtx(uid_bare)

    await bot.morning_start(FakeCallbackUpdate(uid_bare, "go_morning"), ctx_bare)
    await bot.warmup_done(FakeCallbackUpdate(uid_bare, "warmup_done"), ctx_bare)
    await bot.got_writing(FakeTextUpdate(uid_bare, "..."), ctx_bare)
    await bot.got_gratitude(FakeTextUpdate(uid_bare, "..."), ctx_bare)
    await bot.got_child(FakeTextUpdate(uid_bare, "..."), ctx_bare)

    assert ctx_bare.bot.sent == []
    bare_calls = [c for c in OUTBOX if c[0] == uid_bare]
    assert len(bare_calls) == 1, bare_calls
    _, bare_text, bare_kb = bare_calls[0]
    assert "Карточке дня" in bare_text
    assert "Поставить задачи на сегодня?" not in bare_text, \
        "must not offer to set tasks that are already set today"
    print("4. With today's tasks already set, the pinned summary mentions the day card but no task offer")

    # ══════════════════════════════════════════════════════════════════════
    # Same mechanic for the evening ritual, via the quick "Поставлю цели
    # завтра" shortcut (skip_all_goals) after a few real steps.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    ctx2 = FakeCtx(uid2)

    await bot.evening_start(FakeCallbackUpdate(uid2, "go_evening"), ctx2)
    await bot.got_e_ach(FakeTextUpdate(uid2, "Дописал(а) отчёт"), ctx2)
    await bot.skip_e_praise(FakeCallbackUpdate(uid2, "skip_e_praise"), ctx2)
    await bot.skip_e_highlights(FakeCallbackUpdate(uid2, "skip_e_highlights"), ctx2)
    await bot.skip_all_goals(FakeCallbackUpdate(uid2, "skip_all_goals"), ctx2)

    # Same collapse as the morning case: greeting -> achievements -> praise
    # -> highlights -> selfcare all land on the ONE tracked ritual_step
    # message; only that plus the user's own typed achievement answer need
    # deleting: 1 (ritual_step, at cleanup) + 1 (achievement answer, deleted
    # immediately) = 2.
    assert len(ctx2.bot.deleted) == 2, ctx2.bot.deleted
    assert all(cid == uid2 for cid, _ in ctx2.bot.deleted), ctx2.bot.deleted
    assert ctx2.bot.sent == []
    evening_calls = [c for c in OUTBOX if c[0] == uid2]
    assert len(evening_calls) == 1, evening_calls
    assert "День закрыт" in evening_calls[0][1]
    assert "Карточке дня" in evening_calls[0][1]
    print("11. Evening ritual (via skip_all_goals) also cleans up its Q&A trail, with the day-card mention folded into the one summary message")

    print("\nALL RITUAL CLEANUP TESTS PASSED")


asyncio.run(main())
