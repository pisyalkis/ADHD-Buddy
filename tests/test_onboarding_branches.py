import os, sys, asyncio, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_onboarding_branches.db")
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
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Аня', 'F')")
    conn.commit(); conn.close()

    # ══════════════════════════════════════════════════════════════════════
    # got_gender now asks a training-status question instead of jumping
    # straight to the trudnosti checklist -- this decides the branch.
    # ══════════════════════════════════════════════════════════════════════
    ctx = FakeCtx()
    ctx.user_data["onboard_name"] = "Артем"
    upd = FakeUpdate(1, data="gender_M")
    await bot.got_gender(upd, ctx)
    text = upd.callback_query.message.last_text
    assert "тренинг навыков" in text, text
    buttons = all_buttons(upd.callback_query.message.last_kb)
    assert ("ob_trained_yes" in [cb for _, cb in buttons])
    assert ("ob_trained_no" in [cb for _, cb in buttons])
    print("1. got_gender asks the training-status question with both branch buttons")

    # ══════════════════════════════════════════════════════════════════════
    # Branch A ("проходил тренинг") -- goal + before/after, straight to the
    # trudnosti checklist, no guide screens involved.
    # ══════════════════════════════════════════════════════════════════════
    upd_yes = FakeUpdate(1, data="ob_trained_yes")
    await bot.onboard_trained_yes(upd_yes, ctx)
    sent_texts = [t for t, _ in upd_yes.callback_query.message.sent]
    assert any("Без бота" in t and "С ботом" in t for t in sent_texts), sent_texts
    assert any("С чем тебе труднее всего" in t for t in sent_texts), sent_texts
    assert bot.get_user(1).get("skills_trained") == "1"
    print("2. onboard_trained_yes shows goal+before/after and lands directly on the checklist")

    # ══════════════════════════════════════════════════════════════════════
    # Branch B ("не проходил") -- intro, then the curated 5-section guide
    # starting at "what", NOT jumping straight to the checklist.
    # ══════════════════════════════════════════════════════════════════════
    ctx2 = FakeCtx()
    upd_no = FakeUpdate(2, data="ob_trained_no")
    await bot.onboard_trained_no(upd_no, ctx2)
    sent2 = [t for t, _ in upd_no.callback_query.message.sent]
    assert any("Что такое СДВГ" in t for t in sent2), sent2
    assert not any("С чем тебе труднее всего" in t for t in sent2), \
        "must NOT jump straight to the checklist -- the guide comes first"
    assert bot.get_user(2).get("skills_trained") == "0"
    print("3. onboard_trained_no launches the curated guide (starting at 'what'), not the checklist")

    # The guide screen for 'what' must offer exactly the 5 curated dots and a
    # 'Далее' button, plus a 'Пропустить объяснение' escape hatch.
    kb2 = upd_no.callback_query.message.last_kb
    dots = kb2.inline_keyboard[0]
    assert [b.callback_data for b in dots] == [
        "obguide_what", "obguide_problems", "obguide_diagnosis", "obguide_fixes", "obguide_bot"
    ]
    flat = all_buttons(kb2)
    assert any(cb == "obguide_done" for _, cb in flat), "must offer a skip-the-whole-explanation escape hatch"
    print("4. The curated guide screen shows exactly 5 dots (not all 8 GUIDE_SECTIONS) plus a skip button")

    # ══════════════════════════════════════════════════════════════════════
    # Walking through the curated guide never leaks the other 3 (unstarred)
    # GUIDE_SECTIONS, and finishing it lands on the same checklist as branch A.
    # ══════════════════════════════════════════════════════════════════════
    upd_bot_section = FakeUpdate(2, data="obguide_bot")
    await bot.onboard_guide_section(upd_bot_section, ctx2)
    last_text, last_kb = upd_bot_section.callback_query.message.sent[-1]
    assert "Как помогает этот бот" in last_text, last_text
    buttons_last = all_buttons(last_kb)
    assert ("Дальше →", "obguide_done") in buttons_last, buttons_last
    assert not any(cb.startswith("obguide_") and cb not in
                   ("obguide_what", "obguide_problems", "obguide_diagnosis", "obguide_fixes", "obguide_bot", "obguide_done")
                   for _, cb in buttons_last)
    print("5. The last curated section ('bot') offers only 'Дальше →', no leaked full-guide sections")

    upd_done = FakeUpdate(2, data="obguide_done")
    await bot.onboard_guide_done(upd_done, ctx2)
    sent_done = [t for t, _ in upd_done.callback_query.message.sent]
    assert any("До бота" in t and "После" in t for t in sent_done), sent_done
    assert any("С чем тебе труднее всего" in t for t in sent_done), \
        "branch B must converge on the same trudnosti checklist as branch A"
    print("6. Finishing (or skipping) the guide shows the before/after recap and converges on the same checklist")

    # Skipping early (from the very first section) must go straight to the
    # same recap+checklist too, without forcing the remaining 4 sections.
    ctx3 = FakeCtx()
    upd_skip = FakeUpdate(2, data="obguide_done")
    await bot.onboard_guide_done(upd_skip, ctx3)
    assert any("С чем тебе труднее всего" in t for t, _ in upd_skip.callback_query.message.sent)
    print("7. 'Пропустить объяснение' (skip early) reaches the same checklist too")

    print("\nALL ONBOARDING-BRANCHES TESTS PASSED")


asyncio.run(main())
