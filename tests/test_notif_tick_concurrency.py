import os, sys, asyncio, sqlite3, time

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_notif_tick_concurrency.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        class M:
            message_id = 1
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, f"U{uid}"))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", notif_enabled=0)


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real risk (IDEAS.md 2026-08-28): check_notifications used to walk all
    # users strictly sequentially -- one slow/stuck await for a single user
    # (a Telegram network timeout) delayed notifications for everyone else
    # queued behind them in the same once-a-minute tick, risking missing the
    # 60s tick entirely as the user base grows. Verify the tick now actually
    # runs users concurrently (bounded by NOTIF_TICK_CONCURRENCY), not one
    # slow user blocking the rest.
    # ══════════════════════════════════════════════════════════════════════
    N = 20
    for uid in range(1, N + 1):
        make_user(uid)

    delay = 0.3
    call_times = []

    async def slow_process(app, user):
        call_times.append(time.monotonic())
        await asyncio.sleep(delay)

    orig = bot._process_user_notifications
    bot._process_user_notifications = slow_process
    try:
        app = FakeApp()
        started = time.monotonic()
        await bot.check_notifications(app)
        elapsed = time.monotonic() - started
    finally:
        bot._process_user_notifications = orig

    assert len(call_times) == N, f"expected all {N} users processed, got {len(call_times)}"
    # Sequential would take N * delay (~6s for 20 users @ 0.3s each). With
    # NOTIF_TICK_CONCURRENCY=10 concurrent workers, it should take roughly
    # ceil(N / NOTIF_TICK_CONCURRENCY) * delay (~0.6s) -- assert well under
    # half of the fully-sequential time as concurrency proof.
    sequential_time = N * delay
    assert elapsed < sequential_time / 2, (
        f"tick took {elapsed:.2f}s, expected well under half of the fully-sequential "
        f"{sequential_time:.2f}s -- users are not being processed concurrently"
    )
    print(f"1. {N} users processed concurrently in {elapsed:.2f}s (sequential would take ~{sequential_time:.2f}s)")

    # Sanity: NOTIF_TICK_CONCURRENCY actually bounds it -- no more than that
    # many calls should have started within one delay-window of each other
    # at the very start (a crude but real check that it's not fully
    # unbounded asyncio.gather with no semaphore at all).
    first_batch = [t for t in call_times if t - call_times[0] < 0.05]
    assert len(first_batch) <= bot.NOTIF_TICK_CONCURRENCY, (
        f"expected at most NOTIF_TICK_CONCURRENCY={bot.NOTIF_TICK_CONCURRENCY} concurrent starts, "
        f"got {len(first_batch)} nearly-simultaneous starts"
    )
    print(f"2. concurrency is bounded by NOTIF_TICK_CONCURRENCY={bot.NOTIF_TICK_CONCURRENCY}, not unbounded")

    print("\nALL NOTIF-TICK-CONCURRENCY TESTS PASSED")


asyncio.run(main())
