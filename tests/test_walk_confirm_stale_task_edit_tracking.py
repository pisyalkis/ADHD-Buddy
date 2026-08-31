import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_walk_confirm_stale.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [7000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.replies = []

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.replies.append((text, kw.get("reply_markup")))
        return m


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
    bot.add_pool_task(uid, "Купить молоко")
    pool = bot.get_pool_tasks(uid)
    item = pool[0]

    # ══════════════════════════════════════════════════════════════════════
    # Real report: "Выбираю задание Б1 из списка дел (внутри «Поставить/
    # изменить задачи» -- пошаговый проход) -- всё зависает / сообщение не
    # меняется." Repro: earlier THE SAME session, user edited some OTHER
    # slot via the single-slot ✏️ flow (non-walk) -- that sets
    # ctx.user_data["task_edit_msg_id"/"task_edit_chat_id"] to THAT old
    # screen. Walk mode deliberately never sets this tracking (see
    # _offer_task_input) but apply_task_edit's walk branch still calls
    # _edit_tracked_msg(ctx, "task_edit", ...) -- if that stale tracked
    # message still exists, the confirmation text silently lands there
    # instead of anywhere near the screen the person is actually looking
    # at (the one with the pool-suggestion buttons they just tapped),
    # which stays completely unchanged.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    stale_msg = FakeMsg(uid)  # an old single-edit "task_edit" screen from earlier
    ctx.user_data["task_edit_msg_id"] = stale_msg.message_id
    ctx.user_data["task_edit_chat_id"] = stale_msg.chat_id

    walk_screen = FakeMsg(uid)  # the pool-suggestion message the user just tapped
    ctx.user_data["task_walk"] = True

    await bot.apply_task_edit(walk_screen, ctx, uid, "b1", item["text"])

    # Since PR #169/walk-single-message: walk steps now share their OWN
    # track_key ("walk_step", established fresh by the walk itself) -- so
    # some edits via ctx.bot are expected once that tracking exists. What
    # must NOT happen is any edit landing on the STALE "task_edit" message
    # from the unrelated earlier single-slot session.
    assert not any(mid == stale_msg.message_id for _, mid, _ in fbot.edits), \
        f"the walk-mode confirmation must not silently redirect into the stale non-walk 'task_edit' tracked message, got edits={fbot.edits}"
    print("1. Walk-mode confirmation does not hijack the stale 'task_edit' tracked message from an earlier non-walk edit")

    assert walk_screen.replies, \
        "a confirmation reply must be sent from the screen the user actually tapped on"
    confirm_text = walk_screen.replies[0][0]
    assert "Добавил" in confirm_text, confirm_text
    print("2. The confirmation is sent as a new message from the tapped screen, so the person actually sees it")

    print("\nALL WALK-CONFIRM-STALE-TRACKING TESTS PASSED")


asyncio.run(main())
