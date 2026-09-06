import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_reminder_snooze_and_templates.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 700
        self.edits = []

    async def edit_text(self, text, **kw):
        self.edits.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []
    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.callback_query = FakeQuery(uid, data, message)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 701
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-29 + 2026-09-05): a fired reminder only
    # offered "◀️ Меню" -- no snooze; and creating one required the highest-
    # effort input method in the whole bot (free text only), unlike the pool
    # which offers one-tap reuse.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    tz = bot.get_user_tz(bot.get_user(uid))
    now = datetime.now(tz)
    past = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    bot.add_reminder(uid, "Позвонить в банк", past, recur="")
    rem_id = bot.get_due_reminders(uid, now.strftime("%Y-%m-%dT%H:%M:%S"))[0]["id"]

    # 1. Firing a one-time reminder offers a "⏰ Ещё через 10 мин" button,
    #    and the reminder is KEPT (sentinel-disarmed), not deleted -- so the
    #    snooze button can still find it by id afterwards.
    app = FakeApp()
    await bot.send_due_reminders(app, bot.get_user(uid), now)
    assert app.bot.sent, "sanity: the reminder must actually fire"
    _, _, markup = app.bot.sent[0]
    cbs = kb_callbacks(markup)
    assert f"remind_snooze_{rem_id}" in cbs, f"the fired reminder must offer a snooze button, got {cbs}"
    survivor = bot.get_reminder(uid, rem_id)
    assert survivor is not None, "a fired one-time reminder must be kept (sentinel-disarmed), not deleted"
    assert survivor["remind_at"] == bot.REMINDER_FIRED_SENTINEL
    print("1. A fired one-time reminder offers a snooze button and is kept (sentinel-disarmed) so it can still be snoozed")

    # 2. Tapping the snooze button reschedules it to ~10 minutes from now
    #    and confirms via toast + edits the message.
    msg = FakeMsg(uid)
    upd = FakeUpdate(uid, f"remind_snooze_{rem_id}", msg)
    await bot.remind_snooze_callback(upd, FakeCtx())
    rescheduled = bot.get_reminder(uid, rem_id)
    assert rescheduled is not None
    new_dt = datetime.fromisoformat(rescheduled["remind_at"])
    delta = (new_dt - now.replace(tzinfo=None)).total_seconds()
    assert 9 * 60 <= delta <= 11 * 60, f"expected ~10 minutes from now, got {delta}s"
    assert "10 минут" in upd.callback_query.answers[0]
    assert msg.edits, "the message should be edited to show it was snoozed"
    print("2. '⏰ Ещё через 10 мин' reschedules the reminder to ~10 minutes from now")

    # 3. Sanity: an undisturbed RECURRING reminder is still rescheduled to
    #    its next real occurrence, not sentinel-disarmed (no regression).
    bot.add_reminder(uid, "Растяжка", past, recur="daily")
    rem_id2 = [r for r in bot.get_due_reminders(uid, now.strftime("%Y-%m-%dT%H:%M:%S")) if r["text"] == "Растяжка"][0]["id"]
    app2 = FakeApp()
    await bot.send_due_reminders(app2, bot.get_user(uid), now)
    survivor2 = bot.get_reminder(uid, rem_id2)
    assert survivor2["remind_at"] != bot.REMINDER_FIRED_SENTINEL, "a recurring reminder must not be sentinel-disarmed"
    assert survivor2["remind_at"] > past
    print("3. A recurring reminder is still rescheduled to its next real occurrence (no regression)")

    # 4. reminder_add_start's screen offers quick-template buttons.
    q_msg = FakeMsg(uid)
    upd2 = FakeUpdate(uid, "rem_add", q_msg)
    bot.ANTHROPIC_KEY = "fake-key-for-test"
    ctx2 = FakeCtx()
    await bot.reminder_add_start(upd2, ctx2)
    tpl_text, tpl_kb = q_msg.edits[-1] if q_msg.edits else (None, None)
    assert tpl_kb is not None, "reminder_add_start must render a keyboard"
    tpl_cbs = kb_callbacks(tpl_kb)
    assert "remind_tpl_10m" in tpl_cbs and "remind_tpl_1h" in tpl_cbs and "remind_tpl_tmrw" in tpl_cbs, tpl_cbs
    print("4. reminder_add_start offers quick-template time buttons (+10 мин / +1 час / Завтра утром)")

    # 5. Tapping a template arms awaiting_reminder_add with reminder_seed set
    #    to the template's time phrase, and asks only for the content.
    ctx3 = FakeCtx()
    q_msg2 = FakeMsg(uid)
    upd3 = FakeUpdate(uid, "remind_tpl_10m", q_msg2)
    await bot.reminder_quick_template(upd3, ctx3)
    assert ctx3.user_data.get("awaiting_reminder_add") is True
    assert ctx3.user_data.get("reminder_seed") == "через 10 минут"
    print("5. Tapping a template button arms awaiting_reminder_add with the time phrase as reminder_seed")

    # 6. Typing just the content combines with the template's seed before
    #    parse_reminder_request (monkeypatched -- no real ANTHROPIC_KEY here).
    captured = {}
    async def fake_parse(text, now_dt):
        captured["text"] = text
        return ("2026-09-10T09:00:00", "проверить почту", "")
    orig_parse = bot.parse_reminder_request
    bot.parse_reminder_request = fake_parse

    class FakeMsgText:
        def __init__(self, uid_, text):
            self.chat_id = uid_
            self.text = text
        async def reply_text(self, text, **kw):
            return self

    class FakeUpdateText:
        def __init__(self, uid_, text):
            self.effective_user = FakeUser(uid_)
            self.message = FakeMsgText(uid_, text)

    try:
        text_upd = FakeUpdateText(uid, "проверить почту")
        await bot.handle_text(text_upd, ctx3)
    finally:
        bot.parse_reminder_request = orig_parse

    assert captured.get("text") == "проверить почту: через 10 минут", captured
    reminders = bot.get_reminders(uid)
    assert any(r["text"] == "проверить почту" for r in reminders), reminders
    print("6. Typing only the content combines it with the template's time phrase and creates the reminder")

    print("\nALL REMINDER-SNOOZE-AND-TEMPLATES TESTS PASSED")


asyncio.run(main())
