import os, sys, asyncio, time, sqlite3, types

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_async_anthropic_calls.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
# ANTHROPIC_KEY must be truthy for these functions to actually attempt the
# call at all (they short-circuit to a no-op otherwise).
os.environ["ANTHROPIC_KEY"] = "fake-test-key"
import bot
bot.init_db()

BLOCK_SECONDS = 0.3


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeResp:
    def __init__(self, text):
        self.content = [FakeContent(text)]


class SlowSyncClientMessages:
    """Simulates the real anthropic SDK's synchronous client.messages.create
    -- a genuinely blocking call (time.sleep, not asyncio.sleep) that would
    freeze the whole event loop if not offloaded to a thread."""
    def create(self, **kwargs):
        time.sleep(BLOCK_SECONDS)
        return FakeResp('{"remind_at": "2026-09-03T10:00:00", "text": "test", "recur": ""}')


class SlowSyncClient:
    def __init__(self, api_key=None):
        self.messages = SlowSyncClientMessages()


async def main():
    # Patch the `anthropic` module so `from anthropic import Anthropic`
    # inside bot.py's functions resolves to our slow synchronous fake.
    fake_anthropic_module = types.ModuleType("anthropic")
    fake_anthropic_module.Anthropic = SlowSyncClient
    sys.modules["anthropic"] = fake_anthropic_module

    # ══════════════════════════════════════════════════════════════════════
    # Bug: client.messages.create(...) was called directly (synchronously)
    # inside an async def function -- a genuinely blocking call freezes the
    # ENTIRE event loop for its duration, so no other coroutine (including
    # the once-a-minute check_notifications tick) can make progress while
    # it runs. Wrapping it in asyncio.to_thread offloads the blocking work
    # to a worker thread, keeping the loop free.
    # ══════════════════════════════════════════════════════════════════════
    ticks = []

    async def ticker():
        for _ in range(20):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    ticker_task = asyncio.create_task(ticker())
    await bot.parse_reminder_request("напомни завтра в 10 позвонить", bot.datetime.now())
    ticker_task.cancel()
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass

    # If the blocking call had frozen the loop for BLOCK_SECONDS, the
    # ticker (interval 0.02s) would show one big gap >= BLOCK_SECONDS
    # instead of many small ~0.02s gaps.
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert gaps, "the ticker must have gotten at least one tick in while the AI call was in flight"
    max_gap = max(gaps)
    assert max_gap < BLOCK_SECONDS * 0.7, \
        (f"the event loop was blocked for a single gap of {max_gap:.3f}s (>= the simulated "
         f"{BLOCK_SECONDS}s Anthropic call) -- the call must run in a worker thread, not on the loop itself")
    print(f"1. parse_reminder_request does not block the event loop (max tick gap {max_gap:.3f}s < {BLOCK_SECONDS}s)")

    # Sanity: the function must still return a correctly parsed result.
    result = await bot.parse_reminder_request("напомни завтра в 10 позвонить", bot.datetime(2026, 9, 2, 9, 0, 0))
    assert result is not None
    assert result[0] == "2026-09-03T10:00:00", result
    print("2. parse_reminder_request still returns the correct parsed result")

    del sys.modules["anthropic"]
    print("\nALL ASYNC-ANTHROPIC-CALLS TESTS PASSED")


asyncio.run(main())
