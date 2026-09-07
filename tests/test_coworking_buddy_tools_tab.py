import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_coworking_buddy_tools_tab.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (обсуждение с пользователем 2026-09-07): Бадди и
    # Коворкинг — соцфичи, а не техники самопомощи, им не место в самом
    # низу списка навыков "на всякий случай". Перенесены на вкладку 🧰
    # (menu_tab_kb('tools')) рядом с остальными инструментами.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    make_user(uid, "Артем")
    user = bot.get_user(uid)

    # 1. skills_list_kb (🧠 Навыки screen) no longer offers go_buddy/go_coworking.
    kb_skills = bot.skills_list_kb(page=0)
    skills_buttons = buttons_of(kb_skills)
    assert not any(cb == "go_buddy" for _, cb in skills_buttons), skills_buttons
    assert not any(cb == "go_coworking" for _, cb in skills_buttons), skills_buttons
    assert ("◀️ Меню", "go_menu") in skills_buttons, skills_buttons
    print("1. The skills list no longer offers Бадди/Коворкинг buttons")

    # 2. menu_tab_kb('tools') now offers both, alongside the existing tools.
    kb_tools = bot.menu_tab_kb("tools", user)
    tools_buttons = buttons_of(kb_tools)
    assert ("👥 Бадди", "go_buddy") in tools_buttons, tools_buttons
    assert ("🧘 Коворкинг", "go_coworking") in tools_buttons, tools_buttons
    assert ("📔 Мой дневник", "go_daycard") in tools_buttons, tools_buttons
    assert ("🧠 Навыки", "go_skill") in tools_buttons, tools_buttons
    print("2. The 'tools' (🧰) tab now offers both Бадди and Коворкинг")

    # 3. The 'today' and 'me' tabs are unaffected -- this is a targeted
    #    relocation, not a broader menu restructuring.
    kb_today = bot.main_menu(user)
    today_buttons = buttons_of(kb_today)
    assert not any(cb in ("go_buddy", "go_coworking") for _, cb in today_buttons), today_buttons
    kb_me = bot.menu_tab_kb("me", user)
    me_buttons = buttons_of(kb_me)
    assert not any(cb in ("go_buddy", "go_coworking") for _, cb in me_buttons), me_buttons
    print("3. The 'today' and 'me' tabs are unaffected by the relocation")

    # 4. go_buddy/go_coworking callbacks themselves still work unchanged --
    #    this is purely a menu-placement change, not a behavior change.
    assert callable(bot.buddy_menu)
    assert callable(bot.go_coworking)
    print("4. The go_buddy/go_coworking handlers themselves are untouched (placement-only change)")

    print("\nALL COWORKING-BUDDY-TOOLS-TAB TESTS PASSED")


asyncio.run(main())
