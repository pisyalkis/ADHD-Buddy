import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_skill_animations_get_deleted.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeAnimationResult:
    _next_id = [5000]
    def __init__(self, file_id):
        self.animation = type("A", (), {"file_id": file_id})
        self.message_id = FakeAnimationResult._next_id[0]
        FakeAnimationResult._next_id[0] += 1


class FakeMsg:
    _next_id = [6000]
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = FakeMsg._next_id[0]
        FakeMsg._next_id[0] += 1
    async def reply_text(self, text, **kw):
        m = FakeMsg(self.chat_id)
        return m


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg(uid)
    async def answer(self): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)


class FakeBot:
    def __init__(self):
        self.animations_sent = []
        self.messages_sent = []
        self.deleted = []
        self._anim_counter = 0
    async def send_animation(self, chat_id, animation, **kw):
        self._anim_counter += 1
        self.animations_sent.append((chat_id, animation))
        return FakeAnimationResult(f"fake_file_id_{self._anim_counter}")
    async def send_message(self, chat_id, text, **kw):
        m = FakeMsg(chat_id)
        self.messages_sent.append((chat_id, text, kw.get("reply_markup")))
        return m
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
    # Real complaint: "Почему гифки от практик не удаляются?" -- opening the
    # breathing skill card in 🧠 Навыки twice in a row must not leave two
    # gifs in the chat; the second open must delete the first.
    # ══════════════════════════════════════════════════════════════════════
    fbot = FakeBot()
    ctx = FakeCtx(fbot)
    breathing_idx = next(i for i, s in enumerate(bot.SKILLS) if s["name"] == "🌬 Дыхание")

    await bot.show_skill_detail(FakeUpdate(uid, f"skill_{breathing_idx}"), ctx)
    assert len(fbot.animations_sent) == 1
    first_gif_mid = fbot.animations_sent[0]  # (chat_id, animation) -- need message id from DB tracking
    tracked_after_first = bot._get_notif_msg_id(uid, "skill_anim")
    assert tracked_after_first is not None
    assert fbot.deleted == [], "nothing to delete on the very first open"
    print("1. First open of a skill with an animation sends the gif, deletes nothing yet")

    await bot.show_skill_detail(FakeUpdate(uid, f"skill_{breathing_idx}"), ctx)
    assert len(fbot.animations_sent) == 2
    assert (uid, tracked_after_first) in fbot.deleted, \
        f"reopening the same (or another) skill's gif must delete the previous one, got deleted={fbot.deleted}"
    tracked_after_second = bot._get_notif_msg_id(uid, "skill_anim")
    assert tracked_after_second != tracked_after_first
    print("2. Reopening a skill's animation deletes the previously shown gif before sending the new one")

    # ══════════════════════════════════════════════════════════════════════
    # Box breathing (reached via a button from the breathing skill card)
    # shares the same "skill_anim" channel -- opening it must delete
    # whichever gif was showing before, breathing or box_breathing alike.
    # ══════════════════════════════════════════════════════════════════════
    await bot.show_box_breathing(FakeUpdate(uid, "skill_box_breathing"), ctx)
    assert len(fbot.animations_sent) == 3
    assert (uid, tracked_after_second) in fbot.deleted
    print("3. Box breathing (a second animation off the same skill) also replaces the previous gif, not adds to it")

    # ══════════════════════════════════════════════════════════════════════
    # Skill beacon (scheduler-fired) shares the very same channel -- a gif
    # left over from browsing the catalog must be replaced when a beacon
    # with an animated technique fires, and vice versa.
    # ══════════════════════════════════════════════════════════════════════
    tracked_before_beacon = bot._get_notif_msg_id(uid, "skill_anim")
    bot.update_user(uid, skill_beacon_enabled=1, skill_beacon_mode="interval", skill_beacon_interval=1,
                     skill_beacon_last_sent="", beacon_start="00:00", beacon_end="23:59",
                     beacon_types="breathing")
    app = FakeApp(fbot)
    await bot.send_skill_beacon(app, bot.get_user(uid))
    assert len(fbot.animations_sent) == 4
    assert (uid, tracked_before_beacon) in fbot.deleted, \
        "the skill beacon's animation must delete whatever gif was already tracked, even from the catalog"
    tracked_after_beacon = bot._get_notif_msg_id(uid, "skill_anim")
    print("4. The skill beacon's animation replaces a leftover catalog gif via the same shared channel")

    # ══════════════════════════════════════════════════════════════════════
    # Marking the beacon technique "done" must delete its gif too -- it
    # shouldn't outlive the very reminder it illustrated.
    # ══════════════════════════════════════════════════════════════════════
    skill_beacon_mid = bot._get_notif_msg_id(uid, "skill_beacon")
    beacon_query = FakeUpdate(uid, "beacon_technique_done")
    beacon_query.callback_query.message.message_id = skill_beacon_mid
    await bot.beacon_technique_done(beacon_query, ctx)
    assert (uid, tracked_after_beacon) in fbot.deleted, \
        f"'Сделал(а)' must delete the technique's gif, got deleted={fbot.deleted}"
    assert bot._get_notif_msg_id(uid, "skill_anim") is None, \
        "tracking for skill_anim must be cleared once the technique is marked done"
    print("5. beacon_technique_done ('Сделал(а)') deletes the technique's gif along with the text prompt")

    print("\nALL SKILL-ANIMATIONS-GET-DELETED TESTS PASSED")


asyncio.run(main())
