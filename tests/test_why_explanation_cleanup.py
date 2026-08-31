import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_why_explanation_cleanup.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


_next_mid = [7000]

class FakeMsg:
    def __init__(self, text=""):
        self.text = text
        self.message_id = _next_mid[0]
        _next_mid[0] += 1
        self.sent = []
    async def reply_text(self, text, **kw):
        m = FakeMsg(text)
        self.sent.append(m)
        return m


class FakeBot:
    def __init__(self):
        self.deleted = []
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
    async def send_message(self, *a, **kw): pass


class FakeQuery:
    def __init__(self, uid, msg, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = msg
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, msg=None, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, msg or FakeMsg(), data) if data else None
        self.message = msg


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (screenshot): tapping "❓ Зачем это?" on 💛 Внутренний
    # ребёнок shows the explanation as a new message. Answering the actual
    # question afterwards left that explanation sitting in the chat forever.
    # It must now be deleted the moment the field is answered (by text) or
    # skipped.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(bot=fbot)
    original_msg = FakeMsg("💛 Внутренний ребёнок...")

    why_upd = FakeUpdate(uid, original_msg, data="why_m_child")
    await bot.why_callback(why_upd, ctx)
    assert original_msg.sent, "why_callback must send the explanation as a new message"
    explanation_msg = original_msg.sent[-1]
    assert ctx.user_data.get("why_msg_m_child") == explanation_msg.message_id
    print("1. why_callback tracks the id of the explanation message it just sent")

    text_upd = FakeUpdate(uid, FakeMsg("Молодец, что стараешься"))
    await bot.got_child(text_upd, ctx)
    assert (uid, explanation_msg.message_id) in fbot.deleted, \
        "answering the question (m_child) must delete the tracked 'why' explanation immediately"
    assert "why_msg_m_child" not in ctx.user_data
    print("2. Answering the 💛 Внутренний ребёнок question deletes the 'why' explanation right away")

    # Same for skipping instead of answering.
    fbot2 = FakeBot()
    ctx2 = FakeCtx(bot=fbot2)
    original_msg2 = FakeMsg()
    why_upd2 = FakeUpdate(uid, original_msg2, data="why_m_child")
    await bot.why_callback(why_upd2, ctx2)
    explanation_msg2 = original_msg2.sent[-1]

    skip_upd = FakeUpdate(uid, original_msg2, data="skip_m_child")
    await bot.skip_m_child(skip_upd, ctx2)
    assert (uid, explanation_msg2.message_id) in fbot2.deleted, \
        "skipping the question must also delete the tracked 'why' explanation"
    print("3. Skipping the question also deletes the 'why' explanation")

    # Same mechanism for m_gratitude and e_praise (the other two fields
    # using skip_why_kb).
    for why_key, got_handler, field_msg_text in (
        ("m_gratitude", bot.got_gratitude, "Рад(а), что не сдался(лась)"),
        ("e_praise", bot.got_e_praise, "Молодец"),
    ):
        fbot3 = FakeBot()
        ctx3 = FakeCtx(bot=fbot3)
        orig = FakeMsg()
        why_upd3 = FakeUpdate(uid, orig, data=f"why_{why_key}")
        await bot.why_callback(why_upd3, ctx3)
        expl = orig.sent[-1]
        text_upd3 = FakeUpdate(uid, FakeMsg(field_msg_text))
        await got_handler(text_upd3, ctx3)
        assert (uid, expl.message_id) in fbot3.deleted, why_key
    print("4. Same cleanup works for m_gratitude and e_praise (the other two skip_why_kb fields)")

    # send_skill_beacon's "❓ Зачем это?" (why_beacon_technique) uses the
    # same mechanism, cleaned up on "✅ Сделал(а)" (beacon_technique_done).
    fbot4 = FakeBot()
    ctx4 = FakeCtx(bot=fbot4)
    beacon_msg = FakeMsg()
    why_upd4 = FakeUpdate(uid, beacon_msg, data="why_beacon_technique")
    await bot.why_callback(why_upd4, ctx4)
    expl4 = beacon_msg.sent[-1]
    done_upd = FakeUpdate(uid, beacon_msg, data="beacon_technique_done")
    await bot.beacon_technique_done(done_upd, ctx4)
    assert (uid, expl4.message_id) in fbot4.deleted
    print("5. beacon_technique_done also cleans up its 'why' explanation")

    # Sanity: if "❓ Зачем это?" was never tapped, answering/skipping must
    # not attempt any deletion (no-op, not an error).
    fbot5 = FakeBot()
    ctx5 = FakeCtx(bot=fbot5)
    text_upd5 = FakeUpdate(uid, FakeMsg("Спокоен(йна)"))
    await bot.got_child(text_upd5, ctx5)
    assert fbot5.deleted == []
    print("6. No 'why' tap -> no deletion attempted, no crash")

    print("\nALL WHY-EXPLANATION-CLEANUP TESTS PASSED")


asyncio.run(main())
