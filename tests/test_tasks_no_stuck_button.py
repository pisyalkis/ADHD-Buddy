import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_tasks_no_stuck_button.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request: "🆘 Застрял?" on 📋 Задачи (daily tasks) felt out of
    # place there -- remove it. (The same button on the midday check-in
    # screens is unrelated and untouched.)
    # ══════════════════════════════════════════════════════════════════════
    morning = {"focus": "Написать отчёт"}
    text, kb = bot._tasks_text_and_kb(morning, set(), "M", 1)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "mid_coach" not in flat, flat
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert not any("Застрял" in t for t in labels), labels
    print("1. 📋 Задачи no longer has a '🆘 Застрял?' button")


main()
print("\nALL TASKS-NO-STUCK-BUTTON TESTS PASSED")
