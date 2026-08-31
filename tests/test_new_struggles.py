import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_new_struggles.db")
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
    async def edit_reply_markup(self, **kw):
        self.sent.append((None, kw.get("reply_markup")))
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


async def main():
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()
    uid = 1

    # ══════════════════════════════════════════════════════════════════════
    # Structural checks: new group exists, memory_yesterday sits alongside
    # memory (not duplicating the new self-worth group), nothing crashes the
    # existing skill-rotation / mid-checkin machinery for keys with no
    # PROBLEM_TO_SKILLS/PROBLEM_TO_MID entry.
    # ══════════════════════════════════════════════════════════════════════
    group_titles = [title for title, _ in bot.PROBLEM_GROUPS]
    assert "🪞 Отношение к себе" in group_titles, group_titles
    last_title, last_keys = bot.PROBLEM_GROUPS[-1]
    assert set(last_keys) == {"self_esteem", "self_talk", "unfinished_shame"}, last_keys

    memory_group = next(keys for title, keys in bot.PROBLEM_GROUPS if title == "🧠 Не забыть")
    assert set(memory_group) == {"memory", "memory_yesterday"}, memory_group
    print("1. New group '🪞 Отношение к себе' exists; memory_yesterday joins the existing 'Не забыть' group")

    for key in ("self_esteem", "self_talk", "unfinished_shame", "memory_yesterday"):
        assert key in bot.PROBLEM_HELP_TEXT, key
        assert key in bot.PROBLEM_GOAL, key
    print("2. All 4 new keys have both a help text and a goal phrase")

    # ══════════════════════════════════════════════════════════════════════
    # Selecting a new-group struggle must not crash daily-skill rotation or
    # the midday-procrastination reordering, even though these keys have no
    # PROBLEM_TO_SKILLS/PROBLEM_TO_MID entries (deliberately -- there's no
    # single technique that "treats" low self-esteem the way there's one
    # for e.g. phone distraction).
    # ══════════════════════════════════════════════════════════════════════
    bot.update_user(uid, struggles="self_esteem,self_talk")
    skill = bot.get_daily_skill(uid)  # must not raise
    assert skill in bot.SKILLS
    kb = bot.mid_procr_kb(["self_esteem", "self_talk"], "M")  # must not raise
    assert kb.inline_keyboard
    print("3. Selecting only new-group struggles doesn't crash skill rotation or midday reordering (safe fallback)")

    # ══════════════════════════════════════════════════════════════════════
    # Walk through the real checklist UI up to and including the new last
    # group, toggle a couple of new items, finish, and check what actually
    # gets saved + explained.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["onboard_name"] = "Артем"
    last_group_idx = len(bot.PROBLEM_GROUPS) - 1
    await bot.send_problem_group(FakeMsg(), ctx, last_group_idx)  # sanity: doesn't crash

    upd_toggle = FakeUpdate(uid, data=f"pt_{last_group_idx}_self_esteem")
    await bot.toggle_problem(upd_toggle, ctx)
    assert ctx.user_data["onboard_problems"] == ["self_esteem"]
    kb_after_toggle = upd_toggle.callback_query.message.last_kb
    marked = [b.text for row in kb_after_toggle.inline_keyboard for b in row if b.text.startswith("✅")]
    assert any("Низкая самооценка" in t for t in marked), marked
    print("4. Toggling a new-group item in the real checklist UI marks it selected, as usual")

    ctx.user_data["onboard_problems"] = ["self_esteem", "memory_yesterday"]
    upd_done = FakeUpdate(uid, data="prob_done")
    await bot.problems_done(upd_done, ctx)
    assert bot.get_user(uid).get("struggles") == "self_esteem,memory_yesterday"
    print("5. problems_done saves the selected new-group struggles to the DB as usual")

    # ══════════════════════════════════════════════════════════════════════
    # The personalized "explain" screens (step 2/3) must surface the new
    # help texts and goal phrases for these keys, same as any other struggle.
    # ══════════════════════════════════════════════════════════════════════
    ctx2 = FakeCtx()
    ctx2.user_data["onboard_problems"] = ["self_esteem", "memory_yesterday"]
    upd2 = FakeUpdate(uid)
    await bot.send_explain_step(upd2, ctx2, step=2, then="cta")
    text2 = upd2.callback_query.message.last_text
    assert "Низкая самооценка" in text2, text2
    assert "Не помнишь, что было вчера" in text2, text2
    print("6. Step 2 explanation surfaces the new help texts for selected struggles")

    ctx3 = FakeCtx()
    ctx3.user_data["onboard_problems"] = ["self_esteem", "memory_yesterday"]
    upd3 = FakeUpdate(uid)
    await bot.send_explain_step(upd3, ctx3, step=3, then="cta")
    sent3 = [t for t, _ in upd3.callback_query.message.sent if t]
    assert any("видеть, что получается" in t for t in sent3), sent3
    assert any("видеть свои дни" in t for t in sent3), sent3
    print("7. Step 3 explanation surfaces the new goal phrases for selected struggles")

    print("\nALL NEW-STRUGGLES TESTS PASSED")


asyncio.run(main())
