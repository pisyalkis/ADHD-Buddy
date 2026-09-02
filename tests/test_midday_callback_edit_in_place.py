import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_midday_callback_edit_in_place.db")
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
        self.edited = []
        self.sent = []
        self.edit_should_fail = False
    async def edit_text(self, text, **kw):
        if self.edit_should_fail:
            raise Exception("message too old to edit")
        self.edited.append((text, kw.get("reply_markup")))
    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()
    async def answer(self, *a, **kw): pass


class FakeChat:
    def __init__(self, uid): self.id = uid


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(uid)
        self.callback_query = FakeQuery(uid, data)
        self.message = None


class FakeCtx:
    def __init__(self):
        self.user_data = {}


async def run_edits(uid, data):
    """Runs midday_callback twice: once where edit_text succeeds (must edit,
    not send), once where it's forced to fail (must fall back to reply_text)."""
    upd_ok = FakeUpdate(uid, data=data)
    await bot.midday_callback(upd_ok, FakeCtx())
    assert len(upd_ok.callback_query.message.edited) >= 1, \
        f"{data} did not edit the existing message"
    assert len(upd_ok.callback_query.message.sent) == 0, \
        f"{data} sent a new message even though editing succeeded"

    upd_fail = FakeUpdate(uid, data=data)
    upd_fail.callback_query.message.edit_should_fail = True
    await bot.midday_callback(upd_fail, FakeCtx())
    assert len(upd_fail.callback_query.message.sent) >= 1, \
        f"{data} did not fall back to a new message when editing failed"


async def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    bot.update_user(uid, timezone="Asia/Tbilisi", buddy_name="Маша")
    bot.save_diary(uid, "morning", {"focus": "Написать отчёт"}, for_date=bot.datetime.now(bot.get_user_tz(bot.get_user(uid))).date().isoformat())

    # ══════════════════════════════════════════════════════════════════════
    # Real audit finding: every single branch of midday_callback (the daily
    # check-in / task-beacon / resume-check response flow -- ~15 situations
    # like "can't start"/"procrastinating"/"phone"/"all done"/hand off to
    # coach or buddy) sent a brand new message via q.message.reply_text
    # instead of editing the card the person was already looking at.
    # ══════════════════════════════════════════════════════════════════════
    for data in [
        "mid_ok", "mid_procr", "mid_a_done_b", "mid_ab_done_c", "mid_all_done",
        "mid_resting", "mid_a_skipped", "mid_nostart", "mid_scary", "mid_waiting",
        "mid_perfect", "mid_resist", "mid_time", "mid_phone", "mid_coach", "mid_buddy",
    ]:
        await run_edits(uid, data)
        print(f"OK: {data} edits in place, falls back to a new message on failure")

    print("\nALL MIDDAY-CALLBACK-EDIT-IN-PLACE TESTS PASSED")


asyncio.run(main())
