import os, sys, asyncio, sqlite3
from datetime import datetime, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_checkup13_batch.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeMsg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self
    @property
    def last_text(self):
        return self.sent[-1][0]


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, text=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.message = FakeMsg()
        self.message.text = text
        self.message.reply_text = self.message.reply_text
        self.callback_query = None


class FakeCtx:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}


class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, uid, text, **kw):
        self.sent.append((uid, text, kw.get("reply_markup")))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Admin', 'M')")
    conn.commit(); conn.close()
    tz_name = "Asia/Tbilisi"

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (13th checkup, same class as get_latest_evening_plan): weekly_report
    # judged "was the morning/evening ritual done" by ONE field (focus/e_ach)
    # instead of record presence -- a user who disabled "⭐ Достижения дня"
    # (a real toggleable setting) always has e_ach=="" and got undercounted
    # forever, and a user whose morning tasks are set separately via 📋
    # Задачи (not through the ritual) without "focus" got undercounted too.
    # ══════════════════════════════════════════════════════════════════════
    uid = 1
    bot.update_user(uid, timezone=tz_name, disabled_fields="e_ach", streak_hidden=1)
    user = bot.get_user(uid)
    today = datetime.now(bot.get_user_tz(user)).date()
    for i in range(7, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        # Morning: only a non-task field set (gratitude) -- ritual done, but
        # task A ("focus") was never set that day (set separately elsewhere).
        bot.save_diary(uid, "morning", {"gratitude": "штука"}, for_date=d)
        # Evening: e_ach disabled (always ""), but the rest of the evening
        # was genuinely filled in.
        bot.save_diary(uid, "evening", {"e_ach": "", "e_praise": "молодец", "e_energy": 3}, for_date=d)

    app = FakeApp()
    ok = await bot.weekly_report(app, uid)
    assert ok, "weekly_report must not raise"
    report_text = app.bot.sent[0][1]
    assert "Утренних блоков заполнено: *7 из 7*" in report_text, report_text
    assert "Вечерних блоков закрыто: *7 из 7*" in report_text, report_text
    print("1. weekly_report now counts morning/evening completion by record presence, not one field")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (13th checkup): newpromo_command crashed with an unhandled
    # ValueError on a non-numeric days/max_uses argument (a plausible admin
    # typo), unlike the sibling /grant which already guards target_uid.
    # ══════════════════════════════════════════════════════════════════════
    admin_uid = 999
    upd = FakeUpdate(admin_uid)
    ctx = FakeCtx(args=["MYCODE", "abc"])
    await bot.newpromo_command(upd, ctx)  # must not raise
    assert "числами" in upd.message.last_text, upd.message.last_text
    print("2a. newpromo_command no longer crashes on a non-numeric days argument")

    # And the normal numeric path must still work.
    upd2 = FakeUpdate(admin_uid)
    ctx2 = FakeCtx(args=["MYCODE2", "10", "5"])
    await bot.newpromo_command(upd2, ctx2)
    assert "создан" in upd2.message.last_text, upd2.message.last_text
    print("2b. newpromo_command still works normally with valid numeric arguments")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (13th checkup): grant_command guarded target_uid's int() but
    # not days' -- same unhandled-ValueError shape, just for the second arg.
    # ══════════════════════════════════════════════════════════════════════
    upd3 = FakeUpdate(admin_uid)
    ctx3 = FakeCtx(args=["1", "notanumber"])
    await bot.grant_command(upd3, ctx3)  # must not raise
    assert "числом" in upd3.message.last_text, upd3.message.last_text
    print("2c. grant_command no longer crashes on a non-numeric days argument")

    # ══════════════════════════════════════════════════════════════════════
    # Real bug (13th checkup, same class as PR #118's "маячок" naming fix):
    # BEACON_TECHNIQUE_TYPES labeled "stop"/"anchor" differently from the
    # SKILLS catalogue and the evening self-care checklist for the exact
    # same technique.
    # ══════════════════════════════════════════════════════════════════════
    beacon_labels = dict(bot.BEACON_TECHNIQUE_TYPES)
    assert beacon_labels["stop"] == "🛑 Навык СТОП", beacon_labels["stop"]
    assert beacon_labels["anchor"] == "⚓ Бросить якорь", beacon_labels["anchor"]
    skill_names = {s["name"] for s in bot.SKILLS}
    assert beacon_labels["stop"] in skill_names, "beacon 'stop' label must match the SKILLS catalogue name"
    assert beacon_labels["anchor"] in skill_names, "beacon 'anchor' label must match the SKILLS catalogue name"
    print("3. BEACON_TECHNIQUE_TYPES labels for stop/anchor now match the SKILLS catalogue naming")

    print("\nALL CHECKUP13-BATCH TESTS PASSED")


asyncio.run(main())
