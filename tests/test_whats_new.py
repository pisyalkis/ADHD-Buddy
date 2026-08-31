import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_whats_new.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("parse_mode")))


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.text = None
        self.reply_to_message = None
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


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


class FakeCmdUpdate:
    def __init__(self, uid):
        self.effective_user = FakeUser(uid)
        self.message = FakeMsg()


class FakeCtx:
    def __init__(self, args=None):
        self.user_data = {}
        self.args = args or []
        self.bot = FakeBot()


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: a "🆕 Что нового" button, shown only on request (not
    # pushed), that explains new functionality (not just what changed).
    # ══════════════════════════════════════════════════════════════════════
    assert len(bot.CHANGELOG) > 0, "CHANGELOG should be seeded with the recent real features"
    for entry in bot.CHANGELOG:
        assert entry.get("title") and entry.get("text"), entry
    print("1. CHANGELOG is a non-empty list of {title, text} entries")

    kb_me = bot.menu_tab_kb("me")
    assert ("🆕 Что нового", "go_whats_new") in buttons_of(kb_me), buttons_of(kb_me)
    print("2. 'Я' tab offers a '🆕 Что нового' button")

    upd = FakeUpdate(uid, data="go_whats_new")
    ctx = FakeCtx()
    ctx.user_data["awaiting_feedback"] = True
    await bot.show_whats_new(upd, ctx)
    text = upd.callback_query.message.last_text
    assert bot.CHANGELOG[0]["title"] in text, text
    assert bot.CHANGELOG[0]["text"] in text, text
    assert ctx.user_data.get("awaiting_feedback") in (False, None), \
        "show_whats_new must clear stale awaiting flags like every other menu-more entry"
    print("3. show_whats_new displays the latest changelog entries (title + usage explanation) and clears stale flags")

    # ══════════════════════════════════════════════════════════════════════
    # /broadcast latest -- pushes the SAME top changelog entry to everyone,
    # without the admin re-typing the explanation for a push announcement.
    # ══════════════════════════════════════════════════════════════════════
    bot.NOTIFY_USER_ID = 999
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Admin', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (998, 'ОптИн', 'M')")
    conn.commit(); conn.close()
    bot.update_user(998, timezone="Asia/Tbilisi", notify_updates=1)
    upd_admin = FakeCmdUpdate(999)
    ctx_admin = FakeCtx(args=["latest"])
    await bot.admin_broadcast(upd_admin, ctx_admin)
    sent_texts = [t for _, t, _ in ctx_admin.bot.sent]
    assert any(bot.CHANGELOG[0]["title"] in t and bot.CHANGELOG[0]["text"] in t for t in sent_texts), sent_texts
    print("4. /broadcast latest sends the top CHANGELOG entry to users who opted in")

    # Sanity: normal /broadcast <text> and reply-based broadcast still work
    # exactly as before (regression check on the pre-existing behavior).
    ctx_admin2 = FakeCtx(args=["Обычный", "текст", "рассылки"])
    await bot.admin_broadcast(upd_admin, ctx_admin2)
    sent_texts2 = [t for _, t, _ in ctx_admin2.bot.sent]
    assert any("Обычный текст рассылки" in t for t in sent_texts2), sent_texts2
    print("5. Normal /broadcast <text> still works exactly as before")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: add a checkbox on the "Что нового" screen to opt in/out
    # of receiving update announcements as messages.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone="Asia/Tbilisi")

    assert int(bot.get_user(uid2).get("notify_updates") or 0) == 0, \
        "notify_updates must default to opted-out -- update announcements are opt-in"
    print("6. notify_updates defaults to disabled for a fresh user")

    upd_wn = FakeUpdate(uid2, data="go_whats_new")
    await bot.show_whats_new(upd_wn, FakeCtx())
    kb_wn = upd_wn.callback_query.message.sent[0][1]
    wn_buttons = buttons_of(kb_wn)
    assert ("🔕 Присылать анонсы обновлений: выкл", "toggle_notify_updates") in wn_buttons, wn_buttons
    print("7. show_whats_new offers the opt-in toggle, showing the current (off) state")

    upd_toggle = FakeUpdate(uid2, data="toggle_notify_updates")
    await bot.toggle_notify_updates(upd_toggle, FakeCtx())
    assert int(bot.get_user(uid2).get("notify_updates")) == 1
    print("8a. toggle_notify_updates flips the flag on")

    await bot.toggle_notify_updates(upd_toggle, FakeCtx())
    assert int(bot.get_user(uid2).get("notify_updates")) == 0
    print("8b. toggle_notify_updates flips it back off")

    # /broadcast latest must respect the opt-out; a plain /broadcast <text>
    # must NOT be gated (admin's direct message goes to everyone as before).
    uid3 = 3
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'ОптАут', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid3, timezone="Asia/Tbilisi", notify_updates=0)

    ctx_admin3 = FakeCtx(args=["latest"])
    await bot.admin_broadcast(upd_admin, ctx_admin3)
    recipients = {cid for cid, _, _ in ctx_admin3.bot.sent}
    assert uid3 not in recipients, \
        f"a user who opted out of update announcements must not receive /broadcast latest, got recipients {recipients}"
    print("9. /broadcast latest skips users who opted out via the toggle")

    ctx_admin4 = FakeCtx(args=["Важное", "объявление"])
    await bot.admin_broadcast(upd_admin, ctx_admin4)
    recipients2 = {cid for cid, _, _ in ctx_admin4.bot.sent}
    assert uid3 in recipients2, \
        "a plain /broadcast <text> (not tied to the changelog) must still reach everyone, including update-announcement opt-outs"
    print("10. A plain /broadcast <text> is not gated by the update-announcement opt-out")

    # A fresh user who never touched the toggle must ALSO be excluded from
    # /broadcast latest by default (opt-out-by-default, not just explicit opt-out).
    uid5 = 5
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (5, 'Пятый', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid5, timezone="Asia/Tbilisi")

    ctx_admin5 = FakeCtx(args=["latest"])
    await bot.admin_broadcast(upd_admin, ctx_admin5)
    recipients5 = {cid for cid, _, _ in ctx_admin5.bot.sent}
    assert uid5 not in recipients5, \
        f"a never-toggled fresh user must default to opted-out of /broadcast latest, got recipients {recipients5}"
    print("11. A fresh user who never touched the toggle is excluded from /broadcast latest by default")

    print("\nALL WHATS-NEW TESTS PASSED")


asyncio.run(main())
