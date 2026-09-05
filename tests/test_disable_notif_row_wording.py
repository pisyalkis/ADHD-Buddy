import os, sys

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_disable_notif_row_wording.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()


def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request: "Выключить это уведомление" -> "Выключить такие
    # уведомления" -- the permanent-disable button disables the whole
    # notification TYPE going forward (see disable_notification_type/
    # DISABLE_NOTIF_TARGETS), not just this one instance you happen to be
    # looking at, so the wording should say so rather than implying a
    # one-off dismissal.
    #
    # Real follow-up request: a single permanent toggle was too blunt for
    # situational annoyance ("устал сегодня, не насовсем") -- disable_notif_row
    # now offers a "😴 Не сегодня" snooze alongside the permanent one
    # (see snooze_notification_type).
    # ══════════════════════════════════════════════════════════════════════
    row = bot.disable_notif_row("morning")
    assert len(row) == 2, row
    snooze_btn, disable_btn = row
    assert snooze_btn.text == "😴 Не сегодня", snooze_btn.text
    assert snooze_btn.callback_data == "snooze_notif_morning"
    assert disable_btn.text == "🔕 Насовсем", disable_btn.text
    assert disable_btn.callback_data == "disable_notif_morning"
    print("1. disable_notif_row offers both '😴 Не сегодня' (snooze) and '🔕 Насовсем' (permanent)")

    print("\nALL DISABLE-NOTIF-ROW-WORDING TESTS PASSED")


main()
