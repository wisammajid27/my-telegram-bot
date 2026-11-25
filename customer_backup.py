"""Private Telegram backup and restore for customer records."""

import asyncio
import io
import json
import logging
import os
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from telegram.constants import ChatType
from telegram.ext import CommandHandler, MessageHandler, filters

TABLES = {
    "families": "id, user_id, family_name, created_at",
    "passengers": "id, family_id, user_id, name, birth_date, created_at",
}
FORMAT = "rail-bot-customers-v1"
LIMIT = 20 * 1024 * 1024


class BackupError(Exception):
    pass


def connect():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise BackupError("رابط قاعدة البيانات غير مضبوط.")
    return psycopg2.connect(
        url, sslmode=os.getenv("DB_SSLMODE", "require"),
        connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "15")),
    )


def export_customers():
    snapshot = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat()}
    with closing(connect()) as conn, conn, conn.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '30s'")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        for table, columns in TABLES.items():
            cursor.execute(f"SELECT {columns} FROM {table} ORDER BY id")
            snapshot[table] = [
                dict(zip(columns.split(", "), row)) for row in cursor
            ]
    if not any(snapshot[table] for table in TABLES):
        raise BackupError("جداول الزبائن فارغة.")
    data = json.dumps(snapshot, ensure_ascii=False).encode()
    if len(data) > LIMIT:
        raise BackupError("النسخة أكبر من حد الاسترجاع عبر تيليجرام (20 ميغابايت).")
    return data


def parse_backup(data):
    try:
        if len(data) > LIMIT:
            raise ValueError
        snapshot = json.loads(data)
        if snapshot["format"] != FORMAT:
            raise ValueError
        datetime.fromisoformat(snapshot["created_at"])
        for table, columns in TABLES.items():
            rows = snapshot[table]
            if not isinstance(rows, list):
                raise ValueError
            ids = set()
            for row in rows:
                if not isinstance(row, dict) or row.keys() != set(columns.split(", ")):
                    raise ValueError
                row_id = row["id"]
                if type(row_id) is not int or not 0 < row_id < 2147483647 or row_id in ids:
                    raise ValueError
                ids.add(row_id)
                for column, value in row.items():
                    if column == "id" or value is None:
                        continue
                    expected = int if column in {"user_id", "family_id"} else str
                    if type(value) is not expected:
                        raise ValueError
        if not any(snapshot[table] for table in TABLES):
            raise ValueError
        return snapshot
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise BackupError("الملف مو نسخة زبائن صالحة.") from exc


def import_customers(data):
    snapshot = parse_backup(data)
    with closing(connect()) as conn, conn, conn.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = '30s'")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("LOCK TABLE families, passengers IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS (SELECT 1 FROM families) OR EXISTS (SELECT 1 FROM passengers)")
        if cursor.fetchone()[0]:
            raise BackupError("جداول الزبائن تحتوي بيانات. الاسترجاع يحتاج جداول زبائن فارغة.")
        for table, columns in TABLES.items():
            rows = snapshot[table]
            cursor.execute(
                f"INSERT INTO {table} ({columns}) SELECT {columns} "
                f"FROM json_populate_recordset(NULL::{table}, %s::json)",
                (json.dumps(rows),),
            )
            next_id = max((row["id"] for row in rows), default=0) + 1
            cursor.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH %s", (next_id,))
    return snapshot


def cache_backup(path, data):
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temp_path = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        temp_path.replace(path)
    except OSError:
        logging.warning("Could not save the local customer backup")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def install_customer_backup(app, admin_id):
    if app.job_queue is None:
        raise RuntimeError("Install python-telegram-bot with the job-queue extra")
    path = Path(os.getenv("CUSTOMER_BACKUP_PATH", "customer-data/latest.json"))
    lock = asyncio.Lock()

    def authorized(update):
        return (update.effective_chat.type == ChatType.PRIVATE
                and update.effective_user is not None
                and update.effective_user.id == admin_id)

    async def send_backup(bot, allow_previous):
        async with lock:
            try:
                data = await asyncio.to_thread(export_customers)
            except (psycopg2.Error, BackupError) as exc:
                reason = str(exc) if isinstance(exc, BackupError) else "تعذر قراءة قاعدة البيانات."
                if isinstance(exc, psycopg2.Error):
                    logging.warning("Customer backup database error: %s (%s)",
                                    type(exc).__name__, exc.pgcode or "no SQLSTATE")
                    if exc.pgcode == "42P01":
                        reason = "جداول الزبائن غير موجودة في قاعدة البيانات المتصلة."
                    elif isinstance(exc, psycopg2.OperationalError) and not exc.pgcode:
                        reason = "تعذّر الاتصال بقاعدة البيانات. استخدم /dbstatus للفحص."
                if not allow_previous:
                    raise BackupError(reason) from exc
                try:
                    data = await asyncio.to_thread(path.read_bytes)
                    snapshot = parse_backup(data)
                except (OSError, BackupError) as previous_error:
                    raise BackupError(f"{reason} ماكو نسخة محلية سابقة.") from previous_error
                label = f"آخر نسخة محفوظة. {reason}"
            else:
                snapshot = parse_backup(data)
                await asyncio.to_thread(cache_backup, path, data)
                label = "نسخة جديدة"
            await bot.send_document(
                chat_id=admin_id, document=io.BytesIO(data),
                filename=f"customers-{snapshot['created_at'][:10]}.json",
                caption=(f"{label}\nوقت النسخ UTC: {snapshot['created_at']}\n"
                         f"العوائل: {len(snapshot['families'])} | الأفراد: {len(snapshot['passengers'])}"),
            )

    async def backup_command(update, context):
        if authorized(update):
            try:
                await send_backup(context.bot, allow_previous=True)
            except BackupError as exc:
                await update.effective_message.reply_text(str(exc))

    async def daily_backup(context):
        try:
            await send_backup(context.bot, allow_previous=False)
        except BackupError as exc:
            logging.warning("Daily customer backup skipped: %s", exc)

    async def restore_document(update, context):
        if not authorized(update):
            return
        message = update.effective_message
        if message.document.file_size and message.document.file_size > LIMIT:
            await message.reply_text("حجم الملف أكبر من 20 ميغابايت.")
            return
        file = await message.document.get_file()
        data = await file.download_as_bytearray()
        try:
            async with lock:
                snapshot = await asyncio.to_thread(import_customers, data)
                await asyncio.to_thread(cache_backup, path, data)
        except BackupError as exc:
            await message.reply_text(str(exc))
        except psycopg2.Error:
            await message.reply_text("تعذّر الاسترجاع. تأكد من اتصال القاعدة الجديدة وتهيئة جداول البوت.")
        else:
            await message.reply_text(
                f"✅ تم استرجاع {len(snapshot['families'])} عائلة و{len(snapshot['passengers'])} فرد."
            )

    admin_messages = filters.ChatType.PRIVATE & filters.User(user_id=admin_id) & filters.UpdateType.MESSAGE
    app.add_handler(CommandHandler("backup_customers", backup_command, filters=admin_messages))
    app.add_handler(MessageHandler(
        admin_messages & filters.Document.ALL & filters.CaptionRegex(r"^/restore_customers\s*$"),
        restore_document,
    ))
    app.job_queue.run_repeating(daily_backup, interval=86400, first=10, name="customer-backup")
