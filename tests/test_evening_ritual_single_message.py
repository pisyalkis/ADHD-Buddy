import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_evening_ritual_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    _next_id = [21000]
    def __init__(self, chat_id, text="какой-то текст"):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
        self.reply_calls = []
        self.text = text

    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        self.reply_calls.append((text, kw.get("reply_markup")))
        return m

    async def edit_reply_markup(self, **kw):
        pass


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=None, message=None, text_message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = text_message


class FakeBot:
    def __init__(self):
        self.edits = []
        self.deleted = []
        self.sent = []

    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edits.append((chat_id, message_id, text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return FakeMsg(chat_id)

    async def unpin_chat_message(self, **kw): pass
    async def pin_chat_message(self, **kw): pass


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


def cb(uid, data, tracked_id):
    m = FakeMsg(chat_id=uid)
    m.message_id = tracked_id
    return FakeUpdate(uid, data=data, message=m), m


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = bot.evening_day(bot.get_user_tz(bot.get_user(uid))).isoformat()
    bot.save_diary(uid, "morning", {"focus": "Сделать отчёт"}, for_date=today)
    # has_any_evening_diary_ever must be True, otherwise advance_evening
    # silently skips the selfcare step for "first ever" evenings -- seed a
    # past evening entry so the selfcare step is actually exercised here.
    bot.save_diary(uid, "evening", {"e_ach": "x"}, for_date="2020-01-01")

    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    menu_screen = FakeMsg(chat_id=uid)

    upd = FakeUpdate(uid, data="go_evening", message=menu_screen)
    await bot.evening_start(upd, ctx)

    tracked_id = ctx.user_data.get("ritual_step_msg_id")
    assert tracked_id is not None and tracked_id != menu_screen.message_id
    assert "получилось" in fbot.edits[-1][2] or "Что из запланированного" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("1. evening_start starts its own new message (task checklist), leaving the entry screen untouched")

    # Finish the tasks-done checklist -> achievements.
    upd2, _ = cb(uid, "td_done", tracked_id)
    await bot.tasks_done_finish(upd2, ctx)
    assert all(mid == tracked_id for _, mid, _ in fbot.edits)
    assert "Достижения дня" in fbot.edits[-1][2], fbot.edits[-1][2]
    print("2. Finishing the tasks checklist edits the SAME tracked message into 'achievements'")

    # Skip achievements, praise, highlights (all buttons).
    upd3, _ = cb(uid, "skip_e_ach", tracked_id)
    await bot.skip_e_ach(upd3, ctx)
    assert "Похвали себя" in fbot.edits[-1][2], fbot.edits[-1][2]

    upd4, _ = cb(uid, "skip_e_praise", tracked_id)
    await bot.skip_e_praise(upd4, ctx)
    assert "Яркие моменты" in fbot.edits[-1][2], fbot.edits[-1][2]

    upd5, _ = cb(uid, "skip_e_highlights", tracked_id)
    await bot.skip_e_highlights(upd5, ctx)
    assert "Что из этого" in fbot.edits[-1][2], fbot.edits[-1][2]
    assert all(mid == tracked_id for _, mid, _ in fbot.edits)
    print("3. Skipping achievements/praise/highlights all stay on the SAME tracked message, reaching selfcare")

    # Selfcare done -> energy.
    upd6, _ = cb(uid, "sc_done", tracked_id)
    await bot.selfcare_done(upd6, ctx)
    assert "энергии" in fbot.edits[-1][2].lower(), fbot.edits[-1][2]

    # Energy -> plan A.
    upd7, _ = cb(uid, "energy_3", tracked_id)
    await bot.got_energy(upd7, ctx)
    assert "задача A" in fbot.edits[-1][2], fbot.edits[-1][2]
    assert all(mid == tracked_id for _, mid, _ in fbot.edits)
    print("4. Selfcare -> energy -> plan A all stay on the SAME tracked message")

    # Walk through the evening-plan chain A -> B1 -> B2 -> C1 -> C2 -> C3,
    # mixing skip (button) and typed text, same as the morning test.
    upd8, _ = cb(uid, "skip_e_a", tracked_id)
    await bot.skip_e_a(upd8, ctx)
    assert "B1" in fbot.edits[-1][2], fbot.edits[-1][2]

    text_b1 = FakeMsg(chat_id=uid, text="Постирать")
    upd9 = FakeUpdate(uid, text_message=text_b1)
    await bot.got_e_b1(upd9, ctx)
    assert not text_b1.reply_calls
    assert "B2" in fbot.edits[-1][2], fbot.edits[-1][2]

    upd10, _ = cb(uid, "skip_e_b2", tracked_id)
    await bot.skip_e_b2(upd10, ctx)
    assert "C1" in fbot.edits[-1][2], fbot.edits[-1][2]

    text_c1 = FakeMsg(chat_id=uid, text="Разобрать почту")
    upd11 = FakeUpdate(uid, text_message=text_c1)
    await bot.got_e_c1(upd11, ctx)
    assert not text_c1.reply_calls
    assert "C2" in fbot.edits[-1][2], fbot.edits[-1][2]

    text_c2 = FakeMsg(chat_id=uid, text="...")
    upd12 = FakeUpdate(uid, text_message=text_c2)
    await bot.got_e_c2(upd12, ctx)
    assert "C3" in fbot.edits[-1][2], fbot.edits[-1][2]

    text_c3 = FakeMsg(chat_id=uid, text="...")
    upd13 = FakeUpdate(uid, text_message=text_c3)
    await bot.got_e_c3(upd13, ctx)

    assert all(mid == tracked_id for _, mid, _ in fbot.edits), \
        "the entire evening plan-step chain (A->B1->B2->C1->C2->C3) must stay on ONE bot message"
    print("5. The full evening-plan chain (A->B1->B2->C1->C2->C3, mixed skip/typed) stayed on ONE bot message")

    # finish_evening's own separate final summary is sent as a reply to
    # whatever triggered it (the user's last typed message, text_c3).
    assert text_c3.reply_calls and "закрыт" in text_c3.reply_calls[0][0], text_c3.reply_calls

    # Cleanup: the tracked ritual-step message is deleted, tracking cleared.
    assert (uid, tracked_id) in fbot.deleted, fbot.deleted
    assert ctx.user_data.get("ritual_step_msg_id") is None
    assert ctx.user_data.get("ritual_step_chat_id") is None
    print("6. The tracked ritual-step message is deleted and tracking cleared at evening finish")

    print("\nALL EVENING-RITUAL-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
