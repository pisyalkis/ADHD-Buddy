import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_animation.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()


class FakeAnimationResult:
    def __init__(self, file_id):
        self.animation = type("A", (), {"file_id": file_id})


class FakeBot:
    def __init__(self):
        self.animations_sent = []
        self.messages_sent = []
        self._anim_counter = 0
    async def send_animation(self, chat_id, animation, **kw):
        self._anim_counter += 1
        self.animations_sent.append((chat_id, animation))
        return FakeAnimationResult(f"fake_file_id_{self._anim_counter}")
    async def send_message(self, chat_id, text, **kw):
        self.messages_sent.append((chat_id, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1
    bot.update_user(uid, timezone="Asia/Tbilisi", skill_beacon_enabled=1,
                     skill_beacon_mode="interval", skill_beacon_interval=1,
                     skill_beacon_last_sent="", beacon_start="00:00", beacon_end="23:59",
                     beacon_types="breathing")
    bot._skill_animation_file_ids.clear()

    # ══════════════════════════════════════════════════════════════════════
    # Bug (reported by Artem): the skill beacon suggested a technique that
    # has an accompanying animation (e.g. breathing) but never sent it --
    # only the text prompt, unlike the 🧠 Навыки catalog which does send it.
    # ══════════════════════════════════════════════════════════════════════
    app = FakeApp()
    await bot.send_skill_beacon(app, bot.get_user(uid))
    assert len(app.bot.animations_sent) == 1, \
        f"the breathing technique must send its animation, got {app.bot.animations_sent}"
    assert app.bot.animations_sent[0][0] == uid
    assert len(app.bot.messages_sent) == 1
    assert "Дыхание" in app.bot.messages_sent[0][1]
    print("1. send_skill_beacon sends the breathing animation alongside the text prompt")

    # ── Second call re-uses the cached file_id instead of re-uploading ─────
    bot.update_user(uid, skill_beacon_last_sent="")
    app2 = FakeApp()
    await bot.send_skill_beacon(app2, bot.get_user(uid))
    assert len(app2.bot.animations_sent) == 1
    assert app2.bot.animations_sent[0][1] == "fake_file_id_1", \
        "a second send must reuse the cached file_id, not reopen/reupload the gif"
    print("2. Animation file_id is cached and reused on subsequent sends")

    # ══════════════════════════════════════════════════════════════════════
    # A technique WITHOUT an animation (e.g. "stop") must not try to send one.
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, skill_beacon_last_sent="", beacon_types="stop")
    app3 = FakeApp()
    await bot.send_skill_beacon(app3, bot.get_user(uid))
    assert app3.bot.animations_sent == [], app3.bot.animations_sent
    assert len(app3.bot.messages_sent) == 1
    print("3. A technique without an animation (СТОП) sends only the text, no animation attempt")

    print("\nALL BEACON-ANIMATION TESTS PASSED")


asyncio.run(main())
