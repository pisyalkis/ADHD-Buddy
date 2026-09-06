import os, sys

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_problem_to_mid_coverage.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot


def first_button_callback(markup):
    return markup.inline_keyboard[0][0].callback_data


def main():
    # ══════════════════════════════════════════════════════════════════════
    # Real request (IDEAS.md 2026-08-29): PROBLEM_TO_MID covered only 6 of
    # ~18 onboarding difficulty ids -- users who picked any of the other ~12
    # got zero personalization of the "😬 Прокрастинирую" branch ordering.
    # New mappings added only where a mid_* branch is a genuine semantic
    # match -- verify each newly-added id actually reorders mid_procr_kb.
    # ══════════════════════════════════════════════════════════════════════
    new_mappings = {
        "notasks": "mid_nostart",
        "overload": "mid_scary",
        "bedstuck": "mid_resist",
        "self_talk": "mid_perfect",
        "unfinished_shame": "mid_perfect",
    }
    for problem_id, expected_top in new_mappings.items():
        kb = bot.mid_procr_kb([problem_id], "M")
        top_cb = first_button_callback(kb)
        assert top_cb == expected_top, \
            f"struggle '{problem_id}' must put {expected_top} first, got {top_cb}"
    print("1. Each of the 5 newly-added struggle ids correctly promotes its matched mid_* branch to the top")

    # 2. Regression: the 6 originally-covered ids still work exactly as
    #    before -- new entries must not have disturbed the existing mapping.
    original_mappings = {
        "resist": "mid_resist",
        "decompose": "mid_nostart",
        "phone": "mid_phone",
        "time": "mid_time",
    }
    for problem_id, expected_top in original_mappings.items():
        kb = bot.mid_procr_kb([problem_id], "M")
        top_cb = first_button_callback(kb)
        assert top_cb == expected_top, \
            f"regression: struggle '{problem_id}' must still put {expected_top} first, got {top_cb}"
    print("2. The originally-covered struggle ids are unaffected (no regression)")

    # 3. Deliberately-unmapped ids (no honest mid_* match) fall back to the
    #    plain, unpersonalized default order -- same as having no struggles
    #    at all, not a broken/empty keyboard.
    default_kb = bot.mid_procr_kb([], "M")
    default_top = first_button_callback(default_kb)
    for problem_id in ("hyperfocus", "nostructure", "memory", "self_esteem"):
        assert problem_id not in bot.PROBLEM_TO_MID, \
            f"'{problem_id}' was expected to remain deliberately unmapped (no honest mid_* match)"
        kb = bot.mid_procr_kb([problem_id], "M")
        assert first_button_callback(kb) == default_top, \
            f"an unmapped struggle id must fall back to the default order, got a different one for '{problem_id}'"
    print("3. Deliberately-unmapped ids (hyperfocus/nostructure/memory/self_esteem) fall back to the default order, not forced")

    print("\nALL PROBLEM-TO-MID-COVERAGE TESTS PASSED")


main()
