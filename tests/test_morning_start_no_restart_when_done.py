import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_morning_start_no_restart_when_done.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today_iso = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()

    # ══════════════════════════════════════════════════════════════════════
    # Real report: "заполнил утро, но не задал цели. Пришло напоминание
    # ('Утро ещё не закрыто' + кнопка 'Заполнить утро') -- нажимаю, а там
    # всё по новой, разминка. Но я же это уже заполнял!"
    #
    # finish_morning never clears the RESUME_FIELDS keys from ctx.user_data
    # after the ritual genuinely completes -- so re-entering morning_start
    # later the same day (e.g. from this exact reminder's button) found
    # every RESUME_FIELDS key already present and, per the OLD code's own
    # comment, treated that as "finish_morning crashed" and restarted the
    # whole ritual from the warmup -- discarding nothing from the DB, but
    # forcing the person to re-answer writing/gratitude/child for no reason.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["m_progress_date"] = today_iso
    ctx.user_data["m_writing"] = "Сон про кота"
    ctx.user_data["m_gratitude"] = "Утреннему кофе"
    ctx.user_data["m_child"] = "Ты молодец"
    # As finish_morning would have already written to the DB.
    bot.save_diary(uid, "morning", {
        "writing": "Сон про кота", "gratitude": "Утреннему кофе", "child": "Ты молодец",
    }, for_date=today_iso)
    bot.update_user(uid, morning_filled_at=datetime.now(bot.get_user_tz(bot.get_user(uid))).isoformat())

    upd = FakeUpdate(uid, data="go_morning")
    result = await bot.morning_start(upd, ctx)

    sent_text = upd.callback_query.message.sent[0][0]
    # Реальный запрос (позже): вместо общей фразы "поставь задачи" экран
    # показывает то, что реально записано -- задачи сюда не попадают.
    assert "Сон про кота" in sent_text, sent_text
    assert "Утреннему кофе" in sent_text, sent_text
    assert "Ты молодец" in sent_text, sent_text
    print("1. morning_start recognizes a genuinely finished morning and offers task-setting instead of restarting")

    # Must NOT show the warmup / motivational restart text.
    assert not any("Доброе утро" in t for t, _ in upd.callback_query.message.sent), \
        "must not restart the ritual (warmup greeting) when it was already completed today"
    assert len(upd.callback_query.message.sent) == 1, \
        f"must send exactly one message (the redirect), not also proceed into the ritual, got {upd.callback_query.message.sent}"
    print("2. No warmup/restart message is sent -- the ritual is not replayed")

    # ══════════════════════════════════════════════════════════════════════
    # Sanity / regression: the genuine crash-recovery case this fallback
    # was originally meant for -- all RESUME_FIELDS keys present, but
    # morning_filled_at is NOT today (finish_morning really never ran) --
    # must still fall through and restart from the warmup, unchanged.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")
    today_iso2 = datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat()

    ctx2 = FakeCtx()
    ctx2.user_data["m_progress_date"] = today_iso2
    ctx2.user_data["m_writing"] = "..."
    ctx2.user_data["m_gratitude"] = "..."
    ctx2.user_data["m_child"] = "..."
    # morning_filled_at left empty -- finish_morning genuinely never ran.

    upd2 = FakeUpdate(uid2, data="go_morning")
    await bot.morning_start(upd2, ctx2)
    sent_text2 = " ".join(t for t, _ in upd2.callback_query.message.sent)
    assert "Доброе утро" in sent_text2, \
        f"the genuine crash-recovery fallback (finish_morning never ran) must still restart the ritual, got {sent_text2}"
    print("3. When finish_morning genuinely never ran (morning_filled_at not today), the ritual still restarts as before")

    print("\nALL MORNING-START-NO-RESTART-WHEN-DONE TESTS PASSED")


asyncio.run(main())
