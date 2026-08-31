import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_answer_disappears.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.deleted = []
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeMsg:
    _next_id = [1]
    def __init__(self, chat_id, text=""):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.text = text
    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)
    async def edit_text(self, text, **kw):
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text):
        self.effective_user = FakeUser(uid)
        self.message = FakeMsg(uid, text)


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real complaint: "Почему при заполнении задач мой текст не удаляется?"
    # -- walking through task slots (awaiting_task_edit) left every typed
    # task text sitting in the chat forever, unlike ritual answers.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    ctx.user_data["awaiting_task_edit"] = "focus"
    upd = FakeUpdate(uid, "Снять манеру Курпатова")
    await bot.handle_text(upd, ctx)
    assert (uid, upd.message.message_id) in fbot.deleted, \
        f"typed task text (walk/edit flow) must be deleted, got deleted={fbot.deleted}"
    assert bot.get_diary(uid, "morning", bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()).get("focus") == "Снять манеру Курпатова"
    print("1. Task text typed via awaiting_task_edit (walk flow / single edit) is deleted, task is still saved")

    # ══════════════════════════════════════════════════════════════════════
    # Same for the OTHER entry point: proactive free text classified as
    # "поставь задачу — ..." (handle_set_task_intent), not prompted first.
    # ══════════════════════════════════════════════════════════════════════
    upd2 = FakeUpdate(uid, "поставь задачу — купить цветы")
    await bot.handle_set_task_intent(upd2.message, ctx, uid, "купить цветы")
    assert (uid, upd2.message.message_id) in fbot.deleted, \
        f"proactive set_task free text must be deleted too, got deleted={fbot.deleted}"
    print("2. Proactive 'поставь задачу' free text (handle_set_task_intent) is also deleted")

    print("\nALL TASK-ANSWER-DISAPPEARS TESTS PASSED")


asyncio.run(main())
