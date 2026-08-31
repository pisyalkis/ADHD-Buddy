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
    # уведомления" -- the button disables the whole notification TYPE going
    # forward (see disable_notification_type/DISABLE_NOTIF_TARGETS), not
    # just this one instance you happen to be looking at, so the wording
    # should say so ("such notifications", plural) rather than implying a
    # one-off dismissal.
    # ══════════════════════════════════════════════════════════════════════
    row = bot.disable_notif_row("morning")
    assert len(row) == 1
    button = row[0]
    assert button.text == "🔕 Выключить такие уведомления", button.text
    assert button.callback_data == "disable_notif_morning"
    print("1. disable_notif_row now says 'Выключить такие уведомления' (plural/type), not 'это уведомление'")

    print("\nALL DISABLE-NOTIF-ROW-WORDING TESTS PASSED")


main()
