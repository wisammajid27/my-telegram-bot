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
    t.start()

# ====================== إدارة قاعدة البيانات (PostgreSQL) ======================
DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_db():
    """إدارة اتصال قاعدة البيانات بشكل آمن يضمن الإغلاق التلقائي"""
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
            conn.commit()

# تهيئة الجداول عند التشغيل
init_db()

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
}

# Only this Telegram account can change prices from inside the bot.
ADMIN_USER_ID = 7209751288


def fare_code_from_original_price(original_price: int) -> str:
    """Return a stable fare identifier even after its displayed price changes."""
    return f"fare_{original_price}"


def init_fare_prices():
    """Seed editable prices once, without overwriting prices saved by the admin."""
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


def get_fare_prices():
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''
                SELECT fare_code, base_price, price_7_12, price_13_26, price_60_64, price_65_plus
                FROM fare_prices
            ''')
            return {row['fare_code']: dict(row) for row in cur.fetchall()}


def save_fare_prices(updates):
    with get_db() as conn:
        with conn.cursor() as cur:
            for fare_code, prices in updates.items():
                cur.execute('''
                    UPDATE fare_prices
                    SET base_price = %s, price_7_12 = %s, price_13_26 = %s,
                        price_60_64 = %s, price_65_plus = %s, updated_at = %s
                    WHERE fare_code = %s
                ''', (
                    prices['base_price'], prices['price_7_12'], prices['price_13_26'],
                    prices['price_60_64'], prices['price_65_plus'], datetime.now().isoformat(),
                    fare_code,
                ))
            conn.commit()


init_fare_prices()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


def price_update_template():
    """Build a copyable price table for the administrator."""
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
    """Start the administrator's one-message price update flow."""
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
    """Start a single-fare update, without requiring the whole price table."""
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


def parse_price_updates(text: str):
    """Validate the administrator's pasted price table."""
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
        if fare_code not in current_prices:
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
    """Return the railway age: add one year only after a full month past the birthday."""
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

# ====================== دوال العائلات والمسافرين الجاهزة وآمنة الاتصال ======================
def get_user_families(user_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM families WHERE user_id = %s ORDER BY family_name", (user_id,))
            return [dict(row) for row in cur.fetchall()]

def get_family_passengers(family_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM passengers WHERE family_id = %s ORDER BY name", (family_id,))
            return [dict(row) for row in cur.fetchall()]

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
                return None

def add_passenger_to_family(family_id, user_id, name, birth_date):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO passengers (family_id, user_id, name, birth_date, created_at) VALUES (%s, %s, %s, %s, %s)",
                        (family_id, user_id, name, birth_date, datetime.now().isoformat()))
            conn.commit()

def delete_families(family_ids):
    with get_db() as conn:
        with conn.cursor() as cur:
            for fid in family_ids:
                cur.execute("DELETE FROM passengers WHERE family_id = %s", (fid,))
                cur.execute("DELETE FROM families WHERE id = %s", (fid,))
            conn.commit()

def delete_passengers(passenger_ids):
    with get_db() as conn:
        with conn.cursor() as cur:
            for pid in passenger_ids:
                cur.execute("DELETE FROM passengers WHERE id = %s", (pid,))
            conn.commit()

# ====================== دوال البوت الأساسية ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Telegram callback data is limited to 64 bytes; use the route index rather
    # than the Arabic route name so long destination names remain valid.
    keyboard = [[InlineKeyboardButton(dest, callback_data=f"dest_{index}")]
                for index, dest in enumerate(ROUTES.keys())]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🚍 **مرحباً بك في بوت حجز التذاكر**\n\n🗂️ اختر الوجهة المطلوبة:"
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')

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

    elif data.startswith("dest_"):
        try:
            dest_name = list(ROUTES.keys())[int(data[5:])]
        except (ValueError, IndexError):
            return
        context.user_data['selected_dest'] = dest_name
        routes = ROUTES.get(dest_name, [])
        fare_prices = get_fare_prices()
        
        keyboard = []
        for route in routes:
            fare_code = fare_code_from_original_price(route['price'])
            fare = fare_prices.get(fare_code)
            if not fare:
                logging.error(f"Missing fare configuration: {fare_code}")
                continue
            formatted_times = [format_time_with_period(t) for t in route["times"]]
            if route.get("fast"): times_str = " ⚡ سريع"
            elif route.get("slow"): times_str = " 🐢 بطيء"
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
        
        # جلب بيانات الراكب الفردي بطريقة آمنة الاتصال
        p = None
        with get_db() as conn:
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

    if step in ("admin_update_prices", "admin_update_one_price"):
        if not is_admin(user_id):
            context.user_data.pop('step', None)
            await update.message.reply_text("⛔ هذا الأمر مخصص لمدير البوت فقط.")
            return
        try:
            updates = parse_price_updates(text)
            if step == "admin_update_one_price" and len(updates) != 1:
                raise ValueError("أمر /update_price يقبل سطرًا واحدًا فقط")
            current_prices = get_fare_prices()
            preview = []
            for fare_code, prices in updates.items():
                old_price = current_prices[fare_code]['base_price']
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
            keyboard.append([InlineKeyboardButton("🗑️ حذف فرد من العائلة", callback_data=f"delete_member_{family_id}")])
            keyboard.append([InlineKeyboardButton("💰 حساب السعر للمختارين", callback_data="calculate_selected")])
            keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_family_list")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("☐ اختر الأفراد المطلوبين:", reply_markup=reply_markup, parse_mode='Markdown')
        except:
            await update.message.reply_text("❌ التنسيق خاطئ\nمثال: أحمد 15-05-1995 أو أحمد 15/05/1995")
    else:
        if any(word in text for word in ["وجهة", "الوجهة"]):
            await start(update, context)
        else:
            await update.message.reply_text("⚠️ استخدم الأزرار أعلاه")

# ====================== تشغيل البوت والخدمات ======================
if __name__ == '__main__':
    # جلب التوكن الحقيقي من المتغيرات البيئية لضمان الأمان
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        # التوكن الافتراضي الخاص بك في حال عدم تعيين المتغير البيئي للسرعة أثناء الفحص
        raise RuntimeError("TELEGRAM_TOKEN is not configured")
        
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("update_prices", update_prices_command))
    bot_app.add_handler(CommandHandler("update_price", update_one_price_command))
    bot_app.add_handler(MessageHandler(filters.Regex(r'وجهة|الوجهة'), start))
    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    keep_alive()
    print("🚀 البوت يعمل الآن مع قاعدة بيانات PostgreSQL ومحمّي من تسريب الاتصالات!")
    bot_app.run_polling()
