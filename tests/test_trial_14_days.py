import os, sys, sqlite3
from datetime import date, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_trial_14_days.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
os.environ["ANTHROPIC_KEY"] = ""
import bot
bot.init_db()

# ══════════════════════════════════════════════════════════════════════════
# По просьбе: пробный период увеличен с 7 до 14 дней (короче 7 не хватало
# ощутить накопительный эффект ежедневного ритуала, длиннее 21 замедляет
# сигнал по конверсии, который сейчас важнее всего в Фазе 1).
# ══════════════════════════════════════════════════════════════════════════
assert bot.TRIAL_DAYS == 14, f"TRIAL_DAYS should be 14, got {bot.TRIAL_DAYS}"
print("1. TRIAL_DAYS constant is 14")

conn = sqlite3.connect(bot.DB_PATH)
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'День7', 'M')")
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'День14', 'M')")
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'День15', 'M')")
conn.commit(); conn.close()

bot.update_user(1, timezone="Asia/Tbilisi", created_at=(date.today() - timedelta(days=7)).isoformat())
bot.update_user(2, timezone="Asia/Tbilisi", created_at=(date.today() - timedelta(days=14)).isoformat())
bot.update_user(3, timezone="Asia/Tbilisi", created_at=(date.today() - timedelta(days=15)).isoformat())

assert bot.get_access_status(bot.get_user(1)) == "trial", \
    "a user registered 7 days ago must still be in trial now that TRIAL_DAYS=14"
print("2. A user registered 7 days ago is still in trial (would have expired under the old 7-day limit)")

assert bot.get_access_status(bot.get_user(2)) == "trial", \
    "day 14 itself (inclusive) must still count as trial"
print("3. A user registered exactly 14 days ago is still in trial (inclusive boundary)")

assert bot.get_access_status(bot.get_user(3)) == "expired", \
    "day 15 must be expired"
print("4. A user registered 15 days ago has an expired trial")

print("\nALL TRIAL-14-DAYS TESTS PASSED")
