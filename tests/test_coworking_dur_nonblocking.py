import os, sys, asyncio, time, inspect

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_dur_nonblocking.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

from telegram.ext import Application, CallbackQueryHandler
from telegram import Bot as _Bot, User as _User, Update, CallbackQuery, Chat, Message
import datetime as _dt


async def _fake_get_me(self, **kw):
    # The real get_me() caches its result into self._bot_user as a side
    # effect (that's what makes Bot.bot/.id usable afterwards) -- a fake
    # that only returns the User without replicating that assignment leaves
    # the bot looking "uninitialized" to PTB's own internals.
    user = _User(id=123, first_name="TestBot", is_bot=True, username="test_bot")
    self._bot_user = user
    return user

_Bot.get_me = _fake_get_me

# No real Telegram HTTP calls in this test -- CallbackQuery.answer() and the
# creator's own confirmation send are irrelevant to what's being proven here
# (that the ALUMNI BROADCAST doesn't block the whole bot), so both are
# short-circuited to no-ops rather than routed through a fake HTTP layer.
async def _fake_answer(self, *a, **kw):
    return True

CallbackQuery.answer = _fake_answer
real_send_tracked_notification = bot.send_tracked_notification
async def _fake_send_tracked_notification(*a, **kw):
    return None


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real bug (nightly scan 2026-09-10): coworking_set_duration awaits
    # _notify_coworking_alumni() to completion -- which sends a REAL network
    # request per alumnus, sequentially, potentially dozens of them. Its
    # CallbackQueryHandler was registered WITHOUT block=False, and the
    # Application never enables concurrent_updates(True) either -- so PTB
    # (which dispatches updates strictly one at a time by default) stalled
    # the ENTIRE bot for every user, not just the session's creator, for as
    # long as the alumni broadcast took. Same class of bug as warmup_go
    # (see test_warmup_nonblocking.py) -- fixed the same way, block=False
    # on the handler registration.
    # ══════════════════════════════════════════════════════════════════════

    # 1. Registration-level guard: coworking_set_duration's handler must be
    #    block=False, so a future refactor can't silently reintroduce the
    #    global block.
    src = inspect.getsource(bot.main)
    assert 'CallbackQueryHandler(coworking_set_duration,  pattern="^coworking_dur_\\\\d+$", block=False)' in src, \
        "coworking_set_duration's handler registration must set block=False so it doesn't block the whole bot"
    print("1. coworking_set_duration is registered with block=False in bot.main()")

    # 2. Behavioral proof using the REAL handler (not a synthetic stand-in),
    #    through actual PTB dispatch: while _notify_coworking_alumni is mid-
    #    flight (patched to be slow, standing in for a real network-bound
    #    alumni broadcast), a concurrently issued, completely unrelated
    #    update must be dispatched immediately rather than queued behind it.
    real_notify_alumni = bot._notify_coworking_alumni
    events = []

    async def slow_notify_alumni(bot_, session_id, exclude_uid):
        events.append("notify_start")
        await asyncio.sleep(0.4)
        events.append("notify_end")

    bot._notify_coworking_alumni = slow_notify_alumni
    bot.send_tracked_notification = _fake_send_tracked_notification

    app = Application.builder().token("123:FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFA").build()
    await app.initialize()
    app.add_handler(CallbackQueryHandler(bot.coworking_set_duration, pattern="^coworking_dur_\\d+$", block=False))

    async def other_handler(update, ctx):
        events.append(("other", update.effective_user.id))

    app.add_handler(CallbackQueryHandler(other_handler, pattern="^ping$"))

    conn = __import__("sqlite3").connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(1, timezone="Asia/Tbilisi")

    def make_update(uid, uid_no, data):
        user = _User(id=uid, first_name="U", is_bot=False)
        chat = Chat(id=uid, type="private")
        msg = Message(message_id=1, date=_dt.datetime.now(_dt.timezone.utc), chat=chat)
        cq = CallbackQuery(id=str(uid_no), from_user=user, chat_instance=str(uid), data=data, message=msg)
        cq.set_bot(app.bot)
        return Update(update_id=uid_no, callback_query=cq)

    from datetime import timedelta
    app.user_data[1]["coworking_pending_start_utc"] = (
        __import__("datetime").datetime.now(bot.pytz.utc) + timedelta(hours=2)
    ).isoformat()
    upd_create = make_update(1, 1, "coworking_dur_25")
    upd_ping = make_update(2, 2, "ping")

    t0 = time.monotonic()
    await app.process_update(upd_create)
    elapsed_create = time.monotonic() - t0
    assert elapsed_create < 0.2, \
        f"process_update for coworking_set_duration must return immediately (block=False), took {elapsed_create}s"
    await asyncio.sleep(0)
    assert events and events[0] == "notify_start", events
    print(f"2. process_update() for session creation returns immediately ({elapsed_create:.3f}s) instead of blocking for the alumni broadcast")

    t1 = time.monotonic()
    await app.process_update(upd_ping)
    elapsed_ping = time.monotonic() - t1
    assert elapsed_ping < 0.2, \
        f"a completely unrelated update must not be blocked by the in-flight alumni broadcast, took {elapsed_ping}s"
    assert ("other", 2) in events, events
    print(f"3. A second, unrelated user's update is dispatched immediately ({elapsed_ping:.3f}s), unaffected by the in-flight broadcast")

    await asyncio.sleep(0.5)
    assert "notify_end" in events, events
    print("4. The alumni broadcast eventually completes in the background")

    bot._notify_coworking_alumni = real_notify_alumni
    bot.send_tracked_notification = real_send_tracked_notification
    print("\nALL COWORKING-DUR-NONBLOCKING TESTS PASSED")


asyncio.run(main())
