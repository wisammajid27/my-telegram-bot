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

@contextmanager
def get_db():
    """إدارة اتصال قاعدة البيانات بشكل آمن يضمن الإغلاق التلقائي"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn
    except Exception as e:
        conn.rollback()
        logging.error(f"Database error: {e}")
        raise
    finally:
        conn.close()

def init_db():
    try:
        with get_db() as conn:
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
OFFICE_PROFIT = 85[cite: 1]
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
}[cite: 1]

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
}[cite: 1]

ADMIN_USER_ID = 7209751288[cite: 1]

def fare_code_from_original_price(original_price: int) -> str:
    return f"fare_{original_price}"[cite: 1]

def init_fare_prices():
    try:
        with get_db() as conn:
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
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus
                FROM fare_prices
            ''')
            return {row['fare_code']: dict(row) for row in cur.fetchall()}[cite: 1]

def save_fare_prices(updates):
    with get_db() as conn:
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
                ))[cite: 1]
            conn.commit()

def init_route_data():
    try:
        with get_db() as conn:
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
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, route_name FROM travel_routes ORDER BY sort_order, id")
            return [dict(row) for row in cur.fetchall()][cite: 1]

def get_route(route_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT id, route_name FROM travel_routes WHERE id = %s", (route_id,))
            row = cur.fetchone()
            return dict(row) if row else None[cite: 1]

def get_route_trips(route_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, departure_label, service_type
                FROM route_trips
                WHERE route_id = %s
                ORDER BY id
            ''', (route_id,))[cite: 1]
            groups = {}
            for row in cur.fetchall():
                key = (row['fare_code'], row['service_type'])
                groups.setdefault(key, []).append(row['departure_label'])
            return [
                {'fare_code': fare_code, 'service_type': service_type, 'times': times}
                for (fare_code, service_type), times in groups.items()
            ][cite: 1]

def create_route(route_name):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO travel_routes (route_name, sort_order, created_at)
                VALUES (%s, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM travel_routes), %s)
                ON CONFLICT (route_name) DO NOTHING
                RETURNING id
            ''', (route_name, datetime.now().isoformat()))[cite: 1]
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None[cite: 1]

def create_route_trip(route_id, fare_code, departure_label, service_type):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO route_trips (route_id, fare_code, departure_label, service_type, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (route_id, fare_code, departure_label, service_type) DO NOTHING
                RETURNING id
            ''', (route_id, fare_code, departure_label, service_type, datetime.now().isoformat()))[cite: 1]
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None[cite: 1]

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID[cite: 1]

def price_update_template():
    fare_prices = get_fare_prices()
    lines = []
    for fare_code in sorted(fare_prices, key=lambda code: int(code.split('_')[1])):
        fare = fare_prices[fare_code]
        category = fare_code.split('_')[1]
        lines.append(
            f"{category} | {fare['base_price']} | {fare['price_7_12']} | "
            f"{fare['price_13_26']} | {fare['price_60_64']} | {fare['price_65_plus']}"
        )[cite: 1]
    return "\n".join(lines)[cite: 1]

async def update_prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")[cite: 1]
        return

    context.user_data['step'] = 'admin_update_prices'[cite: 1]
    await update.message.reply_text(
        "💼 **تحديث الأسعار دفعة واحدة**\n\n"
        "يمكنك إرسال سطر واحد أو عدة أسطر؛ كل سطر يحدّث فئة واحدة بهذا الترتيب:\n"
        "`رمز الفئة | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "رمز الفئة هو الرقم الأول الثابت، حتى إذا تغير السعر الكامل لاحقًا.\n"
        "انسخ الجدول التالي وعدّل الأرقام فقط، ثم أرسله:\n\n"
        f"```\n{price_update_template()}\n```",
        parse_mode='Markdown',
    )[cite: 1]

async def update_one_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")[cite: 1]
        return

    context.user_data['step'] = 'admin_update_one_price'[cite: 1]
    await update.message.reply_text(
        "💼 **تحديث فئة سعر واحدة**\n\n"
        "أرسل سطرًا واحدًا فقط بهذا الترتيب:\n"
        "`رمز الفئة | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "مثال لتحديث فئة 370:\n"
        "`370 | 400 | 200 | 340 | 340 | 200`\n\n"
        "رمز الفئة هو الرقم الأول الأصلي، وليس السعر الجديد.",
        parse_mode='Markdown',
    )[cite: 1]

async def add_destination_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")[cite: 1]
        return
    context.user_data['step'] = 'admin_add_destination'[cite: 1]
    await update.message.reply_text("🗺️ أرسل اسم الوجهة الجديدة، مثال:\n`انقرة - قونية`", parse_mode='Markdown')[cite: 1]

async def add_trip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")[cite: 1]
        return
    routes = get_routes()
    keyboard = [[InlineKeyboardButton(route['route_name'], callback_data=f"admin_trip_route_{route['id']}")]
                for route in routes][cite: 1]
    context.user_data['step'] = 'admin_select_trip_route'[cite: 1]
    await update.message.reply_text("🚆 اختر الوجهة التي تريد إضافة رحلة لها:", reply_markup=InlineKeyboardMarkup(keyboard))[cite: 1]

async def add_fare_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")[cite: 1]
        return
    context.user_data['step'] = 'admin_add_fare'[cite: 1]
    await update.message.reply_text(
        "💰 أرسل فئة السعر الجديدة في سطر واحد:\n"
        "`رمز جديد | السعر الكامل | 7-12 | 13-26 | 60-64 | +65`\n\n"
        "مثال: `900 | 900 | 450 | 765 | 765 | 450`",
        parse_mode='Markdown',
    )[cite: 1]

def parse_price_updates(text: str, allow_new=False):
    current_prices = get_fare_prices()
    updates = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split('|')]
        if len(parts) != 6:
            raise ValueError("كل سطر يجب أن يحتوي على 6 قيم مفصولة بعلامة |")[cite: 1]

        category = parts[0].replace('fare_', '')
        if not category.isdigit():
            raise ValueError("رمز الفئة يجب أن يكون رقمًا، مثل 370")[cite: 1]
        fare_code = f"fare_{category}"
        if fare_code not in current_prices and not allow_new:
            raise ValueError(f"فئة السعر {category} غير موجودة")[cite: 1]
        if fare_code in updates:
            raise ValueError(f"فئة السعر {category} مكررة")[cite: 1]

        try:
            values = [int(value) for value in parts[1:]]
        except ValueError as error:
            raise ValueError("يجب أن تكون جميع الأسعار أرقامًا صحيحة") from error[cite: 1]
        if any(value < 0 for value in values) or values[0] == 0:
            raise ValueError("الأسعار يجب أن تكون موجبة، والسعر الكامل أكبر من صفر")[cite: 1]

        updates[fare_code] = {
            'base_price': values[0],
            'price_7_12': values[1],
            'price_13_26': values[2],
            'price_60_64': values[3],
            'price_65_plus': values[4],
        }

    if not updates:
        raise ValueError("لم يتم العثور على أي صف أسعار")[cite: 1]
    return updates

BIRTH_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")[cite: 1]

def parse_birth_date(date_str: str) -> datetime:
    date_str = date_str.strip()
    for fmt in BIRTH_DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError("invalid birth date")[cite: 1]

def normalize_birth_date(date_str: str) -> str:
    return parse_birth_date(date_str).strftime("%d-%m-%Y")[cite: 1]

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

    return actual_age + (today >= one_month_after_birthday)[cite: 1]

def format_time_with_period(time_str: str) -> str:
    try:
        hour = int(time_str.split(':')[0])
        if 6 <= hour <= 11: period = "ص"
        elif 12 <= hour <= 15: period = "ظ"
        elif 16 <= hour <= 17: period = "ع"
        elif 18 <= hour <= 19: period = "م"
        else: period = "ل"
        return f"{time_str} {period}"[cite: 1]
    except:
        return time_str[cite: 1]

def get_user_families(user_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM families WHERE user_id = %s ORDER BY family_name", (user_id,))
            return [dict(row) for row in cur.fetchall()][cite: 1]

def get_family_passengers(family_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM passengers WHERE family_id = %s ORDER BY name", (family_id,))
            return [dict(row) for row in cur.fetchall()][cite: 1]

def create_family(user_id, family_name):
    with get_db() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("INSERT INTO families (user_id, family_name, created_at) VALUES (%s, %s, %s) RETURNING id",
                            (user_id, family_name, datetime.now().isoformat()))
                family_id = cur.fetchone()[0]
                conn.commit()
                return family_id
            except Exception as e:
                logging.error(f"Error creating family: {e}")
                return None[cite: 1]

def add_passenger_to_family(family_id, user_id, name, birth_date):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO passengers (family_id, user_id, name, birth_date, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (family_id, user_id, name, birth_date, datetime.now().isoformat()))
            conn.commit()[cite: 1]

def delete_families(family_ids):
    with get_db() as conn:
        with conn.cursor() as cur:
            for fid in family_ids:
                cur.execute("DELETE FROM passengers WHERE family_id = %s", (fid,))
                cur.execute("DELETE FROM families WHERE id = %s", (fid,))[cite: 1]
            conn.commit()[cite: 1]

def delete_passengers(passenger_ids):
    with get_db() as conn:
        with conn.cursor() as cur:
            for pid in passenger_ids:
                cur.execute("DELETE FROM passengers WHERE id = %s", (pid,))[cite: 1]
            conn.commit()[cite: 1]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    routes = get_routes()
    keyboard = [[InlineKeyboardButton(route['route_name'], callback_data=f"dest_{route['id']}")]
                for route in routes][cite: 1]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🚍 **مرحباً بك في بوت حجز التذاكر**\n\n🗂️ اختر الوجهة المطلوبة:"[cite: 1]
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

def is_destination_request(text: str) -> bool:
    normalized = text.strip().replace("ـ", "")
    return normalized in {"وجهة", "الوجهة"}[cite: 1]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()[cite: 1]
    user_id = query.from_user.id[cite: 1]
    data = query.data[cite: 1]

    if data == "confirm_price_updates":
        if not is_admin(user_id):
            return
        updates = context.user_data.get('pending_price_updates')[cite: 1]
        if not updates:
            await query.message.edit_text("⚠️ انتهت جلسة التحديث. استخدم /update_prices مرة أخرى.")[cite: 1]
            return
        save_fare_prices(updates)[cite: 1]
        context.user_data.pop('pending_price_updates', None)[cite: 1]
        context.user_data.pop('step', None)[cite: 1]
        await query.message.edit_text(f"✅ تم حفظ تحديث {len(updates)} فئة سعر بنجاح.")[cite: 1]

    elif data == "cancel_price_updates":
        if not is_admin(user_id):
            return
        context.user_data.pop('pending_price_updates', None)[cite: 1]
        context.user_data.pop('step', None)[cite: 1]
        await query.message.edit_text("تم إلغاء تحديث الأسعار.")[cite: 1]

    elif data.startswith("admin_trip_route_"):
        if not is_admin(user_id):
            return
        try:
            route_id = int(data.rsplit('_', 1)[1])[cite: 1]
        except ValueError:
            return
        route = get_route(route_id)[cite: 1]
        if not route:
            return
        context.user_data['selected_admin_route_id'] = route_id[cite: 1]
        context.user_data['step'] = 'admin_add_trip'[cite: 1]
        await query.message.edit_text(
            f"🚆 **{route['route_name']}**\n\n"
            "أرسل بيانات الرحلة بهذا الترتيب:\n"
            "`رمز فئة السعر | الوقت أو باقي الاوقات | بطيء أو سريع أو عادي`\n\n"
            "مثال: `535 | 01:28 | بطيء`",
            parse_mode='Markdown',
        )[cite: 1]

    elif data.startswith("dest_"):
        try:
            route_id = int(data[5:])[cite: 1]
        except ValueError:
            return
        selected_route = get_route(route_id)[cite: 1]
        if not selected_route:
            return
        dest_name = selected_route['route_name'][cite: 1]
        context.user_data['selected_dest'] = dest_name[cite: 1]
        context.user_data['selected_route_id'] = route_id[cite: 1]
        routes = get_route_trips(route_id)[cite: 1]
        fare_prices = get_fare_prices()[cite: 1]
        
        keyboard = []
        for route in routes:
            fare_code = route['fare_code']
            fare = fare_prices.get(fare_code)
            if not fare:
                logging.error(f"Missing fare configuration: {fare_code}")[cite: 1]
                continue
            formatted_times = [format_time_with_period(t) for t in route["times"]][cite: 1]
            if route['service_type'] == "fast": times_str = " ⚡ سريع"[cite: 1]
            elif route['service_type'] == "slow": times_str = " 🐢 بطيء"[cite: 1]
            else: times_str = ""[cite: 1]
            
            if len(formatted_times) > 5:
                times_display = " | ".join(formatted_times[:5]) + " | وغيرها" + times_str[cite: 1]
            else:
                times_display = " | ".join(formatted_times) + times_str[cite: 1]
                
            button_text = f"{fare['base_price']} ليرة - {times_display}"[cite: 1]
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"price_{fare_code}")])[cite: 1]
        
        keyboard.append([InlineKeyboardButton("⬅️_العودة", callback_data="back_to_dest")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"📍 **الوجهة:** {dest_name}\n\nاختر المسار:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data.startswith("price_"):
        fare_code = data[6:][cite: 1]
        if fare_code not in get_fare_prices():
            return
        context.user_data['selected_fare_code'] = fare_code[cite: 1]
        context.user_data['step'] = "choose_family"[cite: 1]
        
        families = get_user_families(user_id)[cite: 1]
        keyboard = [[InlineKeyboardButton(f"👪 {f['family_name']}", callback_data=f"family_{f['id']}")] for f in families][cite: 1]
        keyboard.append([InlineKeyboardButton("🧮 حساب سريع بدون عائلة", callback_data="quick_calc")])[cite: 1]
        keyboard.append([InlineKeyboardButton("➕ إنشاء عائلة جديدة", callback_data="new_family")])[cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ مسح قيد العائلة", callback_data="delete_family")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_dest")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("👨‍👩‍👧‍👦 **اختر العائلة أو اختر الحساب السريع**:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data == "quick_calc":
        context.user_data['step'] = "quick_calc"[cite: 1]
        await query.message.edit_text("🧮 **قسم الحساب السريع**\n\nأدخل تاريخ الميلاد مباشرة لحساب السعر فوراً:\nمثال: `15-05-1995` أو `15/05/1995` أو `15.05.1995`")[cite: 1]

    elif data == "new_family":
        context.user_data['step'] = "create_family"[cite: 1]
        await query.message.edit_text("👪 أدخل اسم العائلة:")[cite: 1]

    elif data == "delete_family":
        families = get_user_families(user_id)[cite: 1]
        if not families:
            await query.message.edit_text("⚠️ لا توجد عائلات لمسحها!")[cite: 1]
            return
        context.user_data['delete_mode'] = 'family'[cite: 1]
        context.user_data['selected_families_to_delete'] = [][cite: 1]
        keyboard = [[InlineKeyboardButton(f"☐ {f['family_name']}", callback_data=f"del_family_{f['id']}")] for f in families][cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ مسح العائلات المحددة", callback_data="confirm_delete_family")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر العائلات المراد مسحها:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data.startswith("del_family_"):
        family_id = int(data.split("_")[2])[cite: 1]
        selected = context.user_data.get('selected_families_to_delete', [])[cite: 1]
        if family_id in selected:
            selected.remove(family_id)[cite: 1]
        else:
            selected.append(family_id)[cite: 1]
        context.user_data['selected_families_to_delete'] = selected[cite: 1]
        
        families = get_user_families(user_id)[cite: 1]
        keyboard = []
        for f in families:
            is_selected = f['id'] in selected
            emoji = "✅" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(f"{emoji} {f['family_name']}", callback_data=f"del_family_{f['id']}")])[cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ مسح العائلات المحددة", callback_data="confirm_delete_family")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"✅ تم تحديد {len(selected)} عائلة", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data == "confirm_delete_family":
        selected = context.user_data.get('selected_families_to_delete', [])[cite: 1]
        if not selected:
            await query.message.edit_text("⚠️ لم يتم تحديد أي عائلة!")[cite: 1]
            return
        delete_families(selected)[cite: 1]
        context.user_data['selected_families_to_delete'] = [][cite: 1]
        await query.message.edit_text(f"✅ تم مسح {len(selected)} عائلة بنجاح!")[cite: 1]
        await start(update, context)[cite: 1]

    elif data.startswith("family_"):
        family_id = int(data.split("_")[1])[cite: 1]
        context.user_data['selected_family'] = family_id[cite: 1]
        context.user_data['selected_passengers'] = [][cite: 1]
        passengers = get_family_passengers(family_id)[cite: 1]
        keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"toggle_{p['id']}")] for p in passengers][cite: 1]
        keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])[cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])[cite: 1]
        keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data.startswith("delete_member_"):
        family_id = int(data.split("_")[2])[cite: 1]
        context.user_data['delete_mode'] = 'member'[cite: 1]
        context.user_data['selected_family'] = family_id[cite: 1]
        passengers = get_family_passengers(family_id)[cite: 1]
        if not passengers:
            await query.message.edit_text("⚠️ لا يوجد أفراد في هذه العائلة!")[cite: 1]
            return
        context.user_data['selected_members_to_delete'] = [][cite: 1]
        keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"del_member_{p['id']}")] for p in passengers][cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ مسح الأفراد المحددين", callback_data="confirm_delete_member")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر الأفراد المراد مسحهم:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data.startswith("del_member_"):
        passenger_id = int(data.split("_")[2])[cite: 1]
        selected = context.user_data.get('selected_members_to_delete', [])[cite: 1]
        if passenger_id in selected:
            selected.remove(passenger_id)[cite: 1]
        else:
            selected.append(passenger_id)[cite: 1]
        context.user_data['selected_members_to_delete'] = selected[cite: 1]
        
        family_id = context.user_data['selected_family'][cite: 1]
        passengers = get_family_passengers(family_id)[cite: 1]
        keyboard = []
        for p in passengers:
            is_selected = p['id'] in selected
            emoji = "✅" if is_selected else "☐"
            keyboard.append([InlineKeyboardButton(f"{emoji} {p['name']}", callback_data=f"del_member_{p['id']}")])[cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ مسح الأفراد المحددين", callback_data="confirm_delete_member")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"✅ تم تحديد {len(selected)} فرد", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data == "confirm_delete_member":
        selected = context.user_data.get('selected_members_to_delete', [])[cite: 1]
        if not selected:
            await query.message.edit_text("⚠️ لم يتم تحديد أي فرد!")[cite: 1]
            return
        delete_passengers(selected)[cite: 1]
        context.user_data['selected_members_to_delete'] = [][cite: 1]
        await query.message.edit_text(f"✅ تم مسح {len(selected)} فرد بنجاح!")[cite: 1]
        
        family_id = context.user_data['selected_family'][cite: 1]
        passengers = get_family_passengers(family_id)[cite: 1]
        keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"toggle_{p['id']}")] for p in passengers][cite: 1]
        keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])[cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])[cite: 1]
        keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data.startswith("toggle_"):
        passenger_id = int(data.split("_")[1])[cite: 1]
        selected = context.user_data.get('selected_passengers', [])[cite: 1]
        
        p = None
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT * FROM passengers WHERE id = %s", (passenger_id,))
                row = cur.fetchone()
                if row:
                    p = dict(row)[cite: 1]
        
        if p:
            passenger_data = {'id': p['id'], 'name': p['name'], 'birth_date': p['birth_date']}[cite: 1]
            if passenger_id in [sp['id'] for sp in selected]:
                selected = [sp for sp in selected if sp['id'] != passenger_id][cite: 1]
            else:
                selected.append(passenger_data)[cite: 1]
            
            context.user_data['selected_passengers'] = selected[cite: 1]
            family_id = context.user_data['selected_family'][cite: 1]
            passengers = get_family_passengers(family_id)[cite: 1]
            
            keyboard = []
            for p_item in passengers:
                is_selected = any(sp['id'] == p_item['id'] for sp in selected)
                emoji = "✅" if is_selected else "☐"
                keyboard.append([InlineKeyboardButton(f"{emoji} {p_item['name']}", callback_data=f"toggle_{p_item['id']}")])[cite: 1]
            
            keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])[cite: 1]
            keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])[cite: 1]
            keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])[cite: 1]
            keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(f"✅ تم تحديد {len(selected)} فرد", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data == "calculate_selected":
        selected = context.user_data.get('selected_passengers', [])[cite: 1]
        if not selected:
            await query.message.edit_text("⚠️ لم يتم تحديد أي فرد!")[cite: 1]
            return
        
        fare = get_fare_prices().get(context.user_data.get('selected_fare_code'))[cite: 1]
        if not fare:
            await query.message.edit_text("⚠️ تعذر العثور على سعر هذه الرحلة. اختر الوجهة مرة أخرى.")[cite: 1]
            return
        price_base = fare['base_price'][cite: 1]
        rules = {
            "7-12": fare['price_7_12'],
            "13-26": fare['price_13_26'],
            "60-64": fare['price_60_64'],
            "+65": fare['price_65_plus'],
        }[cite: 1]
        dest_name = context.user_data.get('selected_dest', 'غير محددة')[cite: 1]
        
        today = date.today()[cite: 1]
        results = []
        grand_total = 0
        
        for p in selected:
            try:
                dob = parse_birth_date(p['birth_date'])[cite: 1]
                age = calculate_railway_age(dob, today)[cite: 1]
                
                if age < 7:
                    results.append(f"👶 {p['name']} | {p['birth_date']} | العمر: {age} | **مجاناً** (لا يحتاج تذكرة)")[cite: 1]
                    continue
                
                if 7 <= age <= 12:
                    price = rules.get("7-12", price_base)[cite: 1]
                elif 13 <= age <= 26:
                    price = rules.get("13-26", price_base)[cite: 1]
                elif 60 <= age <= 64:
                    price = rules.get("60-64", price_base)[cite: 1]
                elif age >= 65:
                    price = rules.get("+65", price_base)[cite: 1]
                else:
                    price = price_base[cite: 1]
                
                final_price = price + OFFICE_PROFIT[cite: 1]
                grand_total += final_price[cite: 1]
                results.append(f"👤 {p['name']} | {p['birth_date']} | العمر: {age} | **{final_price}** ليرة")[cite: 1]
            except:
                results.append(f"❌ {p['name']} - خطأ في التاريخ")[cite: 1]
        
        response = f"📍 **الوجهة:** {dest_name}\n\n📊 **نتيجة الحساب**\n\n" + "\n".join(results)[cite: 1]
        response += f"\n\n💰 **المجموع الكلي: {grand_total} ليرة تركي**"[cite: 1]
        await query.message.edit_text(response, parse_mode='Markdown')[cite: 1]

    elif data.startswith("add_member_"):
        family_id = int(data.split("_")[2])[cite: 1]
        context.user_data['selected_family'] = family_id[cite: 1]
        context.user_data['step'] = "add_member"[cite: 1]
        await query.message.edit_text("👤 أدخل اسم الشخص + تاريخ الميلاد:\nمثال: `أحمد 15-05-1995` أو `أحمد 15/05/1995`")[cite: 1]

    elif data == "back_to_family_list":
        context.user_data['step'] = "choose_family"[cite: 1]
        families = get_user_families(user_id)[cite: 1]
        keyboard = [[InlineKeyboardButton(f"👪 {f['family_name']}", callback_data=f"family_{f['id']}")] for f in families][cite: 1]
        keyboard.append([InlineKeyboardButton("🧮 حساب سريع بدون عائلة", callback_data="quick_calc")])[cite: 1]
        keyboard.append([InlineKeyboardButton("➕ إنشاء عائلة جديدة", callback_data="new_family")])[cite: 1]
        keyboard.append([InlineKeyboardButton("🗑️ مسح قيد العائلة", callback_data="delete_family")])[cite: 1]
        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_dest")])[cite: 1]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("👨‍👩‍👧‍👦 **اختر العائلة أو اختر الحساب السريع**:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]

    elif data == "back_to_dest":
        await start(update, context)[cite: 1]

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()[cite: 1]
    step = context.user_data.get('step')[cite: 1]
    user_id = update.effective_user.id[cite: 1]

    if is_destination_request(text):
        context.user_data.pop('step', None)[cite: 1]
        await start(update, context)[cite: 1]
        return

    if step in ("admin_update_prices", "admin_update_one_price", "admin_add_fare"):
        if not is_admin(user_id):
            context.user_data.pop('step', None)[cite: 1]
            await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")[cite: 1]
            return
        try:
            updates = parse_price_updates(text, allow_new=step == "admin_add_fare")[cite: 1]
            if step in ("admin_update_one_price", "admin_add_fare") and len(updates) != 1:
                raise ValueError("هذا الأمر يقبل سطرًا واحدًا فقط")[cite: 1]
            current_prices = get_fare_prices()[cite: 1]
            preview = []
            for fare_code, prices in updates.items():
                old_price = current_prices.get(fare_code, {}).get('base_price', 'جديدة')[cite: 1]
                category = fare_code.split('_')[1][cite: 1]
                preview.append(f"فئة {category}: {old_price} ← {prices['base_price']}")[cite: 1]

            context.user_data['pending_price_updates'] = updates[cite: 1]
            context.user_data['step'] = 'admin_confirm_price_updates'[cite: 1]
            keyboard = [
                [InlineKeyboardButton("✅ تأكيد الحفظ", callback_data="confirm_price_updates")],
                [InlineKeyboardButton("✖️ إلغاء", callback_data="cancel_price_updates")],
            ][cite: 1]
            await update.message.reply_text(
                "📋 **معاينة التحديث**\n\n" + "\n".join(preview) +
                "\n\nهل تريد حفظ هذه الأسعار؟",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown',
            )[cite: 1]
        except ValueError as error:
            await update.message.reply_text(
                f"❌ {error}\n\nأعد إرسال الجدول بالصيغة المطلوبة، أو استخدم /update_prices للبدء من جديد."
            )[cite: 1]

    elif step == "admin_add_destination":
        if not is_admin(user_id):
            context.user_data.pop('step', None)[cite: 1]
            return
        route_name = text.strip()[cite: 1]
        if len(route_name) < 3:
            await update.message.reply_text("❌ اسم الوجهة قصير جدًا. أرسله مرة أخرى.")[cite: 1]
            return
        route_id = create_route(route_name)[cite: 1]
        if route_id:
            context.user_data.pop('step', None)[cite: 1]
            await update.message.reply_text(
                f"✅ تمت إضافة وجهة **{route_name}**.\nاستخدم /add_trip لإضافة السعر والوقت.",
                parse_mode='Markdown',
            )[cite: 1]
        else:
            await update.message.reply_text("⚠️ هذه الوجهة موجودة بالفعل، أو تعذر حفظها.")[cite: 1]

    elif step == "admin_add_trip":
        if not is_admin(user_id):
            context.user_data.pop('step', None)[cite: 1]
            return
        try:
            parts = [part.strip() for part in text.split('|')][cite: 1]
            if len(parts) != 3:
                raise ValueError("استخدم 3 قيم مفصولة بعلامة |")[cite: 1]
            category, departure_label, service_label = parts[cite: 1]
            category = category.replace('fare_', '')[cite: 1]
            if not category.isdigit() or not departure_label:
                raise ValueError("رمز السعر والوقت مطلوبان")[cite: 1]
            fare_code = f"fare_{category}"[cite: 1]
            if fare_code not in get_fare_prices():
                raise ValueError(f"فئة السعر {category} غير موجودة. أضفها أولًا عبر /add_fare")[cite: 1]
            service_types = {'بطيء': 'slow', 'slow': 'slow', 'سريع': 'fast', 'fast': 'fast', 'عادي': 'regular', 'regular': 'regular'}[cite: 1]
            service_type = service_types.get(service_label.lower())[cite: 1]
            if not service_type:
                raise ValueError("نوع القطار يجب أن يكون بطيء أو سريع أو عادي")[cite: 1]
            route_id = context.user_data.get('selected_admin_route_id')[cite: 1]
            if not route_id:
                raise ValueError("اختر الوجهة من جديد عبر /add_trip")[cite: 1]
            trip_id = create_route_trip(route_id, fare_code, departure_label, service_type)[cite: 1]
            if trip_id:
                await update.message.reply_text("✅ تمت إضافة الرحلة. يمكنك إرسال سطر رحلة آخر لنفس الوجهة، أو استخدام /add_trip لاختيار وجهة أخرى.")[cite: 1]
            else:
                await update.message.reply_text("⚠️ هذه الرحلة موجودة بالفعل.")[cite: 1]
        except ValueError as error:
            await update.message.reply_text(f"❌ {error}\nمثال: `535 | 01:28 | بطيء`", parse_mode='Markdown')[cite: 1]

    elif step == "quick_calc":
        try:
            dob = parse_birth_date(text)[cite: 1]
            birth_display = normalize_birth_date(text)[cite: 1]
            today = date.today()[cite: 1]
            age = calculate_railway_age(dob, today)[cite: 1]
            
            fare = get_fare_prices().get(context.user_data.get('selected_fare_code'))[cite: 1]
            if not fare:
                await update.message.reply_text("⚠️ تعذر العثور على سعر هذه الرحلة. اختر الوجهة مرة أخرى.")[cite: 1]
                return
            price_base = fare['base_price'][cite: 1]
            rules = {
                "7-12": fare['price_7_12'],
                "13-26": fare['price_13_26'],
                "60-64": fare['price_60_64'],
                "+65": fare['price_65_plus'],
            }[cite: 1]
            dest_name = context.user_data.get('selected_dest', 'غير محددة')[cite: 1]
            if age < 7:
                response = f"📍 **الوجهة:** {dest_name}\n\n📊 **نتيجة الحساب**\n\n"[cite: 1]
                response += f"👶 زبون سريع | {birth_display} | العمر: {age} | **مجاناً** (لا يحتاج تذكرة)\n\n"[cite: 1]
                response += f"💰 **المجموع الكلي: 0 ليرة تركي**"[cite: 1]
            else:
                if 7 <= age <= 12:
                    price = rules.get("7-12", price_base)[cite: 1]
                elif 13 <= age <= 26:
                    price = rules.get("13-26", price_base)[cite: 1]
                elif 60 <= age <= 64:
                    price = rules.get("60-64", price_base)[cite: 1]
                elif age >= 65:
                    price = rules.get("+65", price_base)[cite: 1]
                else:
                    price = price_base[cite: 1]
                
                final_price = price + OFFICE_PROFIT[cite: 1]
                
                response = f"📍 **الوجهة:** {dest_name}\n\n📊 **نتيجة الحساب**\n\n"[cite: 1]
                response += f"👤 زبون سريع | {birth_display} | العمر: {age} | **{final_price}** ليرة\n\n"[cite: 1]
                response += f"💰 **المجموع الكلي: {final_price} ليرة تركي**"[cite: 1]
            
            keyboard = [
                [InlineKeyboardButton("🧮 حساب تاريخ آخر", callback_data="quick_calc")],
                [InlineKeyboardButton("⬅️ عودة لقائمة العوائل", callback_data="back_to_family_list")]
            ][cite: 1]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(response, reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]
            
        except ValueError:
            await update.message.reply_text("❌ التنسيق خاطئ! يرجى إدخال التاريخ بالطريقة التالية:\nمثال: `15-05-1995` أو `15/05/1995`")[cite: 1]

    elif step == "create_family":
        family_id = create_family(user_id, text)[cite: 1]
        if family_id:
            await update.message.reply_text(f"✅ تم إنشاء العائلة: **{text}**")[cite: 1]
            context.user_data['selected_family'] = family_id[cite: 1]
            context.user_data['step'] = "add_member"[cite: 1]
            await update.message.reply_text("👤 أدخل اسم الشخص + تاريخ الميلاد:\nمثال: `أحمد 15-05-1995` أو `أحمد 15/05/1995`")[cite: 1]
        else:
            await update.message.reply_text("❌ حدث خطأ أثناء إنشاء العائلة.")[cite: 1]

    elif step == "add_member":
        try:
            name, birth_date_raw = text.rsplit(maxsplit=1)[cite: 1]
            birth_date = normalize_birth_date(birth_date_raw)[cite: 1]
            family_id = context.user_data['selected_family'][cite: 1]
            add_passenger_to_family(family_id, user_id, name, birth_date)[cite: 1]
            await update.message.reply_text(f"✅ تم إضافة **{name}**")[cite: 1]
            
            passengers = get_family_passengers(family_id)[cite: 1]
            keyboard = [[InlineKeyboardButton(f"☐ {p['name']}", callback_data=f"toggle_{p['id']}")] for p in passengers][cite: 1]
            keyboard.append([InlineKeyboardButton("➕ إضافة فرد جديد", callback_data=f"add_member_{family_id}")])[cite: 1]
            keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data="delete_member_" + str(family_id))])[cite: 1]
            keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])[cite: 1]
            keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])[cite: 1]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')[cite: 1]
        except:
            await update.message.reply_text("❌ التنسيق خاطئ\nمثال: أحمد 15-05-1995 أو أحمد 15/05/1995")[cite: 1]
    else:
        await update.message.reply_text("⚠️ استخدم الأزرار أعلاه")[cite: 1]

# ====================== تشغيل البوت والخدمات ======================
if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)[cite: 1]
    
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
        bot_app = Application.builder().token(TOKEN).build()[cite: 1]
        bot_app.add_handler(CommandHandler("start", start))[cite: 1]
        bot_app.add_handler(CommandHandler("update_prices", update_prices_command))[cite: 1]
        bot_app.add_handler(CommandHandler("update_price", update_one_price_command))[cite: 1]
        bot_app.add_handler(CommandHandler("add_destination", add_destination_command))[cite: 1]
        bot_app.add_handler(CommandHandler("add_trip", add_trip_command))[cite: 1]
        bot_app.add_handler(CommandHandler("add_fare", add_fare_command))[cite: 1]
        bot_app.add_handler(CallbackQueryHandler(handle_callback))[cite: 1]
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))[cite: 1]
        
        keep_alive()[cite: 1]
        print("🚀 البوت يعمل الآن مع قاعدة بيانات PostgreSQL ومحمّي من تسريب الاتصالات!")[cite: 1]
        bot_app.run_polling()[cite: 1]