import os, sys
SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_task_button_text.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()

# ══════════════════════════════════════════════════════════════════════════
# Feedback (Victoria -> Artem): show "A: <task text>" on the button, not
# just "A" -- but shorten long text ourselves (word-boundary, keep the
# leading/main words) instead of letting Telegram truncate mid-word.
# ══════════════════════════════════════════════════════════════════════════
short = "Купить хлеб"
assert bot._short_button_text(short) == short, bot._short_button_text(short)
print("1. Short text passes through unchanged")

long_text = "Админ-гайд допилить и отдать Антону на согласование"
out = bot._short_button_text(long_text, limit=28)
assert len(out) <= 29, out  # limit + ellipsis char
assert out.endswith("…"), out
assert not out[:-1].endswith(" "), out  # no trailing space before the ellipsis
assert long_text.startswith(out[:-1]), \
    f"truncation must cut at a real word boundary from the start, got {out!r}"
print(f"2. Long text is truncated at a word boundary with an ellipsis: {out!r}")

# A single word longer than the limit still gets cut (no infinite loop / crash)
one_long_word = "Оченьдлинноесловобезпробеловкотороенемешаетсянивкакойбюджет"
out2 = bot._short_button_text(one_long_word, limit=15)
assert out2.endswith("…") and len(out2) == 16, out2
print("3. A single word longer than the limit is hard-cut, not left unbounded")

# ── Full button text via _tasks_text_and_kb includes "A: <text>" ───────────
morning = {"focus": long_text, "b1": "Купить хлеб"}
text, kb = bot._tasks_text_and_kb(morning, set(), "M")
button_labels = [row[0].text for row in kb.inline_keyboard if row[0].callback_data.startswith("task_done_")]
assert any(label.startswith("▫️ A: ") for label in button_labels), button_labels
assert any(label == "▫️ B1: Купить хлеб" for label in button_labels), button_labels
print("4. _tasks_text_and_kb renders '<mark> <letter>: <text>' buttons, short text shown in full")

print("\nALL TASK-BUTTON-TEXT TESTS PASSED")
