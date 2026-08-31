import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_walk_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [9000]
    def __init__(self, chat_id=1, message_id=None):
        self.chat_id = chat_id
        self.message_id = message_id if message_id is not None else FakeMsg._next_id[0]
        if message_id is None:
            FakeMsg._next_id[0] += 1
        self.reply_calls = []

    async def reply_text(self, text, **kw):
        self.reply_calls.append((text, kw.get("reply_markup")))
        return FakeMsg(self.chat_id)


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
        self.edits = []  # (chat_id, message_id, text)

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

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "в идеале у нас всегда должно быть одно актуальное
    # сообщение" -- the step-by-step task walk (A→B1→...→C3) used to send
    # a brand-new message on every step (button tap or typed text answer),
    # leaving a growing trail behind. It should instead always edit ONE
    # tracked message in place, whether the step is answered by tapping a
    # button or by typing free text.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    tapped_screen = FakeMsg(chat_id=1)  # e.g. the 📋 Задачи screen with "✏️ Поставить/изменить задачи"

    upd = FakeUpdate(uid, "walk_tasks", tapped_screen)
    await bot.walk_tasks_start(upd, ctx)

    tracked_id = ctx.user_data.get("walk_step_msg_id")
    assert tracked_id == tapped_screen.message_id, \
        f"walk must take over the tapped screen itself, not spawn a new message, got tracked={tracked_id} vs tapped={tapped_screen.message_id}"
    assert not tapped_screen.reply_calls, \
        f"the very first walk step must edit the tapped screen in place, not reply with a new message, got {tapped_screen.reply_calls}"
    assert fbot.edits and fbot.edits[-1][1] == tapped_screen.message_id
    print("1. walk_tasks_start takes over the tapped screen in place (no new message for step 1)")

    # Step 1 (slot "focus"/A, empty, no pool) answered by TYPED TEXT --
    # message here is the user's OWN message object, which must never be
    # edited or replied to; the step's confirmation + next step must still
    # land on the SAME tracked message via the bot API.
    user_text_msg = FakeMsg(chat_id=1)  # a distinct message id -- the user's own text
    await bot.apply_task_edit(user_text_msg, ctx, uid, "focus", "Сделать отчёт")

    assert not user_text_msg.reply_calls, \
        f"answering by typed text must not create a new message from the user's own message, got {user_text_msg.reply_calls}"
    assert all(e[1] == tapped_screen.message_id for e in fbot.edits), \
        f"every edit must target the ONE tracked walk message, got {fbot.edits}"
    assert "Добавил" in fbot.edits[-1][2] or "B1" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("2. Typed-text answer edits the SAME tracked message -- no new message appears")

    # Step 2 (slot "b1", empty) answered via a POOL SELECTION (callback) --
    # message here is q.message, but it must still be the tracked message
    # id (no new one), consistent with the callback-driven case.
    bot.add_pool_task(uid, "Позвонить маме")
    pool = bot.get_pool_tasks(uid)
    pool_screen = FakeMsg(chat_id=1, message_id=tracked_id)  # this IS the tracked message by now
    pool_upd = FakeUpdate(uid, f"pooluse_b1_{pool[0]['id']}", pool_screen)
    await bot.pool_use_item(pool_upd, ctx)

    assert not pool_screen.reply_calls, \
        f"selecting from the pool must not spawn a new message either, got {pool_screen.reply_calls}"
    assert all(e[1] == tapped_screen.message_id for e in fbot.edits)
    print("3. Pool-selection answer also edits the same tracked message")

    # Step 3+ (b2, empty) -- walk should have moved on to B2 (still same
    # message); the pool still has one leftover item (linked to b1, not
    # removed until marked done), so it offers pool-or-type, same as B1 did.
    assert "B2" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("4. Walk correctly advanced to the next empty slot (B2), still on the same message")

    # Finish the walk via typed text for the remaining slots, then walk_finish.
    for key, val in [("b2", "..."), ("c1", "..."), ("c2", "..."), ("c3", "...")]:
        msg = FakeMsg(chat_id=1)
        await bot.apply_task_edit(msg, ctx, uid, key, val)
        assert not msg.reply_calls, f"slot {key}: must not create a new message"

    assert all(e[1] == tapped_screen.message_id for e in fbot.edits), \
        "the entire six-slot walk must stay on a single message from start to finish"
    print("5. The full six-slot walk never created a single extra message -- all edits, one message")

    # After the last slot, the walk should show "Прошлись по всем задачам ✅"
    # and clear the walk_step tracking (walk is over).
    assert "Прошлись по всем задачам" in fbot.edits[-1][2], fbot.edits[-1][2]
    assert ctx.user_data.get("walk_step_msg_id") is None
    assert ctx.user_data.get("walk_step_chat_id") is None
    print("6. Walk-step tracking is cleared once the walk naturally finishes")

    print("\nALL WALK-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
