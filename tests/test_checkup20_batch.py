import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup20_batch.db")
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
        self.sent.append((chat_id, text, kw.get("reply_markup")))
    async def send_animation(self, **kw):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    tz_name = "Asia/Tbilisi"
    bot.update_user(uid, timezone=tz_name)
    tz = bot.get_user_tz(bot.get_user(uid))

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (20th checkup, dedicated whole-file sweep for the "empty-but
    # -truthy diary row" class, following up on round 19's midday_callback/
    # check_notifications instances): get_latest_evening_plan's bare
    # "if today:" check (already fixed once at the 11th checkup for a
    # DIFFERENT reason) breaks again in the opposite direction --
    # checkpoint_evening_progress always writes a full-key, all-empty
    # "evening" row for an interrupted-and-abandoned evening ritual, and
    # that row was masking yesterday's real plan.
    # ══════════════════════════════════════════════════════════════════════
    today_iso = datetime.now(tz).date().isoformat()
    yesterday_iso = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    bot.save_diary(uid, "evening", {"e_a": "Реальный план со вчера", "e_energy": 3}, for_date=yesterday_iso)
    # An interrupted evening ritual today wrote an all-empty row (only
    # e_selfcare_done was ever touched in ctx.user_data -- checkpoint writes
    # every OTHER key as its falsy default).
    bot.save_diary(uid, "evening", {
        "e_ach": "", "e_praise": "", "e_highlights": "",
        "e_a": "", "e_b1": "", "e_b2": "", "e_c1": "", "e_c2": "", "e_c3": "",
        "e_selfcare": [], "e_energy": 0, "e_tasks_done": [],
    }, for_date=today_iso)
    ev = bot.get_latest_evening_plan(uid)
    assert ev.get("e_a") == "Реальный план со вчера", \
        f"get_latest_evening_plan must fall back to yesterday's real plan when today's row is empty-but-present, got {ev}"
    print("1a. get_latest_evening_plan falls back to yesterday's real plan when today's evening row is empty-but-present")

    # Sanity: a genuinely real (if minimal) today's entry is still preferred.
    bot.save_diary(uid, "evening", {"e_a": "", "e_energy": 2}, for_date=today_iso)
    ev2 = bot.get_latest_evening_plan(uid)
    assert ev2.get("e_energy") == 2, \
        f"a real today's entry (non-default e_energy, even with e_a skipped) must still be preferred over yesterday, got {ev2}"
    print("1b. get_latest_evening_plan still prefers today's entry when it has genuinely real (non-default) data")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (20th checkup): send_task_beacon's own comment says the
    # beacon must NOT fire while no tasks have been set yet -- but
    # "if not morning: return" never caught the empty-but-present morning
    # row that finish_morning/checkpoint_morning_progress always write.
    # ══════════════════════════════════════════════════════════════════════
    bot.save_diary(uid, "morning", {k: "" for k in bot.TASK_KEYS}, for_date=today_iso)
    bot.update_user(
        uid, beacon_enabled=1, beacon_interval=2, beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent="", morning_filled_at="", midday_sent_date="",
    )
    app = FakeApp()
    await bot.send_task_beacon(app, bot.get_user(uid))
    assert not app.bot.sent, \
        f"send_task_beacon must not fire while today's morning has zero real tasks (even if the ritual row exists), got {app.bot.sent}"
    print("2a. send_task_beacon does not fire when today's morning row exists but has zero real tasks")

    bot.save_diary(uid, "morning", {"focus": "Реальная задача"}, for_date=today_iso)
    app2 = FakeApp()
    await bot.send_task_beacon(app2, bot.get_user(uid))
    assert app2.bot.sent, "send_task_beacon must still fire normally once a real task exists"
    print("2b. send_task_beacon still fires normally once a real task is set")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (20th checkup): build_day_card_text's "if morning:"/
    # "if evening:" showed dangling empty section headers, and the
    # friendly "Пока пусто..." fallback never appeared, when the diary
    # rows existed but were entirely empty.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Второй', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid2, timezone=tz_name)
    today2 = datetime.now(bot.get_user_tz(bot.get_user(uid2))).date().isoformat()
    bot.save_diary(uid2, "morning", {k: "" for k in bot.TASK_KEYS}, for_date=today2)
    bot.save_diary(uid2, "evening", {"e_a": "", "e_energy": 0}, for_date=today2)
    card_text = bot.build_day_card_text(uid2, today2)
    assert "☀️ *Утро*" not in card_text, card_text
    assert "🌙 *Вечер*" not in card_text, card_text
    assert "Пока пусто" in card_text, card_text
    print("3a. build_day_card_text shows no dangling empty section headers and the 'Пока пусто' fallback for an all-empty day")

    bot.save_diary(uid2, "morning", {"focus": "Настоящая задача"}, for_date=today2)
    card_text2 = bot.build_day_card_text(uid2, today2)
    assert "☀️ *Утро*" in card_text2, card_text2
    assert "Настоящая задача" in card_text2, card_text2
    assert "Пока пусто" not in card_text2, card_text2
    print("3b. build_day_card_text still shows the morning section normally once real data exists")

    print("\nALL CHECKUP20-BATCH TESTS PASSED")


asyncio.run(main())
