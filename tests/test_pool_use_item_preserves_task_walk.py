import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pool_use_item_preserves_task_walk.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id=1, message_id=1):
        self.chat_id = chat_id
        self.message_id = message_id
        self.reply_calls = []

    async def reply_text(self, text, **kw):
        self.reply_calls.append((text, kw.get("reply_markup")))
        return FakeMsg(self.chat_id, self.message_id + 1)


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edits.append((chat_id, message_id, text))


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
    bot.add_pool_task(uid, "Купить молоко")
    pool = bot.get_pool_tasks(uid)

    # ══════════════════════════════════════════════════════════════════════
    # Real bug: clear_awaiting_flags(ctx, update) unconditionally pops
    # "task_walk" -- pool_use_item/pool_write_own/pool_change_page all call
    # it BEFORE checking/using task_walk downstream, so mid-walk taps on
    # these buttons silently fell out of walk mode (apply_task_edit/
    # ask_task_text no longer saw task_walk=True and diverted to the
    # single-slot, non-walk continuation -- the walk just stopped).
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    ctx.user_data["task_walk"] = True
    ctx.user_data["walk_step_msg_id"] = 1
    ctx.user_data["walk_step_chat_id"] = 1

    screen = FakeMsg(chat_id=1, message_id=1)
    upd = FakeUpdate(uid, f"pooluse_b1_{pool[0]['id']}", screen)
    await bot.pool_use_item(upd, ctx)

    assert not screen.reply_calls, \
        f"pool_use_item mid-walk must keep editing the tracked walk message, not fall back to a plain reply, got {screen.reply_calls}"
    assert fbot.edits and "B2" in fbot.edits[-1][2], \
        f"apply_task_edit must have taken the WALK branch (advancing to B2) -- task_walk must survive clear_awaiting_flags, got {fbot.edits}"
    print("1. pool_use_item preserves task_walk across clear_awaiting_flags -- walk correctly advances to B2")

    # pool_write_own: same class of bug.
    ctx2 = FakeCtx(FakeBot())
    ctx2.user_data["task_walk"] = True
    screen2 = FakeMsg(chat_id=1, message_id=2)
    upd2 = FakeUpdate(uid, "poolwrite_b2", screen2)
    await bot.pool_write_own(upd2, ctx2)
    assert ctx2.user_data.get("task_walk") is True, \
        "pool_write_own must not silently clear task_walk for the ask_task_text call it makes"
    print("2. pool_write_own preserves task_walk across clear_awaiting_flags")

    # pool_change_page: same class of bug (affects the NEXT tap, not itself).
    ctx3 = FakeCtx(FakeBot())
    ctx3.user_data["task_walk"] = True
    screen3 = FakeMsg(chat_id=1, message_id=3)

    class FakeMsgWithEditMarkup(FakeMsg):
        async def edit_reply_markup(self, **kw):
            pass

    screen3 = FakeMsgWithEditMarkup(chat_id=1, message_id=3)
    upd3 = FakeUpdate(uid, f"poolpage_b1_{0}", screen3)
    await bot.pool_change_page(upd3, ctx3)
    assert ctx3.user_data.get("task_walk") is True, \
        "pool_change_page must not silently clear task_walk for a later pooluse_/poolwrite_ tap on the same screen"
    print("3. pool_change_page preserves task_walk across clear_awaiting_flags")

    print("\nALL POOL-USE-ITEM-PRESERVES-TASK-WALK TESTS PASSED")


asyncio.run(main())
