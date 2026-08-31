import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_day_purpose_copy.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    async def delete_message(self, chat_id, message_id):
        pass


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.chat_id = 1
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})()


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


ESSENCE_PHRASES = {
    "morning": ["настройка на день", "настроиться на день"],
    "day": ["активная фаза", "делаем задачи и практикуем навыки", "делаешь задачи и практикуешь навыки"],
    "evening": ["закрываем день", "закрыть день"],
}

def has_any(text, phrases):
    low = text.lower()
    return any(p.lower() in low for p in phrases)


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (Artem, direct): the explanation of утро/день/вечер must
    # lead with PURPOSE (настройка / активная фаза действий / закрытие и
    # итоги), not a feature list of specific practices -- "всем по хуй
    # какие практики утром или днём, важна суть".
    # ══════════════════════════════════════════════════════════════════════

    # 1. Onboarding step 2 (generic branch, no struggles selected).
    ctx = FakeCtx()
    upd = FakeUpdate(uid)
    await bot.send_explain_step(upd, ctx, step=2, then="cta")
    text1 = upd.callback_query.message.last_text
    assert has_any(text1, ESSENCE_PHRASES["morning"]), text1
    assert has_any(text1, ESSENCE_PHRASES["day"]), text1
    assert has_any(text1, ESSENCE_PHRASES["evening"]), text1
    print("1. Onboarding step-2 explanation leads with purpose (настройка/активная фаза/закрываем день)")

    # 2. "О боте" screen -- day-structure page specifically (now split
    #    across pages, same principle as 📖 О СДВГ).
    msg2 = FakeMsg()
    await bot.send_about_section(msg2, "day_structure", "M")
    text2 = msg2.last_text
    assert has_any(text2, ESSENCE_PHRASES["morning"]), text2
    assert has_any(text2, ESSENCE_PHRASES["day"]), text2
    assert has_any(text2, ESSENCE_PHRASES["evening"]), text2
    print("2. 'О боте' screen leads with the same purpose-first framing")

    # 3. Full guide's "Как помогает этот бот" section (also part of the
    #    curated onboarding guide for newcomers).
    msg3 = FakeMsg()
    await bot.send_guide_section(msg3, "bot")
    text3 = msg3.last_text
    assert has_any(text3, ESSENCE_PHRASES["morning"]), text3
    assert has_any(text3, ESSENCE_PHRASES["day"]), text3
    assert has_any(text3, ESSENCE_PHRASES["evening"]), text3
    print("3. Guide section 'Как помогает этот бот' also leads with purpose-first framing")

    print("\nALL DAY-PURPOSE-COPY TESTS PASSED")


asyncio.run(main())
