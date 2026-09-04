import os, sys, asyncio, time

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_warmup_nonblocking.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

from telegram.ext import Application, ConversationHandler, CallbackQueryHandler
from telegram import Bot as _Bot, User as _User

async def _fake_get_me(self, **kw):
    return _User(id=123, first_name="TestBot", is_bot=True, username="test_bot")

_Bot.get_me = _fake_get_me


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug: warmup_go sleeps ~2 minutes (6x20s) *inside* the handler. With
    # PTB's default concurrent_updates=False, Application.process_update
    # awaits each top-level handler in sequence -- so while user A is doing
    # the warmup, EVERY other user's update sits queued behind it for the
    # whole 2 minutes. The fix: register warmup_go's CallbackQueryHandler
    # with block=False, so ConversationHandler wraps it in a background
    # asyncio.Task (PendingState) instead of awaiting it inline -- this is
    # a real regression test for that registration, not a re-simulation of
    # PTB's own (already-trusted) internals.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Registration-level guard: warmup_go's handler must be block=False,
    #    so a future refactor can't silently reintroduce the global block.
    app = Application.builder().token("123:FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFA").build()
    await app.initialize()
    # morning_conv is built inside main(), not exposed standalone -- so
    # check its source for the exact registration carrying block=False.
    import inspect
    src = inspect.getsource(bot.main)
    assert 'CallbackQueryHandler(warmup_go,      pattern="^warmup_go$", block=False)' in src, \
        "warmup_go's handler registration must set block=False so it doesn't block the whole bot"
    print("1. warmup_go is registered with block=False in bot.main()")

    # ══════════════════════════════════════════════════════════════════════
    # 2. Behavioral proof, using the real ConversationHandler/PendingState
    #    machinery (not a hand-rolled simulation): while a slow, block=False
    #    handler is mid-sleep for user A, a check_update/handle_update cycle
    #    for a completely different conversation key (user B) must proceed
    #    immediately, without waiting for user A's task.
    # ══════════════════════════════════════════════════════════════════════
    events = []

    async def slow_handler(update, ctx):
        events.append(("slow_start", update.effective_user.id))
        await asyncio.sleep(0.4)
        events.append(("slow_end", update.effective_user.id))
        return 1

    async def fast_handler(update, ctx):
        events.append(("fast", update.effective_user.id))
        return 1

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(slow_handler, pattern="^go$")],
        states={1: [CallbackQueryHandler(fast_handler, pattern="^go$")]},
        fallbacks=[],
        per_message=False,
    )
    # Patch just the entry handler to block=False, mirroring the real fix.
    conv.entry_points[0].block = False
    app.add_handler(conv)

    from telegram import Update, CallbackQuery, User, Chat, Message
    import datetime as _dt

    def make_update(uid, uid_no):
        user = User(id=uid, first_name="U", is_bot=False)
        chat = Chat(id=uid, type="private")
        msg = Message(message_id=1, date=_dt.datetime.now(_dt.timezone.utc), chat=chat)
        cq = CallbackQuery(id=str(uid_no), from_user=user, chat_instance=str(uid),
                            data="go", message=msg)
        cq.set_bot(app.bot)
        upd = Update(update_id=uid_no, callback_query=cq)
        return upd

    upd_a = make_update(111, 1)
    upd_b = make_update(222, 2)

    t0 = time.monotonic()
    # Process user A's update: entry point is block=False, so this returns
    # almost immediately even though slow_handler sleeps 0.4s in the
    # background.
    await app.process_update(upd_a)
    elapsed_a = time.monotonic() - t0
    assert elapsed_a < 0.2, f"process_update for the slow (block=False) handler must return immediately, took {elapsed_a}s"
    # process_update() returning doesn't guarantee the newly created background
    # task has actually run its first line yet -- give the loop one tick.
    await asyncio.sleep(0)
    assert events == [("slow_start", 111)], events
    print(f"2. process_update() for user A returns immediately ({elapsed_a:.3f}s) instead of blocking for 0.4s")

    # Immediately process user B's update on a totally separate conversation
    # key -- this must NOT wait for user A's slow_handler to finish.
    t1 = time.monotonic()
    await app.process_update(upd_b)
    elapsed_b = time.monotonic() - t1
    assert elapsed_b < 0.2, f"a different user's update must not be blocked by user A's in-flight warmup, took {elapsed_b}s"
    await asyncio.sleep(0)
    assert ("slow_start", 222) in events, events
    print(f"3. A second user's update is dispatched immediately ({elapsed_b:.3f}s), unaffected by user A's in-flight task")

    # Let user A's background task actually finish and settle.
    await asyncio.sleep(0.5)
    assert ("slow_end", 111) in events, events
    print("4. User A's background task eventually completes and resolves the conversation state")

    print("\nALL WARMUP-NONBLOCKING TESTS PASSED")


asyncio.run(main())
