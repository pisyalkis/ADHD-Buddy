import os, sys, asyncio, sqlite3
from datetime import datetime

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_mid_energy_option.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.message_id = 1
        self.edited = []
        self.sent = []
    async def edit_text(self, text, **kw):
        self.edited.append((text, kw.get("reply_markup")))
        return self
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data):
        self.from_user = FakeUser(uid); self.message = FakeMsg(uid); self.data = data
    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data):
        self.callback_query = FakeQuery(uid, data)
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeUser(uid)


class FakeCtx:
    def __init__(self):
        self.user_data = {}


def buttons_of(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request: add "low energy" as a procrastination reason in the
    # midday check-in's "😬 Прокрастинирую" branch.
    # ══════════════════════════════════════════════════════════════════════
    kb = bot.mid_procr_kb([], "M")
    flat = buttons_of(kb)
    assert ("🔋 Мало энергии", "mid_energy") in flat, \
        f"mid_procr_kb must offer the new 'low energy' option, got: {flat}"
    print("1. mid_procr_kb offers the new 'Мало энергии' option")

    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi")
    today = datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat()
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=today)

    upd = FakeUpdate(uid, "mid_energy")
    await bot.midday_callback(upd, FakeCtx())

    text, kb2 = upd.callback_query.message.edited[-1]
    assert "Мало энергии" in text, text
    assert "Написать отчёт" in text, "must reference the actual focus task"
    flat2 = buttons_of(kb2)
    skill_buttons = [t for t, cb in flat2 if t.startswith("🧠 Подробнее")]
    assert skill_buttons and "Активация" in skill_buttons[0], \
        f"mid_energy must link to the '⚡ Активация' skill card, got buttons: {flat2}"
    print("2. midday_callback('mid_energy') shows the low-energy guidance and links to ⚡ Активация")

    diary = bot.get_diary(uid, "midday", today)
    assert diary.get("state") == "🔋 Мало энергии", \
        f"the day card must record the chosen state via MIDDAY_LABELS, got: {diary}"
    print("3. The chosen state is saved to the day card (midday diary) like every other option")

    print("\nALL MID-ENERGY-OPTION TESTS PASSED")


asyncio.run(main())
