import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_day_container_quick_controls.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.pinned = []
        self.unpinned = []
    async def send_message(self, chat_id, text=None, **kw):
        text = text if text is not None else kw.get("text")
        self.sent.append((chat_id, text, kw.get("reply_markup")))
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append((chat_id, message_id, text))
    async def pin_chat_message(self, chat_id, message_id, **kw):
        self.pinned.append((chat_id, message_id))
    async def unpin_chat_message(self, chat_id, message_id, **kw):
        self.unpinned.append((chat_id, message_id))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeMsg:
    def __init__(self, message_id=555):
        self.sent = []
        self.message_id = message_id
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return FakeMsg(message_id=self.message_id + 1)
    @property
    def last_text(self):
        return self.sent[-1][0]
    @property
    def last_kb(self):
        return self.sent[-1][1]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
        self.answers = []
    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = type("C", (), {"id": uid})()


class FakeCtx:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot or FakeBot()


def all_kb_buttons(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (voice memo): notes were pinned but users didn't
    # realize why / that it was intentional -- wanted the bot to say
    # explicitly "I pinned this so it's easy to come back to".
    # Also: a daily-conscious-choice ask for task/skill reminders, right
    # on the day's anchor message.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    msg = FakeMsg(message_id=1000)
    today_iso = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=today_iso)
    ctx.user_data.clear()
    await bot.finish_morning(msg, uid, ctx)
    summary_text = msg.last_text
    assert "📌" in summary_text and "Закрепил" in summary_text, summary_text
    kb = msg.last_kb
    buttons = all_kb_buttons(kb)
    assert ("quick_toggle_beacon" in [cb for _, cb in buttons])
    assert ("quick_toggle_skill" in [cb for _, cb in buttons])
    print("1. finish_morning's summary explains it was pinned and offers quick reminder toggles")

    # Empty morning (no tasks at all) -- must NOT claim it pinned something
    # it didn't, since pin_today_tasks is skipped for an empty summary.
    ctx_empty = FakeCtx()
    msg_empty = FakeMsg(message_id=2000)
    bot.update_user(uid, focus="", buddy_name=bot.get_user(uid).get("buddy_name"))
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("DELETE FROM diary WHERE user_id=? AND block='morning'", (uid,))
    conn.commit(); conn.close()
    await bot.finish_morning(msg_empty, uid, ctx_empty)
    assert "Закрепил" not in msg_empty.last_text, msg_empty.last_text
    print("2. finish_morning does NOT claim to have pinned when there's nothing to pin (empty summary)")

    # ══════════════════════════════════════════════════════════════════════
    # Quick toggles on the pinned message flip the right flag, confirm via
    # toast (not by rewriting the whole message -- that would destroy the
    # pinned summary), and redraw just the keyboard.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, beacon_enabled=1, skill_beacon_enabled=0)
    upd = FakeUpdate(uid, data="quick_toggle_beacon")
    await bot.quick_toggle_beacon(upd, ctx)
    assert int(bot.get_user(uid).get("beacon_enabled") or 0) == 0
    assert "выключен" in upd.callback_query.answers[0]
    print("3. quick_toggle_beacon flips beacon_enabled and confirms via toast")

    upd2 = FakeUpdate(uid, data="quick_toggle_skill")
    await bot.quick_toggle_skill(upd2, ctx)
    assert int(bot.get_user(uid).get("skill_beacon_enabled") or 0) == 1
    assert "включ" in upd2.callback_query.answers[0]
    print("4. quick_toggle_skill flips skill_beacon_enabled and confirms via toast")

    # ══════════════════════════════════════════════════════════════════════
    # Closing the day: the pinned message gets edited to show it's closed
    # BEFORE being unpinned, instead of silently vanishing from the pin bar.
    # ══════════════════════════════════════════════════════════════════════
    fake_bot = FakeBot()
    ctx2 = FakeCtx(bot=fake_bot)
    bot.update_user(uid, pinned_msg_id="1234")
    await bot.unpin_today_tasks(ctx2, uid)
    assert fake_bot.edited and fake_bot.edited[0][1] == 1234
    assert "День закрыт" in fake_bot.edited[0][2]
    assert fake_bot.unpinned and fake_bot.unpinned[0][1] == 1234
    assert bot.get_user(uid).get("pinned_msg_id") == ""
    print("5. unpin_today_tasks edits the pinned message to '✅ День закрыт' before actually unpinning it")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback: "на уведомлениях была возможность их выключить, если
    # бесят" -- every notification type below must carry a one-tap disable
    # button, routed to the correct DB column.
    # ══════════════════════════════════════════════════════════════════════
    for kind, column in [
        ("morning", "notif_morning_on"),
        ("midday", "notif_midday_on"),
        ("evening", "notif_evening_on"),
        ("beacon", "beacon_enabled"),
        ("skillbeacon", "skill_beacon_enabled"),
    ]:
        bot.update_user(uid, **{column: 1})
        upd_dis = FakeUpdate(uid, data=f"disable_notif_{kind}")
        await bot.disable_notification_type(upd_dis, ctx)
        assert int(bot.get_user(uid).get(column) or 0) == 0, f"{kind} must disable {column}"
        assert upd_dis.callback_query.answers[0], "must confirm via toast"
        assert "⚙️ Настройки" in upd_dis.callback_query.answers[0]
    print("6. disable_notif_<kind> correctly flips the matching column for all 5 notification types")

    # ══════════════════════════════════════════════════════════════════════
    # Each of the 5 real notification-sending functions must actually
    # include that disable button in what gets sent -- not just that the
    # handler exists in isolation.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    user = bot.get_user(uid)
    bot.update_user(uid, notif_morning_on=1)
    await bot.morning_notification(app, uid)
    kb_morning = app.bot.sent[-1][2]
    assert ("disable_notif_morning" in [cb for _, cb in all_kb_buttons(kb_morning)])
    print("7. morning_notification includes disable_notif_morning")

    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat())
    await bot.midday_notification(app, uid)
    kb_midday = app.bot.sent[-1][2]
    assert ("disable_notif_midday" in [cb for _, cb in all_kb_buttons(kb_midday)])
    print("8. midday_notification includes disable_notif_midday")

    bot.update_user(uid, beacon_enabled=1, beacon_interval=2, beacon_start="00:00", beacon_end="23:59",
                     beacon_last_sent="", morning_filled_at="", midday_sent_date="")
    await bot.send_task_beacon(app, bot.get_user(uid))
    kb_beacon = app.bot.sent[-1][2]
    assert ("disable_notif_beacon" in [cb for _, cb in all_kb_buttons(kb_beacon)])
    print("9. send_task_beacon includes disable_notif_beacon")

    bot.update_user(uid, skill_beacon_enabled=1, skill_beacon_mode="interval", skill_beacon_interval=1,
                     skill_beacon_last_sent="", beacon_types="stop", beacon_start="00:00", beacon_end="23:59")
    await bot.send_skill_beacon(app, bot.get_user(uid))
    kb_skill = app.bot.sent[-1][2]
    assert ("disable_notif_skillbeacon" in [cb for _, cb in all_kb_buttons(kb_skill)])
    assert "🔔 *Маячки внимания*" in app.bot.sent[-1][1]
    print("10. send_skill_beacon includes disable_notif_skillbeacon and self-labels '🔔 Маячки внимания'")

    bot.update_user(uid, notif_evening_on=1)
    await bot.evening_notification(app, uid)
    kb_evening = app.bot.sent[-1][2]
    assert ("disable_notif_evening" in [cb for _, cb in all_kb_buttons(kb_evening)])
    print("11. evening_notification includes disable_notif_evening")

    # ══════════════════════════════════════════════════════════════════════
    # Same class of fix as PR #118 (BEACON_TEXTS) -- BEACON_TECHNIQUE_PROMPTS
    # must self-label as "🔔 Маячки внимания" too, consistently.
    # ══════════════════════════════════════════════════════════════════════
    for text in bot.BEACON_TECHNIQUE_PROMPTS.values():
        assert text.startswith("🔔 *Маячки внимания*"), text
    print("12. All BEACON_TECHNIQUE_PROMPTS consistently self-label as '🔔 Маячки внимания'")

    print("\nALL DAY-CONTAINER-QUICK-CONTROLS TESTS PASSED")


asyncio.run(main())
