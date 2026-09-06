import os, sys, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_clear_awaiting_split.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeConvHandler:
    def __init__(self):
        self._conversations = {}


def main():
    # ══════════════════════════════════════════════════════════════════════
    # Architectural fix (IDEAS.md 2026-08-29): clear_awaiting_flags(ctx,
    # update=None) used to be ONE function whose behavior silently forked
    # on an optional argument -- already the root cause of at least 3 bugs
    # fixed earlier this session (buddy_ping/beacon_technique_done/
    # task_done_callback wrongly called the full form). Split into two
    # explicitly-named, non-optional-argument functions so a future author
    # can't pick the wrong one by accident.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", research_awaiting="3_open:test")

    # 1. clear_awaiting_flags no longer accepts an update argument at all --
    #    calling it the old way must raise TypeError, not silently work.
    ctx = FakeCtx()
    ctx.user_data["awaiting_feedback"] = True
    try:
        bot.clear_awaiting_flags(ctx, FakeUpdate(uid))
        raised = False
    except TypeError:
        raised = True
    assert raised, "clear_awaiting_flags must no longer accept a second (update) argument"
    print("1. clear_awaiting_flags(ctx, update) raises TypeError -- the old ambiguous signature is gone")

    # 2. clear_awaiting_flags(ctx) resets flags but must NOT touch
    #    research_awaiting or any active conversation.
    fake_evening_conv = FakeConvHandler()
    conv_key = (uid, uid)
    fake_evening_conv._conversations[conv_key] = bot.E_ACH
    bot._evening_conv = fake_evening_conv
    try:
        bot.clear_awaiting_flags(ctx)
        assert ctx.user_data.get("awaiting_feedback") is False
        assert bot.get_user(uid).get("research_awaiting") == "3_open:test", \
            "clear_awaiting_flags (soft form) must not touch research_awaiting"
        assert conv_key in fake_evening_conv._conversations, \
            "clear_awaiting_flags (soft form) must not cancel an active ritual conversation"
        print("2. clear_awaiting_flags(ctx) only resets ctx.user_data flags -- research_awaiting and the active ritual are untouched")

        # 3. clear_awaiting_and_cancel_ritual(ctx, update) does everything:
        #    flags + research_awaiting + cancels the active conversation.
        ctx.user_data["awaiting_buddy"] = True
        bot.clear_awaiting_and_cancel_ritual(ctx, FakeUpdate(uid))
        assert ctx.user_data.get("awaiting_buddy") is False
        assert str(bot.get_user(uid).get("research_awaiting") or "0") == "0", \
            "clear_awaiting_and_cancel_ritual must reset research_awaiting"
        assert conv_key not in fake_evening_conv._conversations, \
            "clear_awaiting_and_cancel_ritual must cancel the active ritual conversation"
        print("3. clear_awaiting_and_cancel_ritual(ctx, update) resets flags AND research_awaiting AND cancels the active ritual")
    finally:
        bot._evening_conv = None

    # 4. clear_awaiting_and_cancel_ritual requires update -- no default,
    #    can't be called "softly" by accident either.
    try:
        bot.clear_awaiting_and_cancel_ritual(ctx)
        raised2 = False
    except TypeError:
        raised2 = True
    assert raised2, "clear_awaiting_and_cancel_ritual must require update -- no optional-argument footgun in either direction"
    print("4. clear_awaiting_and_cancel_ritual(ctx) alone raises TypeError -- update is mandatory, not optional")

    # 5. No leftover call sites anywhere in bot.py using the old combined
    #    signature -- guards against a future edit reintroducing it.
    import inspect
    src = inspect.getsource(bot)
    assert "clear_awaiting_flags(ctx, update)" not in src, \
        "no call site should use the old two-argument clear_awaiting_flags(ctx, update) form anymore"
    print("5. No call site in bot.py still uses the old clear_awaiting_flags(ctx, update) form")

    print("\nALL CLEAR-AWAITING-SPLIT TESTS PASSED")


main()
