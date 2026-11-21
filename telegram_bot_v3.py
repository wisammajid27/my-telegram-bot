#!/usr/bin/env python3
"""
Telegram Bot - Complete Version with PostgreSQL Support (Optimized)
+ Export / Import (backup & restore) for saved data
"""
import os
import re
import json
import logging
import calendar
import threading
from io import BytesIO
from datetime import date, datetime
from flask import Flask
from threading import Thread
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import DictCursor
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
    BotCommand, BotCommandScopeChat,
)
from telegram.error import BadRequest
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
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
DB_AVAILABLE = True  # يتحدث تلقائياً حسب حالة الاتصال

_POOL = None
_POOL_LOCK = threading.Lock()

def _get_pool():
    """مجمع اتصالات بدل فتح اتصال SSL جديد مع كل استعلام."""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = pg_pool.ThreadedConnectionPool(
                    1, 5, DATABASE_URL, sslmode=DB_SSLMODE, connect_timeout=5
                )
    return _POOL

def _acquire_connection():
    """يجيب اتصال سليم من المجمع، ويتخلص من الاتصالات الميتة (اللي يقطعها السيرفر بعد الخمول)."""
    pool = _get_pool()
    for _ in range(2):
        conn = pool.getconn()
        try:
            if not conn.closed:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.rollback()
                return pool, conn
        except Exception:
            pass
        pool.putconn(conn, close=True)
    raise psycopg2.OperationalError("could not obtain a healthy database connection")

@contextmanager
def get_db():
    """إدارة اتصال قاعدة البيانات بشكل آمن. يرجع None لو فشل الاتصال بدل ما ينهار البوت.

    ملاحظة: الأخطاء اللي تصير داخل بلوك with (بعد نجاح الاتصال) ترتفع للمستدعي كما هي،
    ولا تُعامل كأن القاعدة غير متاحة.
    """
    global DB_AVAILABLE
    if not DATABASE_URL:
        DB_AVAILABLE = False
        yield None
        return

    try:
        pool, conn = _acquire_connection()
    except Exception as e:
        DB_AVAILABLE = False
        logging.warning(f"Database unavailable (will use static data): {e}")
        yield None
        return

    DB_AVAILABLE = True
    broken = False
    try:
        yield conn
    except Exception as e:
        logging.error(f"Database error: {e}")
        raise
    finally:
        try:
            if not conn.closed:
                conn.rollback()  # ما نرجع اتصال بمعاملة مفتوحة للمجمع
        except Exception:
            broken = True
        pool.putconn(conn, close=broken or bool(conn.closed))

def db_is_up() -> bool:
    with get_db() as conn:
        return conn is not None

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
                cur.execute("CREATE INDEX IF NOT EXISTS idx_families_user ON families (user_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_family ON passengers (family_id)")
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
    "اسكي شهير - اسطنبول بوستانجة": [
        {"price": 535, "times": ["01:28"], "slow": True},
        {"price": 645, "times": ["باقي الاوقات"], "fast": True},
    ],
    "اسطنبول بوستانجة - اسكي شهير": [
        {"price": 535, "times": ["22:59"], "slow": True},
        {"price": 645, "times": ["باقي الاوقات"], "fast": True},
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

SERVICE_TYPES = {'slow', 'fast', 'regular'}
MAX_NAME_LENGTH = 100

def fare_code_from_original_price(original_price: int) -> str:
    return f"fare_{original_price}"

def md(value) -> str:
    """تهريب رموز Markdown حتى لا تكسر الأسماء (مثل علي_حسن) رسائل البوت."""
    text = str(value)
    for ch in ('_', '*', '`', '['):
        text = text.replace(ch, '\\' + ch)
    return text

def static_fare_prices():
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

def init_fare_prices():
    try:
        with get_db() as conn:
            if conn is None:
                logging.warning("Skipping init_fare_prices: database unavailable")
                return
            with conn.cursor() as cur:
                for fare_code, fare in static_fare_prices().items():
                    cur.execute('''
                        INSERT INTO fare_prices
                            (fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (fare_code) DO NOTHING
                    ''', (
                        fare_code, fare['base_price'], fare['price_7_12'], fare['price_13_26'],
                        fare['price_60_64'], fare['price_65_plus'], datetime.now().isoformat(),
                    ))
                conn.commit()
    except Exception as e:
        logging.error(f"Failed to init fare prices: {e}")

def get_fare_prices():
    """يرجع الأسعار من قاعدة البيانات، ولو فشلت يرجع من PRICES_RULES الثابتة"""
    with get_db() as conn:
        if conn is None:
            return static_fare_prices()
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus
                FROM fare_prices
            ''')
            rows = cur.fetchall()
            if rows:
                return {row['fare_code']: dict(row) for row in rows}
            return static_fare_prices()

def save_fare_prices(updates) -> bool:
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot save fare prices: database unavailable")
            return False
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
            return True

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
                                ON CONFLICT DO NOTHING
                            ''', (route_id, fare_code, departure_label, service_type, datetime.now().isoformat()))
                conn.commit()
    except Exception as e:
        logging.error(f"Failed to init routes: {e}")

# أرقام الوجهات الثابتة تبدأ من 1 حتى تطابق أرقام SERIAL بالقاعدة
# (لو انقطعت القاعدة والمستخدم ضغط زر قديم يوصل لنفس الوجهة)
def static_routes():
    return [{'id': idx + 1, 'route_name': name} for idx, name in enumerate(ROUTES.keys())]

def get_routes():
    """يرجع الوجهات من قاعدة البيانات، ولو فشلت يرجع من البيانات الثابتة ROUTES"""
    with get_db() as conn:
        if conn is None:
            return static_routes()
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, route_name FROM travel_routes ORDER BY sort_order, id")
            rows = cur.fetchall()
            if rows:
                return [dict(row) for row in rows]
            return static_routes()

def get_route(route_id):
    with get_db() as conn:
        if conn is None:
            names = list(ROUTES.keys())
            if 1 <= route_id <= len(names):
                return {'id': route_id, 'route_name': names[route_id - 1]}
            return None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, route_name FROM travel_routes WHERE id = %s", (route_id,))
            row = cur.fetchone()
            return dict(row) if row else None

def get_route_trips(route_id):
    with get_db() as conn:
        if conn is None:
            names = list(ROUTES.keys())
            if not (1 <= route_id <= len(names)):
                return []
            groups = ROUTES.get(names[route_id - 1], [])
            result = []
            for group in groups:
                service_type = 'fast' if group.get('fast') else 'slow' if group.get('slow') else 'regular'
                result.append({
                    'fare_code': fare_code_from_original_price(group['price']),
                    'service_type': service_type,
                    'times': group['times'],
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

ADMIN_ONLY_TEXT = "⛔ هذا الأمر مخصص لمدير البوت فقط."

async def update_prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return

    context.user_data['step'] = 'admin_update_prices'
    await update.message.reply_text(
        "💼 *تحديث الأسعار دفعة واحدة*\n\n"
        "يمكنك إرسال سطر واحد أو عدة أسطر؛ كل سطر يحدّث فئة واحدة بهذا الترتيب:\n"
        "`رمز الفئة | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "رمز الفئة هو الرقم الأول الثابت، حتى إذا تغير السعر الكامل لاحقًا.\n"
        "انسخ الجدول التالي وعدّل الأرقام فقط، ثم أرسله:\n\n"
        f"```\n{price_update_template()}\n```",
        parse_mode='Markdown',
    )

async def update_one_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return

    context.user_data['step'] = 'admin_update_one_price'
    await update.message.reply_text(
        "💼 *تحديث فئة سعر واحدة*\n\n"
        "أرسل سطرًا واحدًا فقط بهذا الترتيب:\n"
        "`رمز الفئة | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "مثال لتحديث فئة 370:\n"
        "`370 | 400 | 200 | 340 | 340 | 200`\n\n"
        "رمز الفئة هو الرقم الأول الأصلي، وليس السعر الجديد.",
        parse_mode='Markdown',
    )

async def add_destination_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return
    context.user_data['step'] = 'admin_add_destination'
    await update.message.reply_text("🗺️ أرسل اسم الوجهة الجديدة، مثال:\n`انقرة - قونية`", parse_mode='Markdown')

async def add_trip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return
    routes = get_routes()
    keyboard = [[InlineKeyboardButton(route['route_name'], callback_data=f"admin_trip_route_{route['id']}")]
                for route in routes]
    context.user_data['step'] = 'admin_select_trip_route'
    await update.message.reply_text("🚆 اختر الوجهة التي تريد إضافة رحلة لها:", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_fare_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
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
        fare_code = f"fare_{int(category)}"
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

# ====================== التواريخ والأعمار والأسعار ======================
BIRTH_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")

def parse_birth_date(date_str: str) -> datetime:
    date_str = str(date_str).strip()
    for fmt in BIRTH_DATE_FORMATS:
        try:
            parsed = datetime.strptime(date_str, fmt)
        except ValueError:
            continue
        if parsed.year < 1900 or parsed.date() > date.today():
            raise ValueError("birth date out of range")
        return parsed
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

def ticket_price_for_age(fare: dict, age: int):
    """يرجع السعر النهائي مع ربح المكتب، أو None إذا الطفل مجاني (أقل من 7)."""
    if age < 7:
        return None
    if 7 <= age <= 12:
        price = fare['price_7_12']
    elif 13 <= age <= 26:
        price = fare['price_13_26']
    elif 60 <= age <= 64:
        price = fare['price_60_64']
    elif age >= 65:
        price = fare['price_65_plus']
    else:
        price = fare['base_price']
    return price + OFFICE_PROFIT

def passenger_price_line(fare: dict, name: str, birth_display: str, age: int):
    """يرجع (سطر النتيجة، المبلغ)."""
    final_price = ticket_price_for_age(fare, age)
    if final_price is None:
        return f"👶 {md(name)} | {birth_display} | العمر: {age} | *مجاناً* (لا يحتاج تذكرة)", 0
    return f"👤 {md(name)} | {birth_display} | العمر: {age} | *{final_price}* ليرة", final_price

def format_time_with_period(time_str: str) -> str:
    try:
        hour = int(time_str.split(':')[0])
    except (ValueError, AttributeError):
        return time_str
    if 6 <= hour <= 11: period = "ص"
    elif 12 <= hour <= 15: period = "ظ"
    elif 16 <= hour <= 17: period = "ع"
    elif 18 <= hour <= 19: period = "م"
    else: period = "ل"
    return f"{time_str} {period}"

def split_name_and_date(text: str):
    """يفصل 'الاسم تاريخ_الميلاد' ويرجع (الاسم، التاريخ الموحّد، كائن التاريخ)."""
    parts = text.strip().rsplit(maxsplit=1)
    if len(parts) != 2:
        raise ValueError("name and date required")
    name, birth_raw = parts[0].strip(), parts[1]
    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValueError("invalid name")
    dob = parse_birth_date(birth_raw)
    return name, dob.strftime("%d-%m-%Y"), dob

# ====================== العوائل والمسافرين (مع التحقق من الملكية) ======================
def get_user_families(user_id):
    with get_db() as conn:
        if conn is None:
            return []
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM families WHERE user_id = %s ORDER BY family_name", (user_id,))
            return [dict(row) for row in cur.fetchall()]

def get_family(user_id, family_id):
    """يرجع العائلة فقط إذا كانت ملك هذا المستخدم."""
    with get_db() as conn:
        if conn is None:
            return None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM families WHERE id = %s AND user_id = %s", (family_id, user_id))
            row = cur.fetchone()
            return dict(row) if row else None

def get_family_passengers(family_id):
    with get_db() as conn:
        if conn is None:
            return []
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM passengers WHERE family_id = %s ORDER BY name, id", (family_id,))
            return [dict(row) for row in cur.fetchall()]

def get_passenger(user_id, passenger_id):
    with get_db() as conn:
        if conn is None:
            return None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT p.* FROM passengers p
                JOIN families f ON f.id = p.family_id
                WHERE p.id = %s AND f.user_id = %s
            ''', (passenger_id, user_id))
            row = cur.fetchone()
            return dict(row) if row else None

def create_family(user_id, family_name):
    """يرجع (رقم العائلة، هل_جديدة). يرجع (None, False) إذا القاعدة غير متاحة."""
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot create family: database unavailable")
            return None, False
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM families WHERE user_id = %s AND family_name = %s LIMIT 1",
                        (user_id, family_name))
            existing = cur.fetchone()
            if existing:
                return existing[0], False
            cur.execute("INSERT INTO families (user_id, family_name, created_at) VALUES (%s, %s, %s) RETURNING id",
                        (user_id, family_name, datetime.now().isoformat()))
            family_id = cur.fetchone()[0]
            conn.commit()
            return family_id, True

def add_passenger_to_family(family_id, user_id, name, birth_date) -> bool:
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot add passenger: database unavailable")
            return False
        with conn.cursor() as cur:
            cur.execute("INSERT INTO passengers (family_id, user_id, name, birth_date, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (family_id, user_id, name, birth_date, datetime.now().isoformat()))
            conn.commit()
            return True

def delete_families(user_id, family_ids) -> int:
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot delete families: database unavailable")
            return 0
        with conn.cursor() as cur:
            cur.execute('''
                DELETE FROM passengers
                WHERE family_id IN (SELECT id FROM families WHERE id = ANY(%s) AND user_id = %s)
            ''', (list(family_ids), user_id))
            cur.execute("DELETE FROM families WHERE id = ANY(%s) AND user_id = %s", (list(family_ids), user_id))
            deleted = cur.rowcount
            conn.commit()
            return deleted

def delete_passengers(user_id, family_id, passenger_ids) -> int:
    with get_db() as conn:
        if conn is None:
            logging.warning("Cannot delete passengers: database unavailable")
            return 0
        with conn.cursor() as cur:
            cur.execute('''
                DELETE FROM passengers
                WHERE id = ANY(%s) AND family_id = %s
                  AND family_id IN (SELECT id FROM families WHERE user_id = %s)
            ''', (list(passenger_ids), family_id, user_id))
            deleted = cur.rowcount
            conn.commit()
            return deleted

# ====================== التصدير والاستيراد ======================
BACKUP_FORMAT = "ticket_bot_backup"
BACKUP_VERSION = 1
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_FAMILIES = 2000
MAX_PASSENGERS_PER_FAMILY = 300
FARE_CODE_RE = re.compile(r"^fare_\d+$")

def _families_with_passengers(cur, family_rows, include_user_id):
    family_ids = [row['id'] for row in family_rows]
    passengers_by_family = {}
    if family_ids:
        cur.execute('''
            SELECT family_id, name, birth_date FROM passengers
            WHERE family_id = ANY(%s) ORDER BY name, id
        ''', (family_ids,))
        for row in cur.fetchall():
            passengers_by_family.setdefault(row['family_id'], []).append(
                {'name': row['name'], 'birth_date': row['birth_date']}
            )
    result = []
    for row in family_rows:
        item = {'family_name': row['family_name'], 'passengers': passengers_by_family.get(row['id'], [])}
        if include_user_id:
            item = {'user_id': row['user_id'], **item}
        result.append(item)
    return result

def build_user_export(user_id):
    """نسخة عوائل المستخدم فقط. يرجع None إذا القاعدة غير متاحة."""
    with get_db() as conn:
        if conn is None:
            return None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, user_id, family_name FROM families WHERE user_id = %s ORDER BY family_name, id",
                        (user_id,))
            families = _families_with_passengers(cur, cur.fetchall(), include_user_id=False)
    return {
        'format': BACKUP_FORMAT,
        'version': BACKUP_VERSION,
        'type': 'families',
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'families': families,
    }

def build_full_export():
    """نسخة كاملة (للمدير): الأسعار + الوجهات والرحلات + عوائل كل المستخدمين."""
    with get_db() as conn:
        if conn is None:
            return None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus
                FROM fare_prices ORDER BY base_price, fare_code
            ''')
            fare_prices = [dict(row) for row in cur.fetchall()]

            cur.execute("SELECT id, route_name, sort_order FROM travel_routes ORDER BY sort_order, id")
            routes = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT route_id, fare_code, departure_label, service_type FROM route_trips ORDER BY id")
            trips_by_route = {}
            for row in cur.fetchall():
                trips_by_route.setdefault(row['route_id'], []).append({
                    'fare_code': row['fare_code'],
                    'departure_label': row['departure_label'],
                    'service_type': row['service_type'],
                })
            routes = [
                {'route_name': r['route_name'], 'sort_order': r['sort_order'], 'trips': trips_by_route.get(r['id'], [])}
                for r in routes
            ]

            cur.execute("SELECT id, user_id, family_name FROM families ORDER BY user_id, family_name, id")
            families = _families_with_passengers(cur, cur.fetchall(), include_user_id=True)
    return {
        'format': BACKUP_FORMAT,
        'version': BACKUP_VERSION,
        'type': 'full',
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'fare_prices': fare_prices,
        'routes': routes,
        'families': families,
    }

def backup_to_file(payload, filename):
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    return InputFile(BytesIO(data), filename=filename)

def _clean_text(value, field, max_len=MAX_NAME_LENGTH, min_len=1):
    if not isinstance(value, str):
        raise ValueError(f"الحقل «{field}» يجب أن يكون نصًا")
    value = value.strip()
    if not (min_len <= len(value) <= max_len):
        raise ValueError(f"طول الحقل «{field}» غير صالح: {value[:30]}")
    return value

def _clean_int(value, field, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"الحقل «{field}» يجب أن يكون رقمًا صحيحًا ≥ {minimum}")
    return value

def validate_backup(payload, allow_full: bool, existing_fare_codes=()):
    """يتحقق من ملف النسخة ويرجع نسخة نظيفة جاهزة للاستيراد، أو يرفع ValueError برسالة واضحة."""
    if not isinstance(payload, dict) or payload.get('format') != BACKUP_FORMAT:
        raise ValueError("هذا الملف ليس نسخة احتياطية من هذا البوت")
    version = payload.get('version')
    if not isinstance(version, int) or version > BACKUP_VERSION:
        raise ValueError("إصدار الملف غير مدعوم")
    backup_type = payload.get('type')
    if backup_type not in ('families', 'full'):
        raise ValueError("نوع النسخة غير معروف")
    if backup_type == 'full' and not allow_full:
        raise ValueError("هذه نسخة كاملة، واستيرادها مخصص لمدير البوت فقط")

    families_raw = payload.get('families', [])
    if not isinstance(families_raw, list):
        raise ValueError("قائمة العوائل غير صالحة")
    if len(families_raw) > MAX_IMPORT_FAMILIES:
        raise ValueError(f"عدد العوائل أكبر من الحد المسموح ({MAX_IMPORT_FAMILIES})")

    families = []
    for fam in families_raw:
        if not isinstance(fam, dict):
            raise ValueError("بيانات عائلة غير صالحة")
        family_name = _clean_text(fam.get('family_name'), 'اسم العائلة')
        passengers_raw = fam.get('passengers', [])
        if not isinstance(passengers_raw, list) or len(passengers_raw) > MAX_PASSENGERS_PER_FAMILY:
            raise ValueError(f"قائمة أفراد العائلة «{family_name}» غير صالحة")
        passengers = []
        for p in passengers_raw:
            if not isinstance(p, dict):
                raise ValueError(f"بيانات فرد غير صالحة في عائلة «{family_name}»")
            name = _clean_text(p.get('name'), 'اسم الفرد')
            try:
                birth_date = normalize_birth_date(p.get('birth_date', ''))
            except ValueError:
                raise ValueError(f"تاريخ ميلاد غير صالح للفرد «{name}» في عائلة «{family_name}»")
            passengers.append({'name': name, 'birth_date': birth_date})
        item = {'family_name': family_name, 'passengers': passengers}
        if backup_type == 'full':
            item['user_id'] = _clean_int(fam.get('user_id'), 'user_id', minimum=1)
        families.append(item)

    clean = {'type': backup_type, 'families': families, 'fare_prices': [], 'routes': []}
    if backup_type == 'families':
        return clean

    fare_codes = set(existing_fare_codes)
    for fare in payload.get('fare_prices', []) or []:
        if not isinstance(fare, dict):
            raise ValueError("بيانات سعر غير صالحة")
        code = fare.get('fare_code')
        if not isinstance(code, str) or not FARE_CODE_RE.match(code):
            raise ValueError(f"رمز فئة غير صالح: {code}")
        values = {k: _clean_int(fare.get(k), k) for k in
                  ('base_price', 'price_7_12', 'price_13_26', 'price_60_64', 'price_65_plus')}
        if values['base_price'] == 0:
            raise ValueError(f"السعر الكامل لفئة {code} يجب أن يكون أكبر من صفر")
        clean['fare_prices'].append({'fare_code': code, **values})
        fare_codes.add(code)

    for route in payload.get('routes', []) or []:
        if not isinstance(route, dict):
            raise ValueError("بيانات وجهة غير صالحة")
        route_name = _clean_text(route.get('route_name'), 'اسم الوجهة', min_len=3)
        sort_order = route.get('sort_order', 0)
        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            sort_order = 0
        trips = []
        for trip in route.get('trips', []) or []:
            if not isinstance(trip, dict):
                raise ValueError(f"بيانات رحلة غير صالحة في «{route_name}»")
            code = trip.get('fare_code')
            if code not in fare_codes:
                raise ValueError(f"الرحلة في «{route_name}» تستخدم فئة سعر غير موجودة: {code}")
            service_type = trip.get('service_type')
            if service_type not in SERVICE_TYPES:
                raise ValueError(f"نوع قطار غير صالح في «{route_name}»")
            label = _clean_text(trip.get('departure_label'), 'وقت الرحلة', max_len=50)
            trips.append({'fare_code': code, 'departure_label': label, 'service_type': service_type})
        clean['routes'].append({'route_name': route_name, 'sort_order': sort_order, 'trips': trips})
    return clean

def import_summary(clean) -> str:
    passengers = sum(len(f['passengers']) for f in clean['families'])
    lines = [f"👪 العوائل: {len(clean['families'])}", f"👤 الأفراد: {passengers}"]
    if clean['type'] == 'full':
        trips = sum(len(r['trips']) for r in clean['routes'])
        users = len({f['user_id'] for f in clean['families']})
        lines += [
            f"👥 المستخدمون: {users}",
            f"💰 فئات الأسعار: {len(clean['fare_prices'])}",
            f"🗺️ الوجهات: {len(clean['routes'])}",
            f"🚆 الرحلات: {trips}",
        ]
    return "\n".join(lines)

def apply_import(target_user_id, clean):
    """يطبّق الاستيراد كمعاملة واحدة (يا ينجح كله يا ما يتغير شي).

    - العوائل تُدمج: إذا عائلة بنفس الاسم موجودة نضيف لها الأفراد الناقصين فقط.
    - الفرد المكرر (نفس الاسم ونفس تاريخ الميلاد) يتم تجاهله.
    - في النسخة الكاملة: أسعار الملف تستبدل الأسعار الحالية، والوجهات والرحلات الناقصة تُضاف.
    يرجع قاموس إحصائيات، أو None إذا القاعدة غير متاحة.
    """
    stats = {'families_new': 0, 'passengers_new': 0, 'passengers_skipped': 0,
             'fares': 0, 'routes_new': 0, 'trips_new': 0}
    now = datetime.now().isoformat()
    with get_db() as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            if clean['type'] == 'full':
                for fare in clean['fare_prices']:
                    cur.execute('''
                        INSERT INTO fare_prices
                            (fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (fare_code) DO UPDATE SET
                            base_price = EXCLUDED.base_price, price_7_12 = EXCLUDED.price_7_12,
                            price_13_26 = EXCLUDED.price_13_26, price_60_64 = EXCLUDED.price_60_64,
                            price_65_plus = EXCLUDED.price_65_plus, updated_at = EXCLUDED.updated_at
                    ''', (fare['fare_code'], fare['base_price'], fare['price_7_12'], fare['price_13_26'],
                          fare['price_60_64'], fare['price_65_plus'], now))
                    stats['fares'] += 1

                for route in clean['routes']:
                    cur.execute('''
                        INSERT INTO travel_routes (route_name, sort_order, created_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (route_name) DO NOTHING
                        RETURNING id
                    ''', (route['route_name'], route['sort_order'], now))
                    row = cur.fetchone()
                    if row:
                        route_id = row[0]
                        stats['routes_new'] += 1
                    else:
                        cur.execute("SELECT id FROM travel_routes WHERE route_name = %s", (route['route_name'],))
                        route_id = cur.fetchone()[0]
                    for trip in route['trips']:
                        cur.execute('''
                            INSERT INTO route_trips (route_id, fare_code, departure_label, service_type, created_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (route_id, fare_code, departure_label, service_type) DO NOTHING
                            RETURNING id
                        ''', (route_id, trip['fare_code'], trip['departure_label'], trip['service_type'], now))
                        if cur.fetchone():
                            stats['trips_new'] += 1

            for fam in clean['families']:
                owner_id = fam['user_id'] if clean['type'] == 'full' else target_user_id
                cur.execute("SELECT id FROM families WHERE user_id = %s AND family_name = %s ORDER BY id LIMIT 1",
                            (owner_id, fam['family_name']))
                row = cur.fetchone()
                if row:
                    family_id = row[0]
                else:
                    cur.execute("INSERT INTO families (user_id, family_name, created_at) VALUES (%s, %s, %s) RETURNING id",
                                (owner_id, fam['family_name'], now))
                    family_id = cur.fetchone()[0]
                    stats['families_new'] += 1

                cur.execute("SELECT name, birth_date FROM passengers WHERE family_id = %s", (family_id,))
                existing = {(r[0], r[1]) for r in cur.fetchall()}
                for p in fam['passengers']:
                    key = (p['name'], p['birth_date'])
                    if key in existing:
                        stats['passengers_skipped'] += 1
                        continue
                    cur.execute('''
                        INSERT INTO passengers (family_id, user_id, name, birth_date, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (family_id, owner_id, p['name'], p['birth_date'], now))
                    existing.add(key)
                    stats['passengers_new'] += 1
            conn.commit()
    return stats

def import_stats_text(stats, backup_type) -> str:
    lines = [
        "✅ *تم الاستيراد بنجاح*\n",
        f"👪 عوائل جديدة: {stats['families_new']}",
        f"👤 أفراد جدد: {stats['passengers_new']}",
    ]
    if stats['passengers_skipped']:
        lines.append(f"↩️ أفراد موجودون مسبقًا (تم تجاهلهم): {stats['passengers_skipped']}")
    if backup_type == 'full':
        lines += [
            f"💰 فئات أسعار محدّثة: {stats['fares']}",
            f"🗺️ وجهات جديدة: {stats['routes_new']}",
            f"🚆 رحلات جديدة: {stats['trips_new']}",
        ]
    return "\n".join(lines)

def export_filename(prefix):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"

async def send_user_export(message, user_id):
    payload = build_user_export(user_id)
    if payload is None:
        await message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، حاول لاحقاً.")
        return
    if not payload['families']:
        await message.reply_text("ℹ️ لا توجد عوائل محفوظة لتصديرها.")
        return
    passengers = sum(len(f['passengers']) for f in payload['families'])
    await message.reply_document(
        document=backup_to_file(payload, export_filename("families")),
        caption=(f"📦 نسخة العوائل\n👪 {len(payload['families'])} عائلة | 👤 {passengers} فرد\n\n"
                 "احتفظ بهذا الملف، ويمكنك إرجاعه في أي وقت عبر /import"),
    )

async def send_full_export(message):
    payload = build_full_export()
    if payload is None:
        await message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، حاول لاحقاً.")
        return
    passengers = sum(len(f['passengers']) for f in payload['families'])
    trips = sum(len(r['trips']) for r in payload['routes'])
    await message.reply_document(
        document=backup_to_file(payload, export_filename("full_backup")),
        caption=(f"🗄️ نسخة احتياطية كاملة\n"
                 f"💰 {len(payload['fare_prices'])} فئة سعر | 🗺️ {len(payload['routes'])} وجهة | 🚆 {trips} رحلة\n"
                 f"👪 {len(payload['families'])} عائلة | 👤 {passengers} فرد"),
    )

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("👪 تصدير عوائلي فقط", callback_data="export_mine")],
            [InlineKeyboardButton("🗄️ نسخة احتياطية كاملة", callback_data="export_full")],
        ]
        await update.message.reply_text("📦 ماذا تريد أن تصدّر؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    await send_user_export(update.message, user_id)

async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db_is_up():
        await update.message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، لا يمكن الاستيراد الآن.")
        return
    context.user_data.pop('pending_import', None)
    context.user_data['step'] = 'await_import'
    text = (
        "📥 *استيراد البيانات*\n\n"
        "أرسل الآن ملف النسخة (`.json`) الذي حصلت عليه من /export.\n\n"
        "• العوائل الموجودة بنفس الاسم سيُضاف إليها الأفراد الناقصون فقط.\n"
        "• الأفراد المكررون (نفس الاسم وتاريخ الميلاد) سيتم تجاهلهم.\n"
        "• لن يُحذف أي شيء من بياناتك الحالية."
    )
    if is_admin(update.effective_user.id):
        text += "\n\n🛡️ يمكنك أيضاً إرسال نسخة كاملة؛ أسعارها ستستبدل الأسعار الحالية."
    text += "\n\nللإلغاء أرسل /cancel"
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get('step') != 'await_import':
        await update.message.reply_text("ℹ️ لاستيراد ملف نسخة احتياطية استخدم /import أولاً.")
        return

    doc = update.message.document
    file_name = (doc.file_name or "").lower()
    if not file_name.endswith('.json'):
        await update.message.reply_text("❌ يجب أن يكون الملف بصيغة .json")
        return
    if doc.file_size and doc.file_size > MAX_IMPORT_BYTES:
        await update.message.reply_text("❌ حجم الملف أكبر من الحد المسموح (2 ميغابايت).")
        return

    try:
        tg_file = await doc.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError("حجم الملف أكبر من الحد المسموح (2 ميغابايت)")
        try:
            payload = json.loads(raw.decode('utf-8-sig'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("الملف تالف أو ليس ملف JSON صالحاً")
        clean = validate_backup(payload, allow_full=is_admin(user_id),
                                existing_fare_codes=get_fare_prices().keys())
    except ValueError as error:
        await update.message.reply_text(f"❌ {error}\n\nأرسل ملفاً آخر، أو /cancel للإلغاء.")
        return

    if not clean['families'] and clean['type'] == 'families':
        await update.message.reply_text("ℹ️ الملف لا يحتوي على أي عائلة.")
        return

    context.user_data['pending_import'] = clean
    context.user_data['step'] = 'confirm_import'
    title = "🗄️ نسخة كاملة" if clean['type'] == 'full' else "👪 نسخة عوائل"
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد الاستيراد", callback_data="import_confirm")],
        [InlineKeyboardButton("✖️ إلغاء", callback_data="import_cancel")],
    ]
    await update.message.reply_text(
        f"📋 *معاينة الاستيراد* ({title})\n\n{import_summary(clean)}\n\nهل تريد المتابعة؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown',
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for key in ('step', 'pending_import', 'pending_price_updates'):
        context.user_data.pop(key, None)
    await update.message.reply_text("تم الإلغاء. أرسل /start للبدء من جديد.")

# ====================== واجهات الأزرار ======================
FAMILY_LIST_TEXT = "👨‍👩‍👧‍👦 *اختر العائلة أو اختر الحساب السريع*:"

def family_list_markup(user_id):
    families = get_user_families(user_id)
    keyboard = [[InlineKeyboardButton(f"👪 {f['family_name']}", callback_data=f"family_{f['id']}")] for f in families]
    keyboard.append([InlineKeyboardButton("🧮 حساب سريع بدون عائلة", callback_data="quick_calc")])
    keyboard.append([InlineKeyboardButton("➕ إنشاء عائلة جديدة", callback_data="new_family")])
    if families:
        keyboard.append([InlineKeyboardButton("🗑️ مسح قيد العائلة", callback_data="delete_family")])
    keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_dest")])
    return InlineKeyboardMarkup(keyboard)

def family_members_markup(family_id, selected_ids):
    keyboard = []
    for p in get_family_passengers(family_id):
        mark = "✅" if p['id'] in selected_ids else "☐"
        keyboard.append([InlineKeyboardButton(f"{mark} {p['name']}", callback_data=f"toggle_{p['id']}")])
    keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])
    keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])
    keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])
    keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
    return InlineKeyboardMarkup(keyboard)

def delete_members_markup(family_id, selected_ids):
    keyboard = []
    for p in get_family_passengers(family_id):
        mark = "✅" if p['id'] in selected_ids else "☐"
        keyboard.append([InlineKeyboardButton(f"{mark} {p['name']}", callback_data=f"del_member_{p['id']}")])
    keyboard.append([InlineKeyboardButton("🗑️ مسح الأفراد المحددين", callback_data="confirm_delete_member")])
    keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data=f"family_{family_id}")])
    return InlineKeyboardMarkup(keyboard)

def delete_families_markup(user_id, selected_ids):
    keyboard = []
    for f in get_user_families(user_id):
        mark = "✅" if f['id'] in selected_ids else "☐"
        keyboard.append([InlineKeyboardButton(f"{mark} {f['family_name']}", callback_data=f"del_family_{f['id']}")])
    keyboard.append([InlineKeyboardButton("🗑️ مسح العائلات المحددة", callback_data="confirm_delete_family")])
    keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
    return InlineKeyboardMarkup(keyboard)

def family_header(family) -> str:
    return f"👪 *{md(family['family_name'])}*\n\n"

def callback_int(data: str) -> int | None:
    try:
        return int(data.rsplit('_', 1)[1])
    except (ValueError, IndexError):
        return None

async def safe_edit(query, text, **kwargs):
    """تعديل الرسالة مع تجاهل خطأ 'message is not modified' اللي يصير عند الضغط المكرر."""
    try:
        await query.message.edit_text(text, **kwargs)
    except BadRequest as error:
        if 'not modified' not in str(error).lower():
            raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    routes = get_routes()
    keyboard = [[InlineKeyboardButton(route['route_name'], callback_data=f"dest_{route['id']}")]
                for route in routes]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🚍 *مرحباً بك في بوت حجز التذاكر*\n\n🗂️ اختر الوجهة المطلوبة:"
    if not DB_AVAILABLE:
        text += "\n\n⚠️ _قاعدة البيانات غير متاحة حالياً — يعمل البوت بالبيانات الأساسية. حفظ العائلات غير متوفر مؤقتاً._"

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await safe_edit(update.callback_query, text, reply_markup=reply_markup, parse_mode='Markdown')

def is_destination_request(text: str) -> bool:
    normalized = text.strip().replace("ـ", "")
    return normalized in {"وجهة", "الوجهة"}

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data or ""
    ud = context.user_data

    # ---------- التصدير والاستيراد ----------
    if data == "export_mine":
        await send_user_export(query.message, user_id)

    elif data == "export_full":
        if not is_admin(user_id):
            return
        await send_full_export(query.message)

    elif data == "import_confirm":
        clean = ud.get('pending_import')
        if not clean:
            await safe_edit(query, "⚠️ انتهت جلسة الاستيراد. استخدم /import مرة أخرى.")
            return
        if clean['type'] == 'full' and not is_admin(user_id):
            return
        try:
            stats = apply_import(user_id, clean)
        except Exception as error:
            logging.exception(f"Import failed: {error}")
            await safe_edit(query, "❌ فشل الاستيراد ولم يتم تغيير أي بيانات. حاول مرة أخرى.")
            return
        if stats is None:
            await safe_edit(query, "⚠️ قاعدة البيانات غير متاحة حالياً. لم يتم الاستيراد.")
            return
        ud.pop('pending_import', None)
        ud.pop('step', None)
        await safe_edit(query, import_stats_text(stats, clean['type']), parse_mode='Markdown')

    elif data == "import_cancel":
        ud.pop('pending_import', None)
        ud.pop('step', None)
        await safe_edit(query, "تم إلغاء الاستيراد.")

    # ---------- أوامر المدير ----------
    elif data == "confirm_price_updates":
        if not is_admin(user_id):
            return
        updates = ud.get('pending_price_updates')
        if not updates:
            await safe_edit(query, "⚠️ انتهت جلسة التحديث. استخدم /update_prices مرة أخرى.")
            return
        if not save_fare_prices(updates):
            await safe_edit(query, "⚠️ قاعدة البيانات غير متاحة حالياً، لم يتم حفظ الأسعار. حاول بعد قليل.")
            return
        ud.pop('pending_price_updates', None)
        ud.pop('step', None)
        await safe_edit(query, f"✅ تم حفظ تحديث {len(updates)} فئة سعر بنجاح.")

    elif data == "cancel_price_updates":
        if not is_admin(user_id):
            return
        ud.pop('pending_price_updates', None)
        ud.pop('step', None)
        await safe_edit(query, "تم إلغاء تحديث الأسعار.")

    elif data.startswith("admin_trip_route_"):
        if not is_admin(user_id):
            return
        route_id = callback_int(data)
        route = get_route(route_id) if route_id is not None else None
        if not route:
            return
        ud['selected_admin_route_id'] = route_id
        ud['step'] = 'admin_add_trip'
        await safe_edit(
            query,
            f"🚆 *{md(route['route_name'])}*\n\n"
            "أرسل بيانات الرحلة بهذا الترتيب:\n"
            "`رمز فئة السعر | الوقت أو باقي الاوقات | بطيء أو سريع أو عادي`\n\n"
            "مثال: `535 | 01:28 | بطيء`",
            parse_mode='Markdown',
        )

    # ---------- اختيار الوجهة والسعر ----------
    elif data.startswith("dest_"):
        route_id = callback_int(data)
        selected_route = get_route(route_id) if route_id is not None else None
        if not selected_route:
            await start(update, context)
            return
        dest_name = selected_route['route_name']
        ud['selected_dest'] = dest_name
        ud['selected_route_id'] = route_id
        trips = get_route_trips(route_id)
        fare_prices = get_fare_prices()

        keyboard = []
        for trip in trips:
            fare = fare_prices.get(trip['fare_code'])
            if not fare:
                logging.error(f"Missing fare configuration: {trip['fare_code']}")
                continue
            formatted_times = [format_time_with_period(t) for t in trip["times"]]
            if trip['service_type'] == "fast": service_str = " ⚡ سريع"
            elif trip['service_type'] == "slow": service_str = " 🐢 بطيء"
            else: service_str = ""

            if len(formatted_times) > 5:
                times_display = " | ".join(formatted_times[:5]) + " | وغيرها" + service_str
            else:
                times_display = " | ".join(formatted_times) + service_str

            button_text = f"{fare['base_price']} ليرة - {times_display}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"price_{trip['fare_code']}")])

        if not keyboard:
            keyboard.append([InlineKeyboardButton("لا توجد رحلات لهذه الوجهة حالياً", callback_data="back_to_dest")])
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_dest")])
        await safe_edit(query, f"📍 *الوجهة:* {md(dest_name)}\n\nاختر المسار:",
                        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("price_"):
        fare_code = data[6:]
        if fare_code not in get_fare_prices():
            return
        ud['selected_fare_code'] = fare_code
        ud['step'] = "choose_family"
        await safe_edit(query, FAMILY_LIST_TEXT, reply_markup=family_list_markup(user_id), parse_mode='Markdown')

    # ---------- الحساب السريع ----------
    elif data == "quick_calc":
        # إذا كان الزر مضغوطاً من رسالة نتيجة سابقة → لا نمسح القائمة ونرسل برومبت جديداً
        # حتى تبقى النتيجة القديمة ظاهرة في الشات
        was_already_quick = ud.get('step') == "quick_calc"
        if not was_already_quick:
            ud['quick_passengers'] = []
        ud['step'] = "quick_calc"
        prompt_text = (
            "🧮 *قسم الحساب السريع*\n\n"
            "أدخل اسم الشخص + تاريخ الميلاد لحساب السعر فوراً:\n"
            "مثال: `أحمد محمد 15-05-1995` أو `أحمد محمد 15/05/1995` أو `أحمد محمد 15.05.1995`"
        )
        if was_already_quick:
            await query.message.reply_text(prompt_text, parse_mode='Markdown')
        else:
            await safe_edit(query, prompt_text, parse_mode='Markdown')

    # ---------- العوائل ----------
    elif data == "new_family":
        if not db_is_up():
            await safe_edit(query, "⚠️ قاعدة البيانات غير متاحة حالياً، لا يمكن إنشاء عائلة الآن.",
                            reply_markup=family_list_markup(user_id))
            return
        ud['step'] = "create_family"
        await safe_edit(query, "👪 أدخل اسم العائلة:")

    elif data == "delete_family":
        if not get_user_families(user_id):
            await safe_edit(query, "⚠️ لا توجد عائلات لمسحها!", reply_markup=family_list_markup(user_id))
            return
        ud['selected_families_to_delete'] = []
        await safe_edit(query, "☐ اختر العائلات المراد مسحها:", reply_markup=delete_families_markup(user_id, []))

    elif data.startswith("del_family_"):
        family_id = callback_int(data)
        if family_id is None or not get_family(user_id, family_id):
            return
        selected = ud.get('selected_families_to_delete', [])
        if family_id in selected:
            selected.remove(family_id)
        else:
            selected.append(family_id)
        ud['selected_families_to_delete'] = selected
        await safe_edit(query, f"✅ تم تحديد {len(selected)} عائلة",
                        reply_markup=delete_families_markup(user_id, selected))

    elif data == "confirm_delete_family":
        selected = ud.get('selected_families_to_delete', [])
        if not selected:
            await safe_edit(query, "⚠️ لم يتم تحديد أي عائلة! اختر أولاً:",
                            reply_markup=delete_families_markup(user_id, []))
            return
        deleted = delete_families(user_id, selected)
        ud['selected_families_to_delete'] = []
        if ud.get('selected_family') in selected:
            ud.pop('selected_family', None)
            ud['selected_passengers'] = []
        await safe_edit(query, f"✅ تم مسح {deleted} عائلة بنجاح!\n\n" + FAMILY_LIST_TEXT,
                        reply_markup=family_list_markup(user_id), parse_mode='Markdown')

    elif data.startswith("family_"):
        family_id = callback_int(data)
        family = get_family(user_id, family_id) if family_id is not None else None
        if not family:
            await safe_edit(query, "⚠️ هذه العائلة غير موجودة.\n\n" + FAMILY_LIST_TEXT,
                            reply_markup=family_list_markup(user_id), parse_mode='Markdown')
            return
        if ud.get('selected_family') != family_id:
            ud['selected_passengers'] = []
        ud['selected_family'] = family_id
        ud['step'] = "choose_passengers"
        selected = ud.get('selected_passengers', [])
        await safe_edit(query, family_header(family) + "☐ اختر الأفراد المطلوبين:",
                        reply_markup=family_members_markup(family_id, selected), parse_mode='Markdown')

    elif data.startswith("delete_member_"):
        family_id = callback_int(data)
        family = get_family(user_id, family_id) if family_id is not None else None
        if not family:
            return
        ud['selected_family'] = family_id
        if not get_family_passengers(family_id):
            await safe_edit(query, family_header(family) + "⚠️ لا يوجد أفراد في هذه العائلة!",
                            reply_markup=family_members_markup(family_id, []), parse_mode='Markdown')
            return
        ud['selected_members_to_delete'] = []
        await safe_edit(query, family_header(family) + "☐ اختر الأفراد المراد مسحهم:",
                        reply_markup=delete_members_markup(family_id, []), parse_mode='Markdown')

    elif data.startswith("del_member_"):
        passenger_id = callback_int(data)
        family_id = ud.get('selected_family')
        passenger = get_passenger(user_id, passenger_id) if passenger_id is not None else None
        if not passenger or passenger['family_id'] != family_id:
            return
        selected = ud.get('selected_members_to_delete', [])
        if passenger_id in selected:
            selected.remove(passenger_id)
        else:
            selected.append(passenger_id)
        ud['selected_members_to_delete'] = selected
        await safe_edit(query, f"✅ تم تحديد {len(selected)} فرد",
                        reply_markup=delete_members_markup(family_id, selected))

    elif data == "confirm_delete_member":
        family_id = ud.get('selected_family')
        family = get_family(user_id, family_id) if family_id else None
        if not family:
            return
        selected = ud.get('selected_members_to_delete', [])
        if not selected:
            await safe_edit(query, "⚠️ لم يتم تحديد أي فرد! اختر أولاً:",
                            reply_markup=delete_members_markup(family_id, []))
            return
        deleted = delete_passengers(user_id, family_id, selected)
        ud['selected_members_to_delete'] = []
        ud['selected_passengers'] = [pid for pid in ud.get('selected_passengers', []) if pid not in selected]
        await safe_edit(query, family_header(family) + f"✅ تم مسح {deleted} فرد بنجاح!\n\n☐ اختر الأفراد المطلوبين:",
                        reply_markup=family_members_markup(family_id, ud['selected_passengers']),
                        parse_mode='Markdown')

    elif data.startswith("toggle_"):
        passenger_id = callback_int(data)
        family_id = ud.get('selected_family')
        passenger = get_passenger(user_id, passenger_id) if passenger_id is not None else None
        if not passenger or passenger['family_id'] != family_id:
            return
        selected = ud.get('selected_passengers', [])
        if passenger_id in selected:
            selected.remove(passenger_id)
        else:
            selected.append(passenger_id)
        ud['selected_passengers'] = selected
        await safe_edit(query, f"✅ تم تحديد {len(selected)} فرد",
                        reply_markup=family_members_markup(family_id, selected))

    elif data == "calculate_selected":
        family_id = ud.get('selected_family')
        family = get_family(user_id, family_id) if family_id else None
        if not family:
            await safe_edit(query, FAMILY_LIST_TEXT, reply_markup=family_list_markup(user_id), parse_mode='Markdown')
            return
        selected_ids = set(ud.get('selected_passengers', []))
        passengers = [p for p in get_family_passengers(family_id) if p['id'] in selected_ids]
        if not passengers:
            await safe_edit(query, family_header(family) + "⚠️ لم يتم تحديد أي فرد! اختر الأفراد أولاً:",
                            reply_markup=family_members_markup(family_id, []), parse_mode='Markdown')
            return

        fare = get_fare_prices().get(ud.get('selected_fare_code'))
        if not fare:
            await safe_edit(query, "⚠️ تعذر العثور على سعر هذه الرحلة. اختر الوجهة مرة أخرى.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂️ الوجهات", callback_data="back_to_dest")]]))
            return
        dest_name = ud.get('selected_dest', 'غير محددة')

        today = date.today()
        results = []
        grand_total = 0
        for p in passengers:
            try:
                age = calculate_railway_age(parse_birth_date(p['birth_date']), today)
            except ValueError:
                results.append(f"❌ {md(p['name'])} - خطأ في التاريخ")
                continue
            line, amount = passenger_price_line(fare, p['name'], p['birth_date'], age)
            results.append(line)
            grand_total += amount

        response = (f"📍 *الوجهة:* {md(dest_name)}\n👪 *العائلة:* {md(family['family_name'])}\n\n"
                    f"📊 *نتيجة الحساب*\n\n" + "\n".join(results) +
                    f"\n\n💰 *المجموع الكلي: {grand_total} ليرة تركي*")
        keyboard = [
            [InlineKeyboardButton("⬅️ العودة للعائلة", callback_data=f"family_{family_id}")],
            [InlineKeyboardButton("👨‍👩‍👧‍👦 قائمة العوائل", callback_data="back_to_family_list")],
        ]
        await safe_edit(query, response, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("add_member_"):
        family_id = callback_int(data)
        family = get_family(user_id, family_id) if family_id is not None else None
        if not family:
            return
        ud['selected_family'] = family_id
        ud['step'] = "add_member"
        await safe_edit(query, family_header(family) +
                        "👤 أدخل اسم الشخص + تاريخ الميلاد:\nمثال: `أحمد 15-05-1995` أو `أحمد 15/05/1995`",
                        parse_mode='Markdown')

    elif data == "back_to_family_list":
        ud['step'] = "choose_family"
        ud.pop('quick_passengers', None)  # مسح نتائج الحساب السريع عند العودة
        await safe_edit(query, FAMILY_LIST_TEXT, reply_markup=family_list_markup(user_id), parse_mode='Markdown')

    elif data == "back_to_dest":
        ud.pop('step', None)
        await start(update, context)

# ====================== الرسائل النصية ======================
NAME_DATE_FORMAT_ERROR = (
    "❌ التنسيق خاطئ!\n"
    "يرجى إدخال *اسم الشخص + تاريخ الميلاد* بهذا الشكل:\n"
    "مثال: `أحمد محمد 15-05-1995` أو `أحمد محمد 15/05/1995`\n"
    "(تاريخ الميلاد لا يمكن أن يكون في المستقبل)"
)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ud = context.user_data
    step = ud.get('step')
    user_id = update.effective_user.id

    if is_destination_request(text):
        ud.pop('step', None)
        await start(update, context)
        return

    if step in ("admin_update_prices", "admin_update_one_price", "admin_add_fare"):
        if not is_admin(user_id):
            ud.pop('step', None)
            await update.message.reply_text(ADMIN_ONLY_TEXT)
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

            ud['pending_price_updates'] = updates
            ud['step'] = 'admin_confirm_price_updates'
            keyboard = [
                [InlineKeyboardButton("✅ تأكيد الحفظ", callback_data="confirm_price_updates")],
                [InlineKeyboardButton("✖️ إلغاء", callback_data="cancel_price_updates")],
            ]
            await update.message.reply_text(
                "📋 *معاينة التحديث*\n\n" + "\n".join(preview) +
                "\n\nهل تريد حفظ هذه الأسعار؟",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown',
            )
        except ValueError as error:
            await update.message.reply_text(
                f"❌ {error}\n\nأعد إرسال الجدول بالصيغة المطلوبة، أو استخدم /update_prices للبدء من جديد."
            )

    elif step == "admin_confirm_price_updates":
        await update.message.reply_text("👆 اضغط «تأكيد الحفظ» أو «إلغاء» في الرسالة السابقة، أو أرسل /cancel")

    elif step == "admin_add_destination":
        if not is_admin(user_id):
            ud.pop('step', None)
            return
        route_name = text.strip()
        if len(route_name) < 3 or len(route_name) > MAX_NAME_LENGTH:
            await update.message.reply_text("❌ طول اسم الوجهة غير مناسب. أرسله مرة أخرى.")
            return
        route_id = create_route(route_name)
        if route_id:
            ud.pop('step', None)
            await update.message.reply_text(
                f"✅ تمت إضافة وجهة *{md(route_name)}*.\nاستخدم /add\\_trip لإضافة السعر والوقت.",
                parse_mode='Markdown',
            )
        elif not DB_AVAILABLE:
            await update.message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، لم يتم حفظ الوجهة.")
        else:
            await update.message.reply_text("⚠️ هذه الوجهة موجودة بالفعل.")

    elif step == "admin_add_trip":
        if not is_admin(user_id):
            ud.pop('step', None)
            return
        try:
            parts = [part.strip() for part in text.split('|')]
            if len(parts) != 3:
                raise ValueError("استخدم 3 قيم مفصولة بعلامة |")
            category, departure_label, service_label = parts
            category = category.replace('fare_', '')
            if not category.isdigit() or not departure_label:
                raise ValueError("رمز السعر والوقت مطلوبان")
            fare_code = f"fare_{int(category)}"
            if fare_code not in get_fare_prices():
                raise ValueError(f"فئة السعر {category} غير موجودة. أضفها أولًا عبر /add_fare")
            service_types = {'بطيء': 'slow', 'slow': 'slow', 'سريع': 'fast', 'fast': 'fast', 'عادي': 'regular', 'regular': 'regular'}
            service_type = service_types.get(service_label.lower())
            if not service_type:
                raise ValueError("نوع القطار يجب أن يكون بطيء أو سريع أو عادي")
            route_id = ud.get('selected_admin_route_id')
            if not route_id:
                raise ValueError("اختر الوجهة من جديد عبر /add_trip")
            trip_id = create_route_trip(route_id, fare_code, departure_label, service_type)
            if trip_id:
                await update.message.reply_text("✅ تمت إضافة الرحلة. يمكنك إرسال سطر رحلة آخر لنفس الوجهة، أو استخدام /add_trip لاختيار وجهة أخرى.")
            elif not DB_AVAILABLE:
                await update.message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، لم يتم حفظ الرحلة.")
            else:
                await update.message.reply_text("⚠️ هذه الرحلة موجودة بالفعل.")
        except ValueError as error:
            await update.message.reply_text(f"❌ {md(error)}\nمثال: `535 | 01:28 | بطيء`", parse_mode='Markdown')

    elif step == "quick_calc":
        try:
            name, birth_display, dob = split_name_and_date(text)
        except ValueError:
            await update.message.reply_text(NAME_DATE_FORMAT_ERROR, parse_mode='Markdown')
            return

        fare = get_fare_prices().get(ud.get('selected_fare_code'))
        if not fare:
            await update.message.reply_text("⚠️ تعذر العثور على سعر هذه الرحلة. اختر الوجهة مرة أخرى عبر /start")
            return
        dest_name = ud.get('selected_dest', 'غير محددة')
        age = calculate_railway_age(dob, date.today())
        line, amount = passenger_price_line(fare, name, birth_display, age)

        passengers = ud.setdefault('quick_passengers', [])
        passengers.append({'line': line, 'price': amount})

        results_text = "\n".join(p['line'] for p in passengers)
        grand_total = sum(p['price'] for p in passengers)
        response = (
            f"📍 *الوجهة:* {md(dest_name)}\n\n"
            f"📊 *نتيجة الحساب*\n\n"
            f"{results_text}\n\n"
            f"💰 *المجموع الكلي: {grand_total} ليرة تركي*"
        )
        keyboard = [
            [InlineKeyboardButton("🧮 حساب تاريخ آخر", callback_data="quick_calc")],
            [InlineKeyboardButton("⬅️ عودة لقائمة العوائل", callback_data="back_to_family_list")]
        ]
        await update.message.reply_text(response, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif step == "create_family":
        family_name = text.strip()
        if not family_name or len(family_name) > MAX_NAME_LENGTH:
            await update.message.reply_text("❌ اسم العائلة غير صالح. أرسل اسماً أقصر.")
            return
        family_id, is_new = create_family(user_id, family_name)
        if not family_id:
            await update.message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، لم يتم إنشاء العائلة.")
            return
        ud['selected_family'] = family_id
        ud['selected_passengers'] = []
        ud['step'] = "add_member"
        intro = (f"✅ تم إنشاء العائلة: *{md(family_name)}*" if is_new
                 else f"ℹ️ العائلة *{md(family_name)}* موجودة مسبقاً، سيتم الإضافة إليها.")
        await update.message.reply_text(
            intro + "\n\n👤 أدخل اسم الشخص + تاريخ الميلاد:\nمثال: `أحمد 15-05-1995` أو `أحمد 15/05/1995`",
            parse_mode='Markdown',
        )

    elif step == "add_member":
        family_id = ud.get('selected_family')
        family = get_family(user_id, family_id) if family_id else None
        if not family:
            ud.pop('step', None)
            await update.message.reply_text("⚠️ العائلة غير موجودة. أرسل /start للبدء من جديد.")
            return
        try:
            name, birth_date, _ = split_name_and_date(text)
        except ValueError:
            await update.message.reply_text(NAME_DATE_FORMAT_ERROR, parse_mode='Markdown')
            return
        if not add_passenger_to_family(family_id, user_id, name, birth_date):
            await update.message.reply_text("⚠️ قاعدة البيانات غير متاحة حالياً، لم تتم إضافة الفرد.")
            return
        await update.message.reply_text(
            family_header(family) + f"✅ تم إضافة *{md(name)}*\n\n"
            "يمكنك إرسال فرد آخر مباشرة، أو اختيار الأفراد من القائمة:",
            reply_markup=family_members_markup(family_id, ud.get('selected_passengers', [])),
            parse_mode='Markdown',
        )

    elif step == "await_import":
        await update.message.reply_text("📎 أرسل ملف النسخة الاحتياطية (.json) كملف، أو /cancel للإلغاء.")

    elif step == "confirm_import":
        await update.message.reply_text("👆 اضغط «تأكيد الاستيراد» أو «إلغاء» في الرسالة السابقة، أو أرسل /cancel")

    else:
        await update.message.reply_text("⚠️ استخدم الأزرار أعلاه، أو أرسل /start لعرض الوجهات.")

# ====================== تشغيل البوت والخدمات ======================
USER_COMMANDS = [
    BotCommand("start", "عرض الوجهات"),
    BotCommand("export", "تصدير العوائل المحفوظة"),
    BotCommand("import", "استيراد نسخة احتياطية"),
    BotCommand("cancel", "إلغاء العملية الحالية"),
]
ADMIN_COMMANDS = [
    BotCommand("update_prices", "تحديث الأسعار دفعة واحدة"),
    BotCommand("update_price", "تحديث فئة سعر واحدة"),
    BotCommand("add_fare", "إضافة فئة سعر"),
    BotCommand("add_destination", "إضافة وجهة"),
    BotCommand("add_trip", "إضافة رحلة لوجهة"),
]

async def post_init(application: Application):
    try:
        await application.bot.set_my_commands(USER_COMMANDS)
        await application.bot.set_my_commands(USER_COMMANDS + ADMIN_COMMANDS,
                                              scope=BotCommandScopeChat(ADMIN_USER_ID))
    except Exception as e:
        logging.warning(f"Could not set bot commands: {e}")

async def error_handler(update, context):
    logging.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ حدث خطأ غير متوقع. حاول مرة أخرى أو أرسل /start")
    except Exception:
        pass

def build_application(token: str) -> Application:
    bot_app = Application.builder().token(token).post_init(post_init).build()
    bot_app.add_error_handler(error_handler)

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("cancel", cancel_command))
    bot_app.add_handler(CommandHandler("export", export_command))
    bot_app.add_handler(CommandHandler("import", import_command))
    bot_app.add_handler(CommandHandler("update_prices", update_prices_command))
    bot_app.add_handler(CommandHandler("update_price", update_one_price_command))
    bot_app.add_handler(CommandHandler("add_destination", add_destination_command))
    bot_app.add_handler(CommandHandler("add_trip", add_trip_command))
    bot_app.add_handler(CommandHandler("add_fare", add_fare_command))
    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    # الرسائل المعدّلة ما إلها update.message، فنستقبل الرسائل الجديدة فقط
    bot_app.add_handler(MessageHandler(filters.Document.ALL & filters.UpdateType.MESSAGE, handle_document))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, handle_text))
    return bot_app

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
        bot_app = build_application(TOKEN)
        keep_alive()
        print("🚀 البوت يعمل الآن (مع دعم العمل بدون قاعدة بيانات عند انقطاعها)")
        bot_app.run_polling()
