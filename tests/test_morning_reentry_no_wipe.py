import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_reentry_no_wipe.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [700000]
    def __init__(self, chat_id, text=None):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.text = text
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return FakeMsg(self.chat_id)
    async def reply_animation(self, **kw):
        class _A:
            animation = None
        return _A()


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
    async def send_message(self, chat_id, text, **kw):
        return FakeMsg(chat_id)


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug reported by a user: full morning ritual completed (warmup +
    # writing + gratitude + child, all real answers), declined to set tasks
    # right away. A couple hours later the "+2h, утро ещё не закрыто"
    # reminder fires with a "☀️ Заполнить утро" button (go_morning). By
    # that point ctx.user_data's in-memory ritual bookkeeping is gone
    # (simulating a process restart between the two moments -- PicklePersistence
    # loss, a redeploy, etc.) even though the DB's morning_filled_at is
    # already set for today. Before the fix, morning_start's "resuming"
    # check depended ENTIRELY on ctx.user_data still remembering progress,
    # so a bare ctx.user_data made it restart the WHOLE ritual from warmup,
    # and finish_morning then overwrote the real writing/gratitude/child
    # answers with blanks from the second, rushed pass.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    await bot.morning_start(FakeUpdate(uid, data="go_morning", message=FakeMsg(uid)), ctx)
    await bot.skip_warmup(FakeUpdate(uid, data="skip_warmup", message=FakeMsg(uid)), ctx)
    await bot.got_writing(FakeUpdate(uid, text_message=FakeMsg(uid, text="Мысли о проекте")), ctx)
    await bot.got_gratitude(FakeUpdate(uid, text_message=FakeMsg(uid, text="Благодарен за кофе")), ctx)
    await bot.got_child(FakeUpdate(uid, text_message=FakeMsg(uid, text="Ты молодец")), ctx)
    await bot.morning_task_offer_no(FakeUpdate(uid, data="morning_tasks_no", message=FakeMsg(uid)), ctx)

    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    before = bot.get_diary(uid, "morning", today)
    assert before["writing"] == "Мысли о проекте"
    assert before["gratitude"] == "Благодарен за кофе"
    assert before["child"] == "Ты молодец"
    print("1. Full ritual saved correctly (writing/gratitude/child all present)")

    # Simulate the ctx.user_data loss -- a FRESH context for the same user,
    # as if the process restarted between the ritual and the later tap.
    fresh_ctx = FakeCtx()
    reminder_tap_msg = FakeMsg(uid)
    await bot.morning_start(FakeUpdate(uid, data="go_morning", message=reminder_tap_msg), fresh_ctx)

    assert reminder_tap_msg.sent and "Мысли о проекте" in reminder_tap_msg.sent[-1], \
        f"tapping 'Заполнить утро' from the +2h reminder after a ctx.user_data reset must show " \
        f"today's actual recorded content instead of restarting the ritual, got: {reminder_tap_msg.sent}"
    print("2. Re-tapping 'Заполнить утро' with a blank ctx.user_data (simulated restart) shows " \
          "what was already recorded instead of restarting the ritual")

    after = bot.get_diary(uid, "morning", today)
    assert after["writing"] == "Мысли о проекте", f"writing was wiped! got {after['writing']!r}"
    assert after["gratitude"] == "Благодарен за кофе", f"gratitude was wiped! got {after['gratitude']!r}"
    assert after["child"] == "Ты молодец", f"child was wiped! got {after['child']!r}"
    print("3. The real writing/gratitude/child answers are untouched after the re-entry")

    print("\nALL MORNING-REENTRY-NO-WIPE TESTS PASSED")


asyncio.run(main())
