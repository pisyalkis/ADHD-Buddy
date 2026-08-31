import os, sys, sqlite3
from datetime import date, timedelta

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
os.makedirs(SCRATCH, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(SCRATCH, "test_subscribe_screen.db")
if os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])
os.environ["NOTIFY_USER_ID"] = "999"
import bot
bot.init_db()

conn = sqlite3.connect(bot.DB_PATH)
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (999, 'Владелец', 'M')")
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (1, 'Платный', 'M')")
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (2, 'Триал', 'M')")
conn.execute("INSERT INTO users(user_id, name, gender) VALUES (3, 'Истёк', 'M')")
conn.commit(); conn.close()

def cb_texts(kb):
    return [row[0].text for row in kb.inline_keyboard]

def cb_datas(kb):
    return [row[0].callback_data for row in kb.inline_keyboard]

# ══════════════════════════════════════════════════════════════════════════
# Bug (Artem, screenshot): a user with permanent access ("постоянный
# доступ", no subscription_until -- e.g. the owner) still saw the
# subscribe price AND the promo-code pitch, both meaningless for them.
# ══════════════════════════════════════════════════════════════════════════
bot.update_user(999, timezone="Asia/Tbilisi", subscription_until="")
text1, kb1 = bot._subscribe_text_and_kb(bot.get_user(999))
assert "постоянный доступ" in text1, text1
assert "Stars" not in text1, f"permanent access must not show a subscription price, got: {text1!r}"
assert "промокод" not in text1.lower(), f"permanent access must not mention promo codes, got: {text1!r}"
assert cb_datas(kb1) == ["go_menu"], cb_datas(kb1)
print("1. Permanent access shows only the status, no price/promo pitch, no buy/promo buttons")

# ── A real paying subscriber (has an end date) can still extend early,
#    but is not pitched the trial-promo line -----------------------------
bot.update_user(1, timezone="Asia/Tbilisi", subscription_until=(date.today() + timedelta(days=10)).isoformat())
text1b, kb1b = bot._subscribe_text_and_kb(bot.get_user(1))
assert "промокод" not in text1b.lower(), text1b
assert "go_subscribe_pay" in cb_datas(kb1b)
assert "go_menu" in cb_datas(kb1b)
print("2. An active paid subscription can still be extended, without the promo pitch")

# ══════════════════════════════════════════════════════════════════════════
# Second correction (Artem): the promo code must not be advertised anywhere
# proactively -- not on the paywall, and not on the general subscribe screen
# either. Still redeemable via the explicit /promo command, just not pushed.
# ══════════════════════════════════════════════════════════════════════════
bot.update_user(2, timezone="Asia/Tbilisi", created_at=date.today().isoformat())
text2, kb2 = bot._subscribe_text_and_kb(bot.get_user(2))
assert "промокод" not in text2.lower(), f"trial screen must not mention promo codes anymore, got: {text2!r}"
assert "чашка кофе" in text2, text2
assert "🎁 У меня промокод" not in cb_texts(kb2), cb_texts(kb2)
print("3. A user still in the trial isn't pitched the promo code either, only the coffee-price line")

bot.update_user(3, timezone="Asia/Tbilisi", created_at=(date.today() - timedelta(days=30)).isoformat())
text3, kb3 = bot._subscribe_text_and_kb(bot.get_user(3))
assert "промокод" not in text3.lower(), text3
assert "🎁 У меня промокод" not in cb_texts(kb3), cb_texts(kb3)
print("4. An expired user on the subscribe screen also isn't pitched the promo code")

print("\nALL SUBSCRIBE-SCREEN TESTS PASSED")
