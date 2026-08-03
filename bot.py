"""
ADHD Focus Bot v5
- Персонализация: имя + пол
- Русский язык по умолчанию
- Утро: разминка, фокус, задачи A/B/C, free writing, благодарность, внутренний ребёнок
- Вечер: достижения, похвала, highlights, планы A/B/C, AI-анализ дня
- Навыки СДВГ из тренинга (ежедневный совет)
- AI: коуч + утренняя мотивация + вечерний анализ
- Уведомления: 9:00 и 21:00 по Тбилиси (UTC+4)
"""

import os, json, sqlite3, asyncio, random, threading, time
from datetime import datetime, date, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ── CONFIG ─────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY", "")
# Укажи свой Telegram ID для уведомлений (узнай через @userinfobot)
NOTIFY_USER_ID = int(os.getenv("NOTIFY_USER_ID", "0"))
# Таймзона пользователя — время уведомлений в настройках бота задаётся в этой зоне
# Примеры: "Asia/Tbilisi", "Europe/Moscow", "Europe/Berlin", "UTC"
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "Asia/Tbilisi")
# Путь к SQLite-базе — укажи путь на смонтированном volume (например /data/adhd.db),
# иначе данные будут теряться при каждом передеплое
DB_PATH = os.getenv("DB_PATH", "adhd.db")

# Автосброс зависших диалогов (утро/вечер/онбординг). Без таймаута человек,
# бросивший шаг с вводом текста на середине, застревает в нём навсегда —
# любое следующее сообщение (даже не связанное, например фидбек) будет
# по ошибке принято за ответ на давно забытый вопрос.
CONV_TIMEOUT_SHORT = 600   # 10 минут — онбординг (имя/пол)
CONV_TIMEOUT_LONG  = 1800  # 30 минут — утренний и вечерний блок

# ── CONVERSATION STATES ────────────────────────────────────────────────────
(ONBOARD_NAME, ONBOARD_GENDER,
 M_EXERCISE, M_FOCUS, M_B1, M_B2, M_C1, M_C2, M_C3,
 M_WRITING, M_GRATITUDE, M_CHILD,
 E_TASKS_DONE, E_ACH, E_PRAISE, E_HIGHLIGHTS, E_SELFCARE, E_ENERGY,
 E_A, E_B1, E_B2, E_C1, E_C2, E_C3) = range(24)

# ── ADHD SKILLS FROM TRAINING ──────────────────────────────────────────────
SKILLS = [
    {
        "name": "📋 Список дел и календарь",
        "desc": "Записывай ВСЁ, что приходит в голову и нужно сделать — один общий список, а не только на сегодня.",
        "explanation": "Нет такого дела, которое ты не мог(ла) бы забыть. Список дел разгружает оперативную память мозга — не нужно держать всё в голове, если оно уже записано.",
        "instructions": "Веди один большой список — туда попадает вообще всё: срочное и не очень, крупное и мелкое, даже то, что пригодится через месяц. Удобно вести его в заметках телефона или в блокноте — записывай новое сверху или снизу, а сделанное просто вычёркивай. Из этого списка каждый день ты выбираешь несколько дел и превращаешь их в свои A/B/C задачи на сегодня.\n\nКалендарь — только для встреч и событий с реальной договорённостью с другим человеком. *Не вноси в календарь дела, которым ты сам(а) придумал(а) время* — «помою полы в 12:00». Такие самообещания часто срываются и бьют по самооценке. Всё остальное — в список дел.\n\nОба инструмента проверяй каждый день. Сообщения и задачи из мессенджеров и стикеров — сразу переноси в список дел.\n\n_Список веди отдельно (заметки, блокнот), а сюда каждый день переноси то, что приоритетно именно сегодня._"
    },
    {
        "name": "🔤 Приоритеты A, B, C",
        "desc": "Каждый день — 6 задач: 1 A, 2 B, 3 C. У каждой свой уровень важности.",
        "explanation": "Мозг с СДВГ любит браться за лёгкое и приятное в первую очередь — это ловушка. Система ABC заставляет сначала сделать то, что реально важно, а не то, что хочется сделать.",
        "instructions": "Каждый день ставишь ровно 6 задач:\n🅰️ *1 задача A* — самая важная. Делаешь её первой, до всего остального.\n🅱️ *2 задачи B* — важные, хорошо бы сделать сегодня. Но только после A.\n🅲 *3 задачи C* — менее важные. Делаешь после A и обеих B, если осталось время.\n\nБот каждое утро попросит поставить эти 6 задач, а вечером — отчитаться, что из них получилось."
    },
    {
        "name": "🛑 Навык СТОП",
        "desc": "С-Стой. Т-Только шаг назад. О-Осмотрись. П-Попытайся действовать осознанно.",
        "explanation": "Пауза разрывает автоматическую реакцию и даёт долю секунды, чтобы выбрать действие осознанно, а не по импульсу. Цель — не изменить поведение, а ЗАМЕТИТЬ что происходит.",
        "instructions": "Используй когда: отвлёкся(ась), застрял(а), чувствуешь импульс сделать что-то необдуманное (например открыть телефон), или уже залип(ла) в нём.\n*С* — Стой. Замри на секунду.\n*Т* — Только шаг назад: мысленно отступи от ситуации.\n*О* — Осмотрись: что вообще сейчас происходит вокруг и внутри тебя?\n*П* — Попытайся действовать осознанно, а не на автомате.\n\n⚠️ *Важно — начинай практиковать на лёгких ситуациях:* во время чистки зубов, за утренним кофе, в рандомные моменты дня. Не пытайся применить навык сначала в трудных моментах — это слишком сложно. Чем больше практики в нейтральных ситуациях, тем лучше сработает когда действительно нужно.\n\n_Бот сам предлагает эту технику в дневном чекине, если отметишь «Залип(ла) в телефоне» или «Задача пугает». Вечером можно отметить в чек-листе, если применял(а)._"
    },
    {
        "name": "👣 Первый неподавляющий шаг",
        "desc": "Не планируй все шаги заранее — найди только самый первый, маленький.",
        "explanation": "Начало — самое сложное. После старта обычно легче.",
        "instructions": "Первый шаг должен: завершаться за один день и не вызывать желания отложить. Если хочется отложить — шаг слишком большой, уменьши его.\n\n⚠️ *Не разбивай всю задачу на шаги сразу* — это само по себе подавляет. Выбери только 1-2 следующих шага, не больше. Следующие шаги часто зависят от результата первого.\n\nПример: хочу попасть к врачу → первый шаг «позвонить в регистратуру», а не «найти врача, записаться, выяснить что взять с собой...»\n\n_Бот предлагает эту технику в дневном чекине при «Непонятно с чего начать» и «Задача пугает». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "⚡ Активация",
        "desc": "Не жди мотивации — запусти мозг физическим действием или сильным ощущением.",
        "explanation": "Мотивация — это чувство, которое появляется ПОСЛЕ того как начал(а) действовать, а не до. Ждать её — тупик. Физическое действие или сильное ощущение запускает мозг раньше, чем придёт желание что-то делать.",
        "instructions": "Встань, потянись, сделай 5 приседаний — или используй сильные ощущения: холодная вода, громкая музыка. Это помогает запустить мозг.\n\n_Это же делает утренняя разминка бота. Бот также предлагает активацию в дневном чекине при «Непонятно с чего начать» и «Жду подходящего момента». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "😴 Планирование отдыха",
        "desc": "Отдых нужно планировать намеренно — сам он не случится.",
        "explanation": "Отдыхай ДО того как перегорел(а) — потом уже поздно. Гиперфокус — это не суперсила, он истощает.",
        "instructions": "Перерывы 5-10 минут каждые 25-30 минут. Но сначала вспомни, что тебе реально помогает отдохнуть, и выпиши список заранее — чтобы не было паралича выбора в моменте. Примеры: короткая прогулка, потянуться, музыка, чай, посмотреть в окно, поговорить с кем-то, вздремнуть. Крупные вещи, которые по-настоящему восстанавливают — выезд на природу, встреча с друзьями, целый день без дел — тоже планируй заранее и ставь в планы, как обычную задачу, а не жди, что они случатся сами.\n\n⚠️ *Не всё что выглядит как отдых — является отдыхом именно для тебя.* Скроллинг — это стимуляция, а не отдых. Проверяй себя: «чувствую ли я восстановление сил после этого?». Даже +5-10% — уже результат. Составь свой личный список того, что реально восстанавливает.\n\n_Бот напоминает об этом в дневном чекине, когда всё идёт по плану. Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "⚓ Бросить якорь",
        "desc": "Техника заземления через тело и органы чувств — когда захлестнули эмоции: тревога, паника, злость.",
        "explanation": "Переключение на физические ощущения и звуки вокруг отвлекает мозг от эмоционального шторма и возвращает в настоящий момент. Якорь не уберёт шторм — но удержит тебя в нём.",
        "instructions": "1. Замети шторм внутри (мысли, чувства, ощущения). 2. Вдави ноги в пол, выпрями спину, сожми пальцы. 3. Найди 5 предметов вокруг, услышь 3-4 звука.\n\n_Бот предлагает эту технику в дневном чекине при «Задача пугает», «Жду подходящего момента» и «Мало времени». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "⏱ Работа по таймеру",
        "desc": "Чередуй работу и отдых по таймеру.",
        "explanation": "У СДВГ-мозга слабое чувство времени изнутри — работа незаметно растягивается на часы или, наоборот, кажется невыносимо долгой уже через 5 минут. Таймер задаёт время снаружи, когда мозг не может сделать это сам, и профилактирует гиперфокус и истощение.",
        "instructions": "Выясни сколько минут ты можешь работать над скучной задачей без остановки. Поставь таймер на это время. Работай только до сигнала. Потом отдых.\n\n_Бот упоминает таймер почти в каждой дневной ситуации — от «Задача пугает» до «Мало времени». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "📝 Бумажка гениальных мыслей",
        "desc": "Записывай отвлекающие мысли, но не выполняй их сразу.",
        "explanation": "Мозг держит мысль в фокусе, пока боится её потерять — как только она записана, тревога 'не забыть' исчезает, и внимание освобождается для текущей задачи.",
        "instructions": "Когда садишься за работу — возьми с собой лист A4 или страницу из блокнота и ручку. Когда приходит отвлекающая мысль — не гони её, а сразу выпиши на этот лист, скажи себе 'займусь позже' и вернись к задаче. В конце дня просмотри список: то, что оказалось действительно важным — перенеси в свой общий список дел, остальное можно выбросить.\n\n_Похоже на утреннее Free writing в боте — только в течение дня, а не только утром. Вечером есть отдельный пункт в чек-листе, если применял(а)._"
    },
    {
        "name": "💧 Холодная вода",
        "desc": "Быстрое снижение перевозбуждения через температуру.",
        "explanation": "Это активирует рефлекс ныряльщика и замедляет сердечный ритм.",
        "instructions": "Умойся холодной водой или плесни на лицо. Помогает при сильных эмоциях, перевозбуждении и когда нужно быстро успокоиться.\n\n_Бот предлагает это в дневном чекине при «Задача пугает» и «Жду подходящего момента». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "🌬 Дыхание",
        "desc": "Выдох длиннее вдоха успокаивает нервную систему.",
        "explanation": "Замедленное дыхание активирует парасимпатическую систему.",
        "instructions": "Вдох 4 счёта — выдох 8 счётов. Или квадрат: вдох 4, задержка 4, выдох 4, задержка 4. Используй перед сном, при тревоге, для переключения.\n\n_Бот упоминает дыхание в дневном чекине при «Задача пугает». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "🏠 Изменение среды",
        "desc": "Убери отвлекающие факторы — не полагайся на силу воли.",
        "explanation": "Сила воли — конечный ресурс, который тратится за день. Сопротивляться отвлекающим факторам силой воли — как плыть против течения. Среда без отвлекающих факторов работает даже когда сила воли уже кончилась.",
        "instructions": "Телефон вне поля зрения. Лишние вкладки закрыты. Стол свободен. Наушники надеты. Каждый отвлекающий фактор требует своей стратегии.\n\n_Бот предлагает это в дневном чекине при «Мало времени». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "🤲 Готовность и полуулыбка",
        "desc": "Расслабленная поза тела и лёгкая улыбка себе — техника против сопротивления задаче.",
        "explanation": "Тело и мозг работают в обе стороны: не только настроение влияет на позу, но и поза — на настроение. Расслабленное лицо и полуулыбка сигналят мозгу «сопротивления нет», и внутреннее «не хочу» слабеет.",
        "instructions": "Применяй после того как первый шаг и активация уже попробованы, но сопротивление всё равно есть.\n\n1. Почувствуй опору под ногами. Понаблюдай за дыханием — просто замечай вдох и выдох.\n2. Расслабь мышцы лица от лба вниз — глаза, щёки, челюсть. Мягко приподними уголки губ. Это улыбка себе, не на камеру.\n3. Опусти руки на колени ладонями вверх (или вдоль тела, большие пальцы в стороны). Расслабленные ладони — телесная противоположность злости и напряжения.\n4. Приступи к задаче. Когда заметишь сопротивление — повтори.\n\n_Бот предлагает эту технику в дневном чекине при «Задача пугает», «Боюсь сделать плохо» и «Внутреннее сопротивление». Вечером есть отдельный пункт в чек-листе._"
    },
    {
        "name": "⚖️ За и против",
        "desc": "Инструмент для выхода из прокрастинации и принятия решений.",
        "explanation": "Прокрастинация — это избегание неприятных переживаний. «За и против» делает невидимые выгоды и потери откладывания видимыми, после чего мозгу проще сделать выбор в пользу действия.",
        "instructions": "Возьми лист и заполни 4 клетки:\n🔴 Плюсы откладывания (краткосрочные + долгосрочные)\n🔴 Минусы откладывания (краткосрочные + долгосрочные)\nПотом те же 4 клетки для «приступить сейчас».\n\nПосле этого обычно видно, почему прокрастинация невыгодна. Тот же метод работает для любых жизненных решений — когда не знаешь что выбрать.\n\n_Время на таблицу точно меньше, чем время прокрастинации задачи._"
    },
    {
        "name": "🎯 Выбор из множества решений",
        "desc": "Таблица когда вариантов слишком много или ни один не идеален.",
        "explanation": "Когда вариантов много, мозг с СДВГ зависает — слишком много всего нужно удержать одновременно. Таблица переносит работу из головы на бумагу и даёт ощущение ясности.",
        "instructions": "1. Сформулируй проблему в 1-2 предложениях.\n2. Выпиши ВСЕ возможные решения, даже нереалистичные.\n3. Для каждого — плюсы и минусы (краткосрочные и долгосрочные).\n4. Оцени каждый плюс и минус от 1 до 10 по важности.\n5. Для каждого варианта: сумма плюсов минус сумма минусов = итог.\n\nВыбери вариант с наибольшим итогом. Метод не гарантирует идеальный ответ — но помогает выбрать оптимальный и наконец начать действовать."
    },
    {
        "name": "🔦 Маячки внимания",
        "desc": "Физические напоминалки, которые возвращают тебя к задаче.",
        "explanation": "При СДВГ внутренняя система внимания работает нестабильно. Маячки — это внешняя система, которая работает даже когда внутренняя спит.",
        "instructions": "Поставь стикеры или наклейки там где обычно отвлекаешься: на телефоне, мониторе, холодильнике, окне. Каждый раз видя маячок — задай вопрос: «Я делаю то что должен(а), или отвлёкся(ась)?». Если отвлёкся(ась) — вернись к задаче без самокритики.\n\nРаботают и будильники-напоминания в телефоне во время рабочего блока — с вопросом «а не фигней ли я занимаюсь?».\n\nМаячками могут быть любые фигурки, игрушки, плакаты — любой предмет который ты замечаешь."
    },
    {
        "name": "🧰 Аптечка самоуспокоения",
        "desc": "Коробка с вещами для снижения перевозбуждения — маст хэв при СДВГ.",
        "explanation": "Перевозбуждение — частое состояние при СДВГ. Когда мы в нём, сложно что-то делать. Физические сенсорные предметы помогают быстро снизить возбуждение без усилий воли.",
        "instructions": "Собери небольшую коробку с предметами которые тебя успокаивают: мягкий плед, маска для глаз, наушники, ароматические масла или свечи, антистресс-игрушки, любимые конфеты, фото близких.\n\nДержи на виду рядом с рабочим местом — если надо искать, не вспомнишь.\n\nКогда использовать: когда сложно начать задачу, как перерыв между делами, когда эмоции зашкаливают, перед сном. Даже 5 минут с маской на глазах — это уже восстановление нервной системы."
    },
    {
        "name": "👁 Техника заземления 5-4-3-2-1",
        "desc": "Возвращение в настоящий момент через 5 органов чувств.",
        "explanation": "Тревога и эмоциональный шторм уводят внимание в мысли. Переключение на конкретные физические ощущения возвращает мозг в реальность и снижает перевозбуждение.",
        "instructions": "Используй при тревоге, потере фокуса или эмоциональном шторме. Последовательно:\n👁 5 предметов которые видишь\n✋ 4 вещи которые можешь потрогать (потрогай их)\n👂 3 звука которые слышишь\n👃 2 запаха (или вспомни 2 любимых)\n👅 1 вкус во рту\n\nЭто не убирает стресс — но возвращает тебя в реальность. Можно делать незаметно в любом месте: на работе, в транспорте, на встрече."
    },
    {
        "name": "🏆 Подкрепление",
        "desc": "Хвалить себя за навыки и сделанные дела — не каприз, а необходимость.",
        "explanation": "Мозг с СДВГ плохо получает дофамин от долгосрочных целей. Без маленьких наград за маленькие шаги мотивация быстро кончается. Подкрепление — это буквально топливо для следующего шага.",
        "instructions": "Подкреплять важно за применение навыка — не только за результат.\n\nЧто работает:\n• Сказать себе вслух «Молодец, [имя]!»\n• Сделать победный жест\n• Поставить галочку в трекере или завести банку с монетками\n• Записать в список сделанного\n• Рассказать кому-то\n• Сделать намеренную паузу: вдох-выдох, «я сделал(а) это»\n\nЗаметить сделанное — это уже результат. Главное взять паузу и отметить."
    },
]

MOTIVATIONS_M = [
    "Сегодня хороший день чтобы сделать то, что важно.",
    "Один шаг — и ты уже в движении.",
    "Только одно главное. Остальное подождёт.",
    "Твой мозг нестандартный. Это сила.",
    "Чуть больше чем вчера — этого достаточно.",
    "Проснулся — уже хорошо. Дальше легче.",
    "Сделай одно дело. Потом ещё одно.",
]

MOTIVATIONS_F = [
    "Сегодня хороший день чтобы сделать то, что важно.",
    "Один шаг — и ты уже в движении.",
    "Только одно главное. Остальное подождёт.",
    "Твой мозг нестандартный. Это сила.",
    "Чуть больше чем вчера — этого достаточно.",
    "Проснулась — уже хорошо. Дальше легче.",
    "Сделай одно дело. Потом ещё одно.",
]

WARMUP = [
    ("Шея — повороты 🔄", "Медленно влево-вправо, 5 раз"),
    ("Плечи — круги 🔄", "Вперёд 5 раз, назад 5 раз"),
    ("Запястья 🤲", "Покрути кулаки в обе стороны"),
    ("Поясница ↔️", "Наклоны влево-вправо"),
    ("Колени 🦵", "Поднимай колени стоя, по 5 раз"),
    ("Голеностоп 🦶", "Вращение каждой ногой по 10 сек"),
]

# ── DATABASE ───────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT DEFAULT '',
        gender TEXT DEFAULT 'M',
        focus TEXT DEFAULT '',
        streak TEXT DEFAULT '[]',
        last_skill_date TEXT DEFAULT '',
        buddy_name TEXT DEFAULT '',
        notif_morning TEXT DEFAULT '09:00',
        notif_midday TEXT DEFAULT '13:00',
        notif_evening TEXT DEFAULT '21:00',
        notif_enabled INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS diary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, date TEXT, block TEXT, data TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, text TEXT,
        priority TEXT DEFAULT 'C',
        done INTEGER DEFAULT 0,
        created TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, text TEXT, created TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS research (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, day INTEGER, question TEXT,
        answer TEXT, created TEXT
    )""")

    # Migrate existing DB - add columns if missing
    for col, default in [
        ("buddy_name", "''"),
        ("notif_morning", "'09:00'"),
        ("notif_midday", "'13:00'"),
        ("notif_evening", "'21:00'"),
        ("notif_enabled", "0"),
        ("notif_morning_on", "1"),
        ("notif_midday_on",  "1"),
        ("notif_evening_on", "1"),
        ("beacon_enabled", "0"),
        ("beacon_interval", "2"),
        ("beacon_last_sent", "''"),
        ("focus_active", "0"),
        ("focus_end_time", "''"),
        ("focus_duration", "0"),
        ("focus_minutes_today", "0"),
        ("focus_date", "''"),
        ("city", "''"),
        ("created_at", f"'{date.today().isoformat()}'"),
        ("research_done", "''"),
        ("research_awaiting", "0"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")
        except Exception:
            pass
    conn.commit(); conn.close()

def get_user(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users(user_id) VALUES(?)", (uid,))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        row = c.fetchone()
    result = dict(row)
    conn.close()
    return result

def update_user(uid, **kwargs):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for k, v in kwargs.items():
        c.execute(f"UPDATE users SET {k}=? WHERE user_id=?", (v, uid))
    conn.commit(); conn.close()

def save_diary(uid, block, data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    d = date.today().isoformat()
    c.execute("DELETE FROM diary WHERE user_id=? AND date=? AND block=?", (uid, d, block))
    c.execute("INSERT INTO diary(user_id,date,block,data) VALUES(?,?,?,?)",
              (uid, d, block, json.dumps(data, ensure_ascii=False)))
    conn.commit(); conn.close()

def get_all_notif_users():
    """Все пользователи с включёнными уведомлениями."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE notif_enabled=1 AND name!=''")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_diary(uid, block, for_date=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    d = for_date or date.today().isoformat()
    c.execute("SELECT data FROM diary WHERE user_id=? AND date=? AND block=?", (uid, d, block))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else {}

def get_latest_evening_plan(uid):
    """Вчерашний вечерний дневник для переноса плана в утро.

    Помимо "строго вчера" проверяем ещё и "сегодня": если человек заполнял
    вечерний блок уже за полночь (по своему времени), запись физически
    попадает в бакет "сегодня", а не "вчера" — и обычный "вчера"-запрос её
    не находит, план молча пропадает. Берём непустую запись, отдавая
    приоритет более свежей (сегодняшней), если она есть.
    """
    today = get_diary(uid, "evening", date.today().isoformat())
    if today.get("e_a"):
        return today
    yesterday = get_diary(uid, "evening", (date.today() - timedelta(days=1)).isoformat())
    return yesterday

def save_feedback(uid, text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO feedback(user_id,text,created) VALUES(?,?,?)",
              (uid, text, datetime.now().isoformat()))
    conn.commit(); conn.close()

def add_streak(uid):
    user = get_user(uid)
    streak = json.loads(user["streak"])
    today = date.today().isoformat()
    if today not in streak:
        streak.append(today)
        update_user(uid, streak=json.dumps(streak))

def calc_streak(uid):
    user = get_user(uid)
    streak = sorted(set(json.loads(user["streak"])), reverse=True)
    if not streak: return 0
    count = 0
    cur = date.today()
    for i, d in enumerate(streak):
        if (cur - date.fromisoformat(d)).days == i: count += 1
        else: break
    return count

# ── HELPERS ────────────────────────────────────────────────────────────────
def g(gender, male, female):
    """Вернуть нужную форму слова в зависимости от пола."""
    if gender == 'F': return female
    if gender == 'N': return f"{male}(а)"
    return male

def build_tasks_summary(morning_data):
    """Формирует текстовый список задач из утреннего дневника."""
    lines = []
    if morning_data.get("focus"): lines.append(f"🅰️ {morning_data['focus']}")
    if morning_data.get("b1"):    lines.append(f"🅱️ {morning_data['b1']}")
    if morning_data.get("b2"):    lines.append(f"🅱️ {morning_data['b2']}")
    if morning_data.get("c1"):    lines.append(f"🅲 {morning_data['c1']}")
    if morning_data.get("c2"):    lines.append(f"🅲 {morning_data['c2']}")
    if morning_data.get("c3"):    lines.append(f"🅲 {morning_data['c3']}")
    return "\n".join(lines) if lines else "_задачи не заданы_"


def skip_kb(cb):
    return InlineKeyboardMarkup([[InlineKeyboardButton("Пропустить →", callback_data=cb)]])

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Утро", callback_data="go_morning"),
         InlineKeyboardButton("🌙 Вечер", callback_data="go_evening")],
        [InlineKeyboardButton("🍅 Фокус-режим", callback_data="go_focus"),
         InlineKeyboardButton("📋 Задачи", callback_data="go_tasks")],
        [InlineKeyboardButton("📖 О СДВГ", callback_data="go_guide"),
         InlineKeyboardButton("🤖 Коуч", callback_data="go_coach")],
        [InlineKeyboardButton("🧠 Навыки", callback_data="go_skill"),
         InlineKeyboardButton("🔥 Стрик", callback_data="go_streak")],
        [InlineKeyboardButton("🗂 Карточка дня", callback_data="go_daycard"),
         InlineKeyboardButton("⚙️ Настройки", callback_data="go_settings")],
        [InlineKeyboardButton("💬 Обратная связь", callback_data="go_feedback"),
         InlineKeyboardButton("ℹ️ О боте", callback_data="go_about")],
    ])

def morning_cta_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Заполнить утро", callback_data="go_morning")],
        [InlineKeyboardButton("☰ Меню", callback_data="go_menu")],
    ])

def evening_cta_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌙 Закрыть день", callback_data="go_evening")],
        [InlineKeyboardButton("☰ Меню", callback_data="go_menu")],
    ])

def today_str():
    return datetime.now().strftime("%d %B %Y")

def get_daily_skill(uid):
    """Возвращает навык дня — меняется каждый день."""
    today = date.today().isoformat()
    idx = hash(today + str(uid)) % len(SKILLS)
    return SKILLS[idx]

# ── ONBOARDING ─────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    init_db()
    user = get_user(uid)

    # Если уже зарегистрирован — сразу предложить нужный блок по времени суток
    if user["name"]:
        hour = datetime.now(pytz.timezone(USER_TIMEZONE)).hour
        if hour < 12:
            await update.message.reply_text(
                f"С возвращением, {user['name']}! Сейчас утро — самое время настроиться на день 👇",
                reply_markup=morning_cta_kb()
            )
        elif hour < 18:
            await update.message.reply_text(
                f"С возвращением, {user['name']}! Сейчас день — работаем 👇",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                f"С возвращением, {user['name']}! Сейчас вечер — время подвести итоги дня 👇",
                reply_markup=evening_cta_kb()
            )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я твой личный помощник для людей с СДВГ и всех, у кого есть трудности с фокусом и прокрастинацией.\n\n"
        "🔄 *Три раза в день:*\n"
        "☀️ *Утром* — настроиться, поставить задачи ABC\n"
        "☕ *Днём* — напомнить о задачах, помочь если застрял(а)\n"
        "🌙 *Вечером* — закрыть день, поставить планы на завтра\n\n"
        "🍅 *Фокус-режим* — запускаешь таймер (25, 45 или 60 минут), бот пишет когда время вышло. "
        "Считает сколько минут в фокусе за день.\n\n"
        "🤖 *Коуч* — техники на случай прокрастинации, перегруза, отвлечения.\n"
        "🧠 *Навыки СДВГ* — практики из DBT-тренинга.\n\n"
        "Как тебя зовут?",
        parse_mode="Markdown"
    )
    return ONBOARD_NAME

async def got_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) > 30:
        await update.message.reply_text("Имя слишком длинное, напиши покороче:")
        return ONBOARD_NAME
    ctx.user_data["onboard_name"] = name
    # Сохраняем имя в БД сразу — чтобы оно не потерялось при перезапуске бота
    update_user(update.effective_user.id, name=name)
    await update.message.reply_text(
        f"Отлично, {name}! Один вопрос для персонализации 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Мужской", callback_data="gender_M"),
             InlineKeyboardButton("Женский", callback_data="gender_F")],
            [InlineKeyboardButton("Другое", callback_data="gender_N")],
        ])
    )
    return ONBOARD_GENDER

async def got_gender(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    # ctx.user_data может быть пустым если ConversationHandler перезапустился — берём имя из БД
    name = ctx.user_data.get("onboard_name") or get_user(uid).get("name", "")
    gender = "M" if q.data == "gender_M" else ("F" if q.data == "gender_F" else "N")
    update_user(uid, gender=gender)  # имя уже сохранено в got_name, не перезаписываем

    await q.message.reply_text(
        f"Отлично, {name}! Давай я коротко расскажу как работает бот 👇",
    )
    await asyncio.sleep(0.5)
    await q.message.reply_text(
        "🧠 *Зачем этот бот?*\n\n"
        f"У мозга с СДВГ есть одна особенность: он управляется *интересом и срочностью*, а не важностью. "
        f"Поэтому важные дела откладываются, а день рассыпается.\n\n"
        f"Этот бот даёт мозгу то, чего ему не хватает — *внешнюю структуру*.\n\n"
        f"Структура дня при СДВГ — это не про дисциплину. "
        f"Это про то, чтобы каждое утро знать *одно* главное дело, и каждый вечер видеть что ты {g(gender, 'сделал', 'сделала')}.\n\n"
        f"📚 *Основа бота* — доказательные методы: DBT-тренинг навыков для взрослых с СДВГ и когнитивно-поведенческая терапия (программа Safren). "
        f"Это не мотивашки — это конкретные техники, которые работают на уровне нейробиологии.",
        parse_mode="Markdown"
    )
    await asyncio.sleep(0.8)
    await q.message.reply_text(
        "☀️☕🌙 *Как работает бот — три точки за день*\n\n"
        "*Утром* — помогаю настроиться на день:\n"
        "• Разминка (тело будит мозг)\n"
        "• Свободное письмо — выгрузить всё из головы\n"
        "• Благодарность — настрой на день\n"
        "• Задачи A, B, C — одно главное, ничего лишнего\n\n"
        "*Днём* — напоминаю о задачах и проверяю как ты:\n"
        "• Показываю что запланировано на сегодня\n"
        "• Спрашиваю как дела — застрял(а), не знаешь с чего начать, тревожно?\n"
        "• Даю конкретную технику под ситуацию, а не общий совет «соберись»\n\n"
        "*Вечером* — проверяю каким был день:\n"
        "• Что получилось — даже маленькое\n"
        "• Похвалить себя (это важно — об этом ниже)\n"
        "• Записать A-задачу на завтра\n\n"
        "Утро — это *разгон*, день — *опора*, вечер — *посадка*. "
        "Всё что ты заполняешь за день сохраняется в 🗂 *карточку дня* — можно вернуться и посмотреть.",
        parse_mode="Markdown"
    )
    await asyncio.sleep(0.8)
    await q.message.reply_text(
        "🏆 *Почему важно отмечать победы*\n\n"
        "Мозг с СДВГ плохо вырабатывает дофамин от долгосрочных целей — "
        "он живёт в настоящем.\n\n"
        "Когда ты каждый вечер *замечаешь что сделал(а)* — даже маленькое — "
        "мозг получает сигнал: «это работает, продолжай». "
        "Это не самодовольство, это *топливо* для следующего дня.\n\n"
        "Поэтому вечерний блок начинается не с планов, а с достижений и похвалы себе. "
        "Стрик — это видимое доказательство прогресса.\n\n"
        "_Маленькие победы замеченные каждый день — это и есть мотивация._",
        parse_mode="Markdown",
    )
    await asyncio.sleep(0.5)
    await q.message.reply_text(
        "И последнее — из какого ты города? (можно пропустить)",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Пропустить", callback_data="onboard_done")
        ]])
    )
    ctx.user_data["awaiting_city"] = True
    return ConversationHandler.END

async def onboard_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(
        "🔔 *Последний шаг — уведомления*\n\n"
        "Бот пишет три раза в день: утром, днём и вечером. "
        "Без уведомлений польза от бота сильно меньше.\n\n"
        "Включить уведомления?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Включить", callback_data="onboard_notif_on")],
            [InlineKeyboardButton("Пропустить, настрою позже", callback_data="onboard_notif_skip")],
        ])
    )

async def onboard_notif_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    update_user(uid, notif_enabled=1)
    await q.message.reply_text(
        "✅ *Уведомления включены!*\n\n"
        "По умолчанию: ☀️ 09:00 · ☕ 13:00 · 🌙 21:00\n"
        "Изменить время можно в ⚙️ Настройки.\n\n"
        "Всё готово — начнём! 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

async def onboard_notif_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(
        "Окей! Включить уведомления можно в любой момент через ⚙️ Настройки.\n\nНачнём! 🚀",
        reply_markup=main_menu()
    )

# ── MORNING FLOW ───────────────────────────────────────────────────────────
async def morning_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    name = user["name"]
    gender = user["gender"]
    motiv = random.choice(MOTIVATIONS_F if gender == 'F' else MOTIVATIONS_M)

    # Показать вчерашние планы если есть и сохранить их для предзаполнения задач A/B/C
    ev = get_latest_evening_plan(uid)
    y_plan = {
        "a":  ev.get("e_a", ""),  "b1": ev.get("e_b1", ""), "b2": ev.get("e_b2", ""),
        "c1": ev.get("e_c1", ""), "c2": ev.get("e_c2", ""), "c3": ev.get("e_c3", ""),
    }
    ctx.user_data["y_plan"] = y_plan
    plans_text = ""
    if y_plan["a"]:
        plans_text = f"\n\n⭐ Помни — сегодня тебе важно:\n🅰️ {y_plan['a']}"
        if y_plan["b1"]: plans_text += f"\n🅱️ {y_plan['b1']}"
        if y_plan["b2"]: plans_text += f"\n🅱️ {y_plan['b2']}"

    skill = get_daily_skill(uid)

    # Адаптивное приветствие по уровню энергии вечера
    last_energy = int(ev.get("e_energy", 0) or 0)
    energy_note = ""
    if last_energy in (1, 2):
        energy_note = (
            f"\n\n🔋 *Вчера был тяжёлый день* — ты отметил(а) низкий уровень энергии.\n"
            "Сегодня можно взять темп помедленнее. Главное — одна задача A."
        )

    await q.message.reply_text(
        f"☀️ *Доброе утро, {name}!*\n"
        f"_{today_str()}_\n\n"
        f"_{motiv}_{plans_text}{energy_note}\n\n"
        f"💡 *Навык дня:* {skill['name']}\n"
        f"_{skill['desc']}_",
        parse_mode="Markdown"
    )
    await asyncio.sleep(0.5)

    # Если энергия была низкой — сразу предложить быстрый режим первой кнопкой
    if last_energy in (1, 2):
        warmup_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Только задачи (5 мин)", callback_data="morning_quick")],
            [InlineKeyboardButton("▶️ Полное утро с разминкой", callback_data="warmup_go")],
            [InlineKeyboardButton("✅ Разминку уже сделал(а)", callback_data="warmup_done")],
        ])
        warmup_text = (
            "🏃 *Разминка или сразу к делу?*\n\n"
            "Вчера был тяжёлый день — можно пропустить разминку и сразу поставить задачи.\n"
            "_Даже в лёгкий день одна задача A — уже победа._"
        )
    else:
        warmup_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Начать разминку", callback_data="warmup_go")],
            [InlineKeyboardButton("✅ Уже сделал(а)", callback_data="warmup_done")],
            [InlineKeyboardButton("Пропустить →", callback_data="skip_warmup")],
            [InlineKeyboardButton("⚡ Быстро — только задачи", callback_data="morning_quick")],
        ])
        warmup_text = (
            "🏃 *2 минуты утренней разминки*\n\n"
            "Тело нужно разбудить — это важно для мозга с СДВГ.\n\n"
            "_Это программа-минимум, просто чтобы напомнить и помочь начать. "
            "Если хочется — сделай свою разминку подольше, бот не ограничивает._"
        )

    await q.message.reply_text(warmup_text, parse_mode="Markdown", reply_markup=warmup_kb)
    return M_EXERCISE

async def warmup_go(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    msg = await q.message.reply_text("Начинаем! 🏃")
    for i, (name, hint) in enumerate(WARMUP):
        dots = "🟡"*(i+1) + "⚪"*(len(WARMUP)-i-1)
        await msg.edit_text(f"{dots}\n\n*{name}*\n_{hint}_\n\n⏱ 20 секунд...", parse_mode="Markdown")
        await asyncio.sleep(20)
    await msg.edit_text("✅ *Тело проснулось!* Теперь — настроимся.", parse_mode="Markdown")
    await ask_writing(q.message)
    return M_WRITING

async def warmup_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("💪 Отлично, тело уже разбужено!")
    await ask_writing(q.message)
    return M_WRITING

async def skip_warmup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await ask_writing(q.message)
    return M_WRITING

async def morning_quick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["quick_morning"] = True
    ctx.user_data["m_writing"] = ""
    ctx.user_data["m_gratitude"] = ""
    ctx.user_data["m_child"] = ""
    await ask_morning_focus(q.message, ctx)
    return M_FOCUS

def keep_or_skip_kb(keep_cb, skip_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оставить как есть", callback_data=keep_cb)],
        [InlineKeyboardButton("🗑 Убрать", callback_data=skip_cb)],
    ])

CARRYOVER_HINT = "\n\n_Или просто напиши новый вариант текстом — он заменит этот._"

async def ask_morning_focus(message, ctx):
    y = ctx.user_data.get("y_plan", {})
    intro = (
        "💪 *Теперь — задачи на день.*\n\n"
        "Система ABC: одно главное, не больше.\n\n"
        "🅰️ *A — одна задача, обязательно*\n"
        "_Если сделаешь только её — день прожит не зря._\n\n"
        "🅱️ *B — важные* (до 2)\n"
        "_Желательно сегодня, максимум завтра._\n\n"
        "🅲 *C — по возможности* (до 3)\n"
        "_Только после A и B._\n\n"
        "━━━━━━━━━━━━━━━\n"
    )
    if y.get("a"):
        await message.reply_text(
            intro + f"🎯 *Задача A* — вчера ты запланировал(а):\n_{y['a']}_\n\nОставить как есть?{CARRYOVER_HINT}",
            parse_mode="Markdown",
            reply_markup=keep_or_skip_kb("use_m_focus", "skip_m_focus")
        )
    else:
        await message.reply_text(
            intro + "🎯 *Задача A — что главное сегодня?*",
            parse_mode="Markdown",
            reply_markup=skip_kb("skip_m_focus")
        )

async def got_m_focus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_focus"] = update.message.text
    await ask_m_b1(update.message, ctx)
    return M_B1

async def skip_m_focus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_focus"] = ""
    await ask_m_b1(q.message, ctx)
    return M_B1

async def use_m_focus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_focus"] = ctx.user_data.get("y_plan", {}).get("a", "")
    await ask_m_b1(q.message, ctx)
    return M_B1

async def ask_m_b1(message, ctx):
    y = ctx.user_data.get("y_plan", {})
    if y.get("b1"):
        await message.reply_text(
            f"🅱️ *Задача B1* — вчера была:\n_{y['b1']}_\n\nОставить как есть?{CARRYOVER_HINT}",
            parse_mode="Markdown",
            reply_markup=keep_or_skip_kb("use_m_b1", "skip_m_b1")
        )
    else:
        await message.reply_text(
            "🅱️ *Задача B1* — важно, желательно сегодня:",
            parse_mode="Markdown",
            reply_markup=skip_kb("skip_m_b1")
        )

async def got_m_b1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_b1"] = update.message.text
    await ask_m_b2(update.message, ctx); return M_B2

async def skip_m_b1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_b1"] = ""
    await ask_m_b2(q.message, ctx); return M_B2

async def use_m_b1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_b1"] = ctx.user_data.get("y_plan", {}).get("b1", "")
    await ask_m_b2(q.message, ctx); return M_B2

async def ask_m_b2(message, ctx):
    y = ctx.user_data.get("y_plan", {})
    if y.get("b2"):
        await message.reply_text(
            f"🅱️ *Задача B2* — вчера была:\n_{y['b2']}_\n\nОставить как есть?{CARRYOVER_HINT}",
            parse_mode="Markdown",
            reply_markup=keep_or_skip_kb("use_m_b2", "skip_m_b2")
        )
    else:
        await message.reply_text("🅱️ *Задача B2:*", parse_mode="Markdown", reply_markup=skip_kb("skip_m_b2"))

async def got_m_b2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_b2"] = update.message.text
    await ask_m_c1(update.message, ctx); return M_C1

async def skip_m_b2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_b2"] = ""; await ask_m_c1(q.message, ctx); return M_C1

async def use_m_b2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_b2"] = ctx.user_data.get("y_plan", {}).get("b2", "")
    await ask_m_c1(q.message, ctx); return M_C1

async def ask_m_c1(message, ctx):
    y = ctx.user_data.get("y_plan", {})
    y_c = [y.get(k) for k in ("c1", "c2", "c3") if y.get(k)]
    if y_c:
        listed = "\n".join(f"— {p}" for p in y_c)
        await message.reply_text(
            f"🅲 *Задачи C* — вчера были:\n{listed}\n\nОставить как есть?{CARRYOVER_HINT.replace('вариант', 'C1')}",
            parse_mode="Markdown",
            reply_markup=keep_or_skip_kb("use_m_c_all", "skip_m_c_all")
        )
    else:
        await message.reply_text(
            "🅲 *Задачи C* — если останется время:\n\nC1:",
            parse_mode="Markdown", reply_markup=skip_kb("skip_m_c_all")
        )

async def got_m_c1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_c1"] = update.message.text
    await update.message.reply_text("🅲 *C2:*", parse_mode="Markdown", reply_markup=skip_kb("skip_m_c_all"))
    return M_C2

async def got_m_c2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_c2"] = update.message.text
    await update.message.reply_text("🅲 *C3:*", parse_mode="Markdown", reply_markup=skip_kb("skip_m_c_all"))
    return M_C3

async def got_m_c3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_c3"] = update.message.text
    await finish_morning(update.message, update.effective_user.id, ctx)
    return ConversationHandler.END

async def skip_m_c_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.setdefault("m_c1", "")
    ctx.user_data.setdefault("m_c2", "")
    ctx.user_data.setdefault("m_c3", "")
    await finish_morning(q.message, q.from_user.id, ctx)
    return ConversationHandler.END

async def use_m_c_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    y = ctx.user_data.get("y_plan", {})
    ctx.user_data["m_c1"] = y.get("c1", "")
    ctx.user_data["m_c2"] = y.get("c2", "")
    ctx.user_data["m_c3"] = y.get("c3", "")
    await finish_morning(q.message, q.from_user.id, ctx)
    return ConversationHandler.END

async def ask_writing(message):
    await message.reply_text(
        "📝 *Свободное письмо*\n\nВсё что есть в голове — без фильтра. Мысли, сны, тревоги, идеи.",
        parse_mode="Markdown", reply_markup=skip_kb("skip_m_writing")
    )

async def got_writing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_writing"] = update.message.text
    await ask_gratitude(update.message); return M_GRATITUDE

async def skip_m_writing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_writing"] = ""; await ask_gratitude(q.message); return M_GRATITUDE

async def ask_gratitude(message):
    await message.reply_text(
        "🙏 *Благодарность*\n\nЗа что благодарен(а) сегодня? Большое или маленькое — всё считается.",
        parse_mode="Markdown", reply_markup=skip_kb("skip_m_gratitude")
    )

async def got_gratitude(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_gratitude"] = update.message.text
    await ask_child(update.message); return M_CHILD

async def skip_m_gratitude(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_gratitude"] = ""; await ask_child(q.message); return M_CHILD

async def ask_child(message):
    await message.reply_text(
        "💛 *Inner child*\n\nСкажи себе что-то доброе. Как бы ты поговорил(а) с лучшим другом?",
        parse_mode="Markdown", reply_markup=skip_kb("skip_m_child")
    )

async def got_child(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["m_child"] = update.message.text
    await ask_morning_focus(update.message, ctx)
    return M_FOCUS

async def skip_m_child(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["m_child"] = ""
    await ask_morning_focus(q.message, ctx)
    return M_FOCUS

async def finish_morning(message, uid, ctx):
    user = get_user(uid)
    focus = ctx.user_data.get("m_focus", "")
    if focus: update_user(uid, focus=focus)

    save_diary(uid, "morning", {
        "focus":    focus,
        "b1":       ctx.user_data.get("m_b1", ""),
        "b2":       ctx.user_data.get("m_b2", ""),
        "c1":       ctx.user_data.get("m_c1", ""),
        "c2":       ctx.user_data.get("m_c2", ""),
        "c3":       ctx.user_data.get("m_c3", ""),
        "writing":  ctx.user_data.get("m_writing", ""),
        "gratitude":ctx.user_data.get("m_gratitude", ""),
        "child":    ctx.user_data.get("m_child", ""),
    })
    add_streak(uid)  # стрик растёт и от утра

    tasks_text = ""
    if focus:                          tasks_text += f"\n🅰️ {focus}"
    if ctx.user_data.get("m_b1"):     tasks_text += f"\n🅱️ {ctx.user_data['m_b1']}"
    if ctx.user_data.get("m_b2"):     tasks_text += f"\n🅱️ {ctx.user_data['m_b2']}"
    if ctx.user_data.get("m_c1"):     tasks_text += f"\n🅲 {ctx.user_data['m_c1']}"
    if ctx.user_data.get("m_c2"):     tasks_text += f"\n🅲 {ctx.user_data['m_c2']}"
    if ctx.user_data.get("m_c3"):     tasks_text += f"\n🅲 {ctx.user_data['m_c3']}"

    # AI мотивация если есть ключ
    ai_msg = ""
    if ANTHROPIC_KEY and focus:
        ai_msg = await ai_morning_boost(user["name"], user["gender"], focus)
        if ai_msg: ai_msg = f"\n\n🤖 _{ai_msg}_"

    await message.reply_text(
        f"✅ *Утро {g(user['gender'], 'записано', 'записана')}!*\n"
        f"{tasks_text if tasks_text else '_(задачи не заданы)_'}"
        f"{ai_msg}\n\n"
        f"{g(user['gender'], 'Вперёд', 'Вперёд')}, {user['name']}! 💪",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

# ── EVENING FLOW ───────────────────────────────────────────────────────────
TASK_FIELDS = [("focus", "🅰️"), ("b1", "🅱️"), ("b2", "🅱️"), ("c1", "🅲"), ("c2", "🅲"), ("c3", "🅲")]

def tasks_done_kb(morning, done):
    rows = []
    for key, icon in TASK_FIELDS:
        text = morning.get(key)
        if not text: continue
        mark = "✅" if key in done else "▫️"
        label = f"{mark} {icon} {text}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"td_{key}")])
    rows.append([InlineKeyboardButton("Готово ✅", callback_data="td_done")])
    return InlineKeyboardMarkup(rows)

async def ask_tasks_done(message, uid, ctx):
    morning = get_diary(uid, "morning")
    ctx.user_data["e_tasks_done"] = []
    await message.reply_text(
        "✅ *Что из запланированного получилось?*\n\nОтметь выполненные задачи:",
        parse_mode="Markdown",
        reply_markup=tasks_done_kb(morning, [])
    )

async def toggle_task_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    key = q.data.replace("td_", "")
    done = ctx.user_data.setdefault("e_tasks_done", [])
    if key in done:
        done.remove(key)
    else:
        done.append(key)
    morning = get_diary(q.from_user.id, "morning")
    await q.message.edit_reply_markup(reply_markup=tasks_done_kb(morning, done))
    return E_TASKS_DONE

async def tasks_done_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await ask_achievements(q.message)
    return E_ACH

async def ask_achievements(message):
    await message.reply_text(
        "⭐ *Достижения дня*\n\nЧего достиг(ла) сегодня? Большое или маленькое — всё считается.",
        parse_mode="Markdown", reply_markup=skip_kb("skip_e_ach")
    )

async def evening_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    streak = calc_streak(uid)

    morning = get_diary(uid, "morning")
    focus_recap = f"\n🎯 Фокус был: _{morning['focus']}_" if morning.get("focus") else ""

    await q.message.reply_text(
        f"🌙 *Хороший был день, {user['name']}!*\n"
        f"_{today_str()}_{focus_recap}\n\n"
        f"🔥 Стрик: *{streak} {'день' if streak==1 else 'дня' if streak<5 else 'дней'}*\n\n"
        "Давай закроем этот день.",
        parse_mode="Markdown"
    )
    await asyncio.sleep(0.5)

    if any(morning.get(key) for key, _ in TASK_FIELDS):
        await ask_tasks_done(q.message, uid, ctx)
        return E_TASKS_DONE
    else:
        await ask_achievements(q.message)
        return E_ACH

async def got_e_ach(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_ach"] = update.message.text
    await ask_praise(update.message); return E_PRAISE

async def skip_e_ach(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["e_ach"] = ""; await ask_praise(q.message); return E_PRAISE

async def ask_praise(message):
    await message.reply_text(
        "🎉 *Похвали себя*\n\n"
        "Скажи себе 'молодец'. Что сегодня сделал(а) хорошо?\n"
        "_Даже маленькая победа заслуживает признания._",
        parse_mode="Markdown", reply_markup=skip_kb("skip_e_praise")
    )

async def got_e_praise(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_praise"] = update.message.text
    await ask_highlights(update.message); return E_HIGHLIGHTS

async def skip_e_praise(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["e_praise"] = ""; await ask_highlights(q.message); return E_HIGHLIGHTS

async def ask_highlights(message):
    await message.reply_text(
        "✨ *Яркие моменты дня*\n\nЧто сегодня заставило улыбнуться? Или какой инсайт пришёл?",
        parse_mode="Markdown", reply_markup=skip_kb("skip_e_highlights")
    )

async def got_e_highlights(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_highlights"] = update.message.text
    await ask_selfcare(update.message, ctx); return E_SELFCARE

async def skip_e_highlights(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["e_highlights"] = ""; await ask_selfcare(q.message, ctx); return E_SELFCARE

SELFCARE_ITEMS = [
    ("warmup",      "🏃 Зарядка / физическая активность"),
    ("cold_water",  "💧 Холодная вода / умывание"),
    ("breathing",   "🌬 Дыхательные техники"),
    ("timer",       "⏱ Работа по таймеру"),
    ("stop",        "🛑 Навык СТОП"),
    ("first_step",  "👣 Первый маленький шаг"),
    ("activation",  "⚡ Активация"),
    ("rest",        "😴 Запланированный отдых"),
    ("anchor",      "⚓ Бросить якорь"),
    ("notes",       "📝 Бумажка гениальных мыслей"),
    ("environment", "🏠 Изменение среды"),
    ("willingness", "🤲 Готовность и полуулыбка"),
    ("todolist",    "📋 Список дел / календарь"),
]

def selfcare_kb(selected):
    rows = []
    for key, label in SELFCARE_ITEMS:
        mark = "✅ " if key in selected else "▫️ "
        rows.append([InlineKeyboardButton(mark + label, callback_data=f"sc_{key}")])
    rows.append([InlineKeyboardButton("Готово ✅", callback_data="sc_done")])
    return InlineKeyboardMarkup(rows)

async def ask_selfcare(message, ctx):
    ctx.user_data.setdefault("e_selfcare", [])
    await message.reply_text(
        "🧩 *Что из этого делал(а) сегодня?*\n\n"
        "Отметь всё, что применял(а) — это помогает быть в себе.",
        parse_mode="Markdown",
        reply_markup=selfcare_kb(ctx.user_data["e_selfcare"])
    )

async def toggle_selfcare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    key = q.data.replace("sc_", "")
    selected = ctx.user_data.setdefault("e_selfcare", [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await q.message.edit_reply_markup(reply_markup=selfcare_kb(selected))
    return E_SELFCARE

async def selfcare_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await ask_energy(q.message)
    return E_ENERGY

async def ask_energy(message):
    await message.reply_text(
        "🔋 *Уровень энергии сейчас*\n\n"
        "Как ты себя чувствуешь по итогам дня?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("😴 1 — выжат(а) полностью", callback_data="energy_1")],
            [InlineKeyboardButton("😔 2 — устал(а), тяжело", callback_data="energy_2")],
            [InlineKeyboardButton("😐 3 — нормально, средне", callback_data="energy_3")],
            [InlineKeyboardButton("😊 4 — хорошо, в ресурсе", callback_data="energy_4")],
            [InlineKeyboardButton("⚡ 5 — заряжен(а) на 100%", callback_data="energy_5")],
        ])
    )

async def got_energy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    level = int(q.data.split("_")[1])
    ctx.user_data["e_energy"] = level
    await ask_plan_a(q.message)
    return E_A

async def ask_plan_a(message):
    await message.reply_text(
        "📋 *Планы на завтра — задача A*\n\n"
        "Самое важное на завтра. Обязательно сделать.\n"
        "_Утром увидишь первым._",
        parse_mode="Markdown", reply_markup=skip_kb("skip_e_a")
    )

async def got_e_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_a"] = update.message.text
    await update.message.reply_text("🅱️ *Задача B1 на завтра:*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_b1"))
    return E_B1

async def skip_e_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["e_a"] = ""
    await q.message.reply_text("🅱️ *Задача B1 на завтра:*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_b1"))
    return E_B1

async def got_e_b1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_b1"] = update.message.text
    await update.message.reply_text("🅱️ *Задача B2:*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_b2"))
    return E_B2

async def skip_e_b1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["e_b1"] = ""
    await q.message.reply_text("🅱️ *Задача B2:*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_b2"))
    return E_B2

async def got_e_b2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_b2"] = update.message.text
    await ask_e_c1(update.message); return E_C1

async def skip_e_b2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["e_b2"] = ""; await ask_e_c1(q.message); return E_C1

async def ask_e_c1(message):
    await message.reply_text("🅲 *Задача C1 (по возможности):*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_c_all"))

async def got_e_c1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_c1"] = update.message.text
    await update.message.reply_text("🅲 *C2:*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_c_all"))
    return E_C2

async def got_e_c2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_c2"] = update.message.text
    await update.message.reply_text("🅲 *C3:*", parse_mode="Markdown", reply_markup=skip_kb("skip_e_c_all"))
    return E_C3

async def got_e_c3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["e_c3"] = update.message.text
    await finish_evening(update.message, update.effective_user.id, ctx)
    return ConversationHandler.END

async def skip_e_c_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data.setdefault("e_c1", "")
    ctx.user_data.setdefault("e_c2", "")
    ctx.user_data.setdefault("e_c3", "")
    await finish_evening(q.message, q.from_user.id, ctx)
    return ConversationHandler.END

async def finish_evening(message, uid, ctx):
    user = get_user(uid)
    data = {k: ctx.user_data.get(k, "") for k in
            ["e_ach","e_praise","e_highlights","e_a","e_b1","e_b2","e_c1","e_c2","e_c3"]}
    data["e_selfcare"] = ctx.user_data.get("e_selfcare", [])
    data["e_energy"] = ctx.user_data.get("e_energy", 0)
    data["e_tasks_done"] = ctx.user_data.get("e_tasks_done", [])
    save_diary(uid, "evening", data)
    add_streak(uid)
    streak = calc_streak(uid)

    plans = ""
    if data["e_a"]:  plans += f"\n🅰️ {data['e_a']}"
    if data["e_b1"]: plans += f"\n🅱️ {data['e_b1']}"
    if data["e_b2"]: plans += f"\n🅱️ {data['e_b2']}"
    if data["e_c1"]: plans += f"\n🅲 {data['e_c1']}"

    tasks_summary = ""
    morning_for_summary = get_diary(uid, "morning")
    if any(morning_for_summary.get(k) for k, _ in TASK_FIELDS):
        done = set(data["e_tasks_done"])
        lines = []
        for key, icon in TASK_FIELDS:
            text = morning_for_summary.get(key)
            if not text: continue
            mark = "✅" if key in done else "▫️"
            lines.append(f"{mark} {icon} {text}")
        if lines:
            tasks_summary = "\n\n📋 *Задачи дня:*\n" + "\n".join(lines)

    selfcare_summary = ""
    if data["e_selfcare"]:
        labels = dict(SELFCARE_ITEMS)
        used = [labels[k] for k in data["e_selfcare"] if k in labels]
        if used:
            selfcare_summary = "\n\n🧩 *Сегодня применял(а):*\n" + "\n".join(used)

    # AI анализ дня
    ai_analysis = ""
    if ANTHROPIC_KEY:
        morning = get_diary(uid, "morning")
        ai_analysis = await ai_day_analysis(user["name"], user["gender"], morning, data)
        if ai_analysis: ai_analysis = f"\n\n🤖 *Анализ дня:*\n_{ai_analysis}_"

    await message.reply_text(
        "✅ *День закрыт!*\n\n"
        f"🔥 Стрик: *{streak} {'день' if streak==1 else 'дня' if streak<5 else 'дней'}*\n"
        f"{tasks_summary}"
        f"\n\n{'📋 *Планы на завтра:*' + plans if plans else ''}"
        f"{selfcare_summary}"
        f"{ai_analysis}\n\n"
        f"_Молодец. До завтра, {user['name']}_ 👋",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

# ── AI FUNCTIONS ───────────────────────────────────────────────────────────
async def ai_morning_boost(name, gender, focus):
    """Короткая AI-мотивация утром на основе фокуса."""
    if not ANTHROPIC_KEY: return ""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_KEY)
        gender_hint = "женского рода" if gender == 'F' else "мужского рода"
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=150,
            system=f"Ты поддерживающий коуч. Пользователь: {name}, {gender_hint}, СДВГ. Пиши по-русски, 1-2 предложения, конкретно и тепло.",
            messages=[{"role":"user","content":f"Моя главная задача сегодня: {focus}. Дай короткий мотивирующий посыл."}]
        )
        return resp.content[0].text.strip()
    except: return ""

async def ai_day_analysis(name, gender, morning_data, evening_data):
    """AI-анализ прожитого дня вечером."""
    if not ANTHROPIC_KEY: return ""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_KEY)
        gender_hint = "женского рода" if gender == 'F' else "мужского рода"
        context = f"Утренний фокус: {morning_data.get('focus','не задан')}\n"
        if evening_data.get("e_ach"): context += f"Достижения: {evening_data['e_ach']}\n"
        if evening_data.get("e_highlights"): context += f"Яркие моменты: {evening_data['e_highlights']}\n"
        done = set(evening_data.get("e_tasks_done", []))
        task_lines = [morning_data[k] for k, _ in TASK_FIELDS if morning_data.get(k)]
        if task_lines:
            done_lines = [morning_data[k] for k, _ in TASK_FIELDS if morning_data.get(k) and k in done]
            context += f"Запланированные задачи: {'; '.join(task_lines)}\n"
            context += f"Выполнено из них: {'; '.join(done_lines) if done_lines else 'ничего не отмечено выполненным'}\n"
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=200,
            system=f"Ты коуч для {name} ({gender_hint}), у которой/которого СДВГ. Анализируй день кратко и тепло. 2-3 предложения. Отмечай прогресс и дай один конкретный совет на завтра. Пиши по-русски.",
            messages=[{"role":"user","content":f"Вот мой день:\n{context}\nДай короткий анализ."}]
        )
        return resp.content[0].text.strip()
    except: return ""

async def send_coach(message, text, uid):
    """Отправить запрос AI-коучу."""
    if not ANTHROPIC_KEY:
        await message.reply_text("⚠️ ИИ-коуч не настроен. Добавь ANTHROPIC_KEY в переменные Railway.", reply_markup=main_menu())
        return
    user = get_user(uid)
    gender_hint = "женского рода" if user["gender"] == 'F' else "мужского рода"
    morning = get_diary(uid, "morning")
    tasks = build_tasks_summary(morning)
    tasks_hint = (
        f"\n\nЗадачи пользователя на сегодня:\n{tasks}\n"
        "Если из сообщения понятно, к какой задаче относится проблема — обращайся к ней прямо по названию. "
        "Если неясно и задач больше одной — сначала кратко переспроси, к какой из них вопрос."
        if tasks != "_задачи не заданы_" else ""
    )
    thinking = await message.reply_text("🤖 думаю...")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            system=f"Ты прямой коуч для {user['name']} ({gender_hint}), СДВГ. Кратко, по делу, одно действие. Максимум 2-3 предложения. Используй техники CBT для СДВГ: ABC-приоритеты, первый неподавляющий шаг, активация, СТОП. Пиши по-русски.{tasks_hint}",
            messages=[{"role":"user","content":text}]
        )
        await thinking.edit_text(
            f"🤖 {resp.content[0].text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="go_menu")]])
        )
    except Exception as e:
        await thinking.edit_text(f"Ошибка: {e}")

# ── COACH MENU ─────────────────────────────────────────────────────────────
COACH_PROMPTS = {
    "c_start":    "Не могу начать задачу — застрял(а) и откладываю",
    "c_dist":     "Только что отвлёкся(ась), помоги вернуться к задаче прямо сейчас",
    "c_next":     "Не знаю что делать дальше — подскажи следующий конкретный шаг",
    "c_procr":    "Прокрастинирую и понимаю это — что делать прямо сейчас?",
    "c_overload": "Слишком много всего, не знаю с чего начать — помоги расставить приоритеты",
    "c_tip":      "Дай один быстрый совет из тренинга навыков СДВГ",
}

# Человекочитаемые подписи состояния для дневного чекина — сохраняются в карточку дня
MIDDAY_LABELS = {
    "mid_ok":      "✅ Всё по плану",
    "mid_nostart": "❓ Непонятно с чего начать",
    "mid_scary":   "😰 Задача подавляет/пугает",
    "mid_waiting": "⏳ Жду подходящего момента",
    "mid_perfect": "🎯 Боюсь сделать плохо",
    "mid_resist":  "🧱 Внутреннее сопротивление",
    "mid_time":    "⚡ Мало времени",
    "mid_phone":   "📱 Залип(ла) в телефоне",
}

async def coach_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(
        "🤖 *Коуч*\n\nЧто происходит? Пиши сам(а) или выбери быструю кнопку:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Не могу начать", callback_data="c_start")],
            [InlineKeyboardButton("😵 Отвлёкся(ась)", callback_data="c_dist")],
            [InlineKeyboardButton("❓ Что дальше?", callback_data="c_next")],
            [InlineKeyboardButton("😩 Прокрастинирую", callback_data="c_procr")],
            [InlineKeyboardButton("🌀 Всё навалилось", callback_data="c_overload")],
            [InlineKeyboardButton("💡 Совет дня", callback_data="c_tip")],
            [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
        ])
    )
    ctx.user_data["coach_mode"] = True

async def coach_quick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    prompt = COACH_PROMPTS.get(q.data, "")
    await send_coach(q.message, prompt, q.from_user.id)

# ── SKILL OF THE DAY ───────────────────────────────────────────────────────
def skills_list_kb():
    rows = [[InlineKeyboardButton(s["name"], callback_data=f"skill_{i}")] for i, s in enumerate(SKILLS)]
    rows.append([InlineKeyboardButton("👥 Бадди — совместная работа рядом", callback_data="go_buddy")])
    rows.append([InlineKeyboardButton("◀️ Меню", callback_data="go_menu")])
    return InlineKeyboardMarkup(rows)

async def show_skill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    daily = get_daily_skill(uid)
    await q.message.reply_text(
        "🧠 *Навыки*\n\n"
        f"💡 *Навык дня:* {daily['name']}\n"
        f"_{daily['desc']}_\n\n"
        "Весь список — выбери, чтобы посмотреть подробнее:",
        parse_mode="Markdown",
        reply_markup=skills_list_kb()
    )

async def show_skill_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    idx = int(q.data.replace("skill_", ""))
    skill = SKILLS[idx]
    buttons = [[InlineKeyboardButton("◀️ К списку навыков", callback_data="go_skill")]]
    if "Работа по таймеру" in skill["name"]:
        buttons.insert(0, [InlineKeyboardButton("🍅 Запустить таймер", callback_data="go_focus")])
    buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="go_menu")])
    await q.message.reply_text(
        f"🧠 *{skill['name']}*\n\n"
        f"📖 *Описание*\n{skill['explanation']}\n\n"
        f"✅ *Инструкция*\n{skill['instructions']}\n\n"
        "_Методика: когнитивно-поведенческая терапия для взрослых с СДВГ — «Mastering Your Adult ADHD» (Safren)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ── STREAK ─────────────────────────────────────────────────────────────────
async def show_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    s = calc_streak(uid)
    await q.message.reply_text(
        f"🔥 *Стрик: {s} {'день' if s==1 else 'дня' if s<5 else 'дней'} подряд*\n\n"
        f"{'Продолжай! Каждый день считается.' if s>0 else 'Заполни утро или вечер — и стрик пойдёт.'}\n\n"
        "_Стрик растёт когда ты закрываешь вечерний блок._",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

# ── GENERAL CALLBACKS ──────────────────────────────────────────────────────
# ── SETTINGS: NOTIFICATION TIMES ───────────────────────────────────────────
def _settings_text_and_kb(user):
    enabled  = int(user.get("notif_enabled") or 0)
    m  = user.get("notif_morning", "09:00")
    d  = user.get("notif_midday",  "13:00")
    e  = user.get("notif_evening", "21:00")
    mo = int(user.get("notif_morning_on") or 1)
    do = int(user.get("notif_midday_on")  or 1)
    eo = int(user.get("notif_evening_on") or 1)
    be = int(user.get("beacon_enabled")   or 0)
    bi = int(user.get("beacon_interval")  or 2)

    status = "✅ включены" if enabled else "❌ выключены"
    beacon_label = f"каждые {bi} ч" if bi == 1 else f"каждые {bi} ч"
    text = (
        "⚙️ *Настройки уведомлений*\n\n"
        f"Уведомления: *{status}*\n\n"
        f"{'✅' if mo else '🔕'} Утро: *{m}*\n"
        f"{'✅' if do else '🔕'} День: *{d}*\n"
        f"{'✅' if eo else '🔕'} Вечер: *{e}*\n\n"
        f"{'✅' if be else '🔕'} Маячок внимания: *{'вкл, ' + beacon_label if be else 'выкл'}*\n"
        f"_Маячок периодически спрашивает «что сейчас делаешь?» в течение дня_\n\n"
        "_Нажми на время чтобы изменить, на иконку — включить/выключить_"
    )
    beacon_interval_row = [
        InlineKeyboardButton(f"{'→' if bi==1 else ''} 1 ч", callback_data="beacon_int_1"),
        InlineKeyboardButton(f"{'→' if bi==2 else ''} 2 ч", callback_data="beacon_int_2"),
        InlineKeyboardButton(f"{'→' if bi==3 else ''} 3 ч", callback_data="beacon_int_3"),
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅' if mo else '🔕'} Утро", callback_data="toggle_morning"),
         InlineKeyboardButton(f"☀️ {m}", callback_data="set_morning")],
        [InlineKeyboardButton(f"{'✅' if do else '🔕'} День", callback_data="toggle_midday"),
         InlineKeyboardButton(f"☕ {d}", callback_data="set_midday")],
        [InlineKeyboardButton(f"{'✅' if eo else '🔕'} Вечер", callback_data="toggle_evening"),
         InlineKeyboardButton(f"🌙 {e}", callback_data="set_evening")],
        [InlineKeyboardButton(
            f"{'✅' if be else '🔕'} Маячок", callback_data="toggle_beacon"),
         *([InlineKeyboardButton("Интервал:", callback_data="noop")] if be else [])],
        *([ beacon_interval_row ] if be else []),
        [InlineKeyboardButton(
            "🔕 Выключить все" if enabled else "🔔 Включить все",
            callback_data="toggle_notif"
        )],
        [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
    ])
    return text, kb

async def settings_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    text, kb = _settings_text_and_kb(get_user(uid))
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def set_time_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    block = q.data.replace("set_", "")  # morning / midday / evening
    labels = {"morning": "☀️ утреннее", "midday": "☕ дневное", "evening": "🌙 вечернее"}
    ctx.user_data["setting_notif"] = block
    await q.message.reply_text(
        f"Введи время для {labels.get(block,'')} уведомления\n\n"
        "Формат: *ЧЧ:ММ* (например: `08:30` или `20:00`)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Отмена", callback_data="go_settings")
        ]])
    )
    ctx.user_data["awaiting_time"] = True

async def toggle_notif(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    new_val = 0 if user.get("notif_enabled", 0) else 1
    update_user(uid, notif_enabled=new_val)
    status = "включены ✅" if new_val else "выключены ❌"
    await q.message.reply_text(
        f"Уведомления {status}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Настройки", callback_data="go_settings")]])
    )

async def go_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    text, kb = _settings_text_and_kb(get_user(uid))
    try:
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def toggle_notif_block(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Включить/выключить конкретный блок уведомлений (утро/день/вечер)."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    block = q.data.replace("toggle_", "")  # morning / midday / evening
    col = f"notif_{block}_on"
    user = get_user(uid)
    cur = int(user.get(col) or 1)
    update_user(uid, **{col: 0 if cur else 1})
    text, kb = _settings_text_and_kb(get_user(uid))
    try:
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def toggle_beacon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    cur = int(user.get("beacon_enabled") or 0)
    update_user(uid, beacon_enabled=0 if cur else 1)
    text, kb = _settings_text_and_kb(get_user(uid))
    try:
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def beacon_set_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    interval = int(q.data.split("_")[2])
    update_user(uid, beacon_interval=interval)
    text, kb = _settings_text_and_kb(get_user(uid))
    try:
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def send_beacon(app, user):
    """Маячок внимания — периодический чекин в течение дня."""
    try:
        uid = user["user_id"]
        if not int(user.get("beacon_enabled") or 0): return

        tz = pytz.timezone(USER_TIMEZONE)
        now = datetime.now(tz)
        interval_h = int(user.get("beacon_interval") or 2)

        morning_h, morning_m = map(int, user.get("notif_morning","09:00").split(":"))
        evening_h, evening_m = map(int, user.get("notif_evening","21:00").split(":"))
        now_minutes = now.hour * 60 + now.minute
        if now_minutes < morning_h * 60 + morning_m: return
        if now_minutes > evening_h * 60 + evening_m: return

        last_sent = user.get("beacon_last_sent") or ""
        if last_sent:
            try:
                last_dt = datetime.fromisoformat(last_sent).astimezone(tz)
                if (now - last_dt).total_seconds() < interval_h * 3600 - 30: return
            except Exception:
                pass

        morning = get_diary(uid, "morning")
        tasks = build_tasks_summary(morning) if morning else "_задачи не заданы_"

        BEACON_TEXTS = [
            "👀 *Маячок внимания*\n\nЗадачи дня:\n{tasks}\n\nЧто сейчас делаешь?",
            "⏱ *Стоп на секунду*\n\nЗадачи дня:\n{tasks}\n\nНад чем работаешь прямо сейчас?",
            "🔔 *Проверка*\n\nЗадачи дня:\n{tasks}\n\nКак дела? Всё по плану?",
            "👁 *Внимание, маячок*\n\nЗадачи дня:\n{tasks}\n\nВернёмся к задачам — что сейчас происходит?",
            "🧭 *Сориентируемся*\n\nЗадачи дня:\n{tasks}\n\nТы где сейчас по задачам?",
            "💡 *Короткая пауза*\n\nЗадачи дня:\n{tasks}\n\nНа чём сосредоточен(а) прямо сейчас?",
        ]
        beacon_text = random.choice(BEACON_TEXTS).format(tasks=tasks)

        update_user(uid, beacon_last_sent=now.isoformat())
        await app.bot.send_message(
            chat_id=uid,
            text=beacon_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🅰️ Работаю над A", callback_data="mid_ok")],
                [InlineKeyboardButton("✅ Сделал A, работаю над B", callback_data="mid_a_done_b")],
                [InlineKeyboardButton("✅✅ Сделал A и B, работаю над C", callback_data="mid_ab_done_c")],
                [InlineKeyboardButton("😬 Прокрастинирую", callback_data="mid_procr")],
            ])
        )
    except Exception as e:
        print(f"Ошибка маячка uid={user.get('user_id')}: {e}")


def _tasks_text_and_kb(morning, done_set):
    """Строит текст и клавиатуру задач с отметками выполнения."""
    task_defs = [
        ("focus", "🅰️", "A"),
        ("b1",    "🅱️", "B1"),
        ("b2",    "🅱️", "B2"),
        ("c1",    "🅲",  "C1"),
        ("c2",    "🅲",  "C2"),
        ("c3",    "🅲",  "C3"),
    ]
    lines = []
    buttons = []
    for key, icon, label in task_defs:
        val = morning.get(key, "")
        if not val: continue
        done = label in done_set
        prefix = "✅" if done else icon
        lines.append(f"{prefix} {'~' if done else ''}{val}{'~' if done else ''}")
        if not done:
            buttons.append([InlineKeyboardButton(f"✅ Выполнено: {val[:30]}", callback_data=f"task_done_{label}")])

    text = "📋 *Задачи на сегодня*\n\n" + ("\n".join(lines) if lines else "_задачи не заданы_")
    kb_rows = buttons + [
        [InlineKeyboardButton("🆘 Застрял(а)?", callback_data="mid_coach")],
        [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
    ]
    return text, InlineKeyboardMarkup(kb_rows)

async def show_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать все задачи на сегодня."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    morning = get_diary(uid, "morning")

    if not morning:
        await q.message.reply_text(
            "📋 *Задачи на сегодня*\n\n_Утренний дневник ещё не заполнен._\n\nЗаполни утро чтобы поставить задачи 👇",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    done_data = get_diary(uid, "tasks_done")
    done_set = set(done_data.get("done", []))
    text, kb = _tasks_text_and_kb(morning, done_set)
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def task_done_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Отметить задачу выполненной."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    label = q.data.replace("task_done_", "")  # A, B1, B2, C1, C2, C3

    done_data = get_diary(uid, "tasks_done")
    done_list = done_data.get("done", [])
    if label not in done_list:
        done_list.append(label)
    save_diary(uid, "tasks_done", {"done": done_list})

    morning = get_diary(uid, "morning")
    done_set = set(done_list)
    text, kb = _tasks_text_and_kb(morning, done_set)

    all_keys = [k for k in ["focus","b1","b2","c1","c2","c3"] if morning.get(k)]
    label_map = {"focus":"A","b1":"B1","b2":"B2","c1":"C1","c2":"C2","c3":"C3"}
    all_labels = {label_map[k] for k in all_keys}

    if all_labels and all_labels <= done_set:
        text += "\n\n🎉 *Все задачи выполнены! Отличный день!*"

    try:
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ── DAY CARD ───────────────────────────────────────────────────────────────
def build_day_card_text(uid, for_date):
    morning = get_diary(uid, "morning", for_date)
    midday  = get_diary(uid, "midday",  for_date)
    evening = get_diary(uid, "evening", for_date)

    d = date.fromisoformat(for_date)
    lines = [f"🗂 *Карточка дня — {d.strftime('%d.%m.%Y')}*"]

    if morning:
        lines.append("\n☀️ *Утро*")
        done = set(evening.get("e_tasks_done", []))
        tasks = []
        for key, icon in TASK_FIELDS:
            text = morning.get(key)
            if not text: continue
            mark = "✅ " if key in done else ""
            tasks.append(f"{mark}{icon} {text}")
        if tasks: lines.append("\n".join(tasks))
        if morning.get("writing"):   lines.append(f"📝 Свободное письмо: _{morning['writing']}_")
        if morning.get("gratitude"): lines.append(f"🙏 Благодарность: _{morning['gratitude']}_")
        if morning.get("child"):     lines.append(f"💛 Себе доброе: _{morning['child']}_")

    if midday.get("state"):
        lines.append(f"\n☕ *День*\n{midday['state']}")

    if evening:
        lines.append("\n🌙 *Вечер*")
        if evening.get("e_ach"):        lines.append(f"⭐ Достижения: _{evening['e_ach']}_")
        if evening.get("e_praise"):     lines.append(f"🎉 Похвала себе: _{evening['e_praise']}_")
        if evening.get("e_highlights"): lines.append(f"✨ Яркие моменты: _{evening['e_highlights']}_")
        plans = [l for l in [
            f"🅰️ {evening['e_a']}" if evening.get("e_a") else "",
            f"🅱️ {evening['e_b1']}" if evening.get("e_b1") else "",
            f"🅱️ {evening['e_b2']}" if evening.get("e_b2") else "",
            f"🅲 {evening['e_c1']}" if evening.get("e_c1") else "",
            f"🅲 {evening['e_c2']}" if evening.get("e_c2") else "",
            f"🅲 {evening['e_c3']}" if evening.get("e_c3") else "",
        ] if l]
        if plans: lines.append("📋 Планы на завтра:\n" + "\n".join(plans))
        if evening.get("e_selfcare"):
            labels = dict(SELFCARE_ITEMS)
            used = [labels[k] for k in evening["e_selfcare"] if k in labels]
            if used: lines.append("🧩 Применял(а):\n" + "\n".join(used))

    if not morning and not midday and not evening:
        lines.append("\n_Пока пусто. Заполни утро или вечер — и здесь появятся записи._")

    return "\n".join(lines)

def day_card_kb(for_date):
    d = date.fromisoformat(for_date)
    prev_d = (d - timedelta(days=1)).isoformat()
    buttons = [[InlineKeyboardButton("◀️ Пред. день", callback_data=f"daycard_{prev_d}")]]
    if d < date.today():
        next_d = (d + timedelta(days=1)).isoformat()
        buttons[0].append(InlineKeyboardButton("След. день ▶️", callback_data=f"daycard_{next_d}"))
    buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="go_menu")])
    return InlineKeyboardMarkup(buttons)

async def show_day_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    for_date = date.today().isoformat()
    text = build_day_card_text(uid, for_date)
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=day_card_kb(for_date))

async def day_card_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    for_date = q.data.replace("daycard_", "")
    text = build_day_card_text(uid, for_date)
    await q.message.edit_text(text, parse_mode="Markdown", reply_markup=day_card_kb(for_date))

async def go_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["coach_mode"] = False
    ctx.user_data["awaiting_feedback"] = False
    ctx.user_data["awaiting_buddy"] = False
    ctx.user_data["awaiting_time"] = False
    await q.message.reply_text("Главное меню 👇", reply_markup=main_menu())

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ctx.user_data.get("awaiting_time"):
        ctx.user_data["awaiting_time"] = False
        block = ctx.user_data.get("setting_notif", "")
        text = update.message.text.strip()
        # Validate HH:MM format
        import re
        if re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", text):
            field = f"notif_{block}"
            update_user(uid, **{field: text})
            update_user(uid, notif_enabled=1)
            labels = {"morning": "☀️ Утро", "midday": "☕ День", "evening": "🌙 Вечер"}
            await update.message.reply_text(
                f"{labels.get(block,'')} уведомление установлено на *{text}* ✅\n\nУведомления включены.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Настройки", callback_data="go_settings")]])
            )
        else:
            await update.message.reply_text(
                "Неверный формат. Введи время в формате ЧЧ:ММ, например: `08:30`",
                parse_mode="Markdown"
            )
            ctx.user_data["awaiting_time"] = True
    elif ctx.user_data.get("awaiting_buddy"):
        ctx.user_data["awaiting_buddy"] = False
        bname = update.message.text.strip()
        update_user(uid, buddy_name=bname)
        await update.message.reply_text(
            f"👥 *Бадди добавлен: {bname}*\n\nВ 13:00 бот предложит обратиться к нему при трудностях.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    elif ctx.user_data.get("awaiting_city"):
        ctx.user_data["awaiting_city"] = False
        city = update.message.text.strip()
        update_user(uid, city=city)
        await update.message.reply_text(f"📍 {city} — записал!")
        # Показываем настройку уведомлений (та же логика что и при «Пропустить»)
        await update.message.reply_text(
            "🔔 *Последний шаг — уведомления*\n\n"
            "Бот пишет три раза в день: утром, днём и вечером. "
            "Без уведомлений польза от бота сильно меньше.\n\n"
            "Включить уведомления?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Включить", callback_data="onboard_notif_on")],
                [InlineKeyboardButton("Пропустить, настрою позже", callback_data="onboard_notif_skip")],
            ])
        )
        return
    elif get_user(uid).get("research_awaiting") and str(get_user(uid).get("research_awaiting")) != "0":
        user = get_user(uid)
        awaiting = str(user.get("research_awaiting", ""))
        text = update.message.text.strip()
        # format: "DAY_open" e.g. "3_open"
        day = int(awaiting.split("_")[0]) if "_" in awaiting else 0
        if day:
            save_research(uid, day, f"day{day}_text", text)
            update_user(uid, research_awaiting=0)
            await update.message.reply_text(
                "Спасибо! Твой ответ очень важен 🙏",
                reply_markup=main_menu()
            )
        return
    elif ctx.user_data.get("awaiting_feedback"):
        ctx.user_data["awaiting_feedback"] = False
        text = update.message.text.strip()
        save_feedback(uid, text)
        user = get_user(uid)
        if NOTIFY_USER_ID:
            try:
                await ctx.bot.send_message(
                    NOTIFY_USER_ID,
                    f"💬 *Обратная связь от {user['name'] or uid}:*\n\n{text}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Не удалось переслать обратную связь: {e}")
        await update.message.reply_text(
            "Спасибо! Идею записал(а) 🙏",
            reply_markup=main_menu()
        )
    elif ctx.user_data.get("coach_mode"):
        await send_coach(update.message, update.message.text, uid)
    else:
        await update.message.reply_text("Выбери что хочешь сделать 👇", reply_markup=main_menu())

# ── ABOUT ──────────────────────────────────────────────────────────────────
# ── FOCUS / POMODORO ───────────────────────────────────────────────────────
async def go_focus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)

    # Если таймер уже активен — показать статус
    if str(user.get("focus_active", "0")) == "1" and user.get("focus_end_time"):
        try:
            end_dt = datetime.fromisoformat(user["focus_end_time"])
            tz = pytz.timezone(USER_TIMEZONE)
            now = datetime.now(tz)
            end_dt_tz = end_dt.astimezone(tz)
            remaining = int((end_dt_tz - now).total_seconds() / 60)
            if remaining > 0:
                await q.message.reply_text(
                    f"🍅 *Таймер уже идёт!*\n\n"
                    f"Осталось примерно *{remaining} мин* (до {end_dt_tz.strftime('%H:%M')}).\n\n"
                    f"Не отвлекайся — я напишу когда время выйдет 🔕",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⏹ Остановить", callback_data="focus_stop")],
                        [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
                    ])
                )
                return
        except Exception:
            pass

    # Считаем сколько минут в фокусе сегодня
    today = date.today().isoformat()
    mins_today = int(user.get("focus_minutes_today", 0)) if user.get("focus_date") == today else 0

    morning_data = get_diary(uid, "morning")
    task_hint = ""
    if morning_data.get("focus"):
        task_hint = f"\n\n📌 Твоя задача дня: *{morning_data['focus']}*"

    stats_hint = f"\n\n⏱ Сегодня в фокусе: *{mins_today} мин*" if mins_today > 0 else ""

    await q.message.reply_text(
        f"🍅 *Фокус-режим*\n\n"
        f"📝 *Перед стартом:* возьми листок бумаги и положи рядом.\n"
        f"Это «бумажка гениальных мыслей» — когда во время работы придёт посторонняя идея или мысль, просто запиши её и сразу возвращайся к задаче. Не нужно ничего обдумывать прямо сейчас. Так мозг отпускает мысль и не тратит силы держать её в голове.\n\n"
        f"На сколько минут работаем?{task_hint}{stats_hint}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("5 мин", callback_data="focus_start_5"),
             InlineKeyboardButton("10 мин", callback_data="focus_start_10"),
             InlineKeyboardButton("15 мин", callback_data="focus_start_15")],
            [InlineKeyboardButton("25 мин", callback_data="focus_start_25"),
             InlineKeyboardButton("30 мин", callback_data="focus_start_30"),
             InlineKeyboardButton("45 мин", callback_data="focus_start_45")],
            [InlineKeyboardButton("60 мин", callback_data="focus_start_60"),
             InlineKeyboardButton("90 мин", callback_data="focus_start_90")],
            [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
        ])
    )

async def focus_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    minutes = int(q.data.split("_")[2])

    tz = pytz.timezone(USER_TIMEZONE)
    now = datetime.now(tz)
    end_dt = now + timedelta(minutes=minutes)

    # Обновляем DB
    update_user(uid,
        focus_active=1,
        focus_end_time=end_dt.isoformat(),
        focus_duration=minutes,
    )

    end_str = end_dt.strftime("%H:%M")

    morning_data = get_diary(uid, "morning")
    task_hint = ""
    if morning_data.get("focus"):
        task_hint = f"\n📌 Задача: *{morning_data['focus']}*"

    await q.message.reply_text(
        f"🍅 *Таймер запущен на {minutes} мин*\n\n"
        f"Конец в *{end_str}*.{task_hint}\n\n"
        f"Удачи — не отвлекайся 🔕\n"
        f"_Я напишу когда время выйдет._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Остановить", callback_data="focus_stop")],
        ])
    )

async def focus_stop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)

    # Считаем сколько успел(а) отработать
    worked_mins = 0
    if user.get("focus_end_time") and str(user.get("focus_active","0")) == "1":
        try:
            tz = pytz.timezone(USER_TIMEZONE)
            end_dt = datetime.fromisoformat(user["focus_end_time"]).astimezone(tz)
            # Мы не знаем когда стартовали, но знаем end_time и оставшееся время
            # Проще: просто не добавляем минуты при досрочной остановке
            pass
        except Exception:
            pass

    update_user(uid, focus_active=0, focus_end_time="")

    today = date.today().isoformat()
    mins_today = int(user.get("focus_minutes_today", 0)) if user.get("focus_date") == today else 0

    await q.message.reply_text(
        f"⏹ *Таймер остановлен*\n\n"
        f"Сегодня в фокусе: *{mins_today} мин*\n\n"
        f"Хочешь начать новый раунд?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🍅 Новый раунд", callback_data="go_focus")],
            [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
        ])
    )

async def send_focus_end(app, uid: int, minutes: int):
    """Вызывается из check_notifications когда таймер истёк."""
    try:
        user = get_user(uid)
        today = date.today().isoformat()
        prev_mins = int(user.get("focus_minutes_today", 0)) if user.get("focus_date") == today else 0
        new_mins = prev_mins + minutes
        update_user(uid, focus_active=0, focus_end_time="", focus_minutes_today=new_mins, focus_date=today)

        await app.bot.send_message(
            chat_id=uid,
            text=(
                f"⏰ *Время вышло! {minutes} минут в фокусе — отлично!*\n\n"
                f"Сделай перерыв 5 минут: встань, выпей воды, отойди от экрана.\n\n"
                f"Сегодня в фокусе: *{new_mins} мин* 🎯"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍅 Ещё раунд", callback_data="go_focus")],
                [InlineKeyboardButton("✅ Хватит на сегодня", callback_data="go_menu")],
            ])
        )
    except Exception as e:
        print(f"Ошибка send_focus_end: {e}")


# ── RESEARCH QUESTIONS ─────────────────────────────────────────────────────
def save_research(uid, day, question, answer):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO research(user_id,day,question,answer,created) VALUES(?,?,?,?,?)",
              (uid, day, question, answer, datetime.now().isoformat()))
    conn.commit(); conn.close()

async def send_research_question(app, uid, day):
    """Отправить исследовательский вопрос по дню с момента регистрации."""
    user = get_user(uid)
    name = user.get("name", "")
    research_done = user.get("research_done") or ""

    if str(day) in research_done.split(","): return  # уже отвечал

    if day == 3:
        await app.bot.send_message(
            chat_id=uid,
            text=(
                f"🔬 *{name}, короткий вопрос!*\n\n"
                f"Ты используешь бота уже 3 дня. Как ощущения?\n\n"
                f"Оцени насколько бот полезен прямо сейчас:"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("1 😕", callback_data="research_3_1"),
                 InlineKeyboardButton("2 😐", callback_data="research_3_2"),
                 InlineKeyboardButton("3 🙂", callback_data="research_3_3"),
                 InlineKeyboardButton("4 😊", callback_data="research_3_4"),
                 InlineKeyboardButton("5 🤩", callback_data="research_3_5")],
            ])
        )
        update_user(uid, research_awaiting=f"3_open:что было самым полезным за эти дни?")

    elif day == 7:
        await app.bot.send_message(
            chat_id=uid,
            text=(
                f"🔬 *{name}, ты с ботом уже неделю!*\n\n"
                f"Был ли момент когда подумал(а) «о, это работает»?"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, был такой момент", callback_data="research_7_yes")],
                [InlineKeyboardButton("🤔 Не уверен(а)", callback_data="research_7_maybe")],
                [InlineKeyboardButton("❌ Нет пока", callback_data="research_7_no")],
            ])
        )

    elif day == 14:
        await app.bot.send_message(
            chat_id=uid,
            text=(
                f"🔬 *{name}, 2 недели вместе!*\n\n"
                f"Насколько вероятно что порекомендуешь бота другу с СДВГ?\n\n"
                f"0 — точно не порекомендую, 10 — точно порекомендую"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(str(i), callback_data=f"research_14_{i}") for i in range(0, 6)],
                [InlineKeyboardButton(str(i), callback_data=f"research_14_{i}") for i in range(6, 11)],
            ])
        )
        update_user(uid, research_awaiting="14_open:что стоит упростить или убрать?")

    elif day == 30:
        await app.bot.send_message(
            chat_id=uid,
            text=(
                f"🔬 *{name}, месяц с ботом!*\n\n"
                f"Если бот перестанет работать — как ты к этому отнесёшься?"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("😢 Очень расстроюсь", callback_data="research_30_sad")],
                [InlineKeyboardButton("😕 Немного расстроюсь", callback_data="research_30_meh")],
                [InlineKeyboardButton("😐 Всё равно", callback_data="research_30_nope")],
                [InlineKeyboardButton("😅 Даже рад(а)", callback_data="research_30_glad")],
            ])
        )

async def research_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    parts = q.data.split("_")  # research_DAY_VALUE
    day = int(parts[1])
    value = "_".join(parts[2:])

    LABELS = {
        "yes": "Да, был момент", "maybe": "Не уверен(а)", "no": "Нет пока",
        "sad": "Очень расстроюсь", "meh": "Немного расстроюсь",
        "nope": "Всё равно", "glad": "Даже рад(а)",
    }
    answer = LABELS.get(value, value)
    save_research(uid, day, f"day{day}_rating", answer)

    # Отмечаем день как пройденный
    user = get_user(uid)
    done = user.get("research_done") or ""
    done_list = [x for x in done.split(",") if x]
    if str(day) not in done_list:
        done_list.append(str(day))
    update_user(uid, research_done=",".join(done_list))

    if day == 3:
        update_user(uid, research_awaiting=f"3_open")
        await q.message.reply_text(
            f"Спасибо! Оценка {value}/5 записана.\n\n"
            f"И ещё один вопрос — ответь текстом:\n\n"
            f"*Что было самым полезным за эти 3 дня?*",
            parse_mode="Markdown"
        )
    elif day == 7:
        await q.message.reply_text(
            "Записал! Спасибо за честный ответ 🙏\n\nПродолжай — впереди ещё много интересного.",
            reply_markup=main_menu()
        )
        update_user(uid, research_awaiting="7_open")
        await q.message.reply_text(
            "*И ещё — что мешало использовать бота на этой неделе?*\n\nОтветь текстом.",
            parse_mode="Markdown"
        )
    elif day == 14:
        update_user(uid, research_awaiting="14_open")
        await q.message.reply_text(
            f"NPS {value} — записал!\n\n"
            f"*И последнее — ответь текстом:*\n\nЧто стоит упростить или убрать в боте?",
            parse_mode="Markdown"
        )
    elif day == 30:
        await q.message.reply_text(
            "Спасибо! Это очень важный для меня ответ 🙏\n\nБот продолжает работать — до встречи завтра.",
            reply_markup=main_menu()
        )


async def go_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(
        "ℹ️ *О боте*\n\n"
        "Я — внешняя структура для мозга с СДВГ. Он живёт интересом и срочностью, а не важностью — "
        "поэтому важное откладывается. Я держу структуру дня вместо тебя.\n\n"
        "☀️ *Утром* — разминка, задачи по системе ABC, настрой на день.\n"
        "☕ *Днём* — напоминаю о задачах, если застрял — даю конкретную технику.\n"
        "🌙 *Вечером* — что получилось, что из плана сделано, план на завтра.\n\n"
        "🍅 *Фокус-режим* — запускаешь таймер когда нужно поработать без отвлечений. "
        "Бот напишет когда время вышло и предложит перерыв. "
        "В конце дня видишь сколько минут провёл(а) в фокусе.\n\n"
        "🤖 *Коуч* и 🧠 *Навыки* — на случай когда трудно начать, тревожно или перегруз.\n\n"
        "_Польза не в дисциплине, а в том, чтобы мозгу было на что опереться каждый день._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="go_menu")]])
    )

# ── FEEDBACK ───────────────────────────────────────────────────────────────
async def go_feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["awaiting_feedback"] = True
    await q.message.reply_text(
        "💬 *Обратная связь*\n\n"
        "Напиши что улучшить, что не работает, или какая функция нужна — читаю всё.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="go_menu")]])
    )


# ── BUDDY ──────────────────────────────────────────────────────────────────
async def buddy_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    buddy = user.get("buddy_name","")
    buddy_tip = (
        "🔵 *Совместная работа рядом* — просто работайте рядом (видеозвонок, кафе). "
        "Мозг с СДВГ активируется от присутствия другого человека — даже без слов.\n\n"
        "🟣 *Партнёр по ответственности* — утром говоришь другу свой A-план, вечером отчитываешься. "
        "Внешняя ответственность работает там, где внутренняя не справляется."
    )
    text = f"👥 *Бадди при СДВГ*\n\n{buddy_tip}\n\n"
    if buddy:
        text += f"*Твой бадди:* {buddy}"
        buttons = [
            [InlineKeyboardButton("✏️ Изменить", callback_data="buddy_set")],
            [InlineKeyboardButton("💬 Написать бадди сейчас", callback_data="buddy_ping")],
            [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
        ]
    else:
        text += "_Бадди не задан._"
        buttons = [
            [InlineKeyboardButton("➕ Добавить бадди", callback_data="buddy_set")],
            [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
        ]
    await q.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def buddy_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["awaiting_buddy"] = True
    await q.message.reply_text("Напиши имя своего бадди:")

async def buddy_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    buddy = user.get("buddy_name","бадди")
    morning = get_diary(uid, "morning")
    focus = morning.get("focus","моя главная задача")
    await q.message.reply_text(
        f"👥 *Шаблон для {buddy}:*\n\n"
        f"_«{buddy}, привет! Работаю над: {focus}. Поработаем вместе 25 минут? Можно просто видеозвонок с тишиной.»_\n\n"
        "Скопируй и отправь! Совместная работа рядом работает даже онлайн.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="go_menu")]])
    )

# ── MIDDAY NOTIFICATION ─────────────────────────────────────────────────────
async def midday_notification(app, uid):
    """13:00 — дневной чекин с реальными ситуациями из тренинга."""
    try:
        user = get_user(uid)
        morning = get_diary(uid, "morning")

        if not morning:
            await app.bot.send_message(uid,
                f"☕ *{user['name']}, как дела?*\n\nУтренний дневник не заполнен — и это нормально. Как сейчас?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Всё хорошо", callback_data="mid_ok")],
                    [InlineKeyboardButton("🤖 Нужна помощь", callback_data="mid_coach")],
                ])
            )
            return

        tasks = build_tasks_summary(morning)
        a_task = morning.get("focus", "")
        has_b_or_c = any(morning.get(k) for k in ["b1","b2","c1","c2","c3"])
        await app.bot.send_message(uid,
            f"☕ *Дневной чекин, {user['name']}!*\n\n"
            f"Твои задачи на сегодня:\n{tasks}\n\n"
            f"Над чем работаешь сейчас?\n\n"
            f"_Чтобы выключить дневные уведомления — ⚙️ Настройки_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🅰️ Работаю над A", callback_data="mid_ok")],
                [InlineKeyboardButton("✅ Сделал A, работаю над B", callback_data="mid_a_done_b")],
                [InlineKeyboardButton("✅✅ Сделал A и B, работаю над C", callback_data="mid_ab_done_c")],
                [InlineKeyboardButton("😬 Прокрастинирую", callback_data="mid_procr")],
            ])
        )
    except Exception as e: print(f"Ошибка дневного уведомления: {e}")

async def midday_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ответы на дневной чекин — ситуации и инструменты из реального тренинга."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    user = get_user(uid)
    name = user["name"]
    morning = get_diary(uid, "morning")
    focus = morning.get("focus", "твоя A-задача")
    action = q.data

    if action in MIDDAY_LABELS:
        save_diary(uid, "midday", {"state": MIDDAY_LABELS[action]})

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Коуч поможет", callback_data="mid_coach")],
        [InlineKeyboardButton("👥 Нужен бадди", callback_data="mid_buddy")],
        [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
    ])

    if action == "mid_ok":
        await q.message.reply_text(
            f"💪 *Отлично, {name}!*\n\nПродолжай. Помни про перерывы — 5-10 минут каждые 25-30 минут.\n_Гиперфокус истощает — не пропускай отдых._\n\nДо вечера! 🌙",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    elif action == "mid_procr":
        a_task = morning.get("focus", "А-задача")
        await q.message.reply_text(
            f"Окей, разберёмся. Что происходит?\n\n_{a_task}_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❓ Непонятно с чего начать", callback_data="mid_nostart")],
                [InlineKeyboardButton("😰 Задача подавляет/пугает", callback_data="mid_scary")],
                [InlineKeyboardButton("⏳ Жду подходящего момента", callback_data="mid_waiting")],
                [InlineKeyboardButton("🎯 Боюсь сделать плохо", callback_data="mid_perfect")],
                [InlineKeyboardButton("🧱 Внутреннее сопротивление", callback_data="mid_resist")],
                [InlineKeyboardButton("⚡ Мало времени", callback_data="mid_time")],
                [InlineKeyboardButton("📱 Залип(ла) в телефоне", callback_data="mid_phone")],
                [InlineKeyboardButton("🤖 Коуч", callback_data="mid_coach")],
            ])
        )

    elif action == "mid_a_done_b":
        await q.message.reply_text(
            f"🎉 *А сделана — это главное!*\n\n"
            f"Самое важное уже выполнено. Работай над Б в своём темпе.\n\n"
            f"Помни про перерывы — 5-10 мин каждые 25-30 мин. До вечера! 🌙",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    elif action == "mid_ab_done_c":
        await q.message.reply_text(
            f"🏆 *А и Б сделаны — отличный день!*\n\n"
            f"Всё важное выполнено, В — это бонус. Работай спокойно.\n\n"
            f"Помни про перерывы — 5-10 мин каждые 25-30 мин. До вечера! 🌙",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    elif action == "mid_a_skipped":
        a_task = morning.get("focus", "А-задача")
        await q.message.reply_text(
            f"⚠️ *Стоп — А-задача важнее*\n\n"
            f"_{a_task}_\n\n"
            f"Система ABC работает так: А — самое важное дело, которое нужно сделать *первым*. "
            f"Если браться за Б или В пока А не сделана, мозг создаёт иллюзию продуктивности — ты занят(а), но главное откладывается.\n\n"
            f"Это особенно частая ловушка при СДВГ: браться за лёгкое и приятное вместо важного.\n\n"
            f"*Что сделать прямо сейчас:*\n"
            f"👣 Найди один самый маленький первый шаг по А-задаче\n"
            f"⏱ Поставь таймер на 25 минут только на А\n"
            f"📝 Б и В никуда не денутся — вернись к ним после",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍅 Запустить таймер на А", callback_data="go_focus")],
                [InlineKeyboardButton("🤖 Нужна помощь с А", callback_data="mid_coach")],
                [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
            ])
        )

    elif action == "mid_nostart":
        await q.message.reply_text(
            f"❓ *Непонятно с чего начать*\n\nЗадача: _{focus}_\n\n"
            "Проверенные техники для этой ситуации:\n\n"
            "👣 *Выделить первый шаг* — одно конкретное действие. Что нужно сделать в первую очередь?\n\n"
            "🤔 *За и против* — зачем это вообще важно? Короткое напоминание себе.\n\n"
            "⚡ *Активация тела* — встань, потянись, попрыгай, умойся. Тело запускает мозг.\n\n"
            "👥 *Помощь бадди* — иногда нужно просто сказать кому-то «я начинаю».\n\n"
            "🤖 *Обратиться к ИИ* — опиши задачу и попроси разбить на шаги.\n\n"
            "_Начни с активации тела — это самый быстрый способ запуститься._",
            parse_mode="Markdown", reply_markup=back_kb
        )

    elif action == "mid_scary":
        await q.message.reply_text(
            f"😰 *Задача подавляет — это исполнительная дисфункция, не лень*\n\nЗадача: _{focus}_\n\n"
            "👣 *Найди шаг, который не фрустрирует* — уменьшай пока не исчезнет желание отложить\n\n"
            "🛑 *СТОП* — остановись, дыши, осмотрись прежде чем действовать\n\n"
            "🤲 *Ладони готовности* — расслабь лицо, ладони вверх, приступи\n\n"
            "🖐 *5 чувств* — 5 предметов, 4 ощущения, 3 звука — вернись в тело\n\n"
            "💧 *Успокой себя* — холодная вода, дыхание, аптечка самоуспокоения\n\n"
            "👥 *Поговори с бадди* — совместная работа рядом работает даже без слов\n\n"
            "⏱ *Таймер на 2 минуты* — только начать. После старта обычно легче.",
            parse_mode="Markdown", reply_markup=back_kb
        )

    elif action == "mid_waiting":
        await q.message.reply_text(
            "⏳ *«Начну когда буду готов(а)»*\n\nЭтот момент обычно не наступает — это ловушка.\n\n"
            "🤲 *Ладони + 5 чувств* — возвращает в настоящий момент\n\n"
            "⏱ *Таймер* — поставь на 10 минут. Не на весь день. Просто попробуй.\n\n"
            "⚡ *Активация* — тело сначала, голова потом. Попрыгай, умойся.\n\n"
            "💧 *Тазик/кастрюля ледяной воды* — радикально, но работает мгновенно\n\n"
            "🎵 *Активная музыка* — 3-5 минут энергичной музыки перед стартом\n\n"
            "🔤 *За и против* — напомни себе ЗАЧЕМ это важно\n\n"
            "_Подходящее состояние появляется ПОСЛЕ начала, а не до._",
            parse_mode="Markdown", reply_markup=back_kb
        )

    elif action == "mid_perfect":
        await q.message.reply_text(
            f"🎯 *Перфекционизм — страх сделать недостаточно хорошо*\n\nЗадача: _{focus}_\n\n"
            "💩 *Поставь цель «сделать плохо»* — буквально. Разреши себе черновик.\n\n"
            "✌️ *Сделать просто как-нибудь* — готово > идеально. Всегда.\n\n"
            "🤲 *Принятие реальности* — ладони готовности, позволь себе быть несовершенным(ой)\n\n"
            "📋 *Долгосрочные приоритеты* — это вообще важно в масштабе месяца?\n\n"
            "👏 *Похвали себя* — за то что начал(а), не за результат\n\n"
            "🧠 *Представь что получилось плохо — и прими это* — мысленная репетиция\n\n"
            "👫 *Поговори с другом* — страх часто преувеличен, взгляд со стороны помогает\n\n"
            "_Всем не угодишь. Сделанное лучше идеального._",
            parse_mode="Markdown", reply_markup=back_kb
        )

    elif action == "mid_resist":
        await q.message.reply_text(
            "🧱 *Внутреннее сопротивление*\n\nЗнаешь что надо, но не можешь начать. Пробуй по списку:\n\n"
            "🛌 *Пойти поспать 20 минут* — иногда это честный ответ\n\n"
            "🏋️ *Зарядка/движение* — физическая активность запускает дофамин\n\n"
            "💧 *Тазик ледяной воды* — радикально, но работает\n\n"
            "🤲 *Ладони готовности* — расслабь лицо, ладони вверх, приступи\n\n"
            "🏆 *Награда за выполнение* — что получишь после? Пообещай себе.\n\n"
            "⏱ *Таймер + маячок внимания* — 25 мин работы + стикер на видном месте\n\n"
            "🛑 *СТОП* — остановись и замети что именно сопротивляется\n\n"
            "👏 *Похвали себя* — за любую попытку, не только за результат",
            parse_mode="Markdown", reply_markup=back_kb
        )

    elif action == "mid_time":
        tasks = build_tasks_summary(morning)
        await q.message.reply_text(
            "⚡ *Мало времени — расставляем приоритеты*\n\n"
            f"Твои задачи:\n{tasks}\n\n"
            f"*Только A-задача:* _{focus}_\n\n"
            "🐘 *Разделить слона* — какой самый маленький шаг прямо сейчас?\n\n"
            "🌸 *Начать с приятной части* — войди через то, что не пугает\n\n"
            "⏱ *Работа по таймеру* — короткие спринты, не марафон\n\n"
            "🌍 *Изменить условия* — можно совместить? Слушать тренинг во время рутины\n\n"
            "⚓ *Якорь* — верни внимание в тело, потом к задаче\n\n"
            "_Незавершённые задачи не переносятся — завтра выбираешь заново._",
            parse_mode="Markdown", reply_markup=back_kb
        )

    elif action == "mid_phone":
        await q.message.reply_text(
            "📱 *Поймал(а) себя — это уже победа!*\n\n"
            "Навык *СТОП*:\n"
            "🛑 *С* — Стоп. Положи телефон.\n"
            "👣 *Т* — Шаг назад. Глубокий вдох.\n"
            "👀 *О* — Осмотрись. 5 предметов вокруг.\n"
            "✅ *П* — Попытайся. Возвращайся к задаче.\n\n"
            f"Твоя A-задача: *{focus}*\n\n"
            "_Поставь таймер на 10 минут и просто открой нужный файл._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Иду работать", callback_data="mid_ok")],
                [InlineKeyboardButton("🤖 Нужна помощь", callback_data="mid_coach")],
            ])
        )

    elif action == "mid_coach":
        ctx.user_data["coach_mode"] = True
        await q.message.reply_text(
            f"🤖 *Коуч на связи, {name}.* Что происходит?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚫 Не могу начать", callback_data="c_start")],
                [InlineKeyboardButton("😩 Прокрастинирую", callback_data="c_procr")],
                [InlineKeyboardButton("🌀 Всё навалилось", callback_data="c_overload")],
                [InlineKeyboardButton("◀️ Меню", callback_data="go_menu")],
            ])
        )

    elif action == "mid_buddy":
        buddy = user.get("buddy_name","")
        if buddy:
            await q.message.reply_text(
                "👥 *Бадди-режим!*\n\n"
                f"Напиши {buddy} прямо сейчас:\n\n"
                f"_«{buddy}, привет! Работаю над: {focus}. Поработаем вместе 25 минут? Даже просто видеозвонок с тишиной.»_\n\n"
                "Совместная работа рядом работает даже без слов и с выключенной камерой.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="go_menu")]])
            )
        else:
            await q.message.reply_text("👥 Бадди не задан. Нажми «Бадди» в меню.", reply_markup=main_menu())

# ── SCHEDULED NOTIFICATIONS ────────────────────────────────────────────────
async def morning_notification(app, uid):
    try:
        user = get_user(uid)
        name = user.get("name", "")
        gender = user.get("gender", "M")

        ev = get_latest_evening_plan(uid)
        plan_text = ""
        if ev.get("e_a"):
            plan_text = f"\n\n⭐ *Сегодня тебе важно:*\n🅰️ {ev['e_a']}"
            if ev.get("e_b1"): plan_text += f"\n🅱️ {ev['e_b1']}"
            if ev.get("e_b2"): plan_text += f"\n🅱️ {ev['e_b2']}"

        skill = get_daily_skill(uid)
        motiv = random.choice(MOTIVATIONS_F if gender == 'F' else MOTIVATIONS_M)  # N берёт M — нейтральные фразы

        last_energy = int(ev.get("e_energy", 0) or 0)
        energy_note = ""
        if last_energy in (1, 2):
            energy_note = "\n\n🔋 *Вчера был тяжёлый день.* Сегодня — только одна задача A. Этого достаточно."

        await app.bot.send_message(
            uid,
            f"☀️ *Доброе утро, {name}!*\n\n"
            f"_{motiv}_{plan_text}{energy_note}\n\n"
            f"💡 *Навык дня:* {skill['name']}\n"
            f"_{skill['desc']}_\n\n"
            "Готов(а) начать? 👇",
            parse_mode="Markdown",
            reply_markup=morning_cta_kb()
        )
    except Exception as e:
        print(f"Ошибка утреннего уведомления: {e}")

async def evening_notification(app, uid):
    try:
        user = get_user(uid)
        name = user.get("name", "")
        await app.bot.send_message(
            uid,
            f"🌙 *Привет, {name}!*\n\n"
            "День заканчивается. Время закрыть его и поставить планы на завтра.\n\n"
            "5 минут — и голова свободна 👇",
            parse_mode="Markdown",
            reply_markup=evening_cta_kb()
        )
    except Exception as e:
        print(f"Ошибка вечернего уведомления: {e}")

async def weekly_report(app, uid):
    """Воскресный личный отчёт пользователю."""
    try:
        user = get_user(uid)
        name = user.get("name", "")

        # Собираем данные за последние 7 дней
        today = date.today()
        days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

        mornings_done = 0
        evenings_done = 0
        tasks_total = 0
        tasks_done = 0
        energy_sum = 0
        energy_count = 0

        for d in days:
            m = get_diary(uid, "morning", d)
            e = get_diary(uid, "evening", d)

            if m.get("focus"):
                mornings_done += 1
                # Считаем задачи из утра
                for key, _ in TASK_FIELDS:
                    if m.get(key):
                        tasks_total += 1

            if e.get("e_ach") or e.get("e_a"):
                evenings_done += 1
                done_set = set(e.get("e_tasks_done") or [])
                tasks_done += len(done_set)

            # Энергия вечером
            en = e.get("e_energy")
            if en:
                try:
                    energy_sum += int(en)
                    energy_count += 1
                except:
                    pass

        # Фокус-минуты берём из DB пользователя (накопленное за неделю нет — считаем по записям)
        # Простая версия: показываем что есть
        avg_energy = round(energy_sum / energy_count, 1) if energy_count else None

        streak = calc_streak(uid)

        # Формируем текст отчёта
        lines = [f"📊 *Итоги недели, {name}*\n_{days[0]} — {days[-1]}_\n"]

        lines.append(f"☀️ Утренних блоков заполнено: *{mornings_done} из 7*")
        lines.append(f"🌙 Вечерних блоков закрыто: *{evenings_done} из 7*")

        if tasks_total:
            pct = round(tasks_done / tasks_total * 100) if tasks_total else 0
            lines.append(f"✅ Задач выполнено: *{tasks_done} из {tasks_total}* ({pct}%)")

        if avg_energy:
            energy_label = {1:"😴 низкая", 2:"😔 ниже среднего", 3:"😐 средняя", 4:"😊 хорошая", 5:"⚡ отличная"}.get(round(avg_energy), "")
            lines.append(f"🔋 Средний уровень энергии: *{avg_energy}/5* {energy_label}")

        lines.append(f"🔥 Текущий стрик: *{streak} {'день' if streak==1 else 'дня' if streak<5 else 'дней'}*")

        # Мотивационный вывод
        lines.append("")
        if mornings_done >= 5:
            lines.append("🏆 Отличная неделя! Стабильность — суперсила при СДВГ.")
        elif mornings_done >= 3:
            lines.append("💪 Хорошая работа. Больше половины дней — уже результат.")
        else:
            lines.append("🌱 Неделя была непростой — и это нормально. Новая начинается завтра.")

        lines.append("\n_Следующая неделя начинается с одной задачи A. Ты справишься 💙_")

        await app.bot.send_message(
            uid,
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("☀️ Начать новую неделю", callback_data="go_morning")
            ]])
        )
    except Exception as e:
        print(f"Ошибка еженедельного отчёта: {e}")

# ── MAIN ───────────────────────────────────────────────────────────────────
# ── ADHD GUIDE ─────────────────────────────────────────────────────────────
GUIDE_SECTIONS = {
    "what": {
        "title": "🧠 Что такое СДВГ",
        "text": (
            "🧠 *Что такое СДВГ*\n\n"
            "СДВГ (синдром дефицита внимания и гиперактивности) — это *нейробиологическое расстройство*, "
            "а не лень, слабоволие или плохое воспитание.\n\n"
            "Мозг с СДВГ работает иначе: у него другой уровень дофамина и норадреналина — "
            "нейромедиаторов, которые отвечают за внимание, мотивацию и управление поведением.\n\n"
            "*Три основных симптома:*\n"
            "• 🎯 Нарушение внимания — сложно сосредоточиться, легко отвлечься\n"
            "• ⚡ Импульсивность — действуешь до того как подумал\n"
            "• 🏃 Гиперактивность — сложно сидеть на месте, мозг постоянно в движении\n\n"
            "_У разных людей симптомы проявляются по-разному — и это нормально._\n\n"
            "СДВГ *не связан с интеллектом*. Многие люди с СДВГ очень умны и креативны — "
            "просто их мозгу нужны другие условия для работы."
        ),
        "next": "modern_brain"
    },
    "modern_brain": {
        "title": "📱 Современный мозг",
        "text": (
            "📱 *Современный мозг и короткий дофамин*\n\n"
            "Сегодня СДВГшниками называют в том числе людей *без клинического диагноза* — "
            "но с очень похожими симптомами. И это не случайно.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🎰 *Зависимость от короткого дофамина*\n\n"
            "Соцсети, рилсы, скроллинг — машины быстрого дофамина. "
            "Каждый свайп — маленькая награда. Мозг привыкает и требует постоянной новизны:\n"
            "• Скучные но важные задачи становятся невыносимы\n"
            "• Концентрация дольше 2-3 минут — физически сложно\n"
            "• Тревога когда нечем занять голову\n"
            "• Глубокая работа, книги, длинные задачи — ощущение что «не моё»\n\n"
            "Это не СДВГ — но симптомы очень похожи. И навыки работают одинаково.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "😴 *Сон и перевозбуждение мозга*\n\n"
            "Скроллинг перед сном — двойной удар: синий свет подавляет мелатонин, "
            "а поток контента держит мозг в возбуждении. Он не успевает переключиться в режим покоя.\n\n"
            "Плохой сон → меньше дофамина → сильнее тянет к быстрым стимулам → снова плохой сон. "
            "Замкнутый круг.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "😑 *Скука как триггер*\n\n"
            "СДВГ-мозг (и перестимулированный мозг) плохо переносит скуку — буквально физически. "
            "Монотонная задача вызывает такой же дискомфорт как боль. "
            "Поэтому важные но неинтересные дела откладываются — не из лени, а из-за нейробиологии.\n\n"
            "_Решение: делать скучное коротко и с наградой. Таймер + похвала после._\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🏃 *Физическая активность — натуральный допинг*\n\n"
            "Спорт и движение — доказанный способ улучшить симптомы СДВГ и дофаминового истощения:\n"
            "• 20-30 минут аэробики повышают дофамин и норадреналин на несколько часов\n"
            "• Движение снижает перевозбуждение и помогает переключиться\n"
            "• Регулярный спорт улучшает сон и уменьшает импульсивность\n\n"
            "Поэтому утренняя разминка в боте — не просто привычка. "
            "Это буквально подготовка мозга к работе.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "✅ *Кому поможет этот бот*\n\n"
            "И людям с диагнозом СДВГ, и тем у кого его нет — "
            "но есть трудности с фокусом, прокрастинация или зависимость от скроллинга. "
            "Навыки организации и внимания работают для всех."
        ),
        "next": "diagnosis"
    },
    "diagnosis": {
        "title": "🩺 Диагноз и лечение",
        "text": (
            "🩺 *Диагноз и лечение СДВГ*\n\n"
            "*Диагноз ставит психиатр* — не невролог, не психолог, не тест из интернета. "
            "Только врач может подтвердить СДВГ и исключить другие причины похожих симптомов.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💊 *Медикаментозное лечение*\n\n"
            "Это *первая линия помощи* при СДВГ. Препараты помогают выровнять уровень дофамина "
            "и норадреналина — и жизнь буквально меняется.\n\n"
            "Важно: *лекарства не учат навыкам*. Они создают условия в которых навыки легче осваивать. "
            "Поэтому медикаменты и психотерапия работают лучше вместе, чем по отдельности.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🧠 *Тренинг навыков*\n\n"
            "Когнитивно-поведенческая терапия и тренинг навыков — "
            "это доказанный метод помощи при СДВГ. Лекарства помогают мозгу, "
            "навыки учат его работать эффективнее.\n\n"
            "Этот бот основан на программе *«Mastering Your Adult ADHD»* (Safren) — "
            "доказанном протоколе когнитивно-поведенческой терапии для взрослых с СДВГ.\n\n"
            "_Бот не заменяет врача и психотерапевта — но помогает практиковать навыки каждый день._"
        ),
        "next": "skills_groups"
    },
    "skills_groups": {
        "title": "🛠 Группы навыков",
        "text": (
            "🛠 *Группы навыков при СДВГ*\n\n"
            "Тренинг навыков разделён на несколько блоков. "
            "Каждый закрывает конкретную проблему СДВГ-мозга:\n\n"
            "📋 *1. Организация и планирование*\n"
            "Список дел, календарь, система ABC, цели (мечта → долгосрочная → краткосрочная → шаг). "
            "Основа основ — без этого всё остальное не работает.\n\n"
            "🛑 *2. Управление вниманием*\n"
            "Навык СТОП, работа по таймеру, бумажка гениальных мыслей, маячки внимания. "
            "Учимся замечать где внимание — и возвращать его.\n\n"
            "⚡ *3. Преодоление прокрастинации*\n"
            "Первый неподавляющий шаг, активация тела, выбор из множества решений, "
            "за и против. Учимся начинать даже когда не хочется.\n\n"
            "😴 *4. Отдых и самоуспокоение*\n"
            "Планирование отдыха, навык «бросить якорь», аптечка самоуспокоения, "
            "дыхание, холодная вода. Учимся останавливаться до того как перегорели.\n\n"
            "🏠 *5. Изменение среды*\n"
            "Рабочее место, устранение отвлекающих факторов, место для важных вещей. "
            "Среда работает за нас, а не против нас.\n\n"
            "👥 *6. Бадди и поддержка*\n"
            "Совместная работа рядом, партнёр по ответственности, работа с группой. "
            "Социальное присутствие активирует мозг с СДВГ.\n\n"
            "_Все эти навыки есть в разделе 🧠 Навыки — весь список сразу, открывай любой._"
        ),
        "next": "problems"
    },
    "problems": {
        "title": "😵 Главные трудности",
        "text": (
            "😵 *Главные трудности при СДВГ*\n\n"
            "Это не полный список — но самые частые:\n\n"
            "📋 *Организация и планирование*\n"
            "Сложно начать, сложно закончить, сложно держать несколько дел в голове одновременно.\n\n"
            "⏰ *Тайм-слепота*\n"
            "Время существует в двух форматах: «сейчас» и «потом». "
            "«Потом» — это всё что не происходит прямо сейчас, даже если это через 5 минут.\n\n"
            "🔄 *Прокрастинация*\n"
            "Не лень — а неспособность начать из-за исполнительной дисфункции. "
            "Мозг буквально не может запустить задачу без достаточного дофамина.\n\n"
            "🎢 *Эмоциональная дисрегуляция*\n"
            "Эмоции приходят резко и сильно. Сложно успокоиться или переключиться.\n\n"
            "😴 *Гиперфокус*\n"
            "Парадокс СДВГ — можно часами не отрываться от интересного дела и не заметить как прошло время. "
            "Это не суперсила — это истощает.\n\n"
            "🧠 *Рабочая память*\n"
            "«Зашёл в комнату и забыл зачем» — это каждый день."
        ),
        "next": "why"
    },
    "why": {
        "title": "🔬 Почему так происходит",
        "text": (
            "🔬 *Почему так происходит*\n\n"
            "Всё дело в *исполнительных функциях* — это способность мозга:\n"
            "• Планировать и организовывать\n"
            "• Начинать и заканчивать задачи\n"
            "• Управлять вниманием и эмоциями\n"
            "• Помнить что нужно сделать\n\n"
            "При СДВГ эти функции работают иначе — не хуже, а *по-другому*.\n\n"
            "🔑 *Ключевое понимание:*\n"
            "Мозг с СДВГ управляется *интересом, срочностью и новизной* — а не важностью. "
            "Поэтому важные но скучные задачи откладываются, а срочные или интересные делаются легко.\n\n"
            "Это не выбор и не характер — это нейробиология.\n\n"
            "Хорошая новость: *навыки можно натренировать*. "
            "Мозг пластичен, и при правильной поддержке исполнительные функции улучшаются. "
            "Именно этим занимается этот бот."
        ),
        "next": "fixes"
    },
    "fixes": {
        "title": "🛠 Что реально помогает",
        "text": (
            "🛠 *Что реально помогает при СДВГ*\n\n"
            "Это не волшебные таблетки — это навыки, которые нужно практиковать:\n\n"
            "📋 *Внешние системы*\n"
            "Списки дел, календарь, напоминания — всё что снимает нагрузку с рабочей памяти. "
            "Мозг не должен помнить — он должен делать.\n\n"
            "🔤 *Приоритеты ABC*\n"
            "Одна задача A (обязательно), две B (желательно), три C (по возможности). "
            "Сначала A — всегда.\n\n"
            "⚡ *Активация тела*\n"
            "Движение, холодная вода, музыка — физическое состояние напрямую влияет на способность начать.\n\n"
            "⏱ *Таймер*\n"
            "Работа короткими спринтами с обязательными перерывами. "
            "Гиперфокус — враг, не союзник.\n\n"
            "👥 *Бадди*\n"
            "Присутствие другого человека (даже онлайн) помогает мозгу активироваться.\n\n"
            "🏆 *Подкрепление*\n"
            "Хвалить себя — не каприз, а необходимость. "
            "Дофамин от похвалы буквально помогает делать следующий шаг.\n\n"
            "😴 *Планировать отдых*\n"
            "Отдых не случается сам — его нужно планировать как задачу."
        ),
        "next": "bot"
    },
    "bot": {
        "title": "🤖 Как помогает этот бот",
        "text": (
            "🤖 *Как помогает этот бот*\n\n"
            "Бот — это внешняя система поддержки для мозга с СДВГ.\n\n"
            "☀️ *Утром*\n"
            "Напоминает начать день со структуры: разминка → задачи ABC → свободное письмо → благодарность. "
            "Утром мозг ещё не готов принимать решения — поэтому A-план лучше ставить накануне вечером.\n\n"
            "☕ *Днём*\n"
            "Дневной чекин в выбранное тобой время. Показывает задачи на день и спрашивает как дела. "
            "Если застрял — даёт конкретные инструменты под твою ситуацию.\n\n"
            "🌙 *Вечером*\n"
            "Помогает закрыть день: достижения → похвала → яркие моменты → A-план на завтра. "
            "Завтрашний A-план записанный вечером — это главный лайфхак.\n\n"
            "🧠 *Навыки*\n"
            "Список из 13 навыков когнитивно-поведенческой терапии для СДВГ плюс бадди — "
            "открывай любой, наверху подсвечен навык дня.\n\n"
            "🤖 *ИИ-коуч*\n"
            "Когда застрял или отвлёкся — коуч даёт один конкретный шаг. Без лекций.\n\n"
            "*Главный принцип:*\n"
            "_Бот не делает за тебя — он напоминает, направляет и поддерживает. "
            "Навыки строятся через практику, а не через знание._"
        ),
        "next": None
    },
}

async def guide_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await send_guide_section(q.message, "what")

async def guide_section(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    section_id = q.data.replace("guide_", "")
    await send_guide_section(q.message, section_id)

async def send_guide_section(message, section_id):
    section = GUIDE_SECTIONS.get(section_id)
    if not section: return

    # Build navigation buttons
    buttons = []
    # Section dots navigation
    dot_row = []
    for key in GUIDE_SECTIONS:
        if key == section_id:
            dot_row.append(InlineKeyboardButton("●", callback_data=f"guide_{key}"))
        else:
            dot_row.append(InlineKeyboardButton("○", callback_data=f"guide_{key}"))
    buttons.append(dot_row)

    # Next button
    if section["next"]:
        next_title = GUIDE_SECTIONS[section["next"]]["title"]
        buttons.append([InlineKeyboardButton(f"Далее: {next_title} →", callback_data=f"guide_{section['next']}")])

    buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="go_menu")])

    await message.reply_text(
        section["text"],
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def check_notifications(app):
    """Каждую минуту — уведомления для всех пользователей у кого они включены."""
    global _last_heartbeat
    _last_heartbeat = time.monotonic()
    try:
        users = get_all_notif_users()
        tz = pytz.timezone(USER_TIMEZONE)
        now_dt = datetime.now(tz)
        now = now_dt.strftime("%H:%M")
        is_sunday = now_dt.weekday() == 6

        for user in users:
            uid = user["user_id"]
            try:
                if now == user.get("notif_morning", "09:00") and int(user.get("notif_morning_on") or 1):
                    await morning_notification(app, uid)
                    if is_sunday:
                        await weekly_report(app, uid)

                elif now == user.get("notif_midday", "13:00") and int(user.get("notif_midday_on") or 1):
                    await midday_notification(app, uid)

                elif now == user.get("notif_evening", "21:00") and int(user.get("notif_evening_on") or 1):
                    await evening_notification(app, uid)

                else:
                    # Напоминание если пропустил утро (+2 часа)
                    try:
                        mh, mm = map(int, user.get("notif_morning", "09:00").split(":"))
                        reminder_time = now_dt.replace(hour=mh, minute=mm, second=0, microsecond=0) + timedelta(hours=2)
                        if now == reminder_time.strftime("%H:%M") and int(user.get("notif_morning_on") or 1):
                            if not get_diary(uid, "morning").get("focus"):
                                await app.bot.send_message(
                                    chat_id=uid,
                                    text="☀️ *Утро ещё не закрыто*\n\nЕщё не поздно поставить задачи на день — займёт 2 минуты.",
                                    parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup([[
                                        InlineKeyboardButton("☀️ Заполнить утро", callback_data="go_morning")
                                    ]])
                                )
                    except Exception:
                        pass

                # Маячок
                await send_beacon(app, user)

                # Исследовательские вопросы
                try:
                    created_at = user.get("created_at") or date.today().isoformat()
                    days_since = (date.today() - date.fromisoformat(str(created_at)[:10])).days
                    done_days = [x for x in (user.get("research_done") or "").split(",") if x]
                    for milestone in [3, 7, 14, 30]:
                        if days_since >= milestone and str(milestone) not in done_days:
                            if 10 <= now_dt.hour <= 12:
                                await send_research_question(app, uid, milestone)
                            break
                except Exception as e:
                    print(f"Ошибка research uid={uid}: {e}")

                # Фокус-таймер
                if str(user.get("focus_active", "0")) == "1" and user.get("focus_end_time"):
                    try:
                        end_dt = datetime.fromisoformat(user["focus_end_time"]).astimezone(tz)
                        if now_dt >= end_dt:
                            await send_focus_end(app, uid, int(user.get("focus_duration", 25) or 25))
                    except Exception as e:
                        print(f"Ошибка focus uid={uid}: {e}")

            except Exception as e:
                print(f"Ошибка check_notifications uid={uid}: {e}")

    except Exception as e:
        print(f"Ошибка check_notifications: {e}")


# ── WATCHDOG ───────────────────────────────────────────────────────────────
# check_notifications обновляет heartbeat каждую минуту через APScheduler,
# который работает в том же asyncio event loop, что и long-polling бота.
# Если event loop зависнет (напр. сетевая ошибка Telegram оставила зависший
# запрос без таймаута — так уведомления не приходили 4 дня в июле 2026),
# APScheduler тоже перестаёт тикать и heartbeat не обновляется.
# Watchdog живёт в отдельном OS-потоке и не зависит от event loop, поэтому
# может обнаружить зависание и убить процесс — Railway (restartPolicyType
# ON_FAILURE) поднимет контейнер заново.
_last_heartbeat = time.monotonic()
HEARTBEAT_TIMEOUT_SEC = 5 * 60

def _watchdog_loop():
    while True:
        time.sleep(30)
        stale = time.monotonic() - _last_heartbeat
        if stale > HEARTBEAT_TIMEOUT_SEC:
            print(f"⚠️ Watchdog: event loop завис ({stale:.0f}с без heartbeat) — перезапуск процесса", flush=True)
            os._exit(1)

async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    print(f"⚠️ Необработанная ошибка: {ctx.error}", flush=True)


async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if NOTIFY_USER_ID and uid != NOTIFY_USER_ID:
        await update.message.reply_text(
            f"⛔ Нет доступа.\n\nТвой ID: `{uid}`",
            parse_mode="Markdown"
        )
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        total = cur.execute("SELECT COUNT(*) FROM users WHERE name != ''").fetchone()[0]
        week_ago  = (date.today() - timedelta(days=7)).isoformat()
        month_ago = (date.today() - timedelta(days=30)).isoformat()
        active7  = cur.execute("SELECT COUNT(DISTINCT user_id) FROM diary WHERE date >= ?", (week_ago,)).fetchone()[0]
        active30 = cur.execute("SELECT COUNT(DISTINCT user_id) FROM diary WHERE date >= ?", (month_ago,)).fetchone()[0]

        # Пол
        males   = cur.execute("SELECT COUNT(*) FROM users WHERE gender='M' AND name!=''").fetchone()[0]
        females = cur.execute("SELECT COUNT(*) FROM users WHERE gender='F' AND name!=''").fetchone()[0]

        # Города
        cities = cur.execute(
            "SELECT city, COUNT(*) as cnt FROM users WHERE city!='' AND city IS NOT NULL GROUP BY city ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        checkins = cur.execute(
            "SELECT block, COUNT(*) FROM diary GROUP BY block"
        ).fetchall()
        block_map = {r[0]: r[1] for r in checkins}

        # Research summary
        r3_ratings  = cur.execute("SELECT answer FROM research WHERE day=3 AND question='day3_rating'").fetchall()
        r14_nps     = cur.execute("SELECT answer FROM research WHERE day=14 AND question='day14_rating'").fetchall()
        r30_pmf     = cur.execute("SELECT answer FROM research WHERE day=30 AND question='day30_rating'").fetchall()
        r3_texts    = cur.execute("SELECT answer FROM research WHERE day=3 AND question='day3_text'").fetchall()
        r7_texts    = cur.execute("SELECT answer FROM research WHERE day=7 AND question='day7_text'").fetchall()
        r14_texts   = cur.execute("SELECT answer FROM research WHERE day=14 AND question='day14_text'").fetchall()
        conn.close()

        # Avg day-3 rating
        d3_avg = ""
        if r3_ratings:
            nums = [int(r[0]) for r in r3_ratings if r[0].isdigit()]
            if nums: d3_avg = f"  Оценка день 3: *{sum(nums)/len(nums):.1f}/5* ({len(nums)} отв.)\n"

        # NPS
        nps_str = ""
        if r14_nps:
            scores = [int(r[0]) for r in r14_nps if r[0].isdigit()]
            if scores:
                promoters  = sum(1 for s in scores if s >= 9)
                detractors = sum(1 for s in scores if s <= 6)
                nps = round((promoters - detractors) / len(scores) * 100)
                nps_str = f"  NPS (день 14): *{nps}* ({len(scores)} отв.)\n"

        # PMF
        pmf_str = ""
        if r30_pmf:
            sad_count = sum(1 for r in r30_pmf if "Очень" in r[0])
            pmf_pct = round(sad_count / len(r30_pmf) * 100) if r30_pmf else 0
            pmf_str = f"  PMF «очень расстроюсь» (день 30): *{pmf_pct}%* ({len(r30_pmf)} отв.)\n"

        # Open answers
        def fmt_answers(rows, label):
            if not rows: return ""
            out = f"\n*{label}:*\n"
            for r in rows[-3:]:
                out += f"— _{r[0]}_\n"
            return out

        cities_str = "\n".join(f"  {r[0]}: {r[1]}" for r in cities) if cities else "  —"

        text = (
            f"📊 *Статистика бота*\n\n"
            f"👤 Всего пользователей: *{total}*\n"
            f"  👨 Мужчин: {males} · 👩 Женщин: {females}\n"
            f"📅 Активны за 7 дней: *{active7}*\n"
            f"📅 Активны за 30 дней: *{active30}*\n\n"
            f"🌍 *Города:*\n{cities_str}\n\n"
            f"📋 *Чекины:*\n"
            f"  ☀️ Утро: {block_map.get('morning',0)}\n"
            f"  ☕ День: {block_map.get('midday',0)}\n"
            f"  🌙 Вечер: {block_map.get('evening',0)}\n\n"
            f"🔬 *Исследование:*\n"
            f"{d3_avg}{nps_str}{pmf_str}"
            f"{fmt_answers(r3_texts, 'Что полезно (день 3)')}"
            f"{fmt_answers(r7_texts, 'Что мешало (день 7)')}"
            f"{fmt_answers(r14_texts, 'Что упростить (день 14)')}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: `{e}`", parse_mode="Markdown")


def main():
    init_db()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(40)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(30)
        .build()
    )
    app.add_error_handler(on_error)

    # Онбординг
    onboard_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ONBOARD_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name)],
            ONBOARD_GENDER: [CallbackQueryHandler(got_gender, pattern="^gender_")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
        conversation_timeout=CONV_TIMEOUT_SHORT,
    )

    # Утренний flow (порядок: разминка → ритуал → задачи)
    morning_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(morning_start, pattern="^go_morning$")],
        states={
            M_EXERCISE: [
                CallbackQueryHandler(warmup_go,      pattern="^warmup_go$"),
                CallbackQueryHandler(warmup_done,    pattern="^warmup_done$"),
                CallbackQueryHandler(skip_warmup,    pattern="^skip_warmup$"),
                CallbackQueryHandler(morning_quick,  pattern="^morning_quick$"),
            ],
            # Сначала мягкий ритуал
            M_WRITING:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_writing),    CallbackQueryHandler(skip_m_writing,  pattern="^skip_m_writing$")],
            M_GRATITUDE:[MessageHandler(filters.TEXT & ~filters.COMMAND, got_gratitude),  CallbackQueryHandler(skip_m_gratitude,pattern="^skip_m_gratitude$")],
            M_CHILD:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_child),      CallbackQueryHandler(skip_m_child,    pattern="^skip_m_child$")],
            # Потом задачи ABC
            M_FOCUS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_m_focus),    CallbackQueryHandler(skip_m_focus,    pattern="^skip_m_focus$"), CallbackQueryHandler(use_m_focus, pattern="^use_m_focus$")],
            M_B1:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_m_b1),       CallbackQueryHandler(skip_m_b1,       pattern="^skip_m_b1$"),    CallbackQueryHandler(use_m_b1,    pattern="^use_m_b1$")],
            M_B2:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_m_b2),       CallbackQueryHandler(skip_m_b2,       pattern="^skip_m_b2$"),    CallbackQueryHandler(use_m_b2,    pattern="^use_m_b2$")],
            M_C1:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_m_c1),       CallbackQueryHandler(skip_m_c_all,    pattern="^skip_m_c_all$"), CallbackQueryHandler(use_m_c_all, pattern="^use_m_c_all$")],
            M_C2:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_m_c2),       CallbackQueryHandler(skip_m_c_all,    pattern="^skip_m_c_all$")],
            M_C3:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_m_c3),       CallbackQueryHandler(skip_m_c_all,    pattern="^skip_m_c_all$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
        conversation_timeout=CONV_TIMEOUT_LONG,
    )

    # Вечерний flow
    evening_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(evening_start, pattern="^go_evening$")],
        states={
            E_TASKS_DONE:[CallbackQueryHandler(tasks_done_finish, pattern="^td_done$"), CallbackQueryHandler(toggle_task_done, pattern="^td_")],
            E_ACH:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_ach),      CallbackQueryHandler(skip_e_ach,      pattern="^skip_e_ach$")],
            E_PRAISE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_praise),   CallbackQueryHandler(skip_e_praise,   pattern="^skip_e_praise$")],
            E_HIGHLIGHTS:[MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_highlights),CallbackQueryHandler(skip_e_highlights,pattern="^skip_e_highlights$")],
            E_SELFCARE:  [CallbackQueryHandler(selfcare_done,  pattern="^sc_done$"), CallbackQueryHandler(toggle_selfcare, pattern="^sc_")],
            E_ENERGY:    [CallbackQueryHandler(got_energy, pattern="^energy_[1-5]$")],
            E_A:         [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_a),        CallbackQueryHandler(skip_e_a,        pattern="^skip_e_a$")],
            E_B1:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_b1),       CallbackQueryHandler(skip_e_b1,       pattern="^skip_e_b1$")],
            E_B2:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_b2),       CallbackQueryHandler(skip_e_b2,       pattern="^skip_e_b2$")],
            E_C1:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_c1),       CallbackQueryHandler(skip_e_c_all,    pattern="^skip_e_c_all$")],
            E_C2:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_c2),       CallbackQueryHandler(skip_e_c_all,    pattern="^skip_e_c_all$")],
            E_C3:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_e_c3),       CallbackQueryHandler(skip_e_c_all,    pattern="^skip_e_c_all$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
        conversation_timeout=CONV_TIMEOUT_LONG,
    )

    app.add_handler(CommandHandler("admin", admin_stats), group=-1)
    app.add_handler(onboard_conv)
    app.add_handler(morning_conv)
    app.add_handler(evening_conv)
    app.add_handler(CallbackQueryHandler(onboard_done,       pattern="^onboard_done$"))
    # Fallback для кнопок пола — на случай если ConversationHandler потерял состояние при перезапуске
    app.add_handler(CallbackQueryHandler(got_gender, pattern="^gender_[MFN]$"))
    app.add_handler(CallbackQueryHandler(onboard_notif_on,   pattern="^onboard_notif_on$"))
    app.add_handler(CallbackQueryHandler(onboard_notif_skip, pattern="^onboard_notif_skip$"))
    app.add_handler(CallbackQueryHandler(coach_menu,    pattern="^go_coach$"))
    app.add_handler(CallbackQueryHandler(coach_quick, pattern="^c_(start|dist|next|procr|overload|tip)$"))
    app.add_handler(CallbackQueryHandler(show_skill,  pattern="^go_skill$"))
    app.add_handler(CallbackQueryHandler(show_skill_detail, pattern=r"^skill_\d+$"))
    app.add_handler(CallbackQueryHandler(show_streak, pattern="^go_streak$"))
    app.add_handler(CallbackQueryHandler(go_menu,     pattern="^go_menu$"))
    app.add_handler(CallbackQueryHandler(guide_start,      pattern="^go_guide$"))
    app.add_handler(CallbackQueryHandler(guide_section,    pattern="^guide_"))
    app.add_handler(CallbackQueryHandler(go_settings,      pattern="^go_settings$"))
    app.add_handler(CallbackQueryHandler(set_time_prompt,  pattern="^set_(morning|midday|evening)$"))
    app.add_handler(CallbackQueryHandler(toggle_notif,       pattern="^toggle_notif$"))
    app.add_handler(CallbackQueryHandler(toggle_notif_block, pattern="^toggle_(morning|midday|evening)$"))
    app.add_handler(CallbackQueryHandler(toggle_beacon,      pattern="^toggle_beacon$"))
    app.add_handler(CallbackQueryHandler(beacon_set_interval, pattern="^beacon_int_\\d+$"))
    app.add_handler(CallbackQueryHandler(noop_callback,      pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(research_callback,  pattern="^research_"))
    app.add_handler(CallbackQueryHandler(show_tasks,        pattern="^go_tasks$"))
    app.add_handler(CallbackQueryHandler(task_done_callback, pattern="^task_done_"))
    app.add_handler(CallbackQueryHandler(show_day_card,    pattern="^go_daycard$"))
    app.add_handler(CallbackQueryHandler(day_card_nav,     pattern="^daycard_"))
    app.add_handler(CallbackQueryHandler(go_feedback,      pattern="^go_feedback$"))
    app.add_handler(CallbackQueryHandler(go_about,         pattern="^go_about$"))
    app.add_handler(CallbackQueryHandler(buddy_menu,      pattern="^go_buddy$"))
    app.add_handler(CallbackQueryHandler(buddy_set,       pattern="^buddy_set$"))
    app.add_handler(CallbackQueryHandler(buddy_ping,      pattern="^buddy_ping$"))
    app.add_handler(CallbackQueryHandler(midday_callback, pattern="^mid_"))
    app.add_handler(CallbackQueryHandler(go_focus,          pattern="^go_focus$"))
    app.add_handler(CallbackQueryHandler(focus_start_callback, pattern="^focus_start_\\d+$"))
    app.add_handler(CallbackQueryHandler(focus_stop_callback,  pattern="^focus_stop$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Уведомления (UTC время)
    scheduler = AsyncIOScheduler()
    # Каждую минуту проверяем время уведомлений для каждого пользователя
    scheduler.add_job(check_notifications, 'cron', minute='*', args=[app])
    scheduler.start()

    threading.Thread(target=_watchdog_loop, daemon=True).start()

    print("✅ ADHD бот v5 запущен!")
    print("   Уведомления: по расписанию пользователя (check_notifications каждую минуту)")
    print(f"   Notify user ID: {NOTIFY_USER_ID}")
    print(f"   Watchdog: перезапуск если нет heartbeat > {HEARTBEAT_TIMEOUT_SEC}с")
    app.run_polling()

if __name__ == "__main__":
    main()
