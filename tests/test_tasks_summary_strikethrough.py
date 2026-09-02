import os, sys

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_tasks_summary_strikethrough.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


def main():
    morning = {
        "focus": "Написать тем, кто тестит бот",
        "b1": "Презентацию доделать",
        "b2": "Фокус внимания актеров на таймлайне спектакля",
        "c1": "Поразгонять, откуда получать деньги",
    }

    # ══════════════════════════════════════════════════════════════════════
    # Real request: a task marked done (✅ on the checkbox keyboard) should
    # show as struck-through in the task list text above it -- same visual
    # language already used in the pinned "Утро записано!" message, instead
    # of looking identical to an undone task.
    # ══════════════════════════════════════════════════════════════════════
    done_set = {"focus"}
    text = bot.build_tasks_summary(morning, done_set)
    lines = text.split("\n")
    focus_line = next(l for l in lines if l.startswith("A:"))
    b1_line = next(l for l in lines if l.startswith("B1:"))
    assert bot._strike("Написать тем, кто тестит бот") in focus_line, \
        f"a done task must be struck through, got: {focus_line!r}"
    assert b1_line == "B1: Презентацию доделать", \
        f"an undone task must NOT be struck through, got: {b1_line!r}"
    print("1. build_tasks_summary strikes through a task marked done, leaves others untouched")

    # Sanity: with no done_set at all (existing call sites that omit it),
    # nothing is struck through -- no regression for callers relying on
    # the default.
    text2 = bot.build_tasks_summary(morning)
    assert "̶" not in text2, f"with no done_set, nothing should be struck through, got: {text2!r}"
    print("2. build_tasks_summary with no done_set strikes nothing (no regression)")

    # Sanity: multiple done tasks are all struck through.
    text3 = bot.build_tasks_summary(morning, {"focus", "b2"})
    lines3 = text3.split("\n")
    focus3 = next(l for l in lines3 if l.startswith("A:"))
    b2_3 = next(l for l in lines3 if l.startswith("B2:"))
    c1_3 = next(l for l in lines3 if l.startswith("C1:"))
    assert "̶" in focus3 and "̶" in b2_3, "both done tasks must be struck through"
    assert "̶" not in c1_3, "the undone task must stay plain"
    print("3. build_tasks_summary strikes through multiple done tasks correctly")

    print("\nALL TASKS-SUMMARY-STRIKETHROUGH TESTS PASSED")


main()
