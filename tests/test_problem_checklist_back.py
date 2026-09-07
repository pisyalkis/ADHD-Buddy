import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_problem_checklist_back.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


class FakeBot:
    async def delete_message(self, chat_id, message_id):
        pass


class FakeMsg:
    def __init__(self):
        self.sent = []
        self.chat_id = 1

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self

    async def edit_reply_markup(self, reply_markup=None, **kw):
        self.sent.append((self.sent[-1][0] if self.sent else "", reply_markup))
        return self

    @property
    def last_text(self):
        return self.sent[-1][0]

    @property
    def last_kb(self):
        return self.sent[-1][1]


class FakeUser:
    def __init__(self, uid): self.id = uid


class FakeQuery:
    def __init__(self, uid, data=""):
        self.from_user = FakeUser(uid); self.data = data; self.message = FakeMsg()

    async def answer(self): pass


class FakeUpdate:
    def __init__(self, uid, data=""):
        self.callback_query = FakeQuery(uid, data)


class FakeCtx:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


def all_buttons(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()

    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-09-06): the onboarding trudnosti checklist
    # is 6 groups deep, only "Дальше →" -- an item checked in the wrong
    # group, or a change of mind, could only be fixed by finishing the
    # whole checklist and redoing it later through Settings. Added a
    # symmetric "◀️ Назад" that preserves selections made so far.
    # ══════════════════════════════════════════════════════════════════════

    # 1. The FIRST group has no "Назад" -- there's nothing before it in the
    #    checklist itself.
    ctx = FakeCtx()
    msg0 = FakeMsg()
    await bot.send_problem_group(msg0, ctx, 0)
    buttons0 = all_buttons(msg0.last_kb)
    assert not any(cb == "pb_0" or (cb or "").startswith("pb_") for _, cb in buttons0), buttons0
    print("1. The first group shows no 'Назад' button")

    # 2. A LATER group (not first, not last) shows BOTH 'Назад' and 'Дальше'.
    ctx2 = FakeCtx()
    msg1 = FakeMsg()
    await bot.send_problem_group(msg1, ctx2, 1)
    buttons1 = all_buttons(msg1.last_kb)
    cbs1 = [cb for _, cb in buttons1]
    assert "pb_1" in cbs1, buttons1
    assert "pn_1" in cbs1, buttons1
    print("2. A middle group shows both '◀️ Назад' and 'Дальше →'")

    # 3. The LAST group shows 'Назад' alongside 'Готово', not 'Дальше'.
    last_idx = len(bot.PROBLEM_GROUPS) - 1
    ctx3 = FakeCtx()
    msg_last = FakeMsg()
    await bot.send_problem_group(msg_last, ctx3, last_idx)
    buttons_last = all_buttons(msg_last.last_kb)
    cbs_last = [cb for _, cb in buttons_last]
    assert f"pb_{last_idx}" in cbs_last, buttons_last
    assert "prob_done" in cbs_last, buttons_last
    assert "Дальше →" not in [t for t, _ in buttons_last]
    print("3. The last group shows '◀️ Назад' alongside 'Готово ✅' (no 'Дальше')")

    # 4. Tapping "Назад" goes to the PREVIOUS group AND preserves selections
    #    already made in the current and earlier groups (no data loss).
    ctx4 = FakeCtx()
    ctx4.user_data["onboard_problems"] = []
    msg_g0 = FakeMsg()
    await bot.send_problem_group(msg_g0, ctx4, 0)
    # pick something in group 0
    first_key = bot.PROBLEM_GROUPS[0][1][0]
    upd_toggle = FakeUpdate(1, data=f"pt_0_{first_key}")
    upd_toggle.callback_query.message = msg_g0
    await bot.toggle_problem(upd_toggle, ctx4)
    assert first_key in ctx4.user_data["onboard_problems"]
    # advance to group 1
    upd_next = FakeUpdate(1, data="pn_0")
    await bot.problem_group_next(upd_next, ctx4)
    assert ctx4.user_data["onboard_problems"] == [first_key]
    # now go BACK to group 0 -- must still be group 0's content, selection intact
    upd_back = FakeUpdate(1, data="pb_1")
    await bot.problem_group_back(upd_back, ctx4)
    back_text = upd_back.callback_query.message.last_text
    assert bot.PROBLEM_GROUPS[0][0] in back_text, back_text
    back_buttons = all_buttons(upd_back.callback_query.message.last_kb)
    checked = [t for t, cb in back_buttons if cb == f"pt_0_{first_key}"]
    assert checked and checked[0].startswith("✅"), \
        f"going back must show the earlier selection still checked: {back_buttons}"
    assert ctx4.user_data["onboard_problems"] == [first_key], \
        "selections must survive a Назад/Дальше round trip"
    print("4. Tapping '◀️ Назад' returns to the previous group with selections preserved")

    print("\nALL PROBLEM-CHECKLIST-BACK TESTS PASSED")


asyncio.run(main())
