#!/usr/bin/env python3
"""
Telegram Bot - Complete Version with PostgreSQL Support (Optimized)
"""
import os
import logging
from datetime import datetime
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
            conn.commit()

# تهيئة الجداول عند التشغيل
init_db()

# ====================== البيانات الثابتة والقوانين ======================
OFFICE_PROFIT = 85
ROUTES = {
    "اسكيشهير - انقرة": [
        {"price": 345, "times": ["03:24"], "slow": True},
        {"price": 385, "times": ["05:31"], "slow": True},
        {"price": 465, "times": ["06:35", "14:30"]},
        {"price": 480, "times": ["09:05", "10:10", "10:56", "11:56", "12:46", "13:31", "14:15", "15:12", "16:10", "17:28", "18:16", "19:07", "20:36", "21:27", "22:35", "23:29"]},
    ],
    "انقرة - اسكي شهير": [
        {"price": 345, "times": ["22:00"], "slow": True},
        {"price": 385, "times": ["20:00"], "slow": True},
        {"price": 465, "times": ["11:40", "17:50"]},
        {"price": 480, "times": ["06:00", "06:50", "07:35", "08:40", "09:50", "10:50", "12:05", "12:55", "14:25", "15:15", "15:44", "16:55", "17:25", "18:30", "19:50", "21:00"]},
    ],
    "اسكيشهير - اسطنبول(بندك)": [
        {"price": 500, "times": ["01:28"], "slow": True},
        {"price": 600, "times": ["06:40", "07:23", "07:50", "08:16", "08:58", "10:06", "10:45", "11:13", "12:16", "13:28", "14:01", "14:23", "15:48", "16:41", "17:05", "18:20", "18:51", "19:03", "19:56", "20:39", "21:13", "22:21"]},
    ],
    "اسطنبول(بندك) - اسكيشهير": [
        {"price": 500, "times": ["23:18"], "slow": True},
        {"price": 600, "times": ["06:30", "06:58", "07:48", "08:23", "08:53", "09:29", "10:04", "11:08", "11:40", "12:18", "12:48", "13:35", "15:03", "15:40", "16:10", "16:43", "17:56", "18:49", "19:29", "20:08", "21:25"]},
    ],
    "اسكي شهير - كركالة": [
        {"price": 760, "times": ["11:56"], "fast": True},
        {"price": 765, "times": ["16:10"], "fast": True},
    ],
    "كركالة - اسكي شهير": [
        {"price": 630, "times": ["19:46"], "fast": True},
        {"price": 760, "times": ["14:55"], "fast": True},
        {"price": 765, "times": ["09:06"], "fast": True},
    ],
    "كركالة - انقرة": [
        {"price": 225, "times": ["05:25", "08:31", "10:47"], "slow": True},
        {"price": 285, "times": ["09:06", "14:55", "19:46"], "fast": True},
    ],
    "انقرة - كركالة": [
        {"price": 225, "times": ["05:25", "08:31", "10:47", "11:20", "18:00"], "slow": True},
        {"price": 285, "times": ["07:00", "13:20", "18:40"], "fast": True},
    ],
}

PRICES_RULES = {
    225: {"7-12": 115, "13-26": 195, "60-64": 195},
    345: {"7-12": 175, "13-26": 295, "60-64": 295},
    385: {"7-12": 195, "13-26": 330, "60-64": 330},
    465: {"7-12": 235, "13-26": 400, "60-64": 400},
    480: {"7-12": 240, "13-26": 410, "60-64": 410},
    500: {"7-12": 250, "13-26": 425, "60-64": 425},
    600: {"7-12": 300, "13-26": 510, "60-64": 510},
    630: {"7-12": 320, "13-26": 540, "60-64": 540},
    760: {"7-12": 380, "13-26": 650, "60-64": 650},
    765: {"7-12": 385, "13-26": 655, "60-64": 655},
    285: {"7-12": 145, "13-26": 245, "60-64": 245},
}

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
                cur.execute("DELETE FROM families WHERE id = %s", (fid,))
                cur.execute("DELETE FROM passengers WHERE family_id = %s", (fid,))
            conn.commit()

def delete_passengers(passenger_ids):
    with get_db() as conn:
        with conn.cursor() as cur:
            for pid in passenger_ids:
                cur.execute("DELETE FROM passengers WHERE id = %s", (pid,))
            conn.commit()

# ====================== دوال البوت الأساسية ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(dest, callback_data=f"dest_{dest}")] for dest in ROUTES.keys()]
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

    if data.startswith("dest_"):
        dest_name = data[5:]
        context.user_data['selected_dest'] = dest_name
        routes = ROUTES.get(dest_name, [])
        
        keyboard = []
        for route in routes:
            formatted_times = [format_time_with_period(t) for t in route["times"]]
            if route.get("fast"): times_str = " ⚡ سريع"
            elif route.get("slow"): times_str = " 🐢 بطيء"
            else: times_str = ""
            
            if len(formatted_times) > 5:
                times_display = " | ".join(formatted_times[:5]) + " | وغيرها" + times_str
            else:
                times_display = " | ".join(formatted_times) + times_str
                
            button_text = f"{route['price']} ليرة - {times_display}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"price_{route['price']}")])
        
        keyboard.append([InlineKeyboardButton("⬅️_العودة", callback_data="back_to_dest")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f"📍 **الوجهة:** {dest_name}\n\nاختر المسار:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("price_"):
        price = int(data[6:])
        context.user_data['selected_price'] = price
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
        
        price_base = context.user_data.get('selected_price')
        dest_name = context.user_data.get('selected_dest', 'غير محددة')
        
        today = datetime.now()
        results = []
        grand_total = 0
        
        for p in selected:
            try:
                dob = parse_birth_date(p['birth_date'])
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                
                rules = PRICES_RULES.get(price_base, {})
                if 7 <= age <= 12:
                    price = rules.get("7-12", price_base)
                elif 13 <= age <= 26:
                    price = rules.get("13-26", price_base)
                elif 60 <= age <= 64:
                    price = rules.get("60-64", price_base)
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

    if step == "quick_calc":
        try:
            dob = parse_birth_date(text)
            birth_display = normalize_birth_date(text)
            today = datetime.now()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            
            price_base = context.user_data.get('selected_price')
            dest_name = context.user_data.get('selected_dest', 'غير محددة')
            
            rules = PRICES_RULES.get(price_base, {})
            if 7 <= age <= 12:
                price = rules.get("7-12", price_base)
            elif 13 <= age <= 26:
                price = rules.get("13-26", price_base)
            elif 60 <= age <= 64:
                price = rules.get("60-64", price_base)
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
        TOKEN = "8242305081:AAFvDKxIf8QjKxyYoC3E8IeslgrLHtb1_i0"
        
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.Regex(r'وجهة|الوجهة'), start))
    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    keep_alive()
    print("🚀 البوت يعمل الآن مع قاعدة بيانات PostgreSQL ومحمّي من تسريب الاتصالات!")
    bot_app.run_polling()
