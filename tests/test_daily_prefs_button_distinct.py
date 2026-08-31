import os, sys, sqlite3

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_daily_prefs_button_distinct.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

# Telegram truncates long inline button labels with an ellipsis when the
# rendered text overflows the button's width -- it does this by characters,
# not words, so we can approximate "would this still be told apart on a
# real phone" by comparing a short character-count prefix of each label.
TRUNCATE_PROBE_LEN = 14


def main():
    uid = 1
    conn = sqlite3.connect(bot.DB_PATH)
    conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Артем', 'M')")
    conn.commit(); conn.close()

    # ══════════════════════════════════════════════════════════════════════
    # Real feedback (screenshot): the two side-by-side quick-toggle buttons
    # on the pinned daily message ("🔔 Маячки внимания: задачи" / "🧠 Маячки
    # внимания: навыки") looked IDENTICAL on screen -- both truncated to
    # "Маячки вниман..." because they're half-width buttons and the only
    # differentiating word ("задачи"/"навыки") was the LAST word of a long
    # shared prefix, which is exactly what gets cut off.
    # ══════════════════════════════════════════════════════════════════════
    kb = bot.daily_prefs_kb(bot.get_user(uid))
    row = kb.inline_keyboard[0]
    assert len(row) == 2, row
    label_beacon, label_skill = row[0].text, row[1].text

    assert label_beacon != label_skill
    prefix_a = label_beacon[:TRUNCATE_PROBE_LEN]
    prefix_b = label_skill[:TRUNCATE_PROBE_LEN]
    assert prefix_a != prefix_b, \
        f"the two buttons must remain visually distinct even truncated to {TRUNCATE_PROBE_LEN} chars, got {prefix_a!r} vs {prefix_b!r}"
    print(f"1. The two quick-toggle buttons stay distinct even truncated to {TRUNCATE_PROBE_LEN} chars ({prefix_a!r} vs {prefix_b!r})")

    # Both must still clearly reference "маячки" for recognizability (tied
    # to the fuller "маячки внимания" name used in message bodies/skills) --
    # just not as the very first word, and later shortened further (real
    # request: "мало места на кнопках") from "маячки внимания" to "маячки"
    # on buttons specifically -- message-body text keeps the full name.
    assert "маячки" in label_beacon.lower()
    assert "маячки" in label_skill.lower()
    assert "внимания" not in label_beacon.lower() and "внимания" not in label_skill.lower(), \
        f"buttons must use the shortened 'маячки' (not the full 'маячки внимания') -- real request: little room on buttons, got {label_beacon!r} / {label_skill!r}"
    print("2. Both buttons mention 'маячки' (shortened, not the full 'маячки внимания') for recognizability")

    # Sanity: toggling state still flips the right icon on the right button.
    bot.update_user(uid, beacon_enabled=1, skill_beacon_enabled=0)
    kb2 = bot.daily_prefs_kb(bot.get_user(uid))
    row2 = kb2.inline_keyboard[0]
    assert row2[0].text.startswith("🔔"), row2[0].text
    assert row2[1].text.startswith("🔕"), row2[1].text
    print("3. Toggle state still renders the right icon on the right button after the relabel")

    print("\nALL DAILY-PREFS-BUTTON-DISTINCT TESTS PASSED")


main()
