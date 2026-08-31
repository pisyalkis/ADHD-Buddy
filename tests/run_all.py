#!/usr/bin/env python3
"""Runs every tests/test_*.py as a standalone script (each one does its own
asyncio.run(main()) and exits non-zero on assertion failure) and reports a
pass/fail summary. Used locally and by .github/workflows/tests.yml."""
import glob
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    test_files = sorted(glob.glob(os.path.join(THIS_DIR, "test_*.py")))
    passed = 0
    failed = []
    for path in test_files:
        name = os.path.basename(path)
        result = subprocess.run([sys.executable, path], capture_output=True, text=True)
        if result.returncode != 0:
            failed.append(name)
            print(f"FAIL: {name}")
            print(result.stdout[-2000:])
            print(result.stderr[-2000:])
            print("---")
        else:
            passed += 1

    print(f"\nPASSED: {passed}  FAILED: {len(failed)}")
    if failed:
        print("Failed tests:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
