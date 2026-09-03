import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_skill_anim_ttl.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class SentMsg:
    def __init__(self, mid):
        self.message_id = mid
        self.animation = None


class FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self._next_id = 500
    async def send_animation(self, chat_id, animation, **kw):
        self.sent.append((chat_id, kw))
        mid = self._next_id
        self._next_id += 1
        return SentMsg(mid)
    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)
    async def send_message(self, chat_id, text, **kw):
        mid = self._next_id
        self._next_id += 1
        return SentMsg(mid)


def has_scheduled_deletion(chat_id, message_id):
    conn = sqlite3.connect(bot.DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM scheduled_deletions WHERE chat_id=? AND message_id=?", (chat_id, message_id)
    ).fetchone()
    conn.close()
    return row is not None


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")

    # ══════════════════════════════════════════════════════════════════════
    # Bug: _send_tracked_animation never scheduled its own self-delete --
    # unlike its text companion (send_tracked_notification), which
    # self-deletes after INACTIVE_SCREEN_TTL_SEC of silence. If the user
    # never answers the beacon, the text vanishes but the animation is
    # orphaned in the chat forever, with no button left to clean it up.
    # ══════════════════════════════════════════════════════════════════════
    fake_bot = FakeBot()
    sent = await bot._send_tracked_animation(fake_bot, uid, "skill_anim", b"fake-gif-bytes")
    assert not has_scheduled_deletion(uid, sent.message_id), \
        "sanity: with no ttl_seconds, the old (still-correct) behavior -- no self-delete -- is preserved"
    print("1. _send_tracked_animation without ttl_seconds still doesn't self-delete (catalog screens unaffected)")

    fake_bot2 = FakeBot()
    sent2 = await bot._send_tracked_animation(
        fake_bot2, uid, "skill_anim", b"fake-gif-bytes", ttl_seconds=bot.INACTIVE_SCREEN_TTL_SEC
    )
    assert has_scheduled_deletion(uid, sent2.message_id), \
        "with ttl_seconds passed explicitly, the animation must schedule its own self-delete"
    print("2. _send_tracked_animation with ttl_seconds schedules a self-delete, matching its text companion")

    # ══════════════════════════════════════════════════════════════════════
    # End-to-end: send_skill_beacon's own animation call must now pass
    # ttl_seconds, so a real beacon firing schedules cleanup for the gif.
    # ══════════════════════════════════════════════════════════════════════
    uid2 = 2
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Вика', 'F')")
    conn.commit(); conn.close()
    tz = bot.pytz.timezone("Asia/Tbilisi")
    now = datetime.now(tz)
    bot.update_user(
        uid2, timezone="Asia/Tbilisi", skill_beacon_enabled=1,
        beacon_types="breathing", beacon_start="00:00", beacon_end="23:59",
        skill_beacon_mode="interval", skill_beacon_interval=1,
        skill_beacon_last_sent=(now - timedelta(hours=2)).isoformat(),
    )
    # Give the user a filled-out morning so send_skill_beacon doesn't bail early.
    today_iso = now.date().isoformat()
    bot.save_diary(uid2, "morning", {"focus": "Написать отчёт"}, for_date=today_iso)

    class FakeApp:
        def __init__(self):
            self.bot = FakeBot()

    app = FakeApp()
    await bot.send_skill_beacon(app, bot.get_user(uid2))

    assert app.bot.sent, "sanity: send_skill_beacon must have sent the animation (breathing has a gif)"
    anim_mid = bot._get_notif_msg_id(uid2, "skill_anim")
    assert anim_mid is not None, "sanity: the animation must be tracked under the skill_anim channel"
    assert has_scheduled_deletion(uid2, anim_mid), \
        "send_skill_beacon's animation must schedule a self-delete matching its text prompt's TTL"
    print("3. send_skill_beacon's own animation call now schedules a self-delete")

    print("\nALL SKILL-ANIM-TTL TESTS PASSED")


asyncio.run(main())
