import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_vs_schedule_clarity.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (tester, voice memo): even after a week of daily use,
    # still confused "маячок" (beacon) with the scheduled утро/день/вечер
    # notifications. Root cause traced to the actual delivered message text
    # being structurally near-identical and only self-labeling as "маячок"
    # in 2 of 6 variants.
    # ══════════════════════════════════════════════════════════════════════
    for text in bot.BEACON_TEXTS:
        assert "Маячки внимания" in text, \
            f"every beacon variant must consistently self-label as 'Маячки внимания', got: {text}"
        assert text.startswith("🔔 "), \
            f"every beacon variant must use the same leading icon, so it's recognizable at a glance, got: {text}"
    print("1. All 6 BEACON_TEXTS variants consistently self-label as '🔔 Маячки внимания'")

    # ══════════════════════════════════════════════════════════════════════
    # send_task_beacon must include the same kind of settings-pointer footer
    # that midday_notification already has, so the moment of confusion
    # ("what is this?") comes with an immediate way out.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(
        uid, beacon_enabled=1, beacon_interval=2,
        beacon_start="00:00", beacon_end="23:59",
        beacon_last_sent="", morning_filled_at="",
        midday_sent_date="",
    )
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat())
    app = FakeApp()
    await bot.send_task_beacon(app, bot.get_user(uid))
    assert app.bot.sent, "beacon must actually fire under these settings"
    beacon_msg = app.bot.sent[0][1]
    assert "⚙️ Настройки" in beacon_msg, beacon_msg
    assert "🔔 *Маячки внимания*" in beacon_msg, beacon_msg
    print("2. send_task_beacon's message now points to ⚙️ Настройки, same as the scheduled midday check-in")

    # ══════════════════════════════════════════════════════════════════════
    # The notifications screen must explain the Утро/День/Вечер block --
    # the earlier asymmetry (only beacon explained) itself contributed to
    # the confusion. The beacon block itself now lives one level deeper, on
    # its own dedicated screen (_settings_beacon_text_and_kb).
    # ══════════════════════════════════════════════════════════════════════
    text, kb = bot._settings_notifications_text_and_kb(bot.get_user(uid))
    assert "Основной ритуал дня" in text, text
    beacon_text, beacon_kb = bot._settings_beacon_text_and_kb(bot.get_user(uid))
    assert "Маячки внимания" in beacon_text, beacon_text
    print("3. The notifications screen explains the scheduled Утро/День/Вечер block; the beacon screen self-labels as 'Маячки внимания'")

    print("\nALL BEACON-VS-SCHEDULE-CLARITY TESTS PASSED")


asyncio.run(main())
