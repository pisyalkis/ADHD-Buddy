import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_resume_and_deadcode.db")
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
        self.edited = []
        self.sent = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid)
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery(uid)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Bug 1 (morning_start): the rare edge case where all RESUME_FIELDS are
    # already in ctx.user_data (so the for-loop finds nothing missing and
    # falls through), but morning_filled_at isn't set for today, used to
    # skip the checkpoint entirely (stale_date == today_iso, so the old
    # "stale_date != today_iso" guard blocked it) and then unconditionally
    # wipe the already-written writing/gratitude/child from ctx.user_data.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today_iso = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    ctx = FakeCtx({
        "m_progress_date": today_iso,
        "m_writing": "Голова была занята дедлайном",
        "m_gratitude": "За отпуск",
        "m_child": "Ты справляешься",
    })
    await bot.morning_start(FakeUpdate(uid), ctx)

    saved = bot.get_diary(uid, "morning", today_iso)
    assert saved.get("writing") == "Голова была занята дедлайном", \
        f"the already-written free-form text must be checkpointed, not wiped, got: {saved}"
    assert saved.get("gratitude") == "За отпуск", saved
    assert saved.get("child") == "Ты справляешься", saved
    print("1. morning_start checkpoints already-written text instead of silently wiping it (edge case)")

    # ══════════════════════════════════════════════════════════════════════
    # Bug 2 (evening_start, same class): identical edge case for the
    # evening ritual's RESUME_FIELDS_EVENING.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    tz2 = bot.get_user_tz(bot.get_user(uid2))
    today2 = bot.evening_day(tz2).isoformat()

    ctx2 = FakeCtx({
        "e_progress_date": today2,
        "e_ach": "Сделала отчёт",
        "e_praise": "Молодец",
        "e_highlights": "Хорошо поработала",
        "e_selfcare_done": True,
        "e_energy": 7,
        "e_a": "Задача A",
        "e_b1": "", "e_b2": "",
        "e_c1": "", "e_c2": "", "e_c3": "",
    })
    await bot.evening_start(FakeUpdate(uid2), ctx2)

    saved2 = bot.get_diary(uid2, "evening", today2)
    assert saved2.get("e_ach") == "Сделала отчёт", \
        f"the already-written evening answers must be checkpointed, not wiped, got: {saved2}"
    assert saved2.get("e_praise") == "Молодец", saved2
    assert saved2.get("e_highlights") == "Хорошо поработала", saved2
    print("2. evening_start checkpoints already-written text instead of silently wiping it (edge case)")

    # ══════════════════════════════════════════════════════════════════════
    # Sanity: the ORIGINAL, already-working case (stale_date is genuinely a
    # PREVIOUS day) must still checkpoint correctly -- not a regression.
    # ══════════════════════════════════════════════════════════════════════
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Настя', 'F')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi")
    ctx3 = FakeCtx({
        "m_progress_date": "2020-01-01",  # a genuinely stale, previous day
        "m_writing": "Старый текст",
    })
    await bot.morning_start(FakeUpdate(uid3), ctx3)
    saved3 = bot.get_diary(uid3, "morning", "2020-01-01")
    assert saved3.get("writing") == "Старый текст", \
        f"the pre-existing stale-previous-day checkpoint must still work, got: {saved3}"
    print("3. morning_start still checkpoints a genuinely stale previous day as before (no regression)")

    print("\nALL MORNING-RESUME-AND-DEADCODE TESTS PASSED")


asyncio.run(main())
