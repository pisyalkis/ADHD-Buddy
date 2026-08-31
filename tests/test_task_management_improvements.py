import os, sys, asyncio, sqlite3, types
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_management_improvements.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = "fake-key-for-tests"

_fake_reply = {"text": '{"intent": "other"}'}

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


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    def __init__(self):
        self.edited = []
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append((chat_id, message_id, text))
    async def pin_chat_message(self, **kw): pass
    async def unpin_chat_message(self, **kw): pass


class FakeMsg:
    def __init__(self, message_id=1000):
        self.sent = []
        self.message_id = message_id
    async def reply_text(self, text, **kw):
        m = FakeMsg(message_id=self.message_id + 1)
        m.sent = self.sent
        self.sent.append((text, kw.get("reply_markup")))
        return m
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data="", text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data) if text is None else None
        self.message = None
        if text is not None:
            self.message = FakeMsg()
            self.message.text = text


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot or FakeBot()


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))
    today = datetime.now(tz).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # 1) "🗑 Убрать" on the task-walk screen -- real feedback: could only
    # overwrite or mark done, never clear a slot entirely.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {"focus": "Задача A", "b1": "Задача B1"}, for_date=today)
    bot.add_pool_task(uid, "Задача B1")
    pool_item = bot.get_pool_tasks(uid)[0]
    morning_link = bot.get_diary(uid, "morning", today)
    morning_link["_pool_link_b1"] = pool_item["id"]
    bot.save_diary(uid, "morning", morning_link, for_date=today)
    bot.save_diary(uid, "tasks_done", {"done": ["b1"]}, for_date=today)

    upd = FakeUpdate(uid, data="walk_clear_b1")
    ctx = FakeCtx()
    await bot.walk_clear_callback(upd, ctx)
    morning_after = bot.get_diary(uid, "morning", today)
    assert morning_after.get("b1", "") == "", morning_after
    assert "_pool_link_b1" not in morning_after, morning_after
    done_after = set(bot.get_diary(uid, "tasks_done", today).get("done", []))
    assert "b1" not in done_after, done_after
    print("1a. walk_clear_callback blanks the task slot, drops the pool link, and clears its done-mark")

    # Sanity: it does NOT delete the pool entry itself -- only the link.
    assert any(t["id"] == pool_item["id"] for t in bot.get_pool_tasks(uid))
    print("1b. walk_clear_callback leaves the underlying pool entry untouched")

    # ══════════════════════════════════════════════════════════════════════
    # 2) Pinned message: strikethrough completed tasks, but never grows
    # with tasks added after the pin (real feedback: keep the pinned list
    # in its original form, just cross out what's done).
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone=tz_name)
    tz2 = bot.get_user_tz(bot.get_user(uid2))
    today2 = datetime.now(tz2).date().isoformat()

    ctx2 = FakeCtx()
    ctx2.user_data.update({"m_focus": "", "m_b1": "", "m_b2": "", "m_writing": "", "m_gratitude": "", "m_child": ""})
    # finish_morning reads task fields via _merged_task_fields(ctx, existing)
    # which only reads from the DB now, so seed today's morning directly.
    bot.save_diary(uid2, "morning", {"focus": "Написать отчёт", "b1": "Позвонить маме"}, for_date=today2)
    msg2 = FakeMsg()
    fake_bot2 = FakeBot()
    ctx2.bot = fake_bot2
    await bot.finish_morning(msg2, uid2, ctx2)
    user2 = bot.get_user(uid2)
    assert user2.get("pinned_msg_id"), "finish_morning must pin when real tasks exist"
    pinned_keys2 = set(k for k in (user2.get("pinned_task_keys") or "").split(",") if k)
    assert pinned_keys2 == {"focus", "b1"}, pinned_keys2
    print("2a. finish_morning stores a snapshot of exactly which task keys were pinned")

    # Mark "focus" done via the shared task_done_callback -- pinned message
    # must be edited with a struck-through "A" line, "B1" untouched.
    upd_done = FakeUpdate(uid2, data="task_done_focus")
    ctx_done = FakeCtx(bot=fake_bot2)
    await bot.task_done_callback(upd_done, ctx_done)
    assert fake_bot2.edited, "task_done_callback must refresh the pinned message"
    last_pin_text = fake_bot2.edited[-1][2]
    a_line = next(l for l in last_pin_text.split("\n") if l.startswith("A:"))
    b1_line = next(l for l in last_pin_text.split("\n") if l.startswith("B1:"))
    assert "̶" in a_line, a_line
    assert "̶" not in b1_line, b1_line
    print("2b. task_done_callback re-renders the pinned message with a struck-through completed task, leaving the rest plain")

    # Add a NEW task (C1) after the pin -- it must NOT appear in the
    # pinned message, only in the regular tasks screen.
    bot.save_diary(uid2, "morning", {**bot.get_diary(uid2, "morning", today2), "c1": "Новая задача после пина"}, for_date=today2)
    upd_done2 = FakeUpdate(uid2, data="task_done_b1")
    ctx_done2 = FakeCtx(bot=fake_bot2)
    await bot.task_done_callback(upd_done2, ctx_done2)
    pin_text_after_new_task = fake_bot2.edited[-1][2]
    assert "Новая задача после пина" not in pin_text_after_new_task, pin_text_after_new_task
    print("2c. A task added after the pin never appears in the pinned message (stays in its original form)")

    # ══════════════════════════════════════════════════════════════════════
    # 3) handle_set_task_intent -- free text explicitly about TODAY's task
    # now lands directly in the first empty A/B/C slot.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Третий', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone=tz_name)
    today3 = datetime.now(bot.get_user_tz(bot.get_user(uid3))).date().isoformat()
    bot.save_diary(uid3, "morning", {"focus": "Уже стоит"}, for_date=today3)

    msg3 = FakeMsg()
    ctx3 = FakeCtx()
    await bot.handle_set_task_intent(msg3, ctx3, uid3, "Написать план")
    morning3 = bot.get_diary(uid3, "morning", today3)
    assert morning3.get("b1") == "Написать план", morning3
    print("3a. handle_set_task_intent fills the first empty slot (b1, since focus/A was already set)")

    # All 6 slots full -> graceful message, no crash.
    uid4 = 4
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (4, 'Четвёртый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid4, timezone=tz_name)
    today4 = datetime.now(bot.get_user_tz(bot.get_user(uid4))).date().isoformat()
    bot.save_diary(uid4, "morning", {k: f"Задача {k}" for k in bot.TASK_KEYS}, for_date=today4)
    msg4 = FakeMsg()
    ctx4 = FakeCtx()
    await bot.handle_set_task_intent(msg4, ctx4, uid4, "Ещё одна задача")
    assert "уже заняты" in msg4.last_text, msg4.last_text
    print("3b. handle_set_task_intent handles all-slots-full gracefully")

    # ══════════════════════════════════════════════════════════════════════
    # 4) classify_free_text recognizes and validates the new "set_task"
    # intent (via a mocked Anthropic client -- no real network call).
    # ══════════════════════════════════════════════════════════════════════
    set_fake_reply('{"intent": "set_task", "text": "Разобраться с сайтом"}')
    now_dt = datetime.now(tz)
    routed = await bot.classify_free_text("поставь задачу на сегодня разобраться с сайтом", now_dt)
    assert routed.get("intent") == "set_task", routed
    assert routed.get("text") == "Разобраться с сайтом", routed
    print("4a. classify_free_text correctly passes through a well-formed set_task intent")

    set_fake_reply('{"intent": "set_task", "text": "   "}')
    routed2 = await bot.classify_free_text("бла бла", now_dt)
    assert routed2.get("intent") == "other", routed2
    print("4b. classify_free_text rejects a set_task intent with empty/whitespace-only text, falling back to 'other'")

    # ══════════════════════════════════════════════════════════════════════
    # 5) Real feedback: "можно ли писать какой задачей на день добавить ту,
    # что просишь добавить?" -- an explicitly-named slot in the free text
    # ("поставь как задачу B1 — купить молоко") must land in THAT slot, not
    # just the first empty one.
    # ══════════════════════════════════════════════════════════════════════
    set_fake_reply('{"intent": "set_task", "text": "Купить молоко", "slot": "B1"}')
    routed3 = await bot.classify_free_text("поставь как задачу B1 — купить молоко", now_dt)
    assert routed3.get("intent") == "set_task", routed3
    assert routed3.get("slot_key") == "b1", routed3
    print("5a. classify_free_text extracts an explicitly-named slot (B1 -> slot_key='b1')")

    set_fake_reply('{"intent": "set_task", "text": "Написать план"}')
    routed4 = await bot.classify_free_text("добавь задачу написать план", now_dt)
    assert routed4.get("intent") == "set_task", routed4
    assert routed4.get("slot_key") == "", routed4
    print("5b. classify_free_text leaves slot_key empty when no slot was named")

    uid5 = 5
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (5, 'Пятый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid5, timezone=tz_name)
    today5 = datetime.now(bot.get_user_tz(bot.get_user(uid5))).date().isoformat()
    bot.save_diary(uid5, "morning", {"focus": "Уже стоит A"}, for_date=today5)
    msg5 = FakeMsg()
    ctx5 = FakeCtx()
    await bot.handle_set_task_intent(msg5, ctx5, uid5, "Купить молоко", slot_key="b1")
    morning5 = bot.get_diary(uid5, "morning", today5)
    assert morning5.get("b1") == "Купить молоко", morning5
    assert morning5.get("focus") == "Уже стоит A", "an explicit slot request must not disturb other slots"
    print("5c. handle_set_task_intent puts the task in the explicitly-named slot")

    # Explicit slot that's already occupied gets overwritten (named on purpose).
    msg6 = FakeMsg()
    ctx6 = FakeCtx()
    await bot.handle_set_task_intent(msg6, ctx6, uid5, "На самом деле другое", slot_key="focus")
    morning6 = bot.get_diary(uid5, "morning", today5)
    assert morning6.get("focus") == "На самом деле другое", morning6
    print("5d. handle_set_task_intent overwrites an already-occupied explicitly-named slot")

    print("\nALL TASK-MANAGEMENT-IMPROVEMENTS TESTS PASSED")


asyncio.run(main())
