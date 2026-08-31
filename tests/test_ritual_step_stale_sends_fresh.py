import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_ritual_step_stale_sends_fresh.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.deleted = []
        self.edited = []
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append((chat_id, message_id, text))


class FakeMsg:
    _next_id = [1]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)
    async def edit_text(self, text, **kw):
        raise Exception("plain user message can't be edited")


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    fbot = FakeBot()
    ctx = FakeCtx(fbot)

    # ══════════════════════════════════════════════════════════════════════
    # Real complaint: "заполняю утро позже — вопрос ритуала появляется
    # наверху, а клавиатура и то, что печатаю, внизу" -- if a lot of time
    # passed since the ritual step message was last shown, editing it keeps
    # the update in its old (now buried) position. Past STEP_MSG_STALE_SEC,
    # the next step must send a NEW message instead (and clean up the old
    # one) rather than silently editing something the user isn't looking at.
    # ══════════════════════════════════════════════════════════════════════
    trigger_msg = FakeMsg(chat_id=uid)
    await bot._render_ritual_step(trigger_msg, ctx, "Первый шаг")
    first_mid = ctx.user_data.get("ritual_step_msg_id")
    assert first_mid is not None
    print("1. First render tracks a message as usual")

    # Simulate 6 minutes passing since that render.
    stale_ts = (datetime.now() - timedelta(seconds=bot.STEP_MSG_STALE_SEC + 60)).isoformat()
    ctx.user_data["ritual_step_msg_ts"] = stale_ts

    next_trigger = FakeMsg(chat_id=uid)
    await bot._render_ritual_step(next_trigger, ctx, "Следующий шаг (спустя долгую паузу)")
    assert (uid, first_mid) in fbot.deleted, \
        f"the stale old step message must be deleted, got deleted={fbot.deleted}"
    assert not any(mid == first_mid for _, mid, _ in fbot.edited), \
        "the stale message must not be edited (that keeps the update buried in its old position)"
    new_mid = ctx.user_data.get("ritual_step_msg_id")
    assert new_mid is not None and new_mid != first_mid, \
        "a fresh message must be tracked, not the old stale one"
    print("2. After a long gap, the stale step message is deleted and a fresh one is sent instead of edited")

    # A quick follow-up right after (well within STEP_MSG_STALE_SEC) must go
    # back to normal editing -- no unnecessary send-new/delete churn.
    quick_trigger = FakeMsg(chat_id=uid)
    await bot._render_ritual_step(quick_trigger, ctx, "Быстрый следующий шаг")
    assert ctx.user_data.get("ritual_step_msg_id") == new_mid, \
        "a prompt follow-up must keep editing the same recent message, not send yet another one"
    assert any(mid == new_mid for _, mid, _ in fbot.edited), \
        "a prompt follow-up must actually edit, not silently do nothing"
    assert (uid, new_mid) not in fbot.deleted
    print("3. A prompt follow-up (not stale) still edits the same recent message as usual")

    print("\nALL RITUAL-STEP-STALE-SENDS-FRESH TESTS PASSED")


asyncio.run(main())
