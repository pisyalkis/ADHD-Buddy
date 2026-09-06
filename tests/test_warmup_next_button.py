import os, sys, asyncio, sqlite3, time

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_warmup_next_button.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 500
        self.texts = []

    async def edit_text(self, text, **kw):
        self.texts.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, message):
        self.from_user = FakeUser(uid); self.message = message
    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, message):
        self.callback_query = FakeQuery(uid, message)


class FakeBot:
    def __init__(self):
        self.edited = []

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))


class FakeCtx:
    def __init__(self, bot_):
        self.user_data = {}
        self.bot = bot_


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-02): warmup_go cycles 6 exercises at a
    # fixed 20 seconds each with no way to skip/advance a single exercise --
    # the only place in the whole ritual without a "Дальше" button. The
    # whole-bot freeze this used to cause is already fixed (block=False);
    # only the missing button itself remained.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    fake_bot = FakeBot()
    ctx = FakeCtx(fake_bot)
    msg = FakeMsg(uid)
    upd = FakeUpdate(uid, msg)

    # 1. Tapping "➡️ Дальше" on every step drives the whole warmup to
    #    completion almost instantly, instead of waiting the full ~120s
    #    (6 exercises x 20s).
    task = asyncio.create_task(bot.warmup_go(upd, ctx))
    started = time.monotonic()
    prev_event = None
    for _ in range(len(bot.WARMUP)):
        # Wait until warmup_go has rendered this step and stored a FRESH
        # event for it (not the previous step's already-resolved one).
        for _ in range(1000):
            await asyncio.sleep(0)
            cur = ctx.user_data.get("warmup_skip_event")
            if cur is not None and cur is not prev_event:
                break
        prev_event = ctx.user_data.get("warmup_skip_event")
        next_upd = FakeUpdate(uid, msg)
        await bot.warmup_next(next_upd, ctx)
    await asyncio.wait_for(task, timeout=5)
    elapsed = time.monotonic() - started
    assert elapsed < 2, f"tapping through every step should finish in well under 2s, took {elapsed:.2f}s"
    print(f"1. Tapping '➡️ Дальше' through all {len(bot.WARMUP)} exercises finishes almost instantly ({elapsed:.3f}s), not ~120s")

    # 2. Every per-exercise render includes the "➡️ Дальше" button.
    step_texts = [t for t, kb in fake_bot.edited if "секунд" in t]
    assert len(step_texts) == len(bot.WARMUP), (step_texts, fake_bot.edited)
    for t, kb in fake_bot.edited:
        if "секунд" in t:
            cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
            assert "warmup_next" in cbs, f"each exercise step must offer the '➡️ Дальше' button, got {cbs}"
    print("2. Every exercise step's message offers the '➡️ Дальше' button")

    # 3. The ritual still reaches its normal completion message.
    assert any("проснулось" in t for t, _ in fake_bot.edited), fake_bot.edited
    print("3. The warmup still reaches its normal 'Тело проснулось!' completion message")

    # 4. Tapping "➡️ Дальше" with no warmup in flight (no stored event) is a
    #    harmless no-op -- does not raise.
    ctx2 = FakeCtx(FakeBot())
    msg2 = FakeMsg(2)
    upd2 = FakeUpdate(2, msg2)
    await bot.warmup_next(upd2, ctx2)
    print("4. Tapping '➡️ Дальше' with no active warmup is a safe no-op")

    print("\nALL WARMUP-NEXT-BUTTON TESTS PASSED")


asyncio.run(main())
