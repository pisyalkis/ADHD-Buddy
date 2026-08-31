import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_onboarding_option_b.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot

bot.init_db()


class FakeBot:
    def __init__(self):
        self.deleted = []

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


_next_id = [100]


class FakeMessage:
    def __init__(self, chat_id=1, bot=None):
        self.chat_id = chat_id
        self.message_id = _next_id[0]
        _next_id[0] += 1
        self._bot = bot
        self.text = ""

    async def reply_text(self, text, **kw):
        m = FakeMessage(self.chat_id, self._bot)
        m.text = text
        return m


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeChat:
    def __init__(self, cid):
        self.id = cid


class FakeQuery:
    def __init__(self, message, data, uid):
        self.message = message
        self.data = data
        self.from_user = FakeUser(uid)

    async def answer(self):
        pass


class FakeUpdate:
    def __init__(self, uid, message=None, callback_query=None):
        self.message = message
        self.callback_query = callback_query
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(1)


class FakeCtx:
    def __init__(self, fbot):
        self.user_data = {}
        self.bot = fbot


async def main():
    uid = 777
    fbot = FakeBot()
    ctx = FakeCtx(fbot)

    # ══════════════════════════════════════════════════════════════════════
    # Step 1: /start sends the welcome message (name prompt). Nothing to
    # delete yet -- it's the very first message of the flow.
    # ══════════════════════════════════════════════════════════════════════
    upd_start = FakeUpdate(uid, message=FakeMessage(chat_id=1, bot=fbot))
    await bot.start(upd_start, ctx)
    assert fbot.deleted == [], fbot.deleted
    step1_ids = list(ctx.user_data["onboard_step_msg_ids"])
    assert len(step1_ids) == 1, step1_ids
    print("1. /start tracks the welcome message, deletes nothing (first step)")

    # ══════════════════════════════════════════════════════════════════════
    # Step 2: got_name (user types their name). Must delete step 1's message
    # before sending/tracking its own.
    # ══════════════════════════════════════════════════════════════════════
    incoming_name = FakeMessage(chat_id=1, bot=fbot)
    incoming_name.text = "Артем"
    upd_name = FakeUpdate(uid, message=incoming_name)
    await bot.got_name(upd_name, ctx)
    assert fbot.deleted == [(1, step1_ids[0])], fbot.deleted
    step2_ids = list(ctx.user_data["onboard_step_msg_ids"])
    assert len(step2_ids) == 1 and step2_ids[0] not in fbot.deleted[0], step2_ids
    print("2. got_name deletes step 1's message and tracks its own new one")

    # ══════════════════════════════════════════════════════════════════════
    # Step 3: got_gender sends TWO messages in a row (greeting + question).
    # Must delete step 2's message first, and BOTH new messages must be
    # tracked together -- neither deleted from the other within the step.
    # ══════════════════════════════════════════════════════════════════════
    q_gender = FakeQuery(FakeMessage(chat_id=1, bot=fbot), "gender_M", uid)
    upd_gender = FakeUpdate(uid, callback_query=q_gender)
    await bot.got_gender(upd_gender, ctx)
    assert fbot.deleted == [(1, step1_ids[0]), (1, step2_ids[0])], fbot.deleted
    step3_ids = list(ctx.user_data["onboard_step_msg_ids"])
    assert len(step3_ids) == 2, step3_ids
    assert all((1, mid) not in fbot.deleted for mid in step3_ids), \
        "the two messages within a single step must not delete each other"
    print("3. got_gender deletes step 2's message; its own 2 messages (greeting+question) "
          "accumulate together, undeleted")

    # ══════════════════════════════════════════════════════════════════════
    # Step 4: onboard_trained_yes. Must delete BOTH of step 3's messages
    # together when the next step begins (proving multi-message steps are
    # cleared as a unit, not just their last message).
    # ══════════════════════════════════════════════════════════════════════
    q_trained = FakeQuery(FakeMessage(chat_id=1, bot=fbot), "ob_trained_yes", uid)
    upd_trained = FakeUpdate(uid, callback_query=q_trained)
    await bot.onboard_trained_yes(upd_trained, ctx)
    assert (1, step3_ids[0]) in fbot.deleted and (1, step3_ids[1]) in fbot.deleted, fbot.deleted
    step4_ids = ctx.user_data.get("onboard_step_msg_ids", [])
    assert all((1, mid) not in fbot.deleted for mid in step4_ids)
    print("4. onboard_trained_yes deletes BOTH of step 3's messages together, tracks its own new ones")

    print("\nALL ONBOARDING-OPTION-B TESTS PASSED")


asyncio.run(main())
