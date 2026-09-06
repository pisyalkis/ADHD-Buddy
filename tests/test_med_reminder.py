import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_med_reminder.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 1
        return M()
    async def delete_message(self, chat_id, message_id):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-26): educational text about medication
    # existed ("медикаменты и психотерапия работают лучше вместе"), but no
    # actual reminder to take it -- despite the morning/midday/evening
    # time-slot/toggle infrastructure already supporting this almost for
    # free. New notif_med/notif_med_on slot, off by default (opt-in,
    # independent of notif_enabled, same principle as the beacons).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    user = bot.get_user(uid)

    # 1. Off by default -- a brand-new user gets no medication reminder
    #    unless they explicitly opt in.
    assert int(user.get("notif_med_on") or 0) == 0, "notif_med_on must default to OFF (opt-in feature)"
    print("1. notif_med_on defaults to off for a new user")

    # 2. send_med_reminder sends a tracked message with a disable-notif row
    #    for its own kind ("med"), same pattern as the other notification
    #    channels.
    app = FakeApp()
    ok = await bot.send_med_reminder(app, uid)
    assert ok is True
    assert app.bot.sent, "send_med_reminder must actually send a message"
    chat_id, text, markup = app.bot.sent[0]
    assert "лекарств" in text.lower()
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert any(cb == "disable_notif_med" for cb in callbacks) or any(cb.startswith("snooze_notif_med") for cb in callbacks), \
        f"send_med_reminder must offer the same disable/snooze row as other notification kinds, got {callbacks}"
    print("2. send_med_reminder sends a real message with its own disable/snooze row")

    # 3. _settings_notifications_text_and_kb shows the medication slot and
    #    its own independent toggle/set buttons, separate from morning/day/
    #    evening.
    text2, kb2 = bot._settings_notifications_text_and_kb(bot.get_user(uid))
    assert "Лекарств" in text2
    callbacks2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    assert "toggle_med" in callbacks2 and "set_med" in callbacks2
    print("3. The notifications settings screen shows an independent medication toggle/time row")

    # 4. DISABLE_NOTIF_TARGETS includes "med" -- the in-message disable
    #    button actually resolves to a real column.
    assert "med" in bot.DISABLE_NOTIF_TARGETS
    assert bot.DISABLE_NOTIF_TARGETS["med"][0] == "notif_med_on"
    print("4. DISABLE_NOTIF_TARGETS wires the 'med' kind to notif_med_on")

    print("\nALL MED-REMINDER TESTS PASSED")


asyncio.run(main())
