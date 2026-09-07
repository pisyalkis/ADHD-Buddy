import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_crosslinks.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [91000]

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return FakeMsg(self.chat_id)

    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message

    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message)
        self.message = None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return m

    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self, bot_=None):
        self.user_data = {}
        self.bot = bot_ or FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (обсуждение с пользователем 2026-09-07): коворкинг — это
    # по сути "фокус вместе", а бодидаблинг реально помогает именно в
    # состояниях "мало энергии"/"перегруз". Добавлены прямые кросслинки на
    # 🧘 Коворкинг из 🍅 Фокус-режима (перед стартом таймера) и из веток
    # дневного чекина mid_energy/mid_scary (последняя обслуживает и
    # "overload" через PROBLEM_TO_MID).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    today = datetime.now(TBILISI).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Сделать план"}, for_date=today)

    # 1. go_focus's pre-start screen (no timer running) offers go_coworking.
    ctx1 = FakeCtx()
    upd1 = FakeUpdate(uid, data=None, message=FakeMsg(uid))
    upd1.callback_query = FakeQuery(uid, "go_focus", FakeMsg(uid))
    await bot.go_focus(upd1, ctx1)
    _, _, kb1 = ctx1.bot.sent[-1]
    assert "go_coworking" in kb_callbacks(kb1), kb_callbacks(kb1)
    print("1. The focus-mode pre-start screen offers a 🧘 Коворкинг cross-link")

    # 2. The "timer already running" STATUS screen must NOT offer it --
    #    starting something new mid-round doesn't make sense there.
    bot.update_user(
        uid, focus_active=1,
        focus_end_time=(datetime.now(bot.pytz.utc) + timedelta(minutes=20)).isoformat(),
    )
    ctx2 = FakeCtx()
    upd2 = FakeUpdate(uid, "go_focus", FakeMsg(uid))
    await bot.go_focus(upd2, ctx2)
    _, running_text, kb2 = ctx2.bot.sent[-1]
    assert "уже идёт" in running_text, running_text
    assert "go_coworking" not in kb_callbacks(kb2), kb_callbacks(kb2)
    print("2. The 'timer already running' status screen does NOT offer the coworking cross-link")
    bot.update_user(uid, focus_active=0, focus_end_time="")

    # 3. mid_energy offers the coworking cross-link.
    upd3 = FakeUpdate(uid, "mid_energy", FakeMsg(uid))
    await bot.midday_callback(upd3, FakeCtx())
    _, kb3 = upd3.callback_query.message.sent[-1]
    assert "go_coworking" in kb_callbacks(kb3), kb_callbacks(kb3)
    print("3. mid_energy ('🔋 Мало энергии') offers the 🧘 Коворкинг cross-link")

    # 4. mid_scary offers the coworking cross-link (also serves "overload"
    #    via PROBLEM_TO_MID's "overload": ["mid_scary"] mapping).
    upd4 = FakeUpdate(uid, "mid_scary", FakeMsg(uid))
    await bot.midday_callback(upd4, FakeCtx())
    _, kb4 = upd4.callback_query.message.sent[-1]
    assert "go_coworking" in kb_callbacks(kb4), kb_callbacks(kb4)
    print("4. mid_scary ('😰 Задача подавляет', also serves 'overload') offers the cross-link")

    # 5. A DIFFERENT mid_* branch (e.g. mid_resist) does NOT get this
    #    cross-link -- it's deliberately scoped to energy/scary, not every
    #    branch via back_kb_with_skill.
    upd5 = FakeUpdate(uid, "mid_resist", FakeMsg(uid))
    await bot.midday_callback(upd5, FakeCtx())
    _, kb5 = upd5.callback_query.message.sent[-1]
    assert "go_coworking" not in kb_callbacks(kb5), kb_callbacks(kb5)
    print("5. An unrelated branch (mid_resist) does not get the coworking cross-link (scoped, not global)")

    print("\nALL COWORKING-CROSSLINKS TESTS PASSED")


asyncio.run(main())
