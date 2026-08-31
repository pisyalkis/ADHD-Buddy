import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_pinned_refresh_keeps_beacon_buttons.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.edit_calls = []
    async def edit_message_text(self, **kw):
        self.edit_calls.append(kw)


class FakeCtx:
    def __init__(self, bot):
        self.bot = bot


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real report: "обе кнопки маячки внимания выключают уведомления" /
    # both quick-toggle buttons on the pinned daily message showed 🔕
    # regardless of what was pressed. Traced to _refresh_pinned_tasks_message
    # (called every time a task is marked done/undone) calling
    # ctx.bot.edit_message_text WITHOUT reply_markup -- Telegram resets a
    # message's keyboard when it isn't explicitly resent, so the quick-toggle
    # buttons silently reverted to a stale/blank state on every task tick.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, beacon_enabled=1, skill_beacon_enabled=0,
                     pinned_msg_id="555", pinned_task_keys="focus,b1", pinned_ai_msg="")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт", "b1": "Позвонить маме"}, for_date=today)

    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    await bot._refresh_pinned_tasks_message(ctx, uid)

    assert len(fbot.edit_calls) == 1
    call = fbot.edit_calls[0]
    assert call.get("reply_markup") is not None, \
        "_refresh_pinned_tasks_message must resend the keyboard explicitly, or Telegram drops it"
    labels = buttons_of(call["reply_markup"])
    assert any(cb == "quick_toggle_beacon" for _, cb in labels), labels
    assert any(cb == "quick_toggle_skill" for _, cb in labels), labels
    print("1. _refresh_pinned_tasks_message now passes reply_markup, keeping the quick-toggle buttons")

    # The resent keyboard must reflect the REAL current state (🔔 on for
    # beacon, 🔕 off for skill) -- not some stale/default rendering.
    beacon_label = next(t for t, cb in labels if cb == "quick_toggle_beacon")
    skill_label = next(t for t, cb in labels if cb == "quick_toggle_skill")
    assert beacon_label.startswith("🔔"), beacon_label
    assert skill_label.startswith("🔕"), skill_label
    print("2. The resent keyboard reflects the true beacon_enabled/skill_beacon_enabled state")

    print("\nALL PINNED-REFRESH-KEEPS-BEACON-BUTTONS TESTS PASSED")


asyncio.run(main())
