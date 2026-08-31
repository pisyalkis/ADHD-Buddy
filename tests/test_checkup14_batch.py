import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup14_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.bot = FakeBot()
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_reply_markup(self, **kw):
        self.sent.append((None, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]
    @property
    def last_kb(self):
        return self.sent[-1][1]


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
        self.answered = False
    async def answer(self, *a, **kw):
        self.answered = True


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data="", text=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None
        if text is not None:
            self.message = FakeMsg()
            self.message.text = text
        self.pre_checkout_query = None


class FakeCtxBot:
    async def send_invoice(self, **kw):
        pass
    async def send_message(self, chat_id, text, **kw):
        class _M:
            message_id = 999999
        return _M()
    async def delete_message(self, chat_id, message_id):
        pass


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeCtxBot()


class FakeAppBot:
    def __init__(self):
        self.sent = []
        self.fail_send = False
    async def send_message(self, uid, text, **kw):
        if self.fail_send:
            raise RuntimeError("simulated failure")
        self.sent.append((uid, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeAppBot()


def all_buttons(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Аня', 'F')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Admin', 'M')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): _skill_beacon_random_times anchored the window
    # to TODAY's date even for an overnight window (beacon_start > beacon_end)
    # -- the early-morning tail (00:00 to beacon_end) of a window that
    # actually started YESTERDAY evening never generated a due target.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    bot.update_user(uid, timezone=tz_name, beacon_start="22:00", beacon_end="06:00",
                     skill_beacon_mode="random", skill_beacon_daily_count=3,
                     skill_beacon_last_sent="")
    user = bot.get_user(uid)
    tz = bot.get_user_tz(user)
    now_tail = datetime.now(tz).replace(hour=3, minute=0, second=0, microsecond=0)
    targets = bot._skill_beacon_random_times(user, now_tail, 3)
    assert targets, "must generate targets for the early-morning tail of an overnight window"
    assert all(t <= now_tail + timedelta(hours=6) for t in targets), \
        f"targets must fall within the ALREADY-OPEN overnight window (ending at beacon_end today), not a future one, got {targets}"
    assert any(t <= now_tail for t in targets), \
        f"at least one target must already be due by now_tail=03:00 inside a 22:00-06:00 window, got {targets}"
    print("1. _skill_beacon_random_times now correctly anchors an overnight window's early-morning tail")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): apply_task_edit (📋 Задачи quick-editor path)
    # never updated morning_filled_at, defeating send_task_beacon's
    # throttle-after-just-filling-tasks logic for anyone who sets tasks
    # without doing the full morning ritual.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, morning_filled_at="")
    ctx = FakeCtx()
    msg = FakeMsg()
    await bot.apply_task_edit(msg, ctx, uid, "focus", "Сделать X")
    after = bot.get_user(uid)
    assert after.get("morning_filled_at"), \
        "apply_task_edit must stamp morning_filled_at so the task beacon doesn't fire immediately after"
    print("2. apply_task_edit now stamps morning_filled_at")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): add_pool_and_reply falsely confirmed
    # "✅ Добавил" for a whitespace-only message that added nothing.
    # ══════════════════════════════════════════════════════════════════════
    msg2 = FakeMsg()
    await bot.add_pool_and_reply(msg2, uid, ["   ", ""])
    assert "Не увидел" in msg2.last_text, msg2.last_text
    assert "Добавил" not in msg2.last_text, msg2.last_text
    print("3. add_pool_and_reply no longer falsely confirms success on empty/whitespace input")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): today_str() rendered month names in English
    # (%B in the C locale) inside an all-Russian bot.
    # ══════════════════════════════════════════════════════════════════════
    s = bot.today_str(tz)
    assert any(m in s for m in bot._RU_MONTHS), f"today_str() must render a Russian month name, got {s!r}"
    assert not any(en in s for en in ("January","February","March","April","May","June",
                                       "July","August","September","October","November","December")), s
    print("4. today_str() now renders Russian month names, not English")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): research_callback's low_rating check was
    # copied from the 1-5 scale (day 3) and missed "0" -- the worst possible
    # NPS answer on the 0-10 scale (day 14) -- so it never alerted the admin.
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate(uid, data="research_14_0")
    await bot.research_callback(upd, FakeCtx())
    alert_text = upd.callback_query.message.bot.sent[-1][1]
    assert "НИЗКАЯ ОЦЕНКА" in alert_text, \
        f"an NPS score of 0 (the worst possible) must trigger the low-rating admin alert, got: {alert_text}"
    print("5a. research_callback now alerts on NPS score 0 (day 14)")

    upd2 = FakeUpdate(uid, data="research_14_8")
    await bot.research_callback(upd2, FakeCtx())
    normal_text = upd2.callback_query.message.bot.sent[-1][1]
    assert "НИЗКАЯ ОЦЕНКА" not in normal_text, normal_text
    print("5b. research_callback still does not alert on a normal NPS score")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): go_about/go_privacy/go_subscribe/
    # go_subscribe_pay/successful_payment_callback didn't call
    # clear_awaiting_flags, unlike their menu siblings (go_feedback,
    # go_promo) -- a stale awaiting_feedback (or any other awaiting_*) flag
    # survived tapping these buttons and silently swallowed the user's next
    # ordinary message.
    # ══════════════════════════════════════════════════════════════════════
    for handler_name, data in [
        ("go_about", "go_about"), ("go_privacy", "go_privacy"),
        ("go_subscribe", "go_subscribe"), ("go_subscribe_pay", "go_subscribe_pay"),
    ]:
        ctx3 = FakeCtx()
        ctx3.user_data["awaiting_feedback"] = True
        upd3 = FakeUpdate(uid, data=data)
        handler = getattr(bot, handler_name)
        await handler(upd3, ctx3)
        assert ctx3.user_data.get("awaiting_feedback") in (False, None), \
            f"{handler_name} must clear a stale awaiting_feedback flag, still set: {ctx3.user_data.get('awaiting_feedback')}"
    print("6a. go_about/go_privacy/go_subscribe/go_subscribe_pay now clear stale awaiting flags")

    ctx4 = FakeCtx()
    ctx4.user_data["awaiting_feedback"] = True
    upd4 = FakeUpdate(uid, text="")
    upd4.message = FakeMsg()
    upd4.message.text = ""
    upd4.message.successful_payment = type("P", (), {"total_amount": 100, "currency": "XTR",
                                                        "invoice_payload": f"subscription_{uid}",
                                                        "telegram_payment_charge_id": "test_charge_1"})()
    await bot.successful_payment_callback(upd4, ctx4)
    assert ctx4.user_data.get("awaiting_feedback") in (False, None), \
        f"successful_payment_callback must clear a stale awaiting_feedback flag, still set: {ctx4.user_data.get('awaiting_feedback')}"
    print("6b. successful_payment_callback now clears stale awaiting flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): daily_prefs_kb labeled beacon_enabled/
    # skill_beacon_enabled as "Напоминания о задачах"/"Напоминания с
    # навыками" -- inconsistent with "Маячок" everywhere else, and
    # confusable with the unrelated ⏰ Напоминания feature.
    # ══════════════════════════════════════════════════════════════════════
    kb = bot.daily_prefs_kb(bot.get_user(uid))
    labels = [t for t, _ in all_buttons(kb)]
    # Word order (distinguishing word first, "маячки" second) is itself a
    # later fix (screenshot: both buttons truncated to the identical
    # "Маячки вниман..." since they're side by side and the differentiator
    # was the LAST word); "внимания" was later dropped too (also a
    # screenshot request: "мало места на кнопках") -- both parts must
    # still be present, just as "маячки" rather than "маячки внимания".
    assert any("Задачи" in t and "маячки" in t for t in labels), labels
    assert any("Навыки" in t and "маячки" in t for t in labels), labels
    assert not any("Напоминания" in t for t in labels), \
        f"daily_prefs_kb must not use 'Напоминания' wording (collides with the unrelated ⏰ Напоминания feature), got {labels}"
    print("7. daily_prefs_kb now uses 'маячки' wording consistent with the rest of the bot")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (14th checkup): weekly_report's tasks_done only counted
    # e_tasks_done (the evening-ritual snapshot) -- a day where all tasks
    # were marked done via 📋 Задачи/midday buttons but the evening ritual
    # was skipped entirely contributed 0 to the weekly "tasks done" stat.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    bot.update_user(uid2, timezone=tz_name, streak_hidden=1)
    user2 = bot.get_user(uid2)
    today2 = datetime.now(bot.get_user_tz(user2)).date()
    d = (today2 - timedelta(days=3)).isoformat()
    bot.save_diary(uid2, "morning", {"focus": "Сделать X"}, for_date=d)
    bot.save_diary(uid2, "tasks_done", {"done": ["focus"]}, for_date=d)
    # No evening diary entry at all for this day -- ritual skipped.
    app = FakeApp()
    await bot.weekly_report(app, uid2)
    report_text = app.bot.sent[0][1]
    assert "Задач выполнено: *1 из 1*" in report_text, report_text
    print("8. weekly_report now counts tasks done via 📋 Задачи even when the evening ritual was skipped")

    print("\nALL CHECKUP14-BATCH TESTS PASSED")


asyncio.run(main())
