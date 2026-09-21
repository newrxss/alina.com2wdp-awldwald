import asyncio
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = 1541550837

DB_FILE = "krutyashki.sqlite3"
IMAGE_FILE = "alina.jpg"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения Railway.")


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =========================================================
# СОСТОЯНИЯ
# =========================================================

class ApplicationForm(StatesGroup):
    nickname = State()
    reason = State()
    loyal = State()
    pvp = State()
    age = State()
    email = State()


class AdminDecision(StatesGroup):
    waiting_message = State()


class AdminSearch(StatesGroup):
    waiting_application_id = State()


class AdminBroadcast(StatesGroup):
    waiting_message = State()


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return sqlite3.connect(DB_FILE)


def init_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            nickname TEXT NOT NULL,
            reason TEXT NOT NULL,
            loyal TEXT NOT NULL,
            pvp INTEGER NOT NULL,
            age INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            decided_at TEXT,
            decision_message TEXT,
            email TEXT,
            join_code TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT NOT NULL,
            blocked INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Миграция старой базы
    cursor.execute("PRAGMA table_info(applications)")
    columns = {row[1] for row in cursor.fetchall()}

    if "email" not in columns:
        cursor.execute(
            "ALTER TABLE applications ADD COLUMN email TEXT"
        )

    if "join_code" not in columns:
        cursor.execute(
            "ALTER TABLE applications ADD COLUMN join_code TEXT"
        )

    db.commit()
    db.close()


# =========================================================
# USERS
# =========================================================

def save_user(message: Message):
    user = message.from_user

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            created_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (
        user.id,
        user.username,
        user.first_name,
        datetime.now().isoformat()
    ))

    db.commit()
    db.close()


def is_blocked(user_id: int) -> bool:
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT blocked FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()
    db.close()

    return bool(row and row[0] == 1)


def set_blocked(user_id: int, blocked: bool):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO users (
            user_id,
            created_at,
            blocked
        )
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            blocked = excluded.blocked
    """, (
        user_id,
        datetime.now().isoformat(),
        1 if blocked else 0
    ))

    db.commit()
    db.close()


def get_all_users():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT user_id
        FROM users
        WHERE blocked = 0
    """)

    rows = cursor.fetchall()
    db.close()

    return [row[0] for row in rows]


# =========================================================
# APPLICATIONS
# =========================================================

def create_application(
    user_id,
    username,
    nickname,
    reason,
    loyal,
    pvp,
    age,
    email
):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO applications (
            user_id,
            username,
            nickname,
            reason,
            loyal,
            pvp,
            age,
            status,
            created_at,
            email
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    """, (
        user_id,
        username,
        nickname,
        reason,
        loyal,
        pvp,
        age,
        datetime.now().isoformat(),
        email
    ))

    application_id = cursor.lastrowid

    db.commit()
    db.close()

    return application_id


def get_application(application_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            username,
            nickname,
            reason,
            loyal,
            pvp,
            age,
            status,
            email,
            join_code,
            created_at,
            decided_at,
            decision_message
        FROM applications
        WHERE id = ?
    """, (application_id,))

    row = cursor.fetchone()
    db.close()

    return row


def get_pending_applications():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            nickname,
            age,
            pvp,
            created_at
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cursor.fetchall()
    db.close()

    return rows


def get_recent_applications():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT
            id,
            nickname,
            age,
            pvp,
            status,
            created_at
        FROM applications
        ORDER BY id DESC
        LIMIT 15
    """)

    rows = cursor.fetchall()
    db.close()

    return rows


def has_pending_application(user_id: int):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT id
        FROM applications
        WHERE user_id = ?
        AND status = 'pending'
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    db.close()

    return row


def has_accepted_application(user_id: int):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT id
        FROM applications
        WHERE user_id = ?
        AND status = 'accepted'
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    db.close()

    return row


def get_last_rejected(user_id: int):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT decided_at
        FROM applications
        WHERE user_id = ?
        AND status = 'rejected'
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    db.close()

    return row


def update_application(
    application_id,
    status,
    decision_message,
    join_code=None
):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE applications
        SET
            status = ?,
            decided_at = ?,
            decision_message = ?,
            join_code = ?
        WHERE id = ?
    """, (
        status,
        datetime.now().isoformat(),
        decision_message,
        join_code,
        application_id
    ))

    db.commit()
    db.close()


# =========================================================
# CODE
# =========================================================

def generate_join_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    while True:
        part1 = "".join(
            secrets.choice(alphabet)
            for _ in range(4)
        )

        part2 = "".join(
            secrets.choice(alphabet)
            for _ in range(4)
        )

        code = f"KRUT-{part1}-{part2}"

        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            SELECT id
            FROM applications
            WHERE join_code = ?
        """, (code,))

        exists = cursor.fetchone()

        db.close()

        if not exists:
            return code


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💗 Вступить в клан",
                    callback_data="join"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👑 Обо мне",
                    callback_data="about"
                )
            ]
        ]
    )


def loyalty_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💗 Да, конечно!",
                    callback_data="loyal_yes"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data="loyal_no"
                )
            ]
        ]
    )


def admin_application_keyboard(application_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{application_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{application_id}"
                )
            ]
        ]
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Ожидающие заявки",
                    callback_data="admin_pending"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗂 Последние заявки",
                    callback_data="admin_recent"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 Найти заявку",
                    callback_data="admin_search"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Пользователи",
                    callback_data="admin_users"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin_broadcast"
                )
            ]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    save_user(message)

    if is_blocked(message.from_user.id):
        await message.answer(
            "🚫 Доступ к боту временно ограничен администрацией."
        )
        return

    text = (
        "🌸 <b>Добро пожаловать в бот клана «Крутяшки»!</b>\n\n"
        "💗 Здесь можно подать заявку на вступление "
        "в клан Алиночки-принцессы.\n\n"
        "👑 Выбери действие ниже:"
    )

    if os.path.exists(IMAGE_FILE):
        photo = FSInputFile(IMAGE_FILE)

        await message.answer_photo(
            photo=photo,
            caption=text,
            reply_markup=main_keyboard()
        )
    else:
        await message.answer(
            text,
            reply_markup=main_keyboard()
        )


# =========================================================
# ABOUT
# =========================================================

@dp.callback_query(F.data == "about")
async def about_handler(callback: CallbackQuery):
    text = (
        "👑 <b>Обо мне</b>\n\n"
        "🌸 Я бот-помощник клана <b>«Крутяшки»</b>.\n\n"
        "💗 Через меня можно подать заявку "
        "на вступление в клан Алиночки.\n\n"
        "👑 Главная принцесса:\n"
        "@alino4ka_princes\n\n"
        "✨ Здесь можно узнать о вступлении, "
        "отправить анкету и получить решение администрации.\n\n"
        "💞 Даже если сейчас набор закрыт, "
        "ты всё равно можешь оставить заявку."
    )

    await callback.answer()

    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=main_keyboard()
        )
    except Exception:
        await callback.message.edit_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================================================
# JOIN
# =========================================================

@dp.callback_query(F.data == "join")
async def join_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    if is_blocked(user_id):
        await callback.answer(
            "🚫 Доступ ограничен.",
            show_alert=True
        )
        return

    if has_accepted_application(user_id):
        await callback.answer(
            "💗 Вы уже были приняты в клан.",
            show_alert=True
        )
        return

    if has_pending_application(user_id):
        await callback.answer(
            "⏳ У тебя уже есть заявка на рассмотрении.",
            show_alert=True
        )
        return

    rejected = get_last_rejected(user_id)

    if rejected and rejected[0]:
        try:
            rejected_time = datetime.fromisoformat(rejected[0])
            available_time = rejected_time + timedelta(hours=2)

            if datetime.now() < available_time:
                remaining = available_time - datetime.now()
                minutes = max(1, int(remaining.total_seconds() // 60))

                await callback.answer(
                    f"⏳ Повторно подать заявку можно примерно через {minutes} мин.",
                    show_alert=True
                )
                return

        except Exception:
            pass

    await callback.answer()

    await state.set_state(ApplicationForm.nickname)

    await callback.message.answer(
        "💗 <b>Заявка на вступление</b>\n\n"
        "1️⃣ Напиши свой Minecraft-ник:"
    )


@dp.message(ApplicationForm.nickname)
async def process_nickname(message: Message, state: FSMContext):
    if is_blocked(message.from_user.id):
        await state.clear()
        return

    nickname = message.text.strip()

    if len(nickname) < 2 or len(nickname) > 32:
        await message.answer(
            "❌ Ник должен содержать от 2 до 32 символов."
        )
        return

    await state.update_data(nickname=nickname)
    await state.set_state(ApplicationForm.reason)

    await message.answer(
        "2️⃣ Почему ты хочешь вступить в клан?"
    )


@dp.message(ApplicationForm.reason)
async def process_reason(message: Message, state: FSMContext):
    reason = message.text.strip()

    if len(reason) < 3:
        await message.answer(
            "❌ Напиши хотя бы несколько слов."
        )
        return

    await state.update_data(reason=reason)
    await state.set_state(ApplicationForm.loyal)

    await message.answer(
        "3️⃣ Клянёшься быть верным клану "
        "и уважать Алину? 💗",
        reply_markup=loyalty_keyboard()
    )


@dp.callback_query(
    ApplicationForm.loyal,
    F.data.in_(["loyal_yes", "loyal_no"])
)
async def process_loyal(
    callback: CallbackQuery,
    state: FSMContext
):
    loyal = (
        "Да, обещает быть верным клану и уважать Алину 💗"
        if callback.data == "loyal_yes"
        else "Нет"
    )

    await state.update_data(loyal=loyal)
    await state.set_state(ApplicationForm.pvp)

    await callback.answer()

    await callback.message.answer(
        "4️⃣ Оцени свой PvP от 1 до 10:"
    )


@dp.message(ApplicationForm.pvp)
async def process_pvp(message: Message, state: FSMContext):
    try:
        pvp = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Введи число от 1 до 10."
        )
        return

    if not 1 <= pvp <= 10:
        await message.answer(
            "❌ PvP должен быть от 1 до 10."
        )
        return

    await state.update_data(pvp=pvp)
    await state.set_state(ApplicationForm.age)

    await message.answer(
        "5️⃣ Сколько тебе лет?"
    )


@dp.message(ApplicationForm.age)
async def process_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Введи возраст числом."
        )
        return

    if not 5 <= age <= 100:
        await message.answer(
            "❌ Укажи реальный возраст."
        )
        return

    await state.update_data(age=age)
    await state.set_state(ApplicationForm.email)

    await message.answer(
        "6️⃣ Укажи свою Gmail-почту.\n\n"
        "📧 Например: <code>example@gmail.com</code>\n\n"
        "Почта нужна администрации для отправки "
        "кода вступления."
    )


@dp.message(ApplicationForm.email)
async def process_email(message: Message, state: FSMContext):
    email = message.text.strip().lower()

    if not re.fullmatch(
        r"[a-zA-Z0-9._%+-]+@gmail\.com",
        email
    ):
        await message.answer(
            "❌ Похоже, это не Gmail.\n\n"
            "Напиши адрес в формате:\n"
            "<code>example@gmail.com</code>"
        )
        return

    data = await state.get_data()

    application_id = create_application(
        user_id=message.from_user.id,
        username=message.from_user.username,
        nickname=data["nickname"],
        reason=data["reason"],
        loyal=data["loyal"],
        pvp=data["pvp"],
        age=data["age"],
        email=email
    )

    await state.clear()

    await message.answer(
        "💗 <b>Заявка отправлена!</b>\n\n"
        f"🆔 Номер заявки: <code>#{application_id}</code>\n\n"
        "⏳ Теперь администрация рассмотрит её.\n"
        "Если заявку примут, код вступления будет "
        "подготовлен администрацией."
    )

    username = (
        f"@{escape(message.from_user.username)}"
        if message.from_user.username
        else "нет username"
    )

    admin_text = (
        "💗 <b>НОВАЯ ЗАЯВКА В КЛАН</b>\n\n"
        f"🆔 Заявка: <code>#{application_id}</code>\n"
        f"👤 Telegram: {username}\n"
        f"🆔 User ID: <code>{message.from_user.id}</code>\n\n"
        f"🎮 Minecraft: <b>{escape(data['nickname'])}</b>\n"
        f"📝 Причина: {escape(data['reason'])}\n"
        f"💗 Верность: {escape(data['loyal'])}\n"
        f"⚔️ PvP: <b>{data['pvp']}/10</b>\n"
        f"🎂 Возраст: <b>{data['age']}</b>\n"
        f"📧 Gmail: <code>{escape(email)}</code>"
    )

    await bot.send_message(
        ADMIN_ID,
        admin_text,
        reply_markup=admin_application_keyboard(application_id)
    )


# =========================================================
# ADMIN COMMAND
# =========================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Добро пожаловать, главный администратор.\n"
        "Выбери нужный раздел:",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN STATS
# =========================================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(*) FROM applications")
    total = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM applications
        WHERE status = 'pending'
    """)
    pending = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM applications
        WHERE status = 'accepted'
    """)
    accepted = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM applications
        WHERE status = 'rejected'
    """)
    rejected = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE blocked = 1
    """)
    blocked = cursor.fetchone()[0]

    db.close()

    await callback.answer()

    await callback.message.edit_text(
        "📊 <b>СТАТИСТИКА КЛАНА</b>\n\n"
        f"👥 Пользователей: <b>{users}</b>\n"
        f"🚫 Заблокировано: <b>{blocked}</b>\n\n"
        f"📋 Всего заявок: <b>{total}</b>\n"
        f"⏳ На рассмотрении: <b>{pending}</b>\n"
        f"✅ Принято: <b>{accepted}</b>\n"
        f"❌ Отклонено: <b>{rejected}</b>",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN PENDING
# =========================================================

@dp.callback_query(F.data == "admin_pending")
async def admin_pending(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    rows = get_pending_applications()

    await callback.answer()

    if not rows:
        await callback.message.edit_text(
            "📥 <b>Ожидающие заявки</b>\n\n"
            "✨ Сейчас новых заявок нет.",
            reply_markup=admin_keyboard()
        )
        return

    text = "📥 <b>ОЖИДАЮЩИЕ ЗАЯВКИ</b>\n\n"

    for row in rows:
        app_id, user_id, nickname, age, pvp, created_at = row

        text += (
            f"🆔 <code>#{app_id}</code> — "
            f"<b>{escape(nickname)}</b>\n"
            f"👤 ID: <code>{user_id}</code>\n"
            f"🎂 {age} лет | ⚔️ PvP {pvp}/10\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN RECENT
# =========================================================

@dp.callback_query(F.data == "admin_recent")
async def admin_recent(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    rows = get_recent_applications()

    await callback.answer()

    if not rows:
        await callback.message.edit_text(
            "🗂 Заявок пока нет.",
            reply_markup=admin_keyboard()
        )
        return

    text = "🗂 <b>ПОСЛЕДНИЕ ЗАЯВКИ</b>\n\n"

    status_names = {
        "pending": "⏳",
        "accepted": "✅",
        "rejected": "❌"
    }

    for row in rows:
        app_id, nickname, age, pvp, status, created_at = row

        text += (
            f"{status_names.get(status, '❔')} "
            f"<code>#{app_id}</code> "
            f"<b>{escape(nickname)}</b>\n"
            f"🎂 {age} | ⚔️ {pvp}/10\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN SEARCH
# =========================================================

@dp.callback_query(F.data == "admin_search")
async def admin_search(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.answer()

    await state.set_state(AdminSearch.waiting_application_id)

    await callback.message.answer(
        "🔎 Введи номер заявки.\n\n"
        "Например:\n"
        "<code>15</code>"
    )


@dp.message(AdminSearch.waiting_application_id)
async def admin_search_result(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        application_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Введи номер заявки числом."
        )
        return

    application = get_application(application_id)

    if not application:
        await message.answer(
            "❌ Такая заявка не найдена."
        )
        return

    (
        app_id,
        user_id,
        username,
        nickname,
        reason,
        loyal,
        pvp,
        age,
        status,
        email,
        join_code,
        created_at,
        decided_at,
        decision_message
    ) = application

    text = (
        "🔎 <b>ЗАЯВКА</b>\n\n"
        f"🆔 Номер: <code>#{app_id}</code>\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"👤 Username: @{escape(username) if username else 'нет'}\n\n"
        f"🎮 Minecraft: <b>{escape(nickname)}</b>\n"
        f"📝 Причина: {escape(reason)}\n"
        f"💗 Верность: {escape(loyal)}\n"
        f"⚔️ PvP: <b>{pvp}/10</b>\n"
        f"🎂 Возраст: <b>{age}</b>\n"
        f"📧 Gmail: <code>{escape(email or 'нет')}</code>\n\n"
        f"📌 Статус: <b>{escape(status)}</b>\n"
    )

    if join_code:
        text += f"🔐 Код: <code>{escape(join_code)}</code>\n"

    if decision_message:
        text += (
            f"\n💬 Сообщение администрации:\n"
            f"{escape(decision_message)}"
        )

    await state.clear()

    await message.answer(
        text,
        reply_markup=(
            admin_application_keyboard(app_id)
            if status == "pending"
            else admin_keyboard()
        )
    )


# =========================================================
# ADMIN USERS
# =========================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT user_id, username, first_name, blocked
        FROM users
        ORDER BY rowid DESC
        LIMIT 20
    """)

    rows = cursor.fetchall()
    db.close()

    await callback.answer()

    if not rows:
        await callback.message.edit_text(
            "👥 Пользователей пока нет.",
            reply_markup=admin_keyboard()
        )
        return

    text = "👥 <b>ПОСЛЕДНИЕ ПОЛЬЗОВАТЕЛИ</b>\n\n"

    for user_id, username, first_name, blocked in rows:
        status = "🚫" if blocked else "🟢"

        text += (
            f"{status} <code>{user_id}</code> — "
            f"{escape(first_name or '')}"
        )

        if username:
            text += f" (@{escape(username)})"

        text += "\n"

    text += (
        "\nℹ️ Блокировку можно использовать "
        "через команду администратора."
    )

    await callback.message.edit_text(
        text,
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN BLOCK / UNBLOCK
# =========================================================

@dp.message(Command("block"))
async def admin_block(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "Использование:\n"
            "<code>/block 123456789</code>"
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный Telegram ID.")
        return

    if user_id == ADMIN_ID:
        await message.answer(
            "😄 Себя заблокировать нельзя."
        )
        return

    set_blocked(user_id, True)

    await message.answer(
        f"🚫 Пользователь <code>{user_id}</code> заблокирован."
    )


@dp.message(Command("unblock"))
async def admin_unblock(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "Использование:\n"
            "<code>/unblock 123456789</code>"
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный Telegram ID.")
        return

    set_blocked(user_id, False)

    await message.answer(
        f"🔓 Пользователь <code>{user_id}</code> разблокирован."
    )


# =========================================================
# ADMIN BROADCAST
# =========================================================

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.answer()

    await state.set_state(AdminBroadcast.waiting_message)

    await callback.message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Отправь сообщение, которое нужно разослать "
        "пользователям бота.\n\n"
        "⚠️ Рассылка уйдёт всем незаблокированным "
        "пользователям."
    )


@dp.message(AdminBroadcast.waiting_message)
async def process_broadcast(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text or message.caption

    if not text:
        await message.answer(
            "❌ Для рассылки сейчас поддерживается текст."
        )
        return

    users = get_all_users()

    sent = 0
    failed = 0

    await message.answer(
        f"📢 Начинаю рассылку...\n"
        f"👥 Получателей: {len(users)}"
    )

    for user_id in users:
        try:
            await bot.send_message(
                user_id,
                text
            )

            sent += 1

            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

    await state.clear()

    await message.answer(
        "📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>"
    )


# =========================================================
# ACCEPT / REJECT
# =========================================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_application(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    application_id = int(
        callback.data.split(":")[1]
    )

    application = get_application(application_id)

    if not application:
        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )
        return

    status = application[8]

    if status != "pending":
        await callback.answer(
            f"Заявка уже обработана: {status}",
            show_alert=True
        )
        return

    await state.update_data(
        application_id=application_id,
        decision="accepted"
    )

    await state.set_state(
        AdminDecision.waiting_message
    )

    await callback.answer()

    await callback.message.answer(
        "✅ <b>Заявка будет ПРИНЯТА.</b>\n\n"
        "Напиши сообщение, которое хочешь отправить "
        "пользователю.\n\n"
        "После этого бот:\n"
        "🔐 сгенерирует уникальный код;\n"
        "📧 покажет Gmail пользователя;\n"
        "📋 подготовит готовый текст письма."
    )


@dp.callback_query(F.data.startswith("reject:"))
async def reject_application(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )
        return

    application_id = int(
        callback.data.split(":")[1]
    )

    application = get_application(application_id)

    if not application:
        await callback.answer(
            "Заявка не найдена.",
            show_alert=True
        )
        return

    status = application[8]

    if status != "pending":
        await callback.answer(
            f"Заявка уже обработана: {status}",
            show_alert=True
        )
        return

    await state.update_data(
        application_id=application_id,
        decision="rejected"
    )

    await state.set_state(
        AdminDecision.waiting_message
    )

    await callback.answer()

    await callback.message.answer(
        "❌ <b>Заявка будет ОТКЛОНЕНА.</b>\n\n"
        "Напиши сообщение, которое отправить пользователю.\n\n"
        "Например:\n"
        "<i>К сожалению, сейчас мы не можем принять "
        "тебя. Попробуй подать заявку снова через 2 часа.</i>"
    )


# =========================================================
# ADMIN DECISION MESSAGE
# =========================================================

@dp.message(AdminDecision.waiting_message)
async def admin_decision_message(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()

    application_id = data.get("application_id")
    decision = data.get("decision")

    if not application_id or not decision:
        await state.clear()
        return

    decision_message = message.text.strip()

    application = get_application(application_id)

    if not application:
        await message.answer(
            "❌ Заявка больше не найдена."
        )
        await state.clear()
        return

    (
        app_id,
        user_id,
        username,
        nickname,
        reason,
        loyal,
        pvp,
        age,
        status,
        email,
        old_code,
        created_at,
        decided_at,
        old_message
    ) = application

    if status != "pending":
        await message.answer(
            "⚠️ Эта заявка уже была обработана."
        )
        await state.clear()
        return

    if decision == "accepted":
        join_code = generate_join_code()

        update_application(
            application_id=application_id,
            status="accepted",
            decision_message=decision_message,
            join_code=join_code
        )

        try:
            await bot.send_message(
                user_id,
                "🎉 <b>ПОЗДРАВЛЯЕМ!</b>\n\n"
                "💗 Твоя заявка в клан "
                "<b>«Крутяшки»</b> принята!\n\n"
                f"💬 Сообщение администрации:\n"
                f"{escape(decision_message)}\n\n"
                "📧 Администратор отправит код вступления "
                "на указанную тобой Gmail-почту."
            )

            user_sent = True

        except Exception:
            user_sent = False

        email_text = (
            "Здравствуйте! 🌸\n\n"
            f"Ваша заявка в клан «Крутяшки» была принята.\n\n"
            f"Ваш код вступления:\n"
            f"{join_code}\n\n"
            f"Сообщение от администрации:\n"
            f"{decision_message}\n\n"
            "Добро пожаловать! 💗"
        )

        await message.answer(
            "🎉 <b>ЗАЯВКА ПРИНЯТА</b>\n\n"
            f"🆔 Заявка: <code>#{application_id}</code>\n"
            f"🎮 Minecraft: <b>{escape(nickname)}</b>\n\n"
            f"📧 Gmail:\n"
            f"<code>{escape(email or 'не указана')}</code>\n\n"
            f"🔐 <b>КОД ВСТУПЛЕНИЯ:</b>\n"
            f"<code>{join_code}</code>\n\n"
            "📋 <b>ГОТОВЫЙ ТЕКСТ ПИСЬМА:</b>\n\n"
            f"<code>{escape(email_text)}</code>\n\n"
            + (
                "✅ Пользователь уведомлён в Telegram."
                if user_sent
                else "⚠️ Не удалось отправить сообщение пользователю."
            ),
            reply_markup=admin_keyboard()
        )

    else:
        update_application(
            application_id=application_id,
            status="rejected",
            decision_message=decision_message,
            join_code=None
        )

        try:
            await bot.send_message(
                user_id,
                "💔 <b>Заявка отклонена</b>\n\n"
                f"{escape(decision_message)}\n\n"
                "⏰ Повторно подать заявку можно через 2 часа."
            )

            user_sent = True

        except Exception:
            user_sent = False

        await message.answer(
            "❌ <b>ЗАЯВКА ОТКЛОНЕНА</b>\n\n"
            f"🆔 Заявка: <code>#{application_id}</code>\n"
            f"🎮 Minecraft: <b>{escape(nickname)}</b>\n\n"
            + (
                "✅ Пользователь уведомлён."
                if user_sent
                else "⚠️ Не удалось уведомить пользователя."
            ),
            reply_markup=admin_keyboard()
        )

    await state.clear()


# =========================================================
# CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel_command(
    message: Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Текущее действие отменено."
    )


# =========================================================
# BLOCKED USERS
# =========================================================

@dp.message()
async def blocked_check(message: Message):
    if message.from_user.id == ADMIN_ID:
        return

    save_user(message)

    if is_blocked(message.from_user.id):
        await message.answer(
            "🚫 Доступ к боту ограничен администрацией."
        )


# =========================================================
# MAIN
# =========================================================

async def main():
    init_db()

    logging.info("Бот запущен.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
