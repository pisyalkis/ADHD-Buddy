import os, sys, sqlite3
from datetime import timedelta

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

# Реальный баг (обнаружен при доработке фичи снуза уведомлений): created_at
# ниже строился через наивную date.today() -- дату в ТЕКУЩЕМ системном
# часовом поясе контейнера (не обязательно Asia/Tbilisi). Но
# get_access_status/get_trial_days_left (после фикса #243) считают
# "сегодня" именно в Asia/Tbilisi (USER_TIMEZONE) -- см. _trial_today().
# Примерно 4 часа в сутки (когда UTC ещё "вчера", а Тбилиси, UTC+4, уже
# "сегодня") эти две даты расходятся, и тест ловил ложный fail ровно в это
# окно. Используем ту же таймзону, что и сам расчёт триала.
today = bot.datetime.now(bot.pytz.timezone("Asia/Tbilisi")).date()

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

bot.update_user(1, timezone="Asia/Tbilisi", created_at=(today - timedelta(days=7)).isoformat())
bot.update_user(2, timezone="Asia/Tbilisi", created_at=(today - timedelta(days=14)).isoformat())
bot.update_user(3, timezone="Asia/Tbilisi", created_at=(today - timedelta(days=15)).isoformat())

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
