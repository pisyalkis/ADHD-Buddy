import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_skill_anim_cleared_when_no_gif.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeAnimationResult:
    _next_id = [7000]
    def __init__(self, file_id):
        self.animation = type("A", (), {"file_id": file_id})
        self.message_id = FakeAnimationResult._next_id[0]
        FakeAnimationResult._next_id[0] += 1


class FakeMsg:
    _next_id = [8000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
    async def reply_text(self, text, **kw):
        return FakeMsg(self.chat_id)
    async def edit_text(self, text, **kw):
        return self


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg(uid)
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)


class FakeBot:
    def __init__(self):
        self.animations_sent = []
        self.deleted = []
        self._anim_counter = 0
    async def send_animation(self, chat_id, animation, **kw):
        self._anim_counter += 1
        self.animations_sent.append((chat_id, animation))
        return FakeAnimationResult(f"fake_file_id_{self._anim_counter}")
    async def send_message(self, chat_id, text, **kw):
        return FakeMsg(chat_id)
    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
    async def edit_message_text(self, chat_id, message_id, text, **kw):
        pass


class FakeCtx:
    def __init__(self, bot):
        self.user_data = {}
        self.bot = bot


class FakeApp:
    def __init__(self, bot):
        self.bot = bot


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    bot._skill_animation_file_ids.clear()

    # ══════════════════════════════════════════════════════════════════════
    # Real complaint: "бот всё ещё удаляет сообщение с практикой и оставляет
    # гифку" -- a technique WITHOUT an animation, shown after one WITH an
    # animation, must clear the leftover gif. The old code only cleared the
    # previous gif when the NEW technique also had one (the delete-previous
    # logic lived inside _send_tracked_animation, which was simply never
    # called when there's nothing new to send).
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    breathing_idx = next(i for i, s in enumerate(bot.SKILLS) if s["name"] == "🌬 Дыхание")
    stop_idx = next(i for i, s in enumerate(bot.SKILLS) if "СТОП" in s["name"])

    await bot.show_skill_detail(FakeUpdate(uid, f"skill_{breathing_idx}"), ctx)
    assert len(fbot.animations_sent) == 1
    breathing_gif_mid = bot._get_notif_msg_id(uid, "skill_anim")
    assert breathing_gif_mid is not None

    await bot.show_skill_detail(FakeUpdate(uid, f"skill_{stop_idx}"), ctx)
    assert len(fbot.animations_sent) == 1, "СТОП has no animation -- must not send a new one"
    assert (uid, breathing_gif_mid) in fbot.deleted, \
        f"opening a skill WITHOUT a gif must still clear the leftover gif from before, got deleted={fbot.deleted}"
    assert bot._get_notif_msg_id(uid, "skill_anim") is None
    print("1. show_skill_detail clears a leftover gif when the newly opened skill has none")

    # Same for the skill beacon (scheduler-fired): a gif-less technique
    # firing after a gif technique must also clear it.
    fbot2 = FakeBot()
    ctx2 = FakeCtx(fbot2)
    app = FakeApp(fbot2)
    bot.update_user(uid, skill_beacon_enabled=1, skill_beacon_mode="interval", skill_beacon_interval=1,
                     skill_beacon_last_sent="", beacon_start="00:00", beacon_end="23:59",
                     beacon_types="breathing")
    await bot.send_skill_beacon(app, bot.get_user(uid))
    assert len(fbot2.animations_sent) == 1
    beacon_gif_mid = bot._get_notif_msg_id(uid, "skill_anim")
    assert beacon_gif_mid is not None

    bot.update_user(uid, skill_beacon_last_sent="", beacon_types="stop")
    await bot.send_skill_beacon(app, bot.get_user(uid))
    assert len(fbot2.animations_sent) == 1, "СТОП has no animation -- beacon must not send a new gif"
    assert (uid, beacon_gif_mid) in fbot2.deleted, \
        f"the beacon firing a gif-less technique must clear the leftover gif, got deleted={fbot2.deleted}"
    assert bot._get_notif_msg_id(uid, "skill_anim") is None
    print("2. send_skill_beacon clears a leftover gif when the newly rotated technique has none")

    print("\nALL SKILL-ANIM-CLEARED-WHEN-NO-GIF TESTS PASSED")


asyncio.run(main())
