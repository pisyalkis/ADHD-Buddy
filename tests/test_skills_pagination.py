import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_skills_pagination.db")
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
        self.sent = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
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


def buttons_of(kb):
    return [[(b.text, b.callback_data) for b in row] for row in kb.inline_keyboard]


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: split the (19-item) skills list across two screens,
    # paged the same way as 📖 О СДВГ (dot navigation ●/○).
    # ══════════════════════════════════════════════════════════════════════
    half = (len(bot.SKILLS) + 1) // 2

    upd1 = FakeUpdate(uid, data="go_skill")
    ctx1 = FakeCtx()
    await bot.show_skill(upd1, ctx1)
    rows1 = buttons_of(upd1.callback_query.message.edited[-1][1])
    skill_buttons_1 = [cb for row in rows1 for _, cb in row if cb and cb.startswith("skill_")]
    assert len(skill_buttons_1) == half, skill_buttons_1
    assert skill_buttons_1 == [f"skill_{i}" for i in range(half)], skill_buttons_1
    dot_row_1 = [cb for row in rows1 for t, cb in row if cb and cb.startswith("skills_page_")]
    assert dot_row_1 == ["skills_page_0", "skills_page_1"], dot_row_1
    labels_1 = [t for row in rows1 for t, cb in row if cb and cb.startswith("skills_page_")]
    assert labels_1 == ["●", "○"], labels_1
    print("1. Page 0 shows the first half of the skills and marks itself with '●'")

    upd2 = FakeUpdate(uid, data="skills_page_1")
    ctx2 = FakeCtx()
    await bot.skills_page_nav(upd2, ctx2)
    rows2 = buttons_of(upd2.callback_query.message.edited[-1][1])
    skill_buttons_2 = [cb for row in rows2 for _, cb in row if cb and cb.startswith("skill_")]
    assert skill_buttons_2 == [f"skill_{i}" for i in range(half, len(bot.SKILLS))], skill_buttons_2
    labels_2 = [t for row in rows2 for t, cb in row if cb and cb.startswith("skills_page_")]
    assert labels_2 == ["○", "●"], labels_2
    print("2. Tapping the second dot shows the remaining skills and marks itself with '●'")

    # The page 2 -> page 1 dot must lead back correctly.
    upd3 = FakeUpdate(uid, data="skills_page_0")
    ctx3 = FakeCtx()
    await bot.skills_page_nav(upd3, ctx3)
    rows3 = buttons_of(upd3.callback_query.message.edited[-1][1])
    skill_buttons_3 = [cb for row in rows3 for _, cb in row if cb and cb.startswith("skill_")]
    assert skill_buttons_3 == skill_buttons_1, skill_buttons_3
    print("3. Navigating back to page 0 shows the first half again")

    # The daily-skill header and the non-paged footer buttons stay intact.
    text = upd1.callback_query.message.edited[-1][0]
    assert "Навык дня" in text, text
    flat3 = [cb for row in rows3 for _, cb in row]
    assert "go_buddy" in flat3 and "go_menu" in flat3 and "reroll_skill" in flat3, flat3
    print("4. The daily-skill header and footer buttons (buddy/menu/reroll) are unaffected by paging")

    print("\nALL SKILLS-PAGINATION TESTS PASSED")


asyncio.run(main())
