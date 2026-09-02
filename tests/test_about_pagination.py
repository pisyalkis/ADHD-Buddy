import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_about_pagination.db")
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
        self.edit_should_fail = False
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message too old to edit")
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

    # ══════════════════════════════════════════════════════════════════════
    # Real request: split "О боте" into pages, same principle as 📖 О СДВГ
    # (dot navigation ●/○, "Далее" button), instead of one long screen.
    # ══════════════════════════════════════════════════════════════════════
    upd = FakeUpdate(uid, data="go_about")
    ctx = FakeCtx()
    await bot.go_about(upd, ctx)
    msg = upd.callback_query.message
    assert msg.edited and not msg.sent, "go_about must edit in place"
    text0, kb0 = msg.edited[-1]
    rows0 = buttons_of(kb0)
    dot_labels_0 = [t for row in rows0 for t, cb in row if cb and cb.startswith("about_")]
    assert dot_labels_0.count("●") == 1 and dot_labels_0[0] == "●", dot_labels_0
    flat0 = [cb for row in rows0 for _, cb in row]
    assert "go_privacy" in flat0 and "go_menu" in flat0, flat0
    print("1. go_about opens the first page, editing in place, with dot navigation and the privacy/menu footer")

    # Tapping "Далее" (about_day_structure) must edit the SAME message.
    next_cb = next(cb for row in rows0 for t, cb in row if t.startswith("Далее"))
    upd2 = FakeUpdate(uid, data=next_cb)
    upd2.callback_query.message = msg
    await bot.about_section(upd2, FakeCtx())
    assert len(msg.edited) == 2 and not msg.sent, msg.edited
    text1 = msg.edited[-1][0]
    assert "Утром" in text1 and "Днём" in text1 and "Вечером" in text1, text1
    print("2. 'Далее' pages to the day-structure section, editing the same message")

    # Every page must be reachable via its own dot, and only ONE dot is active at a time.
    for section_id in bot.ABOUT_SECTIONS:
        upd_dot = FakeUpdate(uid, data=f"about_{section_id}")
        upd_dot.callback_query.message = msg
        await bot.about_section(upd_dot, FakeCtx())
        rows = buttons_of(msg.edited[-1][1])
        dots = [(t, cb) for row in rows for t, cb in row if cb and cb.startswith("about_")]
        active = [t for t, cb in dots if t == "●"]
        assert active == ["●"], (section_id, dots)
        assert (f"about_{section_id}" in [cb for t, cb in dots if t == "●"]), (section_id, dots)
    print("3. Every section is reachable via its own dot, exactly one dot marked active each time")

    # The last section has no "Далее" button.
    upd_last = FakeUpdate(uid, data="about_science")
    upd_last.callback_query.message = msg
    await bot.about_section(upd_last, FakeCtx())
    rows_last = buttons_of(msg.edited[-1][1])
    flat_last = [t for row in rows_last for t, _ in row]
    assert not any(t.startswith("Далее") for t in flat_last), flat_last
    print("4. The last page has no 'Далее' button")

    # Falls back to a new message when editing fails.
    msg.edit_should_fail = True
    upd_fail = FakeUpdate(uid, data="go_about")
    upd_fail.callback_query.message = msg
    await bot.go_about(upd_fail, FakeCtx())
    assert msg.sent, "must fall back to a new message when editing fails"
    print("5. Falls back to a new message when editing the old one fails")

    print("\nALL ABOUT-PAGINATION TESTS PASSED")


asyncio.run(main())
