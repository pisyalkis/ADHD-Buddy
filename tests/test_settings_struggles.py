import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_settings_struggles.db")
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

    async def edit_text(self, text, **kw):
        return self

    async def reply_text(self, text, **kw):
        return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = FakeMsg(uid)

    async def answer(self, *a, **kw): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-27): "главные трудности" (user.struggles)
    # were only ever set once, during onboarding (start_problem_checklist) --
    # no way to revisit them later even though they drive the daily skill
    # rotation (get_daily_skill) and the checkin's cause ordering
    # (PROBLEM_TO_MID/mid_procr_kb). Added a settings screen to edit them.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    bot.update_user(uid, struggles="resist,phone")

    # 1. ⚙️ Общие (main settings screen) links to the new screen.
    text, kb = bot._settings_main_text_and_kb(bot.get_user(uid))
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "go_settings_struggles" in callbacks, callbacks
    print("1. ⚙️ Общие links to 'go_settings_struggles'")

    # 2. The struggles screen shows every PROBLEM_ITEMS entry, checked
    #    correctly against the user's current selection.
    text2, kb2 = bot._settings_struggles_text_and_kb(bot.get_user(uid))
    buttons = [b for row in kb2.inline_keyboard for b in row]
    struggle_buttons = {b.callback_data: b.text for b in buttons if b.callback_data.startswith("toggle_struggle_")}
    assert len(struggle_buttons) == len(bot.PROBLEM_ITEMS), struggle_buttons
    assert struggle_buttons["toggle_struggle_resist"].startswith("✅ "), struggle_buttons["toggle_struggle_resist"]
    assert struggle_buttons["toggle_struggle_phone"].startswith("✅ "), struggle_buttons["toggle_struggle_phone"]
    assert struggle_buttons["toggle_struggle_scary"].startswith("▫️ "), struggle_buttons["toggle_struggle_scary"]
    print("2. The struggles screen lists every PROBLEM_ITEMS entry, correctly checked against current selection")

    # 3. Tapping an unchecked item adds it to user.struggles and persists.
    upd_add = FakeUpdate(uid, "toggle_struggle_scary")
    ctx = FakeCtx()
    await bot.toggle_struggle_callback(upd_add, ctx)
    selected_after_add = set((bot.get_user(uid).get("struggles") or "").split(","))
    assert selected_after_add == {"resist", "phone", "scary"}, selected_after_add
    print("3. Tapping an unchecked item adds it to user.struggles")

    # 4. Tapping an already-checked item removes it (toggle both ways).
    upd_remove = FakeUpdate(uid, "toggle_struggle_resist")
    ctx2 = FakeCtx()
    await bot.toggle_struggle_callback(upd_remove, ctx2)
    selected_after_remove = set((bot.get_user(uid).get("struggles") or "").split(","))
    assert selected_after_remove == {"phone", "scary"}, selected_after_remove
    print("4. Tapping an already-checked item removes it from user.struggles")

    # 5. A key with an underscore in it (unfinished_shame) round-trips
    #    correctly -- the "toggle_struggle_" prefix strip must not mangle it.
    upd_shame = FakeUpdate(uid, "toggle_struggle_unfinished_shame")
    ctx3 = FakeCtx()
    await bot.toggle_struggle_callback(upd_shame, ctx3)
    assert "unfinished_shame" in (bot.get_user(uid).get("struggles") or "").split(",")
    print("5. An underscore-containing key (unfinished_shame) round-trips correctly through the toggle")

    # 6. go_settings_struggles (the callback entry point) renders without error.
    upd_open = FakeUpdate(uid, "go_settings_struggles")
    ctx4 = FakeCtx()
    await bot.go_settings_struggles(upd_open, ctx4)  # must not raise
    print("6. go_settings_struggles renders the screen without error")

    print("\nALL SETTINGS-STRUGGLES TESTS PASSED")


asyncio.run(main())
