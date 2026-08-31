import os, sys, asyncio, sqlite3, types
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_multi_pool_add.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-tests"

_fake_reply = {"text": ""}

class FakeContent:
    def __init__(self, text): self.text = text

class FakeResp:
    def __init__(self, text): self.content = [FakeContent(text)]

class FakeMessages:
    def create(self, **kw):
        return FakeResp(_fake_reply["text"])

class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()

fake_module = types.ModuleType("anthropic")
fake_module.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake_module

def set_fake_reply(text):
    _fake_reply["text"] = text

import bot
bot.init_db()


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.callback_query = None
        self.message = FakeMsg()
        self.message.text = text


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = None


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    now_dt = datetime.now(bot.get_user_tz(bot.get_user(uid)))

    # ══════════════════════════════════════════════════════════════════════
    # add_pool_and_reply: single string still works exactly as before
    # ══════════════════════════════════════════════════════════════════════
    msg1 = FakeMsg()
    await bot.add_pool_and_reply(msg1, uid, "Купить хлеб")
    assert [t["text"] for t in bot.get_pool_tasks(uid)] == ["Купить хлеб"]
    assert "Добавил в список дел." in msg1.last_text and "Добавил 1" not in msg1.last_text
    print("1. add_pool_and_reply(single string) still works exactly as before")

    for t in bot.get_pool_tasks(uid):
        bot.delete_pool_task(uid, t["id"])

    # ══════════════════════════════════════════════════════════════════════
    # add_pool_and_reply: a list of items adds each as its own pool entry
    # ══════════════════════════════════════════════════════════════════════
    items = [
        "план по боту",
        "Разобраться с оплатой",
        "Скачать впн",
        "дать наушники Никите",
        "Медитация 10 мин",
        "разобраться с работой автоматизированных программ на фоне",
    ]
    msg2 = FakeMsg()
    await bot.add_pool_and_reply(msg2, uid, items)
    pool_texts = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert pool_texts == items, pool_texts
    assert "Добавил 6 дел в список." in msg2.last_text, msg2.last_text
    print("2. add_pool_and_reply(list) adds each item as its own separate pool entry")

    for t in bot.get_pool_tasks(uid):
        bot.delete_pool_task(uid, t["id"])

    # ── Blank/whitespace-only lines in the list are filtered out ───────────
    msg3 = FakeMsg()
    await bot.add_pool_and_reply(msg3, uid, ["Дело раз", "", "   ", "Дело два"])
    assert [t["text"] for t in bot.get_pool_tasks(uid)] == ["Дело раз", "Дело два"]
    print("3. Blank lines in a multi-item list are filtered out, not added as empty tasks")

    for t in bot.get_pool_tasks(uid):
        bot.delete_pool_task(uid, t["id"])

    # ══════════════════════════════════════════════════════════════════════
    # Full handle_text flow: the explicit "✏️ Добавить дело" screen splits
    # a pasted multi-line message into separate items (no AI call needed).
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["awaiting_pool_add"] = True
    pasted = "план по боту\nРазобраться с оплатой\nСкачать впн"
    upd = FakeUpdate(uid, text=pasted)
    await bot.handle_text(upd, ctx)
    assert ctx.user_data.get("awaiting_pool_add") is False
    pool_texts2 = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert pool_texts2 == ["план по боту", "Разобраться с оплатой", "Скачать впн"], pool_texts2
    print("4. Pasting a multi-line message on the explicit 'Добавить дело' screen splits into separate items")

    for t in bot.get_pool_tasks(uid):
        bot.delete_pool_task(uid, t["id"])

    # ══════════════════════════════════════════════════════════════════════
    # classify_free_text: model returns multiple items -> all get added,
    # exactly Artem's reported scenario ("добавь это в список дел: <list>")
    # ══════════════════════════════════════════════════════════════════════
    set_fake_reply(
        '{"intent": "add_pool", "items": ["план по боту", "Разобраться с оплатой", '
        '"Скачать впн", "дать наушники Никите", "Медитация 10 мин", '
        '"разобраться с работой автоматизированных программ на фоне"]}'
    )
    ctx2 = FakeCtx()
    full_message = (
        "добавь это в список дел:\n\n"
        "план по боту\n"
        "Разобраться с оплатой\n"
        "Скачать впн\n"
        "дать наушники Никите\n"
        "Медитация 10 мин\n"
        "разобраться с работой автоматизированных программ на фоне"
    )
    upd2 = FakeUpdate(uid, text=full_message)
    await bot.handle_text(upd2, ctx2)
    pool_texts3 = [t["text"] for t in bot.get_pool_tasks(uid)]
    assert pool_texts3 == items, pool_texts3
    assert "Добавил 6 дел в список." in upd2.message.last_text, upd2.message.last_text
    print("5. Free-text router splits a multi-item 'добавь в список дел' message into 6 separate items")

    for t in bot.get_pool_tasks(uid):
        bot.delete_pool_task(uid, t["id"])

    # ── Backward compat: model still returns the old singular "text" field ─
    set_fake_reply('{"intent": "add_pool", "text": "купить молоко"}')
    routed = await bot.classify_free_text("добавь в список дел купить молоко", now_dt)
    assert routed.get("intent") == "add_pool" and routed.get("items") == ["купить молоко"], routed
    print("6. classify_free_text still accepts the old singular 'text' field, wraps it into items")

    print("\nALL MULTI-POOL-ADD TESTS PASSED")


asyncio.run(main())
