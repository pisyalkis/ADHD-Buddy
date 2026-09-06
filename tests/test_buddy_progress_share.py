import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_buddy_progress_share.db")
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


_next_id = [100]


class FakeMessage:
    def __init__(self, chat_id=1):
        self.chat_id = chat_id
        self.message_id = _next_id[0]
        _next_id[0] += 1
        self.text = ""

    async def reply_text(self, text, **kw):
        m = FakeMessage(self.chat_id)
        m.text = text
        return m

    async def edit_text(self, text, **kw):
        self.text = text
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, data=None, message=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data, message) if data is not None else None
        self.message = message


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 901
        return M()


class FakeCtx:
    def __init__(self, bot_=None):
        self.user_data = {}
        self.bot = bot_


def make_user(uid, name, gender="M"):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, ?)", (uid, name, gender))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (product discussion, this session): share with your buddy
    # the FACT that you completed morning ritual / set today's goals /
    # closed out the evening -- three separate events, opt-in once at
    # pairing, adaptive wording ("давай тоже..." cooperative invite if the
    # recipient hasn't done theirs yet today, celebratory "тоже сегодня!" if
    # they already have) -- explicitly NOT "а ты уже?" (rejected phrasing).
    # ══════════════════════════════════════════════════════════════════════
    uid1 = 1; uid2 = 2
    make_user(uid1, "Артем", "M"); make_user(uid2, "Вика", "F")
    bot.finalize_buddy_pairing(uid1, uid2)

    # 1. With sharing OFF (the default), nothing is sent at all.
    fbot1 = FakeBot()
    await bot._share_buddy_progress(fbot1, uid1, "morning")
    assert not fbot1.sent, "sharing must be off by default until explicitly enabled"
    print("1. _share_buddy_progress is a no-op while buddy_share_progress is off (the default)")

    # 2. buddy_share_on / buddy_share_off toggle the flag.
    ctx_on = FakeCtx(FakeBot())
    await bot.buddy_share_on(FakeUpdate(uid1, data="buddy_share_on", message=FakeMessage(uid1)), ctx_on)
    assert int(bot.get_user(uid1)["buddy_share_progress"]) == 1
    ctx_off = FakeCtx(FakeBot())
    await bot.buddy_share_off(FakeUpdate(uid1, data="buddy_share_off", message=FakeMessage(uid1)), ctx_off)
    assert int(bot.get_user(uid1)["buddy_share_progress"]) == 0
    bot.update_user(uid1, buddy_share_progress=1)  # re-enable for the rest of the test
    print("2. buddy_share_on/buddy_share_off toggle buddy_share_progress")

    # 3. Cooperative "давай тоже" wording when the recipient (uid2) has NOT
    #    done their morning yet -- NOT "а ты уже?" (explicitly rejected).
    fbot3 = FakeBot()
    await bot._share_buddy_progress(fbot3, uid1, "morning")
    assert len(fbot3.sent) == 1
    chat, text, _ = fbot3.sent[0]
    assert chat == uid2
    assert "Артем" in text and "закрыл" in text
    assert "Давай тоже заполним утро" in text
    assert "а ты уже" not in text.lower()
    print("3. _share_buddy_progress uses cooperative 'давай тоже' wording when the recipient hasn't done it yet")

    # 4. Celebratory wording when the recipient HAS already done their own
    #    morning today.
    bot.update_user(uid2, morning_filled_at=datetime.now(bot.pytz.utc).isoformat())
    fbot4 = FakeBot()
    await bot._share_buddy_progress(fbot4, uid1, "morning")
    _, text4, _ = fbot4.sent[0]
    assert "тоже" in text4 and "закрыл" in text4 and "сегодня!" in text4
    assert "Давай" not in text4, "must not invite someone who's already done it"
    print("4. _share_buddy_progress switches to celebratory wording once the recipient has already done it today")

    # 5. "goals" event checks the recipient's own focus field for today.
    bot.update_user(uid1, buddy_share_progress=1)
    fbot5 = FakeBot()
    await bot._share_buddy_progress(fbot5, uid1, "goals")
    _, text5, _ = fbot5.sent[0]
    assert "поставил" in text5 and "Давай тоже поставим цели" in text5, text5
    today = datetime.now(TBILISI).date().isoformat()
    bot.save_diary(uid2, "morning", {"focus": "Уже поставил"}, for_date=today)
    fbot5b = FakeBot()
    await bot._share_buddy_progress(fbot5b, uid1, "goals")
    _, text5b, _ = fbot5b.sent[0]
    assert "тоже" in text5b and "сегодня!" in text5b, text5b
    print("5. 'goals' event correctly reads the recipient's own focus field for today")

    # 6. "evening" event checks the recipient's own evening diary entry.
    fbot6 = FakeBot()
    await bot._share_buddy_progress(fbot6, uid1, "evening")
    _, text6, _ = fbot6.sent[0]
    assert "закрыл" in text6 and "Давай тоже закроем день" in text6, text6
    ev_today = bot.evening_day(bot.get_user_tz(bot.get_user(uid2))).isoformat()
    bot.save_diary(uid2, "evening", {"e_ach": "done"}, for_date=ev_today)
    fbot6b = FakeBot()
    await bot._share_buddy_progress(fbot6b, uid1, "evening")
    _, text6b, _ = fbot6b.sent[0]
    assert "тоже" in text6b and "сегодня!" in text6b, text6b
    print("6. 'evening' event correctly reads the recipient's own evening diary entry")

    # 7. Sharing requires ONLY the sender's own opt-in -- the recipient's own
    #    preference (even if explicitly off) does not gate it.
    uid3 = 3; uid4 = 4
    make_user(uid3, "Игорь", "M"); make_user(uid4, "Соня", "F")
    bot.finalize_buddy_pairing(uid3, uid4)
    bot.update_user(uid3, buddy_share_progress=1)
    bot.update_user(uid4, buddy_share_progress=0)  # recipient explicitly opted OUT of sharing THEIR OWN facts
    fbot7 = FakeBot()
    await bot._share_buddy_progress(fbot7, uid3, "morning")
    assert len(fbot7.sent) == 1, "the sender's own opt-in is what gates sharing, not the recipient's preference"
    print("7. Only the sender's own opt-in gates sharing -- unaffected by the recipient's own preference")

    # 8. finish_morning end-to-end: shares ONLY 'morning' -- "goals" is a
    #    separate event that lives exclusively in apply_task_edit (📋 Задачи
    #    is always the path that sets task fields; the ritual itself only
    #    ever reads back whatever's already in the diary, per
    #    _merged_task_fields -- "задачи ставятся отдельно").
    uid5 = 5; uid6 = 6
    make_user(uid5, "Соло1", "M"); make_user(uid6, "Соло2", "F")
    bot.finalize_buddy_pairing(uid5, uid6)
    bot.update_user(uid5, buddy_share_progress=1)
    fbot8 = FakeBot()
    ctx8 = FakeCtx(fbot8)
    await bot.finish_morning(FakeMessage(uid5), uid5, ctx8)
    assert len(fbot8.sent) == 1, fbot8.sent
    assert "закрыл" in fbot8.sent[0][1], fbot8.sent
    print("8. finish_morning shares only the 'morning' event -- 'goals' is apply_task_edit's exclusive concern")

    # 9. apply_task_edit (the standalone 📋 Задачи path, outside the ritual)
    #    shares 'goals' only on the FIRST time focus becomes non-empty --
    #    not on every subsequent edit of it.
    uid7 = 7; uid8 = 8
    make_user(uid7, "Отдельный1", "M"); make_user(uid8, "Отдельный2", "F")
    bot.finalize_buddy_pairing(uid7, uid8)
    bot.update_user(uid7, buddy_share_progress=1)
    fbot9 = FakeBot()
    ctx9 = FakeCtx(fbot9)
    await bot.apply_task_edit(FakeMessage(uid7), ctx9, uid7, "focus", "Моя первая задача")
    assert len(fbot9.sent) == 1, fbot9.sent
    fbot9b = FakeBot()
    ctx9b = FakeCtx(fbot9b)
    await bot.apply_task_edit(FakeMessage(uid7), ctx9b, uid7, "focus", "Поменял формулировку")
    assert not fbot9b.sent, "editing an already-set focus again must not re-share 'goals'"
    print("9. apply_task_edit shares 'goals' only the first time focus is set today, not on later edits")

    print("\nALL BUDDY PROGRESS SHARE TESTS PASSED")


asyncio.run(main())
