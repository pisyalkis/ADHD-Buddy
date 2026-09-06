import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_beacon_technique_expansion.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

TBILISI = bot.pytz.timezone("Asia/Tbilisi")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        class M:
            message_id = 1
            animation = None
        return M()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.user_data = {}


def make_user(uid, name):
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (?, ?, 'M')", (uid, name))
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-30): the skill/self-help beacon only
    # rotated 4 techniques (stop/breathing/grounding/anchor) while the
    # evening SELFCARE_ITEMS checklist and the 🧠 Навыки catalog offer 13.
    # Extended the rotation with every technique that fits a short text nudge
    # with no picture/animation needed -- everything except "todolist" (that
    # is conceptually the task beacon's own job, not a short pause technique).
    # ══════════════════════════════════════════════════════════════════════

    # 1. Every technique in BEACON_TECHNIQUE_TYPES has a matching prompt --
    #    no KeyError risk in send_skill_beacon regardless of which slot fires.
    for key, label in bot.BEACON_TECHNIQUE_TYPES:
        assert key in bot.BEACON_TECHNIQUE_PROMPTS, f"missing prompt for {key}"
    print("1. Every BEACON_TECHNIQUE_TYPES key has a matching BEACON_TECHNIQUE_PROMPTS entry")

    # 2. The rotation actually grew -- new techniques beyond the original 4
    #    are present, and the redundant "todolist" was deliberately excluded.
    keys = [k for k, _ in bot.BEACON_TECHNIQUE_TYPES]
    original = {"stop", "breathing", "grounding", "anchor"}
    assert original.issubset(set(keys))
    new_keys = set(keys) - original
    assert len(new_keys) >= 6, f"expected several new techniques, got {new_keys}"
    assert "todolist" not in keys, "todolist duplicates the task beacon's own job, must not be a technique slot"
    print(f"2. Beacon technique rotation expanded with {len(new_keys)} new techniques: {sorted(new_keys)}")

    # 3. _beacon_types_kb (settings screen) shows a checkbox row for every
    #    technique, old and new.
    uid = 1
    make_user(uid, "Артем")
    kb = bot._beacon_types_kb(bot.get_user(uid))
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    for key, _ in bot.BEACON_TECHNIQUE_TYPES:
        assert f"toggle_beacontype_{key}" in callbacks, f"{key} missing from settings screen"
    print("3. _beacon_types_kb shows a toggle row for every technique, including the new ones")

    # 4. A fresh user turning on the skill beacon for the first time (empty
    #    beacon_types) gets ALL techniques enabled by default, not just the
    #    original 4 -- same "don't leave it silently mute" safety net as
    #    before (19th checkup), now covering the full expanded catalog.
    uid2 = 2
    make_user(uid2, "Вика")
    bot.update_user(uid2, beacon_types="")
    await bot.toggle_skill_beacon(_fake_toggle_update(uid2), _FakeCtx())
    enabled = set((bot.get_user(uid2).get("beacon_types") or "").split(","))
    assert enabled == set(keys), f"expected all {len(keys)} techniques enabled by default, got {enabled}"
    print("4. Turning on the skill beacon fresh enables the full expanded technique catalog by default")

    # 5. next_beacon_slot rotates through a newly-added technique too (not
    #    just the original 4) when only that technique is enabled.
    uid3 = 3
    make_user(uid3, "Игорь")
    bot.update_user(uid3, beacon_types="first_step", beacon_rotation_idx="0")
    slot, next_idx = bot.next_beacon_slot(uid3)
    assert slot == "first_step", slot
    print("5. next_beacon_slot correctly rotates a newly-added technique when it's the only one enabled")

    print("\nALL BEACON-TECHNIQUE-EXPANSION TESTS PASSED")


class _FakeCtx:
    def __init__(self):
        self.user_data = {}


def _fake_toggle_update(uid):
    class FakeUser:
        id = uid

    class FakeMsg:
        async def edit_reply_markup(self, **kw):
            return self

        async def edit_text(self, *a, **kw):
            return self

        async def reply_text(self, *a, **kw):
            return self

    class FakeQuery:
        from_user = FakeUser()
        data = "toggle_skillbeacon"
        message = FakeMsg()

        async def answer(self, *a, **kw):
            pass

    class FakeUpdate:
        callback_query = FakeQuery()
        effective_user = FakeUser()
        effective_chat = type("C", (), {"id": uid})

    return FakeUpdate()


asyncio.run(main())
