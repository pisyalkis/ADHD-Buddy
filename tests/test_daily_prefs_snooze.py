import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_daily_prefs_snooze.db")
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
        self.markups = []

    async def edit_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)


class FakeQuery:
    def __init__(self, uid, data, message):
        self.from_user = FakeUser(uid); self.data = data; self.message = message
        self.answers = []
    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, data, message):
        self.callback_query = FakeQuery(uid, data, message)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def kb_callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-29): quick_toggle_beacon/quick_toggle_skill
    # on the pinned daily message permanently disabled a beacon in one tap,
    # with no "not today" option -- the same gap already fixed for
    # disable_notif_row in PR #253 (which reuses the SAME notif_snooze_beacon/
    # notif_snooze_skillbeacon columns -- read here, but until now nothing
    # on the pinned message could ever WRITE them).
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    bot.update_user(uid, beacon_enabled=1, skill_beacon_enabled=1)

    # 1. Tapping an ENABLED beacon toggle shows the snooze/forever submenu
    #    instead of disabling instantly.
    msg = FakeMsg()
    upd = FakeUpdate(uid, "quick_toggle_beacon", msg)
    await bot.quick_toggle_beacon(upd, FakeCtx())
    assert int(bot.get_user(uid).get("beacon_enabled") or 0) == 1, "must not disable instantly"
    submenu_cbs = kb_callbacks(msg.markups[-1])
    assert "daily_snooze_beacon" in submenu_cbs and "daily_disable_beacon" in submenu_cbs and "daily_cancel_beacon" in submenu_cbs
    print("1. Tapping an enabled beacon toggle shows the snooze/forever/cancel submenu, not an instant disable")

    # 2. "😴 Не сегодня" snoozes for today (notif_snooze_beacon = today) and
    #    leaves beacon_enabled untouched -- the feature stays on for
    #    tomorrow, matching disable_notif_row's snooze semantics.
    upd2 = FakeUpdate(uid, "daily_snooze_beacon", msg)
    await bot.daily_prefs_snooze_today(upd2, FakeCtx())
    user = bot.get_user(uid)
    assert int(user.get("beacon_enabled") or 0) == 1, "snoozing for today must not touch the permanent enabled flag"
    today = bot.datetime.now(bot.get_user_tz(user)).date().isoformat()
    assert user.get("notif_snooze_beacon") == today
    print("2. '😴 Не сегодня' snoozes just for today via the existing notif_snooze_beacon column, feature stays on")

    # 3. send_task_beacon actually respects that snooze (reusing the guard
    #    already shipped in PR #253) -- end-to-end proof the two features
    #    are properly wired together, not just parallel unconnected columns.
    class FakeBot2:
        def __init__(self): self.sent = []
        async def send_message(self, chat_id, text, **kw):
            self.sent.append((chat_id, text)); return type("M", (), {"message_id": 1})()
    class FakeApp:
        def __init__(self): self.bot = FakeBot2()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, bot.datetime.now(bot.get_user_tz(user)).date().isoformat())
    app = FakeApp()
    await bot.send_task_beacon(app, bot.get_user(uid))
    assert not app.bot.sent, "send_task_beacon must respect the snooze written by the new daily-prefs submenu"
    print("3. send_task_beacon respects the snooze set from the pinned-message submenu (end-to-end wiring)")

    # 4. "🔕 Насовсем" actually disables the feature permanently.
    upd3 = FakeUpdate(uid, "daily_disable_skillbeacon", msg)
    await bot.daily_prefs_disable_forever(upd3, FakeCtx())
    assert int(bot.get_user(uid).get("skill_beacon_enabled") or 0) == 0
    print("4. '🔕 Насовсем' permanently disables the feature")

    # 5. "◀️ Отмена" leaves everything untouched and just redraws the
    #    normal daily_prefs_kb.
    bot.update_user(uid, beacon_enabled=1)
    upd4 = FakeUpdate(uid, "daily_cancel_beacon", msg)
    await bot.daily_prefs_cancel_snooze(upd4, FakeCtx())
    assert int(bot.get_user(uid).get("beacon_enabled") or 0) == 1
    cancel_cbs = kb_callbacks(msg.markups[-1])
    assert "quick_toggle_beacon" in cancel_cbs, "cancel must redraw the normal daily_prefs_kb, not leave the submenu up"
    print("5. '◀️ Отмена' changes nothing and restores the normal toggle keyboard")

    # 6. Regression: turning an OFF beacon back ON still works instantly, no
    #    submenu -- only the "turning off" direction got the extra step.
    bot.update_user(uid, beacon_enabled=0)
    upd5 = FakeUpdate(uid, "quick_toggle_beacon", msg)
    await bot.quick_toggle_beacon(upd5, FakeCtx())
    assert int(bot.get_user(uid).get("beacon_enabled") or 0) == 1, "re-enabling must stay instant, no submenu"
    print("6. Re-enabling a disabled beacon is still instant (no submenu) -- no regression")

    print("\nALL DAILY-PREFS-SNOOZE TESTS PASSED")


asyncio.run(main())
