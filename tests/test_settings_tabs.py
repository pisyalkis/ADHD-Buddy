import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_settings_tabs.db")
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
        self.edited = []
        self.edit_should_fail = False
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message is not modified")
        self.edited.append((text, kw.get("reply_markup")))


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
    bot.update_user(uid, timezone="Asia/Tbilisi", name="Артем", city="Тбилиси")
    user = bot.get_user(uid)

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "внутри ⚙️ Общие сделать закрытым — уведомления, тайм
    # зона, имя и т.д. открываются только по тапу, как основное меню".
    # The old 2-tab screen (🔔 Уведомления / 👤 Профиль) is replaced by a
    # 3-level flat+nested structure: a flat top list (🔔 Уведомления / ✏️ Имя /
    # 🌍 Город / 🎛 Редактировать отчёты / 🔥 Стрик / ◀️ Меню), where
    # 🔔 Уведомления opens its own screen (утро/день/вечер schedule), which
    # itself nests 📳 Маячки внимания as its own sub-screen one level deeper.
    # ══════════════════════════════════════════════════════════════════════
    text_main, kb_main = bot._settings_main_text_and_kb(user)
    main_buttons = buttons_of(kb_main)
    assert main_buttons[0] == ("🔔 Уведомления", "go_settings_notifications"), main_buttons
    assert ("✏️ Имя", "set_name") in main_buttons
    assert ("🌍 Город", "set_city") in main_buttons
    assert ("🎛 Редактировать отчёты", "edit_reports") in main_buttons
    assert any(cb == "toggle_streak_visibility" for _, cb in main_buttons)
    assert ("◀️ Меню", "go_menu") in main_buttons
    # Closed list -- no schedule/beacon detail leaks onto the top screen.
    assert not any(cb in ("toggle_morning", "toggle_beacon", "toggle_skill_beacon", "set_morning") for _, cb in main_buttons), \
        f"the top-level settings list must stay flat/closed, got {main_buttons}"
    print("1. _settings_main_text_and_kb is a flat closed list: Уведомления / Имя / Город / Редактировать отчёты / Стрик / Меню")

    text_n, kb_n = bot._settings_notifications_text_and_kb(user)
    n_buttons = buttons_of(kb_n)
    assert ("☀️ 09:00", "set_morning") in n_buttons or any(cb == "set_morning" for _, cb in n_buttons)
    assert any(cb == "toggle_morning" for _, cb in n_buttons)
    assert ("📳 Маячки →", "go_settings_beacon") in n_buttons, \
        "the beacon block must be nested one level deeper, behind its own button, not inlined here"
    assert not any(cb in ("toggle_beacon", "toggle_skill_beacon", "beacon_int_1") for _, cb in n_buttons), \
        f"beacon controls must not leak onto the notifications screen, got {n_buttons}"
    assert ("◀️ Общие", "go_settings") in n_buttons
    print("2. _settings_notifications_text_and_kb shows the schedule and a nested '📳 Маячки →' button, nothing else")

    text_b, kb_b = bot._settings_beacon_text_and_kb(user)
    b_buttons = buttons_of(kb_b)
    assert any(cb == "toggle_beacon" for _, cb in b_buttons)
    assert any(cb == "toggle_skill_beacon" for _, cb in b_buttons)
    assert ("◀️ Уведомления", "go_settings_notifications") in b_buttons
    assert not any(cb in ("toggle_morning", "set_morning") for _, cb in b_buttons), \
        f"schedule controls must not leak onto the beacon screen, got {b_buttons}"
    assert "Маячки внимания" in text_b
    print("3. _settings_beacon_text_and_kb is its own dedicated screen for both beacon types, with a back button to notifications")

    # ══════════════════════════════════════════════════════════════════════
    # Navigation: each screen edits the same message in place (same mechanic
    # as go_tab), and falls back to a new message only when editing fails.
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate(uid, data="go_settings")
    await bot.go_settings(upd, FakeCtx())
    assert len(upd.callback_query.message.edited) == 1
    assert "Общие" in upd.callback_query.message.edited[0][0]
    print("4. go_settings opens the flat top-level list, editing in place")

    upd2 = FakeUpdate(uid, data="go_settings_notifications")
    await bot.go_settings_notifications(upd2, FakeCtx())
    assert len(upd2.callback_query.message.edited) == 1
    assert "Уведомления" in upd2.callback_query.message.edited[0][0]
    print("5. go_settings_notifications opens the notifications screen, editing in place")

    upd3 = FakeUpdate(uid, data="go_settings_beacon")
    await bot.go_settings_beacon(upd3, FakeCtx())
    assert len(upd3.callback_query.message.edited) == 1
    assert "Маячки внимания" in upd3.callback_query.message.edited[0][0]
    print("6. go_settings_beacon opens the beacon screen, editing in place")

    upd4 = FakeUpdate(uid, data="go_settings")
    upd4.callback_query.message.edit_should_fail = True
    await bot.go_settings(upd4, FakeCtx())
    assert len(upd4.callback_query.message.sent) == 1
    print("7. go_settings falls back to a new message when editing the old one fails")

    # ══════════════════════════════════════════════════════════════════════
    # Every mutating handler must redraw the screen it actually belongs to.
    # ══════════════════════════════════════════════════════════════════════
    upd5 = FakeUpdate(uid, data="toggle_streak_visibility")
    await bot.toggle_streak_visibility(upd5, FakeCtx())
    redraw_text = upd5.callback_query.message.edited[0][0]
    assert "Общие" in redraw_text, "toggle_streak_visibility must redraw the top-level list it lives on"
    print("8. toggle_streak_visibility redraws the top-level list")

    upd6 = FakeUpdate(uid, data="toggle_morning")
    await bot.toggle_notif_block(upd6, FakeCtx())
    redraw_text6 = upd6.callback_query.message.edited[0][0]
    assert "Уведомления" in redraw_text6, "toggle_morning must redraw the notifications screen"
    print("9. toggle_notif_block (toggle_morning) redraws the notifications screen")

    upd7 = FakeUpdate(uid, data="toggle_beacon")
    await bot.toggle_beacon(upd7, FakeCtx())
    redraw_text7 = upd7.callback_query.message.edited[0][0]
    assert "Маячки внимания" in redraw_text7, "toggle_beacon must redraw the beacon screen, not notifications"
    print("10. toggle_beacon redraws the beacon screen specifically")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: opening a prompt from ⚙️ Общие (✏️ Имя, 🌍 Город, etc.)
    # must EDIT the current message in place, not send a new one -- otherwise
    # the old settings screen behind it is left untouched, and "Отмена"
    # (which edits that new prompt message back into settings) creates a
    # SECOND, duplicate settings screen instead of restoring the original.
    # ══════════════════════════════════════════════════════════════════════
    upd8 = FakeUpdate(uid, data="set_name")
    await bot.set_name_prompt(upd8, FakeCtx())
    assert upd8.callback_query.message.sent == [], \
        "set_name_prompt must edit the existing message, not send a new one (would leave a duplicate settings screen behind)"
    cancel_kb = upd8.callback_query.message.edited[0][1]
    assert ("Отмена", "go_settings") in buttons_of(cancel_kb)
    print("11. set_name_prompt edits in place; its cancel button returns to the top-level settings list")

    upd9 = FakeUpdate(uid, data="set_city")
    await bot.set_city_prompt(upd9, FakeCtx())
    assert upd9.callback_query.message.sent == []
    cancel_kb2 = upd9.callback_query.message.edited[0][1]
    assert ("Отмена", "go_settings") in buttons_of(cancel_kb2)
    print("12. set_city_prompt edits in place; its cancel button returns to the top-level settings list")

    reports_kb = bot._edit_reports_kb(user)
    assert ("◀️ Общие", "go_settings") in buttons_of(reports_kb)
    upd_reports = FakeUpdate(uid, data="edit_reports")
    await bot.edit_reports_menu(upd_reports, FakeCtx())
    assert upd_reports.callback_query.message.sent == [], \
        "edit_reports_menu must edit the existing message, not send a new one"
    print("13. edit_reports_menu edits in place; its back button returns to the top-level settings list")

    # set_time_prompt: cancel must route to the right screen depending on
    # WHICH time is being set -- notifications for morning/midday/evening,
    # beacon for beacon_start/beacon_end. Must also edit in place.
    upd10 = FakeUpdate(uid, data="set_morning")
    await bot.set_time_prompt(upd10, FakeCtx())
    assert upd10.callback_query.message.sent == []
    cancel_kb3 = upd10.callback_query.message.edited[0][1]
    assert ("Отмена", "go_settings_notifications") in buttons_of(cancel_kb3)
    print("14. set_time_prompt (set_morning) edits in place; cancels back to the notifications screen")

    upd11 = FakeUpdate(uid, data="set_beacon_start")
    await bot.set_time_prompt(upd11, FakeCtx())
    assert upd11.callback_query.message.sent == []
    cancel_kb4 = upd11.callback_query.message.edited[0][1]
    assert ("Отмена", "go_settings_beacon") in buttons_of(cancel_kb4)
    print("15. set_time_prompt (set_beacon_start) edits in place; cancels back to the beacon screen")

    beacon_types_kb = bot._beacon_types_kb(user)
    assert ("◀️ Маячки", "go_settings_beacon") in buttons_of(beacon_types_kb)
    upd_bt = FakeUpdate(uid, data="beacon_types_menu")
    await bot.beacon_types_menu(upd_bt, FakeCtx())
    assert upd_bt.callback_query.message.sent == [], \
        "beacon_types_menu must edit the existing message, not send a new one"
    print("16. beacon_types_menu edits in place; its back button returns to the beacon screen")

    # Full round trip on a SINGLE message: Общие -> ✏️ Имя -> Отмена -> back
    # at Общие, with nothing ever appended to .sent (no duplicate ever
    # created), only .edited.
    upd12 = FakeUpdate(uid, data="go_settings")
    await bot.go_settings(upd12, FakeCtx())
    msg = upd12.callback_query.message
    upd13 = FakeUpdate(uid, data="set_name")
    upd13.callback_query.message = msg  # same underlying message object
    await bot.set_name_prompt(upd13, FakeCtx())
    upd14 = FakeUpdate(uid, data="go_settings")
    upd14.callback_query.message = msg
    await bot.go_settings(upd14, FakeCtx())
    assert msg.sent == [], f"the whole Общие -> Имя -> Отмена round trip must never send a new message, got {msg.sent}"
    assert "Общие" in msg.edited[-1][0]
    print("17. The full Общие → ✏️ Имя → Отмена round trip stays on one message the whole way, no duplicate left behind")

    print("\nALL SETTINGS TABS TESTS PASSED")


asyncio.run(main())
