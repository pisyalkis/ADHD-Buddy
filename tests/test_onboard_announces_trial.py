import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_onboard_announces_trial.db")
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
    # ══════════════════════════════════════════════════════════════════════
    # По просьбе (Фаза 1): в онбординге нигде не звучали ни длина пробного
    # периода, ни цена подписки -- человек узнавал об этом только упершись
    # в пейволл через TRIAL_DAYS дней. Теперь это должно проговариваться в
    # обеих ветках последнего шага онбординга (включил/выключил уведомления).
    # ══════════════════════════════════════════════════════════════════════
    uid_a = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Тест', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid_a, timezone="Asia/Tbilisi")

    upd = FakeUpdate(uid_a)
    ctx = FakeCtx()
    await bot.onboard_notif_on(upd, ctx)
    texts = [t for t, kw in upd.callback_query.message.sent]
    assert any(str(bot.TRIAL_DAYS) in t and str(bot.STARS_PRICE_MONTHLY) in t for t in texts), \
        f"onboard_notif_on must announce trial length and price, got: {texts}"
    print("1. onboard_notif_on (notifications kept on) announces trial length and price")

    uid_b = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест2', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid_b, timezone="Asia/Tbilisi")

    upd2 = FakeUpdate(uid_b)
    ctx2 = FakeCtx()
    await bot.onboard_notif_skip(upd2, ctx2)
    texts2 = [t for t, kw in upd2.callback_query.message.sent]
    assert any(str(bot.TRIAL_DAYS) in t and str(bot.STARS_PRICE_MONTHLY) in t for t in texts2), \
        f"onboard_notif_skip must also announce trial length and price, got: {texts2}"
    print("2. onboard_notif_skip (notifications turned off) also announces trial length and price")

    print("\nALL ONBOARD-ANNOUNCES-TRIAL TESTS PASSED")


asyncio.run(main())
