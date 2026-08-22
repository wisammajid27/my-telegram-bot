#!/usr/bin/env python3
"""
Telegram Bot - Complete Version with PostgreSQL Support (Optimized)
"""
import os
import logging
import calendar
from datetime import date, datetime
from flask import Flask
from threading import Thread
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ====================== سيرفر Flask لإبقاء البوت حياً ======================
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot is Alive!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# ====================== إدارة قاعدة البيانات (PostgreSQL) ======================
DATABASE_URL = os.getenv("DATABASE_URL")
DB_AVAILABLE = True  # يتحدث تلقائياً حسب حالة الاتصال

@contextmanager
def get_db():
    """إدارة اتصال قاعدة البيانات بشكل آمن. يرجع None لو فشل الاتصال بدل ما ينهار البوت."""
    global DB_AVAILABLE
    if not DATABASE_URL:
        DB_AVAILABLE = False
        yield None
        return

    conn = None
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            sslmode='require',
            connect_timeout=5
        )
        DB_AVAILABLE = True
        try:
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    except Exception as e:
        DB_AVAILABLE = False
        logging.warning(f"Database unavailable (will use static data): {e}")
        yield None

def init_db():
    try:
        with get_db() as conn:
            if conn is None:
                logging.warning("Skipping init_db: database unavailable")
                return
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS families (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        family_name TEXT,
                        created_at TEXT
                    );
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS passengers (
                        id SERIAL PRIMARY KEY,
                        family_id INTEGER,
                        user_id BIGINT,
                        name TEXT,
                        birth_date TEXT,
                        created_at TEXT
                    );
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS fare_prices (
                        fare_code TEXT PRIMARY KEY,
                        base_price INTEGER NOT NULL,
                        price_7_12 INTEGER NOT NULL,
                        price_13_26 INTEGER NOT NULL,
                        price_60_64 INTEGER NOT NULL,
                        price_65_plus INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS travel_routes (
                        id SERIAL PRIMARY KEY,
                        route_name TEXT UNIQUE NOT NULL,
                        sort_order INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    );
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS route_trips (
                        id SERIAL PRIMARY KEY,
                        route_id INTEGER NOT NULL REFERENCES travel_routes(id) ON DELETE CASCADE,
                        fare_code TEXT NOT NULL,
                        departure_label TEXT NOT NULL,
                        service_type TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE (route_id, fare_code, departure_label, service_type)
                    );
                ''')
                conn.commit()
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")

# ====================== البيانات الثابتة والقوانين ======================
OFFICE_PROFIT = 85
ROUTES = {
    "اسكيشهير - انقرة": [
        {"price": 370, "times": ["03:24"], "slow": True},
        {"price": 415, "times": ["05:31"], "slow": True},
        {"price": 500, "times": ["06:35", "14:30"]},
        {"price": 515, "times": ["باقي الاوقات"]},
    ],
    "انقرة - اسكي شهير": [
        {"price": 370, "times": ["22:00"], "slow": True},
        {"price": 415, "times": ["20:00"], "slow": True},
        {"price": 500, "times": ["11:40", "17:50"]},
        {"price": 515, "times": ["باقي الاوقات"]},
    ],
    "اسكيشهير - اسطنبول(بندك)": [
        {"price": 535, "times": ["01:28"], "slow": True},
        {"price": 645, "times": ["باقي الاوقات"]},
    ],
    "اسطنبول(بندك) - اسكيشهير": [
        {"price": 535, "times": ["23:18"], "slow": True},
        {"price": 645, "times": ["باقي الاوقات"]},
    ],
    "اسكي شهير - اسطنبول (سوغوتلوجشمة)": [
        {"price": 535, "times": ["01:28"], "slow": True},
        {"price": 645, "times": ["باقي الاوقات"]},
    ],
    "اسطنبول (سوغوتلوجشمة) - اسكي شهير": [
        {"price": 535, "times": ["22:47"], "slow": True},
        {"price": 645, "times": ["باقي الاوقات"], "fast": True},
    ],
    "اسكي شهير - كركالة": [
        {"price": 820, "times": ["11:56"], "fast": True},
        {"price": 820, "times": ["16:10"], "fast": True},
    ],
    "كركالة - اسكي شهير": [
        {"price": 820, "times": ["19:46"], "fast": True},
        {"price": 820, "times": ["14:55"], "fast": True},
        {"price": 820, "times": ["09:06"], "fast": True},
    ],
    "كركالة - انقرة": [
        {"price": 240, "times": ["05:25", "08:31", "10:47"], "slow": True},
        {"price": 305, "times": ["09:06", "14:55", "17:31", "21:56"], "fast": True},
    ],
    "انقرة - كركالة": [
        {"price": 240, "times": ["11:20", "18:00"], "slow": True},
        {"price": 305, "times": ["07:00", "13:20", "18:40"], "fast": True},
    ],
    "اسكي شهير- اسطنبول هالك": [
        {"price": 610, "times": ["01:28"], "slow": True},
        {"price": 740, "times": ["باقي الاوقات"], "fast": True},
    ],
    "اسطنبول هالك - اسكي شهير": [
        {"price": 610, "times": ["22:00"], "slow": True},
        {"price": 740, "times": ["باقي الاوقات"], "fast": True},
    ],
    "اسكي شهير - اسطنبول بكركوي": [
        {"price": 610, "times": ["01:28"], "slow": True},
        {"price": 740, "times": ["باقي الاوقات"], "fast": True},
    ],
    "اسطنبول بكركوي - اسكي شهير": [
        {"price": 610, "times": ["22:17"], "slow": True},
        {"price": 740, "times": ["باقي الاوقات"], "fast": True},
    ],
}

PRICES_RULES = {
    370: {"7-12": 185, "13-26": 315, "60-64": 315, "+65": 185},
    415: {"7-12": 210, "13-26": 355, "60-64": 355, "+65": 210},
    500: {"7-12": 250, "13-26": 425, "60-64": 425, "+65": 250},
    515: {"7-12": 260, "13-26": 440, "60-64": 440, "+65": 260},
    535: {"7-12": 270, "13-26": 455, "60-64": 455, "+65": 270},
    645: {"7-12": 325, "13-26": 550, "60-64": 550, "+65": 325},
    820: {"7-12": 410, "13-26": 700, "60-64": 700, "+65": 410},
    240: {"7-12": 120, "13-26": 205, "60-64": 205, "+65": 120},
    305: {"7-12": 155, "13-26": 260, "60-64": 260, "+65": 155},
    610: {"7-12": 305, "13-26": 520, "60-64": 520, "+65": 305},
    740: {"7-12": 370, "13-26": 630, "60-64": 630, "+65": 370},
}

ADMIN_USER_ID = 7209751288

def fare_code_from_original_price(original_price: int) -> str:
    return f"fare_{original_price}"

def init_fare_prices():
    try:
        with get_db() as conn:
            if conn is None:
                logging.warning("Skipping init_fare_prices: database unavailable")
                return
            with conn.cursor() as cur:
                for base_price, rules in PRICES_RULES.items():
                    cur.execute('''
                        INSERT INTO fare_prices
                            (fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (fare_code) DO NOTHING
                    ''', (
                        fare_code_from_original_price(base_price), base_price,
                        rules.get("7-12", base_price), rules.get("13-26", base_price),
                        rules.get("60-64", base_price), rules.get("+65", base_price),
                        datetime.now().isoformat(),
                    ))
                conn.commit()
    except Exception as e:
        logging.error(f"Failed to init fare prices: {e}")

def get_fare_prices():
    """يرجع الأسعار من قاعدة البيانات، ولو فشلت يرجع من PRICES_RULES الثابتة"""
    with get_db() as conn:
        if conn is None:
            # Fallback
            result = {}
            for base_price, rules in PRICES_RULES.items():
                fare_code = fare_code_from_original_price(base_price)
                result[fare_code] = {
                    'fare_code': fare_code,
                    'base_price': base_price,
                    'price_7_12': rules.get("7-12", base_price),
                    'price_13_26': rules.get("13-26", base_price),
                    'price_60_64': rules.get("60-64", base_price),
                    'price_65_plus': rules.get("+65", base_price),
                }
            return result

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus
                FROM fare_prices
            ''')
            rows = cur.fetchall()
            if rows:
                return {row['fare_code']: dict(row) for row in rows}
            # لو فاضي نرجع الثابتة
            result = {}
            for base_price, rules in PRICES_RULES.items():
                fare_code = fare_code_from_original_price(base_price)
                result[fare_code] = {
                    'fare_code': fare_code,
                    'base_price': base_price,
                    'price_7_12': rules.get("7-12", base_price),
                    'price_13_26': rules.get("13-26", base_price),
                    'price_60_64': rules.get("60-64", base_price),
                    'price_65_plus': rules.get("+65", base_price),
                }
            return result

def save_fare_prices(updates):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot save fare prices: database unavailable")
            return
        with conn.cursor() as cur:
            for fare_code, prices in updates.items():
                cur.execute('''
                    INSERT INTO fare_prices
                        (fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (fare_code) DO UPDATE SET
                        base_price = EXCLUDED.base_price, price_7_12 = EXCLUDED.price_7_12,
                        price_13_26 = EXCLUDED.price_13_26, price_60_64 = EXCLUDED.price_60_64,
                        price_65_plus = EXCLUDED.price_65_plus, updated_at = EXCLUDED.updated_at
                ''', (
                    fare_code, prices['base_price'], prices['price_7_12'], prices['price_13_26'],
                    prices['price_60_64'], prices['price_65_plus'], datetime.now().isoformat(),
                ))
            conn.commit()

def init_route_data():
    try:
        with get_db() as conn:
            if conn is None:
                logging.warning("Skipping init_route_data: database unavailable")
                return
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM travel_routes")
                if cur.fetchone()[0] > 0:
                    return
                for sort_order, (route_name, route_groups) in enumerate(ROUTES.items()):
                    cur.execute('''
                        INSERT INTO travel_routes (route_name, sort_order, created_at)
                        VALUES (%s, %s, %s) RETURNING id
                    ''', (route_name, sort_order, datetime.now().isoformat()))
                    route_id = cur.fetchone()[0]
                    for group in route_groups:
                        service_type = 'fast' if group.get('fast') else 'slow' if group.get('slow') else 'regular'
                        fare_code = fare_code_from_original_price(group['price'])
                        for departure_label in group['times']:
                            cur.execute('''
                                INSERT INTO route_trips
                                    (route_id, fare_code, departure_label, service_type, created_at)
                                VALUES (%s, %s, %s, %s, %s)
                            ''', (route_id, fare_code, departure_label, service_type, datetime.now().isoformat()))
                conn.commit()
    except Exception as e:
        logging.error(f"Failed to init routes: {e}")

def get_routes():
    """يرجع الوجهات من قاعدة البيانات، ولو فشلت يرجع من البيانات الثابتة ROUTES"""
    with get_db() as conn:
        if conn is None:
            # Fallback: استخدم البيانات الثابتة
            return [
                {'id': idx, 'route_name': name}
                for idx, name in enumerate(ROUTES.keys())
            ]
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, route_name FROM travel_routes ORDER BY sort_order, id")
            rows = cur.fetchall()
            if rows:
                return [dict(row) for row in rows]
            # لو الجدول فاضي نرجع الثابتة
            return [
                {'id': idx, 'route_name': name}
                for idx, name in enumerate(ROUTES.keys())
            ]

def get_route(route_id):
    with get_db() as conn:
        if conn is None:
            # Fallback
            names = list(ROUTES.keys())
            if 0 <= route_id < len(names):
                return {'id': route_id, 'route_name': names[route_id]}
            return None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, route_name FROM travel_routes WHERE id = %s", (route_id,))
            row = cur.fetchone()
            return dict(row) if row else None

def get_route_trips(route_id):
    with get_db() as conn:
        if conn is None:
            # Fallback من البيانات الثابتة
            names = list(ROUTES.keys())
            if not (0 <= route_id < len(names)):
                return []
            route_name = names[route_id]
            groups = ROUTES.get(route_name, [])
            result = []
            for group in groups:
                service_type = 'fast' if group.get('fast') else 'slow' if group.get('slow') else 'regular'
                fare_code = fare_code_from_original_price(group['price'])
                result.append({
                    'fare_code': fare_code,
                    'service_type': service_type,
                    'times': group['times']
                })
            return result

        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, departure_label, service_type
                FROM route_trips
                WHERE route_id = %s
                ORDER BY id
            ''', (route_id,))
            groups = {}
            for row in cur.fetchall():
                key = (row['fare_code'], row['service_type'])
                groups.setdefault(key, []).append(row['departure_label'])
            return [
                {'fare_code': fare_code, 'service_type': service_type, 'times': times}
                for (fare_code, service_type), times in groups.items()
            ]

def create_route(route_name):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot create route: database unavailable")
            return None
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO travel_routes (route_name, sort_order, created_at)
                VALUES (%s, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM travel_routes), %s)
                ON CONFLICT (route_name) DO NOTHING
                RETURNING id
            ''', (route_name, datetime.now().isoformat()))
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None

def create_route_trip(route_id, fare_code, departure_label, service_type):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot create route trip: database unavailable")
            return None
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO route_trips (route_id, fare_code, departure_label, service_type, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (route_id, fare_code, departure_label, service_type) DO NOTHING
                RETURNING id
            ''', (route_id, fare_code, departure_label, service_type, datetime.now().isoformat()))
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def price_update_template():
    fare_prices = get_fare_prices()
    lines = []
    for fare_code in sorted(fare_prices, key=lambda code: int(code.split('_')[1])):
        fare = fare_prices[fare_code]
        category = fare_code.split('_')[1]
        lines.append(
            f"{category} | {fare['base_price']} | {fare['price_7_12']} | "
            f"{fare['price_13_26']} | {fare['price_60_64']} | {fare['price_65_plus']}"
        )
    return "\n".join(lines)

async def update_prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
        return

    context.user_data['step'] = 'admin_update_prices'
    await update.message.reply_text(
        "💼 **تحديث الأسعار دفعة واحدة**\n\n"
        "يمكنك إرسال سطر واحد أو عدة أسطر؛ كل سطر يحدّث فئة واحدة بهذا الترتيب:\n"
        "`رمز الفئة | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "رمز الفئة هو الرقم الأول الثابت، حتى إذا تغير السعر الكامل لاحقًا.\n"
        "انسخ الجدول التالي وعدّل الأرقام فقط، ثم أرسله:\n\n"
        f"```\n{price_update_template()}\n```",
        parse_mode='Markdown',
    )

async def update_one_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
        return

    context.user_data['step'] = 'admin_update_one_price'
    await update.message.reply_text(
        "💼 **تحديث فئة سعر واحدة**\n\n"
        "أرسل سطرًا واحدًا فقط بهذا الترتيب:\n"
        "`رمز الفئة | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "مثال لتحديث فئة 370:\n"
        "`370 | 400 | 200 | 340 | 340 | 200`\n\n"
        "رمز الفئة هو الرقم الأول الأصلي، وليس السعر الجديد.",
        parse_mode='Markdown',
    )

async def add_destination_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
        return
    context.user_data['step'] = 'admin_add_destination'
    await update.message.reply_text("🗺️ أرسل اسم الوجهة الجديدة، مثال:\n`انقرة - قونية`", parse_mode='Markdown')

async def add_trip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
        return
    routes = get_routes()
    keyboard = [[InlineKeyboardButton(route['route_name'], callback_data=f"admin_trip_route_{route['id']}")]
                for route in routes]
    context.user_data['step'] = 'admin_select_trip_route'
    await update.message.reply_text("🚆 اختر الوجهة التي تريد إضافة رحلة لها:", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_fare_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
        return
    context.user_data['step'] = 'admin_add_fare'
    await update.message.reply_text(
        "💰 أرسل فئة السعر الجديدة في سطر واحد:\n"
        "`رمز جديد | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "مثال: `900 | 900 | 450 | 765 | 765 | 450`",
        parse_mode='Markdown',
    )

def parse_price_updates(text: str, allow_new=False):
    current_prices = get_fare_prices()
    updates = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split('|')]
        if len(parts) != 6:
            raise ValueError("كل سطر يجب أن يحتوي على 6 قيم مفصولة بعلامة |")

        category = parts[0].replace('fare_', '')
        if not category.isdigit():
            raise ValueError("رمز الفئة يجب أن يكون رقمًا، مثل 370")
        fare_code = f"fare_{category}"
        if fare_code not in current_prices and not allow_new:
            raise ValueError(f"فئة السعر {category} غير موجودة")
        if fare_code in updates:
            raise ValueError(f"فئة السعر {category} مكررة")

        try:
            values = [int(value) for value in parts[1:]]
        except ValueError as error:
            raise ValueError("يجب أن تكون جميع الأسعار أرقامًا صحيحة") from error
        if any(value < 0 for value in values) or values[0] == 0:
            raise ValueError("الأسعار يجب أن تكون موجبة، والسعر الكامل أكبر من صفر")

        updates[fare_code] = {
            'base_price': values[0],
            'price_7_12': values[1],
            'price_13_26': values[2],
            'price_60_64': values[3],
            'price_65_plus': values[4],
        }

    if not updates:
        raise ValueError("لم يتم العثور على أي صف أسعار")
    return updates

BIRTH_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")

def parse_birth_date(date_str: str) -> datetime:
    date_str = date_str.strip()
    for fmt in BIRTH_DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError("invalid birth date")

def normalize_birth_date(date_str: str) -> str:
    return parse_birth_date(date_str).strftime("%d-%m-%Y")

def calculate_railway_age(birth_date: datetime, today: date | None = None) -> int:
    today = today or date.today()

    def birthday_in(year: int) -> date:
        day = min(birth_date.day, calendar.monthrange(year, birth_date.month)[1])
        return date(year, birth_date.month, day)

    this_year_birthday = birthday_in(today.year)
    last_birthday = this_year_birthday if today >= this_year_birthday else birthday_in(today.year - 1)
    actual_age = last_birthday.year - birth_date.year

    next_month = last_birthday.month % 12 + 1
    next_month_year = last_birthday.year + (last_birthday.month == 12)
    first_month_day = min(last_birthday.day, calendar.monthrange(next_month_year, next_month)[1])
    one_month_after_birthday = date(next_month_year, next_month, first_month_day)

    return actual_age + (today >= one_month_after_birthday)

def format_time_with_period(time_str: str) -> str:
    try:
        hour = int(time_str.split(':')[0])
        if 6 <= hour <= 11: period = "ص"
        elif 12 <= hour <= 15: period = "ظ"
        elif 16 <= hour <= 17: period = "ع"
        elif 18 <= hour <= 19: period = "م"
        else: period = "ل"
        return f"{time_str} {period}"
    except:
        return time_str

def get_user_families(user_id):
    with get_db() as conn:
        if conn is None:
            return []
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM families WHERE user_id = %s ORDER BY family_name", (user_id,))
            return [dict(row) for row in cur.fetchall()]

def get_family_passengers(family_id):
    with get_db() as conn:
        if conn is None:
            return []
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM passengers WHERE family_id = %s ORDER BY name", (family_id,))
            return [dict(row) for row in cur.fetchall()]

def create_family(user_id, family_name):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot create family: database unavailable")
            return None
        with conn.cursor() as cur:
            try:
                cur.execute("INSERT INTO families (user_id, family_name, created_at) VALUES (%s, %s, %s) RETURNING id",
                            (user_id, family_name, datetime.now().isoformat()))
                family_id = cur.fetchone()[0]
                conn.commit()
                return family_id
            except Exception as e:
                logging.error(f"Error creating family: {e}")
                return None

def add_passenger_to_family(family_id, user_id, name, birth_date):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot add passenger: database unavailable")
            return
        with conn.cursor() as cur:
            cur.execute("INSERT INTO passengers (family_id, user_id, name, birth_date, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (family_id, user_id, name, birth_date, datetime.now().isoformat()))
            conn.commit()

def delete_families(family_ids):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot delete families: database unavailable")
            return
        with conn.cursor() as cur:
            for fid in family_ids:
                cur.execute("DELETE FROM passengers WHERE family_id = %s", (fid,))
                cur.execute("DELETE FROM families WHERE id = %s", (fid,))
            conn.commit()

def delete_passengers(passenger_ids):
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot delete passengers: database unavailable")
            return
        with conn.cursor() as cur:
            for pid in passenger_ids:
                cur.execute("DELETE FROM passengers WHERE id = %s", (pid,))
            conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    routes = get_routes()
    keyboard = [[InlineKeyboardButton(route['route_name'], callback_data=f"dest_{route['id']}")]
                for route in routes]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🚍 **مرحباً بك في بوت حجز التذاكر**\n\n🗂️ اختر الوجهة المطلوبة:"
    if not DB_AVAILABLE:
        text += "\n\n⚠️ _قاعدة البيانات غير متاحة حالياً — يعمل البوت بالبيانات الأساسية. حفظ العائلات غير متوفر مؤقتاً._"

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')

def is_destination_request(text: str) -> bool:
    normalized = text.strip().replace("ـ", "")
    return normalized in {"وجهة", "الوجهة"}

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "confirm_price_updates":
        if not is_admin(user_id):
            return
        updates = context.user_data.get('pending_price_updates')
        if not updates:
            await query.message.edit_text("⚠️ انتهت جلسة التحديث. استخدم /update_prices مرة أخرى.")
            return
        save_fare_prices(updates)
        context.user_data.pop('pending_price_updates', None)
        context.user_data.pop('step', None)
        await query.message.edit_text(f"✅ تم حفظ تحديث {len(updates)} فئة سعر بنجاح.")

    elif data == "cancel_price_updates":
        if not is_admin(user_id):
            return
        context.user_data.pop('pending_price_updates', None)
        context.user_data.pop('step', None)
        await query.message.edit_text("تم إلغاء تحديث الأسعار.")

    elif data.startswith("admin_trip_route_"):
        if not is_admin(user_id):
            return
        try:
            route_id = int(data.rsplit('_', 1)[1])
        except ValueError:
            return
        route = get_route(route_id)
        if not route:
            return
        context.user_data['selected_admin_route_id'] = route_id
        context.user_data['step'] = 'admin_add_trip'
        await query.message.edit_text(
            f"🚆 **{route['route_name']}**\n\n"
            "أرسل بيانات الرحلة بهذا الترتيب:\n"
            "`رمز فئة السعر | الوقت أو باقي الاوقات | بطيء أو سريع أو عادي`\n\n"
            "مثال: `535 | 01:28 | بطيء`",
            parse_mode='Markdown',
        )
    elif data.startswith("dest_"):
        try:
            route_id = int(data[5:])
        except ValueError:
            return
        selected_route = get_route(route_id)
        if not selected_route:
            return
        dest_name = selected_route['route_name']
        context.user_data['selected_dest'] = dest_name
        context.user_data['selected_route_id'] = route_id
        routes = get_route_trips(route_id)
        fare_prices = get_fare_prices()
        
        keyboard = []
        for route in routes:
            fare_code = route['fare_code']
            fare = fare_prices.get(fare_code)
            if not fare:
                logging.error(f"Missing fare configuration: {fare_code}")
                continue
            formatted_times = [format_time_with_period(t) for t in route["times"]]
            if route['service_type'] == "fast": times_str = " ⚡ سريع"
            elif route['service_type'] == "slow": times_str = " 🐢 بطيء"
            else: times_str = ""
            
            if len(formatted_times) > 5:
                times_display = " | ".join(formatted_times[:5]) + " | وغيرها" + times_str
            else:
                times_display = " | ".join(formatted_times) + times_str
                
            button_text = f"{fare['base_price']} ليرة - {times_display}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"price_{fare_code}")])
        
        keyboard.append([InlineKeyboardButton("⬅️_العودة", callback_data="back_to_dest")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"📍 **الوجهة:** {dest_name}\n\nاختر المسار:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("price_"):
        fare_code = data[6:]
        if fare_code not in get_fare_prices():
            return
        context.user_data['selected_fare_code'] = fare_code
        context.user_data['step'] = "choose_family"
        
        families = get_user_families(user_id)
        keyboard = [[InlineKeyboardButton(f"👪 {f['family_name']}", callback_data=f"family_{f['id']}")] for f in families]
        keyboard.append([InlineKeyboardButton("🧮 حساب سريع بدون عائلة", callback_data="quick_calc")])
        keyboard.append([InlineKeyboardButton("➕ إنشاء عائلة جديدة", callback_data="new_family")])
        keyboard.append([InlineKeyboardButton("🗑️ مسح قيد العائلة", callback_data="delete_family")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_dest")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("👨‍👩‍👧‍👦 **اختر العائلة أو اختر الحساب السريع**:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "quick_calc":
        context.user_data['step'] = "quick_calc"
        await query.message.edit_text("🧮 **قسم الحساب السريع**\n\nأدخل تاريخ الميلاد مباشرة لحساب السعر فوراً:\nمثال: `15-05-1995` أو `15/05/1995` أو `15.05.1995`")

    elif data == "new_family":
        context.user_data['step'] = "create_family"
        await query.message.edit_text("👪 أدخل اسم العائلة:")

    elif data == "delete_family":
        families = get_user_families(user_id)
        if not families:
            await query.message.edit_text("⚠️ لا توجد عائلات لمسحها!")
            return
        context.user_data['delete_mode'] = 'family'
        context.user_data['selected_families_to_delete'] = []
        keyboard = [[InlineKeyboardButton(f"☐ {f['family_name']}", callback_data=f"del_family_{f['id']}")] for f in families]
        keyboard.append([InlineKeyboardButton("🗑️ مسح العائلات المحددة", callback_data="confirm_delete_family")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر العائلات المراد مسحها:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("del_family_"):
        family_id = int(data.split("_")[2])
        selected = context.user_data.get('selected_families_to_delete', [])
        if family_id in selected:
            selected.remove(family_id)
        else:
            selected.append(family_id)
        context.user_data['selected_families_to_delete'] = selected
        
        families = get_user_families(user_id)
        keyboard = []
        for f in families:
            is_selected = f['id'] in selected
            emoji = "✅" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(f"{emoji} {f['family_name']}", callback_data=f"del_family_{f['id']}")])
        keyboard.append([InlineKeyboardButton("🗑️ مسح العائلات المحددة", callback_data="confirm_delete_family")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"✅ تم تحديد {len(selected)} عائلة", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "confirm_delete_family":
        selected = context.user_data.get('selected_families_to_delete', [])
        if not selected:
            await query.message.edit_text("⚠️ لم يتم تحديد أي عائلة!")
            return
        delete_families(selected)
        context.user_data['selected_families_to_delete'] = []
        await query.message.edit_text(f"✅ تم مسح {len(selected)} عائلة بنجاح!")
        await start(update, context)

    elif data.startswith("family_"):
        family_id = int(data.split("_")[1])
        context.user_data['selected_family'] = family_id
        context.user_data['selected_passengers'] = []
        passengers = get_family_passengers(family_id)
        keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"toggle_{p['id']}")] for p in passengers]
        keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])
        keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])
        keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("delete_member_"):
        family_id = int(data.split("_")[2])
        context.user_data['delete_mode'] = 'member'
        context.user_data['selected_family'] = family_id
        passengers = get_family_passengers(family_id)
        if not passengers:
            await query.message.edit_text("⚠️ لا يوجد أفراد في هذه العائلة!")
            return
        context.user_data['selected_members_to_delete'] = []
        keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"del_member_{p['id']}")] for p in passengers]
        keyboard.append([InlineKeyboardButton("🗑️ مسح الأفراد المحددين", callback_data="confirm_delete_member")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر الأفراد المراد مسحهم:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("del_member_"):
        passenger_id = int(data.split("_")[2])
        selected = context.user_data.get('selected_members_to_delete', [])
        if passenger_id in selected:
            selected.remove(passenger_id)
        else:
            selected.append(passenger_id)
        context.user_data['selected_members_to_delete'] = selected
        
        family_id = context.user_data['selected_family']
        passengers = get_family_passengers(family_id)
        keyboard = []
        for p in passengers:
            is_selected = p['id'] in selected
            emoji = "✅" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(f"{emoji} {p['name']}", callback_data=f"del_member_{p['id']}")])
        keyboard.append([InlineKeyboardButton("🗑️ مسح الأفراد المحددين", callback_data="confirm_delete_member")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"✅ تم تحديد {len(selected)} فرد", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "confirm_delete_member":
        selected = context.user_data.get('selected_members_to_delete', [])
        if not selected:
            await query.message.edit_text("⚠️ لم يتم تحديد أي فرد!")
            return
        delete_passengers(selected)
        context.user_data['selected_members_to_delete'] = []
        await query.message.edit_text(f"✅ تم مسح {len(selected)} فرد بنجاح!")
        
        family_id = context.user_data['selected_family']
        passengers = get_family_passengers(family_id)
        keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"toggle_{p['id']}")] for p in passengers]
        keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])
        keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])
        keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("toggle_"):
        passenger_id = int(data.split("_")[1])
        selected = context.user_data.get('selected_passengers', [])
        
        p = None
        with get_db() as conn:
            if conn is not None:
                with conn.cursor(cursor_factory=DictCursor) as cur:
                    cur.execute("SELECT * FROM passengers WHERE id = %s", (passenger_id,))
                    row = cur.fetchone()
                    if row:
                        p = dict(row)
        
        if p:
            passenger_data = {'id': p['id'], 'name': p['name'], 'birth_date': p['birth_date']}
            if passenger_id in [sp['id'] for sp in selected]:
                selected = [sp for sp in selected if sp['id'] != passenger_id]
            else:
                selected.append(passenger_data)
            
            context.user_data['selected_passengers'] = selected
            family_id = context.user_data['selected_family']
            passengers = get_family_passengers(family_id)
            
            keyboard = []
            for p_item in passengers:
                is_selected = any(sp['id'] == p_item['id'] for sp in selected)
                emoji = "✅" if is_selected else "☐"
                keyboard.append([InlineKeyboardButton(f"{emoji} {p_item['name']}", callback_data=f"toggle_{p_item['id']}")])
            
            keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])
            keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])
            keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])
            keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(f"✅ تم تحديد {len(selected)} فرد", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "calculate_selected":
        selected = context.user_data.get('selected_passengers', [])
        if not selected:
            await query.message.edit_text("⚠️ لم يتم تحديد أي فرد!")
            return
        
        fare = get_fare_prices().get(context.user_data.get('selected_fare_code'))
        if not fare:
            await query.message.edit_text("⚠️ تعذر العثور على سعر هذه الرحلة. اختر الوجهة مرة أخرى.")
            return
        price_base = fare['base_price']
        rules = {
            "7-12": fare['price_7_12'],
            "13-26": fare['price_13_26'],
            "60-64": fare['price_60_64'],
            "+65": fare['price_65_plus'],
        }
        dest_name = context.user_data.get('selected_dest', 'غير محددة')
        
        today = date.today()
        results = []
        grand_total = 0
        
        for p in selected:
            try:
                dob = parse_birth_date(p['birth_date'])
                age = calculate_railway_age(dob, today)
                
                if age < 7:
                    results.append(f"👶 {p['name']} | {p['birth_date']} | العمر: {age} | **مجاناً** (لا يحتاج تذكرة)")
                    continue
                
                if 7 <= age <= 12:
                    price = rules.get("7-12", price_base)
                elif 13 <= age <= 26:
                    price = rules.get("13-26", price_base)
                elif 60 <= age <= 64:
                    price = rules.get("60-64", price_base)
                elif age >= 65:
                    price = rules.get("+65", price_base)
                else:
                    price = price_base
                
                final_price = price + OFFICE_PROFIT
                grand_total += final_price
                results.append(f"👤 {p['name']} | {p['birth_date']} | العمر: {age} | **{final_price}** ليرة")
            except:
                results.append(f"❌ {p['name']} - خطأ في التاريخ")
        
        response = f"📍 **الوجهة:** {dest_name}\n\n📊 **نتيجة الحساب**\n\n" + "\n".join(results)
        response += f"\n\n💰 **المجموع الكلي: {grand_total} ليرة تركي**"
        await query.message.edit_text(response, parse_mode='Markdown')

    elif data.startswith("add_member_"):
        family_id = int(data.split("_")[2])
        context.user_data['selected_family'] = family_id
        context.user_data['step'] = "add_member"
        await query.message.edit_text("👤 أدخل اسم الشخص + تاريخ الميلاد:\nمثال: `أحمد 15-05-1995` أو `أحمد 15/05/1995`")

    elif data == "back_to_family_list":
        context.user_data['step'] = "choose_family"
        families = get_user_families(user_id)
        keyboard = [[InlineKeyboardButton(f"👪 {f['family_name']}", callback_data=f"family_{f['id']}")] for f in families]
        keyboard.append([InlineKeyboardButton("🧮 حساب سريع بدون عائلة", callback_data="quick_calc")])
        keyboard.append([InlineKeyboardButton("➕ إنشاء عائلة جديدة", callback_data="new_family")])
        keyboard.append([InlineKeyboardButton("🗑️ مسح قيد العائلة", callback_data="delete_family")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_dest")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("👨‍👩‍👧‍👦 **اختر العائلة أو اختر الحساب السريع**:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "back_to_dest":
        await start(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get('step')
    user_id = update.effective_user.id

    if is_destination_request(text):
        context.user_data.pop('step', None)
        await start(update, context)
        return

    if step in ("admin_update_prices", "admin_update_one_price", "admin_add_fare"):
        if not is_admin(user_id):
            context.user_data.pop('step', None)
            await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
            return
        try:
            updates = parse_price_updates(text, allow_new=step == "admin_add_fare")
            if step in ("admin_update_one_price", "admin_add_fare") and len(updates) != 1:
                raise ValueError("هذا الأمر يقبل سطرًا واحدًا فقط")
            current_prices = get_fare_prices()
            preview = []
            for fare_code, prices in updates.items():
                old_price = current_prices.get(fare_code, {}).get('base_price', 'جديدة')
                category = fare_code.split('_')[1]
                preview.append(f"فئة {category}: {old_price} ← {prices['base_price']}")

            context.user_data['pending_price_updates'] = updates
            context.user_data['step'] = 'admin_confirm_price_updates'
            keyboard = [
                [InlineKeyboardButton("✅ تأكيد الحفظ", callback_data="confirm_price_updates")],
                [InlineKeyboardButton("✖️ إلغاء", callback_data="cancel_price_updates")],
            ]
            await update.message.reply_text(
                "📋 **معاينة التحديث**\n\n" + "\n".join(preview) +
                "\n\nهل تريد حفظ هذه الأسعار؟",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown',
            )
        except ValueError as error:
            await update.message.reply_text(
                f"❌ {error}\n\nأعد إرسال الجدول بالصيغة المطلوبة، أو استخدم /update_prices للبدء من جديد."
            )

    elif step == "admin_add_destination":
        if not is_admin(user_id):
            context.user_data.pop('step', None)
            return
        route_name = text.strip()
        if len(route_name) < 3:
            await update.message.reply_text("❌ اسم الوجهة قصير جدًا. أرسله مرة أخرى.")
            return
        route_id = create_route(route_name)
        if route_id:
            context.user_data.pop('step', None)
            await update.message.reply_text(
                f"✅ تمت إضافة وجهة **{route_name}**.\nاستخدم /add_trip لإضافة السعر والوقت.",
                parse_mode='Markdown',
            )
        else:
            await update.message.reply_text("⚠️ هذه الوجهة موجودة بالفعل، أو تعذر حفظها.")

    elif step == "admin_add_trip":
        if not is_admin(user_id):
            context.user_data.pop('step', None)
            return
        try:
            parts = [part.strip() for part in text.split('|')]
            if len(parts) != 3:
                raise ValueError("استخدم 3 قيم مفصولة بعلامة |")
            category, departure_label, service_label = parts
            category = category.replace('fare_', '')
            if not category.isdigit() or not departure_label:
                raise ValueError("رمز السعر والوقت مطلوبان")
            fare_code = f"fare_{category}"
            if fare_code not in get_fare_prices():
                raise ValueError(f"فئة السعر {category} غير موجودة. أضفها أولًا عبر /add_fare")
            service_types = {'بطيء': 'slow', 'slow': 'slow', 'سريع': 'fast', 'fast': 'fast', 'عادي': 'regular', 'regular': 'regular'}
            service_type = service_types.get(service_label.lower())
            if not service_type:
                raise ValueError("نوع القطار يجب أن يكون بطيء أو سريع أو عادي")
            route_id = context.user_data.get('selected_admin_route_id')
            if not route_id:
                raise ValueError("اختر الوجهة من جديد عبر /add_trip")
            trip_id = create_route_trip(route_id, fare_code, departure_label, service_type)
            if trip_id:
                await update.message.reply_text("✅ تمت إضافة الرحلة. يمكنك إرسال سطر رحلة آخر لنفس الوجهة، أو استخدام /add_trip لاختيار وجهة أخرى.")
            else:
                await update.message.reply_text("⚠️ هذه الرحلة موجودة بالفعل.")
        except ValueError as error:
            await update.message.reply_text(f"❌ {error}\nمثال: `535 | 01:28 | بطيء`", parse_mode='Markdown')

    elif step == "quick_calc":
        try:
            dob = parse_birth_date(text)
            birth_display = normalize_birth_date(text)
            today = date.today()
            age = calculate_railway_age(dob, today)
            
            fare = get_fare_prices().get(context.user_data.get('selected_fare_code'))
            if not fare:
                await update.message.reply_text("⚠️ تعذر العثور على سعر هذه الرحلة. اختر الوجهة مرة أخرى.")
                return
            price_base = fare['base_price']
            rules = {
                "7-12": fare['price_7_12'],
                "13-26": fare['price_13_26'],
                "60-64": fare['price_60_64'],
                "+65": fare['price_65_plus'],
            }
            dest_name = context.user_data.get('selected_dest', 'غير محددة')
            if age < 7:
                response = f"📍 **الوجهة:** {dest_name}\n\n📊 **نتيجة الحساب**\n\n"
                response += f"👶 زبون سريع | {birth_display} | العمر: {age} | **مجاناً** (لا يحتاج تذكرة)\n\n"
                response += f"💰 **المجموع الكلي: 0 ليرة تركي**"
            else:
                if 7 <= age <= 12:
                    price = rules.get("7-12", price_base)
                elif 13 <= age <= 26:
                    price = rules.get("13-26", price_base)
                elif 60 <= age <= 64:
                    price = rules.get("60-64", price_base)
                elif age >= 65:
                    price = rules.get("+65", price_base)
                else:
                    price = price_base
                
                final_price = price + OFFICE_PROFIT
                
                response = f"📍 **الوجهة:** {dest_name}\n\n📊 **نتيجة الحساب**\n\n"
                response += f"👤 زبون سريع | {birth_display} | العمر: {age} | **{final_price}** ليرة\n\n"
                response += f"💰 **المجموع الكلي: {final_price} ليرة تركي**"
            
            keyboard = [
                [InlineKeyboardButton("🧮 حساب تاريخ آخر", callback_data="quick_calc")],
                [InlineKeyboardButton("⬅️ عودة لقائمة العوائل", callback_data="back_to_family_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(response, reply_markup=reply_markup, parse_mode='Markdown')
            
        except ValueError:
            await update.message.reply_text("❌ التنسيق خاطئ! يرجى إدخال التاريخ بالطريقة التالية:\nمثال: `15-05-1995` أو `15/05/1995`")

    elif step == "create_family":
        family_id = create_family(user_id, text)
        if family_id:
            await update.message.reply_text(f"✅ تم إنشاء العائلة: **{text}**")
            context.user_data['selected_family'] = family_id
            context.user_data['step'] = "add_member"
            await update.message.reply_text("👤 أدخل اسم الشخص + تاريخ الميلاد:\nمثال: `أحمد 15-05-1995` أو `أحمد 15/05/1995`")
        else:
            await update.message.reply_text("❌ حدث خطأ أثناء إنشاء العائلة.")

    elif step == "add_member":
        try:
            name, birth_date_raw = text.rsplit(maxsplit=1)
            birth_date = normalize_birth_date(birth_date_raw)
            family_id = context.user_data['selected_family']
            add_passenger_to_family(family_id, user_id, name, birth_date)
            await update.message.reply_text(f"✅ تم إضافة **{name}**")
            
            passengers = get_family_passengers(family_id)
            keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"toggle_{p['id']}")] for p in passengers]
            keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])
            keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data="delete_member_" + str(family_id))])
            keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])
            keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')
        except:
            await update.message.reply_text("❌ التنسيق خاطئ\nمثال: أحمد 15-05-1995 أو أحمد 15/05/1995")
    else:
        await update.message.reply_text("⚠️ استخدم الأزرار أعلاه")

# ====================== تشغيل البوت والخدمات ======================
if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    
    # التهيئة المبدئية لقواعد البيانات عند تشغيل الملف
    if DATABASE_URL:
        init_db()
        init_fare_prices()
        init_route_data()
    else:
        logging.warning("⚠️ DATABASE_URL isn't set yet. DB setup will be deferred.")

    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        logging.error("❌ TELEGRAM_TOKEN environment variable is missing!")
    else:
        bot_app = Application.builder().token(TOKEN).build()

        # ====================== معالج أخطاء Telegram ======================
        async def error_handler(update, context):
            logging.error(f"Update {update} caused error {context.error}", exc_info=context.error)

        bot_app.add_error_handler(error_handler)

        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CommandHandler("update_prices", update_prices_command))
        bot_app.add_handler(CommandHandler("update_price", update_one_price_command))
        bot_app.add_handler(CommandHandler("add_destination", add_destination_command))
        bot_app.add_handler(CommandHandler("add_trip", add_trip_command))
        bot_app.add_handler(CommandHandler("add_fare", add_fare_command))
        bot_app.add_handler(CallbackQueryHandler(handle_callback))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        
        keep_alive()
        print("🚀 البوت يعمل الآن (مع دعم العمل بدون قاعدة بيانات عند انقطاعها)")
        bot_app.run_polling()
