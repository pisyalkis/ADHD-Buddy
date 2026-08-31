import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_settings_single_message.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


_next_mid = [1000]

class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = _next_mid[0]
        _next_mid[0] += 1
        self.sent = []
        self.edited = []
        self.edit_should_fail = False
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        new = FakeMsg(self.chat_id)
        return new
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message is not modified")
        self.edited.append((text, kw.get("reply_markup")))
        return self


class FakeBot:
    def __init__(self, msg):
        self.msg = msg  # the single tracked settings message, shared across the test
        self.edit_calls = []
        self.raise_on_edit = False
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        if self.raise_on_edit or message_id != self.msg.message_id or chat_id != self.msg.chat_id:
            raise Exception("can't edit")
        self.edit_calls.append((chat_id, message_id, text, kw.get("reply_markup")))
        self.msg.edited.append((text, kw.get("reply_markup")))
    async def send_message(self, **kw): pass
    async def delete_message(self, chat_id, message_id):
        pass


class FakeQuery:
    def __init__(self, uid, msg, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = msg
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, msg, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, msg, data)
        self.message = None


class FakeTextUpdate:
    def __init__(self, uid, text):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = None
        self.message = FakeTextMsg(text)


class FakeTextMsg:
    def __init__(self, text):
        self.text = text
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


def pending_deletions(chat_id, message_id):
    conn = sqlite3.connect(bot.DB_PATH)
    rows = conn.execute(
        "SELECT delete_at FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (chat_id, message_id)
    ).fetchall()
    conn.close()
    return rows


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real request: "чтобы меню всегда было одним сообщением. Которое через
    # некоторое время удаляется" -- opening ⚙️ Общие must track its message
    # and schedule it for self-deletion after SETTINGS_MENU_TTL_SEC of
    # inactivity (reusing the existing scheduled_deletions/sweep infra from
    # the ritual-cleanup feature).
    # ══════════════════════════════════════════════════════════════════════
    msg = FakeMsg(uid)
    ctx = FakeCtx(bot=FakeBot(msg))
    upd = FakeUpdate(uid, msg, data="go_settings")
    await bot.go_settings(upd, ctx)
    assert ctx.user_data.get("settings_msg_id") == msg.message_id
    assert ctx.user_data.get("settings_chat_id") == msg.chat_id
    rows = pending_deletions(msg.chat_id, msg.message_id)
    assert len(rows) == 1, rows
    delta = (datetime.fromisoformat(rows[0][0]) - datetime.now()).total_seconds()
    assert bot.SETTINGS_MENU_TTL_SEC - 10 <= delta <= bot.SETTINGS_MENU_TTL_SEC + 10, delta
    print("1. go_settings tracks the settings message and schedules it for self-deletion in ~SETTINGS_MENU_TTL_SEC")

    # ══════════════════════════════════════════════════════════════════════
    # Navigating around inside settings (a chain of callback taps) must
    # stay on the SAME message the whole time, and must keep resetting the
    # deletion timer (not accumulate stale rows, not let an old row fire
    # early while the user is still actively using the screen).
    # ══════════════════════════════════════════════════════════════════════
    upd2 = FakeUpdate(uid, msg, data="go_settings_notifications")
    await bot.go_settings_notifications(upd2, ctx)
    upd3 = FakeUpdate(uid, msg, data="go_settings_beacon")
    await bot.go_settings_beacon(upd3, ctx)
    upd4 = FakeUpdate(uid, msg, data="toggle_beacon")
    await bot.toggle_beacon(upd4, ctx)
    assert msg.sent == [], "the whole navigation chain must never create a new message"
    rows_after = pending_deletions(msg.chat_id, msg.message_id)
    assert len(rows_after) == 1, f"repeated interaction must replace the pending deletion, not accumulate rows, got {rows_after}"
    print("2. Navigating notifications -> beacon -> toggle_beacon stays on one message and keeps exactly one pending deletion row")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug found while implementing this: toggle_notif (the "Включить/
    # выключить все" button) sent a brand new confirmation message instead
    # of redrawing the notifications screen in place -- same duplicate-
    # message bug as PR #156 fixed elsewhere, missed here at the time.
    # ══════════════════════════════════════════════════════════════════════
    upd5 = FakeUpdate(uid, msg, data="toggle_notif")
    await bot.toggle_notif(upd5, ctx)
    assert msg.sent == [], "toggle_notif must redraw in place, not send a new confirmation message"
    assert "Уведомления" in msg.edited[-1][0]
    print("3. toggle_notif (bug found during this work) now redraws the notifications screen in place instead of sending a new message")

    # ══════════════════════════════════════════════════════════════════════
    # set_name_prompt opens the name prompt on the SAME message (already
    # covered by PR #156's tests) -- now also confirm typing the answer as
    # PLAIN TEXT edits that same tracked message via ctx.bot.edit_message_text,
    # instead of update.message.reply_text (a NEW message) as before.
    # ══════════════════════════════════════════════════════════════════════
    upd6 = FakeUpdate(uid, msg, data="set_name")
    await bot.set_name_prompt(upd6, ctx)
    assert msg.sent == []
    assert ctx.user_data.get("awaiting_name") is True

    text_upd = FakeTextUpdate(uid, "Аня")
    await bot.handle_text(text_upd, ctx)
    assert text_upd.message.sent == [], \
        "typing the new name must edit the tracked settings message, not reply with a new one"
    assert ctx.bot.edit_calls, "handle_text must call ctx.bot.edit_message_text for the tracked settings message"
    last_call = ctx.bot.edit_calls[-1]
    assert last_call[0] == msg.chat_id and last_call[1] == msg.message_id
    assert "Аня" in last_call[2]
    print("4. Typing a new name edits the SAME tracked settings message via ctx.bot.edit_message_text, no new message")

    # Invalid time format retry must also edit in place.
    upd7 = FakeUpdate(uid, msg, data="set_morning")
    await bot.set_time_prompt(upd7, ctx)
    text_upd2 = FakeTextUpdate(uid, "not a time")
    await bot.handle_text(text_upd2, ctx)
    assert text_upd2.message.sent == []
    assert "Неверный формат" in ctx.bot.edit_calls[-1][2]
    print("5. An invalid time reply also edits the tracked settings message in place (retry prompt)")

    # A valid time answer edits in place too, with the beacon/notifications
    # back button depending on which block was being set.
    text_upd3 = FakeTextUpdate(uid, "08:15")
    await bot.handle_text(text_upd3, ctx)
    assert text_upd3.message.sent == []
    assert "08:15" in ctx.bot.edit_calls[-1][2]
    print("6. A valid time answer edits the tracked settings message in place too")

    # ══════════════════════════════════════════════════════════════════════
    # Fallback safety net: if there is no tracked settings message (e.g. a
    # flow that never opened ⚙️ Общие via callback first), handle_text must
    # fall back to sending a normal new message, exactly like before this
    # feature existed -- must not silently swallow the user's answer.
    # ══════════════════════════════════════════════════════════════════════
    ctx_notrack = FakeCtx(bot=FakeBot(FakeMsg(uid)))
    ctx_notrack.user_data["awaiting_name"] = True
    text_upd4 = FakeTextUpdate(uid, "Боря")
    await bot.handle_text(text_upd4, ctx_notrack)
    assert text_upd4.message.sent, "without a tracked settings message, handle_text must fall back to a normal reply"
    assert "Боря" in text_upd4.message.sent[0][0]
    print("7. Without a tracked settings message, handle_text falls back to a normal new message (no regression)")

    # ══════════════════════════════════════════════════════════════════════
    # The scheduled deletion is real, durable DB state -- sweep_scheduled_
    # deletions (the same ~1-minute cron tick that already sweeps ritual
    # confirmations) must actually delete the settings message once its
    # TTL elapses, and must leave it alone before that.
    # ══════════════════════════════════════════════════════════════════════
    class SweepApp:
        def __init__(self, bot): self.bot = bot
    sweep_bot = FakeBot(msg)
    deleted = []
    async def _delete_message(chat_id, message_id):
        deleted.append((chat_id, message_id))
    sweep_bot.delete_message = _delete_message
    app = SweepApp(sweep_bot)

    await bot.sweep_scheduled_deletions(app)
    assert deleted == [], "must not delete before the TTL is due"

    conn = sqlite3.connect(bot.DB_PATH)
    past = (datetime.now() - timedelta(seconds=5)).isoformat()
    conn.execute("UPDATE scheduled_deletions SET delete_at=? WHERE chat_id=? AND message_id=?", (past, msg.chat_id, msg.message_id))
    conn.commit(); conn.close()
    await bot.sweep_scheduled_deletions(app)
    assert (msg.chat_id, msg.message_id) in deleted
    print("8. sweep_scheduled_deletions deletes the settings message once its TTL is actually due")

    print("\nALL SETTINGS-SINGLE-MESSAGE TESTS PASSED")


asyncio.run(main())
