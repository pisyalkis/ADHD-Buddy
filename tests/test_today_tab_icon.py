import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_today_tab_icon.db")
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
        self.edited = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
    async def reply_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self


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


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "Сегодня" tab title had no icon, unlike "🧩 Инструменты"
    # and "⚙️ Настройки".
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate(uid, data="go_tab_today")
    await bot.go_tab(upd, FakeCtx())
    text = upd.callback_query.message.edited[-1][0]
    assert text.startswith("📅"), text
    print("1. The 'Сегодня' tab title now has an icon, like the other two tabs")

    print("\nALL TODAY-TAB-ICON TESTS PASSED")


asyncio.run(main())
