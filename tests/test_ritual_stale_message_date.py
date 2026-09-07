import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta, timezone

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_ritual_stale_message_date.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeMsg:
    def __init__(self, chat_id, message_id, date=None):
        self.chat_id = chat_id
        self.message_id = message_id
        self.date = date
        self.edit_calls = []
        self.reply_calls = []
        self.deleted = False

    async def edit_text(self, text, **kw):
        if self.deleted:
            raise Exception("Message to edit not found")
        self.edit_calls.append(text)
        return self

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, **kw):
        self.reply_calls.append(text)
        return FakeMsg(self.chat_id, self.message_id + 1000)


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug report (Артем, with screenshot): resuming an interrupted
    # ritual (e.g. evening) edits `message` -- the message attached to the
    # tapped button -- in place. If that message is itself old (e.g. last
    # night's evening notification, or a menu screen opened a while ago),
    # the resumed ritual step ends up edited wherever that old message
    # sits in the chat -- NOT at the bottom -- while anything else sent to
    # the chat since then (reminders, backups, admin replies) buries it.
    # `_render_step_msg` already treats a step as "stale" using its OWN
    # ctx.user_data bookkeeping (STEP_MSG_STALE_SEC), but that bookkeeping
    # is empty exactly in the resume-after-a-gap case (process restarted,
    # or this track_key was never rendered before) -- so the old code fell
    # straight through to editing the old `message` in place. Now `message.
    # date` (Telegram's own timestamp) is used as a second signal.
    # ══════════════════════════════════════════════════════════════════════

    # 1. `message` is OLD (older than STEP_MSG_STALE_SEC) and there's no
    #    ctx.user_data memory of a previous render (fresh ctx, simulating a
    #    resume after a process restart) -- must delete the old message and
    #    send a NEW one, not edit in place.
    ctx = FakeCtx()
    old_date = datetime.now(timezone.utc) - timedelta(seconds=bot.STEP_MSG_STALE_SEC + 60)
    old_msg = FakeMsg(chat_id=1, message_id=100, date=old_date)
    await bot._render_ritual_step(old_msg, ctx, "↩️ Продолжаем с того места, где остановился сегодня вечером:")
    assert old_msg.deleted, "an old message.date must cause the stale message to be deleted"
    assert not old_msg.edit_calls, "the old message must NOT be edited in place"
    assert old_msg.reply_calls, "a fresh message must be sent instead"
    assert old_msg.reply_calls[0] == "↩️ Продолжаем с того места, где остановился сегодня вечером:"
    print("1. Resuming via an OLD message (by message.date) deletes it and sends a fresh one instead of editing in place")

    # 2. `message` is RECENT (just sent) and no prior ctx.user_data memory --
    #    must edit in place as before (e.g. "hold down evening from menu,
    #    appears in place of the menu" -- an intentional, still-desired UX).
    ctx2 = FakeCtx()
    fresh_msg = FakeMsg(chat_id=2, message_id=200, date=datetime.now(timezone.utc))
    await bot._render_ritual_step(fresh_msg, ctx2, "🌙 Хороший был день! Давай закроем этот день.")
    assert not fresh_msg.deleted, "a recent message must not be deleted"
    assert fresh_msg.edit_calls == ["🌙 Хороший был день! Давай закроем этот день."], fresh_msg.edit_calls
    assert not fresh_msg.reply_calls, "a recent message must be edited in place, not replaced"
    print("2. A RECENT message (menu just opened) is still edited in place -- no regression")

    # 3. `message.date` is missing (None, e.g. a synthetic/test message) --
    #    must not crash, falls back to the normal edit-in-place behavior.
    ctx3 = FakeCtx()
    no_date_msg = FakeMsg(chat_id=3, message_id=300, date=None)
    await bot._render_ritual_step(no_date_msg, ctx3, "Вопрос без даты сообщения")
    assert not no_date_msg.deleted
    assert no_date_msg.edit_calls == ["Вопрос без даты сообщения"]
    print("3. A message with no .date attribute doesn't crash and falls back to editing in place")

    # 4. The EXISTING ctx.user_data-based staleness path (a step re-rendered
    #    after STEP_MSG_STALE_SEC of its OWN last render) still works --
    #    regression guard for the pre-existing mechanism this change sits
    #    next to.
    ctx4 = FakeCtx()
    stale_ts = (datetime.now() - timedelta(seconds=bot.STEP_MSG_STALE_SEC + 60)).isoformat()
    ctx4.user_data["ritual_step_msg_id"] = 400
    ctx4.user_data["ritual_step_chat_id"] = 4
    ctx4.user_data["ritual_step_msg_ts"] = stale_ts

    class FakeBot:
        def __init__(self):
            self.deleted_ids = []

        async def delete_message(self, chat_id, message_id):
            self.deleted_ids.append((chat_id, message_id))

    ctx4.bot = FakeBot()
    fresh_button_msg = FakeMsg(chat_id=4, message_id=401, date=datetime.now(timezone.utc))
    await bot._render_ritual_step(fresh_button_msg, ctx4, "Следующий вопрос")
    assert (4, 400) in ctx4.bot.deleted_ids, \
        "the OLD tracked ritual_step message (400) must still be deleted via the pre-existing ctx.user_data staleness path"
    assert fresh_button_msg.edit_calls == ["Следующий вопрос"], fresh_button_msg.edit_calls
    print("4. The pre-existing ctx.user_data-based staleness path (different track) still works unchanged")

    print("\nALL RITUAL-STALE-MESSAGE-DATE TESTS PASSED")


asyncio.run(main())
