import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup7_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import pytz
import bot
bot.init_db()

# Avoid evening_day()'s 00:00-04:00 window so "today" here matches "today"
# inside evening_start/finish_evening deterministically for the fallback test.
SAFE_TZ = "Asia/Tbilisi"
for offset in range(-11, 13):
    candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
    try:
        cand = pytz.timezone(candidate)
        if datetime.now(cand).hour >= 5:
            SAFE_TZ = candidate
            break
    except Exception:
        continue

# For the evening_start date-consistency test specifically, we need a
# timezone where it IS currently in evening_day()'s 00:00-04:00 shift
# window -- that's the exact scenario the bug only shows up in (morning
# saved under yesterday's calendar date, evening opened just after
# midnight). Outside that window, calendar-date and evening_day agree and
# the bug can't be observed either way.
MIDNIGHT_TZ = None
for offset in range(-11, 13):
    candidate = f"Etc/GMT{'+' if -offset >= 0 else '-'}{abs(-offset)}" if offset != 0 else "UTC"
    try:
        cand = pytz.timezone(candidate)
        if datetime.now(cand).hour < 4:
            MIDNIGHT_TZ = candidate
            break
    except Exception:
        continue


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.markup_edits = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_reply_markup(self, **kw):
        self.markup_edits.append(kw.get("reply_markup"))
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, text=None, data=None):
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})
        self.effective_message = FakeMsg()
        self.message = self.effective_message
        self.message.text = text
        self.message.successful_payment = None
        self.callback_query = FakeQuery(uid, data) if data is not None else None
        self.pre_checkout_query = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone=SAFE_TZ)

    # ══════════════════════════════════════════════════════════════════════
    # Bug: access_gate blocks an update and stops propagation without
    # clearing awaiting_* flags / active morning-evening conversation state
    # -- a flag set right before the trial expired stays armed and hijacks
    # the user's first message after they resubscribe.
    # ══════════════════════════════════════════════════════════════════════
    bot.ACCESS_GATE_ENABLED = True
    bot.update_user(uid, created_at="2020-01-01", subscription_until="")
    assert bot.get_access_status(bot.get_user(uid)) == "expired"

    ctx = FakeCtx()
    ctx.user_data["awaiting_feedback"] = True
    upd = FakeUpdate(uid, text="какой-то текст")
    try:
        await bot.access_gate(upd, ctx)
        raised = False
    except bot.ApplicationHandlerStop:
        raised = True
    assert raised, "an expired user's message must still be stopped by the gate"
    assert ctx.user_data.get("awaiting_feedback") is False, \
        f"access_gate must clear stale awaiting_* flags before stopping propagation, got {ctx.user_data}"
    print("1. access_gate clears a stale awaiting_feedback flag before blocking")
    bot.ACCESS_GATE_ENABLED = False

    # ══════════════════════════════════════════════════════════════════════
    # Bug: evening_start looked up "morning" by plain calendar date only --
    # wrong in the ordinary case of opening the evening ritual after
    # midnight, when the morning it should find lives under evening_day's
    # date (yesterday's calendar date), not today's brand-new calendar date.
    # ══════════════════════════════════════════════════════════════════════
    if MIDNIGHT_TZ:
        conn = sqlite3.connect(bot.DB_PATH)
        conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Тест', 'M')")
        conn.commit(); conn.close()
        uid2 = 2
        bot.update_user(uid2, timezone=MIDNIGHT_TZ)
        tz2 = bot.get_user_tz(bot.get_user(uid2))
        ev_day = bot.evening_day(tz2).isoformat()
        real_today = datetime.now(tz2).date().isoformat()
        assert ev_day != real_today, "sanity: evening_day must resolve to yesterday in this window"
        # Morning was done normally yesterday (calendar) -- evening_day
        # correctly resolves "today" to that same date right now.
        bot.save_diary(uid2, "morning", {"focus": "Сходить к врачу", "b1": "Купить хлеб"}, for_date=ev_day)

        ctx2 = FakeCtx()
        upd2 = FakeUpdate(uid2, data="go_evening")
        state = await bot.evening_start(upd2, ctx2)
        assert state == bot.E_TASKS_DONE, \
            f"a real morning (found via evening_day, not the brand-new calendar day) must lead to the tasks-done checklist, got state={state}"
        assert ctx2.user_data.get("e_morning_date") == ev_day, ctx2.user_data
        print("2. evening_start opened just after midnight still finds yesterday's real morning")

        focus_recap_found = any("Сходить к врачу" in text for text, _ in upd2.callback_query.message.sent)
        assert focus_recap_found, "the evening greeting must recap the real focus task"
        print("3. The evening greeting correctly recaps the real focus task in this window")

        # ask_tasks_done and toggle_task_done must agree on the same date --
        # toggling a checkbox must not silently blank out the checklist.
        ctx3 = FakeCtx()
        ctx3.user_data["e_morning_date"] = ev_day
        ctx3.user_data["e_tasks_done"] = []
        upd3 = FakeUpdate(uid2, data="td_focus")
        await bot.toggle_task_done(upd3, ctx3)
        edited_kb = upd3.callback_query.message.markup_edits[-1]
        button_texts = [row[0].text for row in edited_kb.inline_keyboard]
        assert any("Сходить к врачу" in t for t in button_texts), \
            f"toggle_task_done must render the real checklist, not an empty one, got {button_texts}"
        print("4. toggle_task_done reuses the same resolved date as ask_tasks_done -- checklist stays populated")
    else:
        print("2-4. SKIPPED (no timezone currently in the 00:00-04:00 window -- harmless, rare)")

    print("\nALL CHECKUP-7 BATCH TESTS PASSED")


asyncio.run(main())
