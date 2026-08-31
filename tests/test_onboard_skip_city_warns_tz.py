import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_onboard_skip_city_warns_tz.db")
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
        self.message_id = 1
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))
        return self
    async def delete(self):
        pass


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid)
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)


class FakeBot:
    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Тест', 'M')")
    conn.commit(); conn.close()

    # ══════════════════════════════════════════════════════════════════════
    # Реальная находка (Фаза 1, аудит воронки для незнакомых пользователей):
    # кнопка "Пропустить" на шаге города молча оставляла таймзону бота-
    # владельца (USER_TIMEZONE) без единого слова объяснения -- в отличие от
    # соседней ветки (неудачный геокодинг города), где такое предупреждение
    # уже есть. Человек не из этого пояса узнавал о проблеме только когда
    # уведомление приходило посреди ночи.
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate(uid)
    ctx = FakeCtx()
    await bot.onboard_done(upd, ctx)
    sent_texts = [t for t, kw in upd.callback_query.message.sent]
    assert any(bot.USER_TIMEZONE in t and "Без города" in t for t in sent_texts), \
        f"onboard_done (skip) must warn about the default timezone, got: {sent_texts}"
    assert any("Последний шаг" in t for t in sent_texts), \
        "onboard_done must still proceed to the notifications step"
    print("1. onboard_done (skip city) now warns about the default timezone before notifications step")

    print("\nALL ONBOARD-SKIP-CITY-WARNS-TZ TESTS PASSED")


asyncio.run(main())
