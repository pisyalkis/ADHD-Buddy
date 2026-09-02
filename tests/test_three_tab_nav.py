import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_three_tab_nav.db")
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
            raise Exception("message too old to edit")
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
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")
    user = bot.get_user(uid)

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: navigation felt overloaded -- main menu had 7 buttons
    # plus an "Ещё" hiding 8 more, two levels deep. New: three always-visible
    # tabs (Сегодня / Инструменты / Я), each capped at ~5 items, switching
    # in place rather than piling up new messages.
    # ══════════════════════════════════════════════════════════════════════
    kb_today = bot.main_menu(user)
    today_buttons = buttons_of(kb_today)
    assert today_buttons[0] == ("[ Сегодня ]", "noop"), today_buttons
    assert ("Инструменты", "go_tab_tools") in today_buttons, today_buttons
    assert ("Настройки", "go_tab_me") in today_buttons, today_buttons
    assert ("☀️ Утро", "go_morning") in today_buttons
    assert ("🌙 Вечер", "go_evening") in today_buttons
    assert ("📋 Задачи", "go_tasks") in today_buttons
    assert ("🍅 Фокус-режим", "go_focus") in today_buttons
    assert ("🤖 Коуч", "go_coach") in today_buttons
    assert ("🔥 Стрик", "go_streak") in today_buttons
    # No item hidden two levels deep any more -- nothing named "Ещё".
    assert not any(t == "🧩 Ещё" for t, _ in today_buttons), today_buttons
    print("1. main_menu ('today' tab) shows the daily actions plus an active tab indicator")

    kb_tools = bot.menu_tab_kb("tools", user)
    tools_buttons = buttons_of(kb_tools)
    assert tools_buttons[0] == ("Сегодня", "go_tab_today"), tools_buttons
    assert tools_buttons[1] == ("[ Инструменты ]", "noop"), tools_buttons
    assert ("📔 Мой дневник", "go_daycard") in tools_buttons
    assert ("📥 Список дел", "go_task_pool") in tools_buttons
    assert ("⏰ Напоминания", "go_reminders") in tools_buttons
    assert ("🧠 Навыки", "go_skill") in tools_buttons
    assert ("📖 О СДВГ", "go_guide") in tools_buttons
    # ≤5 real items per tab (excluding the tab-switcher row itself).
    assert len(tools_buttons) - 3 <= 5, tools_buttons
    print("2. menu_tab_kb('tools') groups the occasional-use items, capped at 5")

    kb_me = bot.menu_tab_kb("me", user)
    me_buttons = buttons_of(kb_me)
    assert ("[ Настройки ]", "noop") in me_buttons, me_buttons
    assert ("⚙️ Общие", "go_settings") in me_buttons, me_buttons
    assert ("💎 Подписка", "go_subscribe") in me_buttons
    assert ("🆕 Что нового", "go_whats_new") in me_buttons
    assert ("ℹ️ О боте", "go_about") in me_buttons
    assert ("💬 Обратная связь", "go_feedback") in me_buttons
    assert len(me_buttons) - 3 <= 5, me_buttons
    print("3. menu_tab_kb('me') ('Настройки' tab) groups account/about items, capped at 5")

    # Streak button honors streak_hidden exactly like before, on the 'today' tab.
    bot.update_user(uid, streak_hidden=1)
    kb_today_hidden = bot.main_menu(bot.get_user(uid))
    assert not any(cb == "go_streak" for _, cb in buttons_of(kb_today_hidden))
    bot.update_user(uid, streak_hidden=0)
    print("4. streak_hidden still hides the 'Стрик' button on the 'today' tab")

    # ══════════════════════════════════════════════════════════════════════
    # Tapping a tab EDITS the same message in place (real tab feel), not a
    # new message every time; falls back to a fresh message if the edit fails
    # (e.g. message too old to edit).
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate(uid, data="go_tab_tools")
    await bot.go_tab(upd, FakeCtx())
    assert len(upd.callback_query.message.edited) == 1, upd.callback_query.message.edited
    edited_text, edited_kb = upd.callback_query.message.edited[0]
    assert "Инструменты" in edited_text
    assert ("📖 О СДВГ", "go_guide") in buttons_of(edited_kb)
    assert len(upd.callback_query.message.sent) == 0
    print("5. go_tab_tools edits the existing message in place")

    upd2 = FakeUpdate(uid, data="go_tab_me")
    upd2.callback_query.message.edit_should_fail = True
    await bot.go_tab(upd2, FakeCtx())
    assert len(upd2.callback_query.message.sent) == 1
    sent_text, sent_kb = upd2.callback_query.message.sent[0]
    assert ("⚙️ Общие", "go_settings") in buttons_of(sent_kb)
    print("6. go_tab falls back to a new message when editing the old one fails")

    # go_menu_more (legacy "Ещё" callback data, still reachable from any
    # message a user hasn't refreshed) now opens the 'tools' tab, editing
    # in place like the rest of the menu (same "always one message" fix
    # applied to go_menu/go_tab).
    ctx3 = FakeCtx()
    ctx3.user_data["awaiting_name"] = True
    upd3 = FakeUpdate(uid, data="go_menu_more")
    await bot.go_menu_more(upd3, ctx3)
    assert upd3.callback_query.message.sent == []
    sent3_text, sent3_kb = upd3.callback_query.message.edited[0]
    assert ("📔 Мой дневник", "go_daycard") in buttons_of(sent3_kb)
    assert ctx3.user_data.get("awaiting_name") in (False, None)
    print("7. go_menu_more (legacy 'Ещё' callback) opens the tools tab in place and still clears stale flags")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: the trailing pointing-finger emoji ("👇") on menu/tab
    # titles read as if it were pointing at the tab-switcher row itself
    # rather than the buttons below it -- dropped from every menu entry text.
    # ══════════════════════════════════════════════════════════════════════
    upd_menu = FakeUpdate(uid, data="go_menu")
    await bot.go_menu(upd_menu, FakeCtx())
    assert "👇" not in upd_menu.callback_query.message.edited[0][0]
    print("8a. go_menu's greeting no longer has the pointing-finger emoji")

    upd_more = FakeUpdate(uid, data="go_menu_more")
    ctx_more = FakeCtx()
    await bot.go_menu_more(upd_more, ctx_more)
    assert "👇" not in upd_more.callback_query.message.edited[0][0]
    print("8b. go_menu_more's title no longer has the pointing-finger emoji")

    for tab in ("today", "tools", "me"):
        upd_t = FakeUpdate(uid, data=f"go_tab_{tab}")
        await bot.go_tab(upd_t, FakeCtx())
        assert "👇" not in upd_t.callback_query.message.edited[0][0], tab
    print("8c. go_tab's titles no longer have the pointing-finger emoji, for every tab")

    print("\nALL THREE-TAB-NAV TESTS PASSED")


asyncio.run(main())
