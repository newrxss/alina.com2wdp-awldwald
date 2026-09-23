import asyncio
import logging
import os
import re
import secrets
import random
import sqlite3
from datetime import datetime, timedelta
from html import escape
from email.message import EmailMessage

import aiosmtplib

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
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

DB_FILE = os.getenv("DB_FILE", "krutyashki.sqlite3")

IMAGE_FILE = "alina.jpg"

OFFICIAL_CHANNEL = "https://t.me/alino4kaprincssss"
OFFICIAL_BOT = "https://t.me/krytyashki_clan_bot"
ALINA_USERNAME = "@alino4ka_princes"

REAPPLY_COOLDOWN_HOURS = 2


# =========================================================
# SMTP / GMAIL
# =========================================================

SMTP_HOST = os.getenv(
    "SMTP_HOST",
    "smtp-relay.brevo.com"
)

SMTP_PORT = int(
    os.getenv("SMTP_PORT", "587")
)

SMTP_LOGIN = os.getenv(
    "SMTP_LOGIN",
    ""
)

SMTP_PASSWORD = os.getenv(
    "SMTP_PASSWORD",
    ""
)

SMTP_FROM = os.getenv(
    "SMTP_FROM",
    ""
)

EMAIL_CODE_EXPIRE_MINUTES = 10


# =========================================================
# ЛОГИ
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN в переменных окружения Railway."
    )

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# =========================================================
# FSM
# =========================================================

class ApplicationForm(StatesGroup):
    nickname = State()
    reason = State()
    loyal = State()
    pvp = State()
    pve = State()
    age = State()
    email = State()
    email_code = State()


class AdminDecision(StatesGroup):
    message = State()


class AdminSearch(StatesGroup):
    application_id = State()


class AdminBlock(StatesGroup):
    user_id = State()


class AdminUnblock(StatesGroup):
    user_id = State()


class AdminBroadcast(StatesGroup):
    message = State()


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            nickname TEXT,
            reason TEXT,
            loyal TEXT,
            pvp INTEGER,
            pve INTEGER,
            age INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            decided_at TEXT,
            decision_message TEXT,
            email TEXT,
            join_code TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT,
            blocked INTEGER DEFAULT 0
        )
    """)

    cur.execute("PRAGMA table_info(applications)")
    columns = [row[1] for row in cur.fetchall()]

    if "pve" not in columns:
        cur.execute(
            "ALTER TABLE applications ADD COLUMN pve INTEGER"
        )

    if "email" not in columns:
        cur.execute(
            "ALTER TABLE applications ADD COLUMN email TEXT"
        )

    if "join_code" not in columns:
        cur.execute(
            "ALTER TABLE applications ADD COLUMN join_code TEXT"
        )

    conn.commit()
    conn.close()


# =========================================================
# USERS
# =========================================================

def save_user(message: Message):
    conn = get_db()
    cur = conn.cursor()

    now = datetime.now().isoformat()

    cur.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            created_at,
            blocked
        )
        VALUES (?, ?, ?, ?, 0)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        now
    ))

    conn.commit()
    conn.close()


def is_blocked(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT blocked FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()
    conn.close()

    return bool(row and row[0] == 1)


def set_blocked(user_id: int, value: bool):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            created_at,
            blocked
        )
        VALUES (?, '', '', ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            blocked = excluded.blocked
    """, (
        user_id,
        datetime.now().isoformat(),
        1 if value else 0
    ))

    conn.commit()
    conn.close()


def get_all_users():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id
        FROM users
        WHERE blocked = 0
    """)

    rows = cur.fetchall()
    conn.close()

    return [row[0] for row in rows]


# =========================================================
# DATABASE BACKUP
# =========================================================

def create_database_backup():
    if not os.path.exists(DB_FILE):
        return None

    backup_file = "krutyashki_backup.sqlite3"

    source = sqlite3.connect(DB_FILE)
    destination = sqlite3.connect(backup_file)

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    return backup_file


def get_database_info():

    if not os.path.exists(DB_FILE):
        return {
            "exists": False,
            "users": 0,
            "applications": 0,
            "blocked": 0,
            "pending": 0,
            "accepted": 0,
            "rejected": 0,
            "size": 0,
        }

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE blocked = 1
    """)
    blocked = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM applications")
    applications = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM applications
        WHERE status = 'pending'
    """)
    pending = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM applications
        WHERE status = 'accepted'
    """)
    accepted = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM applications
        WHERE status = 'rejected'
    """)
    rejected = cur.fetchone()[0]

    conn.close()

    return {
        "exists": True,
        "users": users,
        "applications": applications,
        "blocked": blocked,
        "pending": pending,
        "accepted": accepted,
        "rejected": rejected,
        "size": os.path.getsize(DB_FILE),
    }


# =========================================================
# APPLICATION HELPERS
# =========================================================

def get_last_rejected_application(user_id: int):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT decided_at
        FROM applications
        WHERE user_id = ?
          AND status = 'rejected'
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


def application_exists_pending(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM applications
        WHERE user_id = ?
          AND status = 'pending'
        LIMIT 1
    """, (user_id,))

    row = cur.fetchone()
    conn.close()

    return row is not None


def has_accepted_application(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM applications
        WHERE user_id = ?
          AND status = 'accepted'
        LIMIT 1
    """, (user_id,))

    row = cur.fetchone()
    conn.close()

    return row is not None


def generate_join_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    part1 = "".join(
        secrets.choice(alphabet)
        for _ in range(4)
    )

    part2 = "".join(
        secrets.choice(alphabet)
        for _ in range(4)
    )

    return f"KRUT-{part1}-{part2}"


# =========================================================
# EMAIL VERIFICATION
# =========================================================

async def send_email_verification_code(
    email: str,
    code: str
):
    if not SMTP_LOGIN:
        raise RuntimeError(
            "SMTP_LOGIN не указан в Railway Variables."
        )

    if not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP_PASSWORD не указан в Railway Variables."
        )

    if not SMTP_FROM:
        raise RuntimeError(
            "SMTP_FROM не указан в Railway Variables."
        )

    msg = EmailMessage()

    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg["Subject"] = "Подтверждение Gmail — Крутяшки"

    msg.set_content(
        f"""Здравствуйте!

Вы указали этот Gmail при подаче заявки в клан «Крутяшки».

Ваш код подтверждения:

{code}

Код действует {EMAIL_CODE_EXPIRE_MINUTES} минут.

Если вы не подавали заявку, просто проигнорируйте это письмо.

Клан «Крутяшки»
"""
    )

    # -----------------------------------------------------
    # ПОРТ 587
    # -----------------------------------------------------

    try:
        logger.info(
            "SMTP: подключение к %s:587",
            SMTP_HOST
        )

        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=587,
            username=SMTP_LOGIN,
            password=SMTP_PASSWORD,
            start_tls=True,
            timeout=15
        )

        logger.info(
            "SMTP: письмо отправлено через порт 587"
        )

        return

    except Exception as error_587:
        logger.warning(
            "SMTP: порт 587 не сработал: %s",
            error_587
        )

    # -----------------------------------------------------
    # ПОРТ 2525
    # -----------------------------------------------------

    try:
        logger.info(
            "SMTP: пробуем резервный порт 2525"
        )

        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=2525,
            username=SMTP_LOGIN,
            password=SMTP_PASSWORD,
            start_tls=True,
            timeout=15
        )

        logger.info(
            "SMTP: письмо отправлено через порт 2525"
        )

        return

    except Exception as error_2525:
        logger.exception(
            "SMTP: не удалось подключиться ни через 587, "
            "ни через 2525"
        )

        raise RuntimeError(
            "Brevo SMTP недоступен через порты 587 и 2525."
        ) from error_2525


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
            ],
            [
                InlineKeyboardButton(
                    text="🔐 Проверить официальный бот",
                    callback_data="official_bot"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Официальный канал",
                    url=OFFICIAL_CHANNEL
                )
            ]
        ]
    )


def official_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Официальный бот",
                    url=OFFICIAL_BOT
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Официальный канал",
                    url=OFFICIAL_CHANNEL
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main"
                )
            ]
        ]
    )


def loyal_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💗 Да",
                    callback_data="loyal_yes"
                ),
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data="loyal_no"
                )
            ]
        ]
    )


def rating_keyboard(prefix: str):
    buttons = []

    for start in (1, 6):
        row = []

        for number in range(start, start + 5):
            row.append(
                InlineKeyboardButton(
                    text=str(number),
                    callback_data=f"{prefix}_{number}"
                )
            )

        buttons.append(row)

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


def admin_application_keyboard(app_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept_{app_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_{app_id}"
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
                    text="📥 Заявки",
                    callback_data="admin_pending"
                ),
                InlineKeyboardButton(
                    text="🗂 Последние",
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
                    text="🚫 Заблокировать",
                    callback_data="admin_block"
                ),
                InlineKeyboardButton(
                    text="🔓 Разблокировать",
                    callback_data="admin_unblock"
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
async def start_handler(
    message: Message,
    state: FSMContext
):
    await state.clear()

    save_user(message)

    if is_blocked(message.from_user.id):
        await message.answer(
            "🚫 <b>Доступ ограничен.</b>\n\n"
            "Вы не можете использовать этого бота."
        )
        return

    splash = await message.answer(
        "✓ <b>Официальный бот Алины</b>\n\n"
        "Загрузка..."
    )

    await asyncio.sleep(3)

    loading_frames = [
        "Загрузка.\n\n▫️▫️▫️▫️▫️",
        "Загрузка..\n\n🟩▫️▫️▫️▫️",
        "Загрузка...\n\n🟩🟩▫️▫️▫️",
        "Загрузка...\n\n🟩🟩🟩▫️▫️",
        "Загрузка...\n\n🟩🟩🟩🟩▫️",
        "Загрузка...\n\n🟩🟩🟩🟩🟩",
    ]

    for frame in loading_frames:
        try:
            await splash.edit_text(
                "✓ <b>Официальный бот Алины</b>\n\n"
                f"{frame}"
            )
        except Exception:
            pass

        await asyncio.sleep(5 / len(loading_frames))

    text = (
        "💗 <b>Добро пожаловать!</b>\n\n"
        "Это официальный бот клана <b>Крутяшки</b>.\n\n"
        "Здесь ты можешь подать заявку на вступление "
        "и узнать информацию о клане.\n\n"
        f"👑 Создатель: {ALINA_USERNAME}"
    )

    try:
        if os.path.exists(IMAGE_FILE):
            await splash.delete()

            await message.answer_photo(
                photo=FSInputFile(IMAGE_FILE),
                caption=text,
                reply_markup=main_keyboard()
            )
        else:
            await splash.edit_text(
                text,
                reply_markup=main_keyboard()
            )

    except Exception as e:
        logger.error(
            "Ошибка отправки главного меню: %s",
            e
        )

        try:
            await splash.edit_text(
                text,
                reply_markup=main_keyboard()
            )
        except Exception:
            pass


# =========================================================
# OFFICIAL BOT
# =========================================================

@dp.callback_query(F.data == "official_bot")
async def official_bot_handler(callback: CallbackQuery):
    text = (
        "🔐 <b>Проверка официальности</b>\n\n"
        "✅ Вы находитесь в официальном боте "
        "клана <b>Крутяшки</b>.\n\n"
        "🤖 Официальный бот:\n"
        "<code>@krytyashki_clan_bot</code>\n\n"
        "📢 Официальный канал:\n"
        "<code>@alino4kaprincssss</code>\n\n"
        "⚠️ Если другой бот использует наше название, "
        "оформление, изображения или тексты — "
        "проверяйте его через официальный канал."
    )

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=official_keyboard()
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=official_keyboard()
        )

    await callback.answer()


# =========================================================
# BACK MAIN
# =========================================================

@dp.callback_query(F.data == "back_main")
async def back_main_handler(callback: CallbackQuery):
    text = (
        "💗 <b>Добро пожаловать!</b>\n\n"
        "Это официальный бот клана <b>Крутяшки</b>.\n\n"
        "Здесь ты можешь подать заявку на вступление "
        "и узнать информацию о клане.\n\n"
        f"👑 Создатель: {ALINA_USERNAME}"
    )

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=main_keyboard()
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=main_keyboard()
        )

    await callback.answer()


# =========================================================
# ABOUT
# =========================================================

@dp.callback_query(F.data == "about")
async def about_handler(callback: CallbackQuery):
    text = (
        "👑 <b>Обо мне</b>\n\n"
        "Я — бот-помощник клана <b>Крутяшки</b>.\n\n"
        "Здесь можно подать заявку на вступление "
        "в клан Алины.\n\n"
        "💗 Оригинал Алины:\n"
        f"{ALINA_USERNAME}\n\n"
        "📢 Официальный канал:\n"
        "<code>@alino4kaprincssss</code>\n\n"
        "🤖 Официальный бот:\n"
        "<code>@krytyashki_clan_bot</code>\n\n"
        "✨ Бот создан специально для удобного "
        "приёма заявок и общения с участниками."
    )

    if callback.message.photo:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=main_keyboard()
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=main_keyboard()
        )

    await callback.answer()


# =========================================================
# JOIN
# =========================================================

@dp.callback_query(F.data == "join")
async def join_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    user_id = callback.from_user.id

    if is_blocked(user_id):
        await callback.answer(
            "Доступ ограничен.",
            show_alert=True
        )
        return

    if has_accepted_application(user_id):
        await callback.answer(
            "Вы уже приняты в клан!",
            show_alert=True
        )
        return

    if application_exists_pending(user_id):
        await callback.answer(
            "Ваша заявка уже находится на рассмотрении.",
            show_alert=True
        )
        return

    last_rejected = get_last_rejected_application(user_id)

    if last_rejected:
        try:
            rejected_time = datetime.fromisoformat(last_rejected)

            if datetime.now() < rejected_time + timedelta(
                hours=REAPPLY_COOLDOWN_HOURS
            ):
                remaining = (
                    rejected_time
                    + timedelta(hours=REAPPLY_COOLDOWN_HOURS)
                    - datetime.now()
                )

                minutes = max(
                    1,
                    int(remaining.total_seconds() // 60)
                )

                await callback.answer(
                    f"Повторно подать заявку можно примерно "
                    f"через {minutes} мин.",
                    show_alert=True
                )
                return

        except Exception:
            pass

    await state.set_state(ApplicationForm.nickname)

    await callback.message.answer(
        "💗 <b>Заявка на вступление</b>\n\n"
        "Шаг 1 из 7\n\n"
        "🎮 Напиши свой <b>Minecraft ник</b>:"
    )

    await callback.answer()


# =========================================================
# NICKNAME
# =========================================================

@dp.message(ApplicationForm.nickname)
async def nickname_handler(
    message: Message,
    state: FSMContext
):
    if is_blocked(message.from_user.id):
        await message.answer("🚫 Доступ ограничен.")
        await state.clear()
        return

    nickname = (message.text or "").strip()

    if len(nickname) < 2 or len(nickname) > 32:
        await message.answer(
            "❌ Ник должен содержать от 2 до 32 символов.\n"
            "Попробуй ещё раз:"
        )
        return

    await state.update_data(nickname=nickname)
    await state.set_state(ApplicationForm.reason)

    await message.answer(
        "📝 <b>Шаг 2 из 7</b>\n\n"
        "Почему ты хочешь вступить в клан?"
    )


# =========================================================
# REASON
# =========================================================

@dp.message(ApplicationForm.reason)
async def reason_handler(
    message: Message,
    state: FSMContext
):
    reason = (message.text or "").strip()

    if len(reason) < 3:
        await message.answer(
            "Напиши немного подробнее, почему хочешь вступить:"
        )
        return

    await state.update_data(reason=reason)
    await state.set_state(ApplicationForm.loyal)

    await message.answer(
        "💗 <b>Шаг 3 из 7</b>\n\n"
        "Готов ли ты быть верным клану и уважать Алину?",
        reply_markup=loyal_keyboard()
    )


# =========================================================
# LOYAL
# =========================================================

@dp.callback_query(
    ApplicationForm.loyal,
    F.data.in_({"loyal_yes", "loyal_no"})
)
async def loyal_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    loyal = "Да" if callback.data == "loyal_yes" else "Нет"

    await state.update_data(loyal=loyal)
    await state.set_state(ApplicationForm.pvp)

    await callback.message.answer(
        "⚔️ <b>Шаг 4 из 7</b>\n\n"
        "Оцени свой <b>PvP</b> от 1 до 10:\n\n"
        "1 — начинающий\n"
        "10 — очень сильный игрок",
        reply_markup=rating_keyboard("pvp")
    )

    await callback.answer()


# =========================================================
# PVP
# =========================================================

@dp.callback_query(
    ApplicationForm.pvp,
    F.data.regexp(r"^pvp_(10|[1-9])$")
)
async def pvp_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    pvp = int(callback.data.split("_")[1])

    await state.update_data(pvp=pvp)
    await state.set_state(ApplicationForm.pve)

    await callback.message.answer(
        "⛏️ <b>Шаг 5 из 7</b>\n\n"
        "Оцени свои навыки <b>PvE</b> от 1 до 10:\n\n"
        "1 — начинающий\n"
        "10 — очень сильный игрок",
        reply_markup=rating_keyboard("pve")
    )

    await callback.answer()


# =========================================================
# PVE
# =========================================================

@dp.callback_query(
    ApplicationForm.pve,
    F.data.regexp(r"^pve_(10|[1-9])$")
)
async def pve_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    pve = int(callback.data.split("_")[1])

    await state.update_data(pve=pve)
    await state.set_state(ApplicationForm.age)

    await callback.message.answer(
        "🎂 <b>Шаг 6 из 7</b>\n\n"
        "Сколько тебе лет?"
    )

    await callback.answer()


# =========================================================
# AGE
# =========================================================

@dp.message(ApplicationForm.age)
async def age_handler(
    message: Message,
    state: FSMContext
):
    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer(
            "❌ Напиши возраст числом."
        )
        return

    age = int(text)

    if age < 1 or age > 100:
        await message.answer(
            "❌ Укажи корректный возраст."
        )
        return

    await state.update_data(age=age)
    await state.set_state(ApplicationForm.email)

    await message.answer(
        "📧 <b>Шаг 7 из 7</b>\n\n"
        "Укажи свой Gmail для связи:\n\n"
        "Например:\n"
        "<code>example@gmail.com</code>"
    )


# =========================================================
# EMAIL
# =========================================================

@dp.message(ApplicationForm.email)
async def email_handler(
    message: Message,
    state: FSMContext
):
    email = (message.text or "").strip().lower()

    if not re.fullmatch(
        r"[a-zA-Z0-9._%+-]+@gmail\.com",
        email
    ):
        await message.answer(
            "❌ Нужен именно адрес Gmail.\n\n"
            "Пример:\n"
            "<code>example@gmail.com</code>"
        )
        return

    if not SMTP_LOGIN or not SMTP_PASSWORD or not SMTP_FROM:
        logger.error(
            "SMTP настроен не полностью."
        )

        await message.answer(
            "❌ Система подтверждения Gmail сейчас "
            "не настроена администрацией.\n\n"
            "Попробуй позже."
        )
        return

    code = str(
        random.randint(100000, 999999)
    )

    status_message = await message.answer(
        "📨 <b>Отправляю код на Gmail...</b>\n\n"
        "Это может занять несколько секунд."
    )

    try:
        await send_email_verification_code(
            email,
            code
        )

    except Exception as e:
        logger.exception(
            "Ошибка отправки Gmail-кода: %s",
            e
        )

        try:
            await status_message.edit_text(
                "❌ <b>Не удалось отправить код.</b>\n\n"
                "Проверь Gmail и попробуй ещё раз.\n\n"
                "Если проблема повторяется — сообщи администрации."
            )
        except Exception:
            await message.answer(
                "❌ Не удалось отправить код.\n\n"
                "Попробуй ещё раз."
            )

        return

    await state.update_data(
        verification_email=email,
        verification_code=code,
        verification_created_at=datetime.now().isoformat()
    )

    await state.set_state(
        ApplicationForm.email_code
    )

    try:
        await status_message.edit_text(
            "📨 <b>Код отправлен!</b>\n\n"
            f"Мы отправили 6-значный код на:\n"
            f"<code>{escape(email)}</code>\n\n"
            "Введи код из письма сюда.\n\n"
            f"⏱ Код действует "
            f"{EMAIL_CODE_EXPIRE_MINUTES} минут."
        )
    except Exception:
        await message.answer(
            "📨 <b>Код отправлен!</b>\n\n"
            f"Введи код из письма.\n\n"
            f"⏱ Код действует "
            f"{EMAIL_CODE_EXPIRE_MINUTES} минут."
        )


# =========================================================
# EMAIL CODE
# =========================================================

@dp.message(ApplicationForm.email_code)
async def email_code_handler(
    message: Message,
    state: FSMContext
):
    code = (message.text or "").strip()

    if not re.fullmatch(r"\d{6}", code):
        await message.answer(
            "❌ Код должен состоять из 6 цифр.\n\n"
            "Попробуй ещё раз:"
        )
        return

    data = await state.get_data()

    saved_code = data.get("verification_code")
    created_at_text = data.get("verification_created_at")
    email = data.get("verification_email")

    if not saved_code or not created_at_text or not email:
        await state.clear()

        await message.answer(
            "❌ Сессия подтверждения истекла.\n\n"
            "Начни подачу заявки заново."
        )
        return

    try:
        created_at = datetime.fromisoformat(
            created_at_text
        )
    except Exception:
        await state.clear()

        await message.answer(
            "❌ Ошибка проверки кода.\n\n"
            "Начни заявку заново."
        )
        return

    if datetime.now() > created_at + timedelta(
        minutes=EMAIL_CODE_EXPIRE_MINUTES
    ):
        await state.clear()

        await message.answer(
            "⌛ <b>Код истёк.</b>\n\n"
            "Начни заявку заново, чтобы получить новый код."
        )
        return

    if code != saved_code:
        await message.answer(
            "❌ Неверный код.\n\n"
            "Проверь письмо и введи код ещё раз."
        )
        return

    now = datetime.now().isoformat()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO applications (
            user_id,
            username,
            nickname,
            reason,
            loyal,
            pvp,
            pve,
            age,
            status,
            created_at,
            email,
            join_code
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        message.from_user.username,
        data["nickname"],
        data["reason"],
        data["loyal"],
        data["pvp"],
        data["pve"],
        data["age"],
        "pending",
        now,
        email,
        None
    ))

    application_id = cur.lastrowid

    conn.commit()
    conn.close()

    await state.clear()

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "нет username"
    )

    admin_text = (
        "📥 <b>Новая заявка!</b>\n\n"
        f"🆔 Заявка: <code>#{application_id}</code>\n"
        f"👤 Telegram: {escape(username)}\n"
        f"🆔 User ID: <code>{message.from_user.id}</code>\n\n"
        f"🎮 Minecraft: <b>{escape(data['nickname'])}</b>\n"
        f"📝 Причина: {escape(data['reason'])}\n"
        f"💗 Верность: <b>{escape(data['loyal'])}</b>\n"
        f"⚔️ PvP: <b>{data['pvp']}/10</b>\n"
        f"⛏️ PvE: <b>{data['pve']}/10</b>\n"
        f"🎂 Возраст: <b>{data['age']}</b>\n"
        f"📧 Gmail: <code>{escape(email)}</code>\n"
        "✅ Gmail подтверждён\n\n"
        "Выберите решение:"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=admin_application_keyboard(
                application_id
            )
        )

    except Exception as e:
        logger.error(
            "Не удалось отправить заявку админу: %s",
            e
        )

    await message.answer(
        "✅ <b>Gmail подтверждён!</b>\n\n"
        "📥 <b>Заявка отправлена администрации.</b>\n\n"
        "Теперь её рассмотрит администрация клана.\n"
        "Ожидай решения 💗"
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "👑 <b>Панель администратора</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_keyboard()
    )


@dp.message(Command("dbinfo"))
async def dbinfo_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    info = get_database_info()

    if not info["exists"]:
        await message.answer(
            "❌ Файл базы данных не найден.\n\n"
            f"Путь: <code>{escape(os.path.abspath(DB_FILE))}</code>"
        )
        return

    size_kb = info["size"] / 1024

    await message.answer(
        "📊 <b>Информация о базе</b>\n\n"
        f"👥 Пользователей: <b>{info['users']}</b>\n"
        f"🚫 Заблокировано: <b>{info['blocked']}</b>\n\n"
        f"📨 Всего заявок: <b>{info['applications']}</b>\n"
        f"📥 На рассмотрении: <b>{info['pending']}</b>\n"
        f"✅ Принято: <b>{info['accepted']}</b>\n"
        f"❌ Отклонено: <b>{info['rejected']}</b>\n\n"
        f"💾 Размер: <b>{size_kb:.2f} KB</b>\n"
        f"📁 Файл: <code>{escape(os.path.abspath(DB_FILE))}</code>"
    )


@dp.message(Command("backupdb"))
async def backupdb_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "💾 Создаю резервную копию базы..."
    )

    try:
        backup_file = create_database_backup()

        if not backup_file or not os.path.exists(backup_file):
            await message.answer(
                "❌ Не удалось создать резервную копию."
            )
            return

        info = get_database_info()

        await message.answer_document(
            FSInputFile(backup_file),
            caption=(
                "💾 <b>Резервная копия базы «Крутяшки»</b>\n\n"
                f"👥 Пользователей: {info['users']}\n"
                f"📨 Заявок: {info['applications']}\n\n"
                "Сохрани этот файл в безопасном месте."
            )
        )

        try:
            os.remove(backup_file)
        except Exception:
            pass

    except Exception as e:
        logger.exception(
            "Ошибка создания backup: %s",
            e
        )

        await message.answer(
            "❌ Ошибка создания резервной копии:\n"
            f"<code>{escape(str(e))}</code>"
        )


# =========================================================
# ADMIN STATS
# =========================================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM applications")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM applications
        WHERE status = 'pending'
    """)
    pending = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM applications
        WHERE status = 'accepted'
    """)
    accepted = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM applications
        WHERE status = 'rejected'
    """)
    rejected = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM users
        WHERE blocked = 1
    """)
    blocked = cur.fetchone()[0]

    conn.close()

    await callback.message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{users}</b>\n"
        f"🚫 Заблокировано: <b>{blocked}</b>\n\n"
        f"📨 Всего заявок: <b>{total}</b>\n"
        f"📥 На рассмотрении: <b>{pending}</b>\n"
        f"✅ Принято: <b>{accepted}</b>\n"
        f"❌ Отклонено: <b>{rejected}</b>"
    )

    await callback.answer()


# =========================================================
# ADMIN PENDING
# =========================================================

@dp.callback_query(F.data == "admin_pending")
async def admin_pending(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, user_id, nickname, pvp, pve, created_at
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer(
            "📥 Новых заявок нет."
        )
        await callback.answer()
        return

    text = "📥 <b>Заявки на рассмотрении</b>\n\n"

    for row in rows:
        app_id, user_id, nickname, pvp, pve, created_at = row

        text += (
            f"🆔 <code>#{app_id}</code>\n"
            f"🎮 {escape(nickname)}\n"
            f"⚔️ PvP: {pvp}/10 | ⛏️ PvE: {pve}/10\n"
            f"👤 ID: <code>{user_id}</code>\n"
            f"🕐 {created_at[:16]}\n\n"
        )

    await callback.message.answer(text)
    await callback.answer()


# =========================================================
# ADMIN RECENT
# =========================================================

@dp.callback_query(F.data == "admin_recent")
async def admin_recent(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, nickname, status, created_at
        FROM applications
        ORDER BY id DESC
        LIMIT 15
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer(
            "🗂 Заявок пока нет."
        )
        await callback.answer()
        return

    text = "🗂 <b>Последние заявки</b>\n\n"

    status_names = {
        "pending": "📥 На рассмотрении",
        "accepted": "✅ Принята",
        "rejected": "❌ Отклонена"
    }

    for app_id, nickname, status, created_at in rows:
        text += (
            f"<code>#{app_id}</code> "
            f"<b>{escape(nickname)}</b>\n"
            f"{status_names.get(status, status)}\n"
            f"🕐 {created_at[:16]}\n\n"
        )

    await callback.message.answer(text)
    await callback.answer()


# =========================================================
# ADMIN SEARCH
# =========================================================

@dp.callback_query(F.data == "admin_search")
async def admin_search_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        return

    await state.set_state(AdminSearch.application_id)

    await callback.message.answer(
        "🔎 Введи ID заявки.\n\n"
        "Например:\n"
        "<code>15</code>"
    )

    await callback.answer()


@dp.message(AdminSearch.application_id)
async def admin_search_result(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer(
            "❌ ID должен быть числом."
        )
        return

    app_id = int(text)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            username,
            nickname,
            reason,
            loyal,
            pvp,
            pve,
            age,
            status,
            created_at,
            decided_at,
            decision_message,
            email,
            join_code
        FROM applications
        WHERE id = ?
    """, (app_id,))

    row = cur.fetchone()
    conn.close()

    await state.clear()

    if not row:
        await message.answer(
            "❌ Заявка не найдена."
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
        pve,
        age,
        status,
        created_at,
        decided_at,
        decision_message,
        email,
        join_code
    ) = row

    await message.answer(
        "🔎 <b>Заявка найдена</b>\n\n"
        f"🆔 #{app_id}\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"👤 Username: @{escape(username or 'нет')}\n"
        f"🎮 Minecraft: <b>{escape(nickname)}</b>\n"
        f"📝 Причина: {escape(reason)}\n"
        f"💗 Верность: {escape(loyal)}\n"
        f"⚔️ PvP: {pvp}/10\n"
        f"⛏️ PvE: {pve}/10\n"
        f"🎂 Возраст: {age}\n"
        f"📧 Gmail: <code>{escape(email or 'нет')}</code>\n"
        f"🔑 Код: <code>{escape(join_code or 'ещё нет')}</code>\n"
        f"📌 Статус: <b>{escape(status)}</b>\n"
        f"🕐 Создана: {created_at}"
    )


# =========================================================
# ADMIN USERS
# =========================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, username, first_name, blocked
        FROM users
        ORDER BY created_at DESC
        LIMIT 30
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer(
            "👥 Пользователей пока нет."
        )
        await callback.answer()
        return

    text = "👥 <b>Пользователи</b>\n\n"

    for user_id, username, first_name, blocked in rows:
        status = "🚫" if blocked else "✅"

        text += (
            f"{status} <code>{user_id}</code> — "
            f"{escape(first_name or '')} "
            f"@{escape(username or 'нет')}\n"
        )

    await callback.message.answer(text)
    await callback.answer()


# =========================================================
# BLOCK
# =========================================================

@dp.callback_query(F.data == "admin_block")
async def admin_block_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        return

    await state.set_state(AdminBlock.user_id)

    await callback.message.answer(
        "🚫 Введи Telegram ID пользователя:"
    )

    await callback.answer()


@dp.message(AdminBlock.user_id)
async def admin_block_process(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer(
            "❌ Telegram ID должен быть числом."
        )
        return

    user_id = int(text)

    if user_id == ADMIN_ID:
        await message.answer(
            "❌ Нельзя заблокировать владельца."
        )
        await state.clear()
        return

    set_blocked(user_id, True)

    await state.clear()

    await message.answer(
        f"🚫 Пользователь <code>{user_id}</code> заблокирован."
    )


# =========================================================
# UNBLOCK
# =========================================================

@dp.callback_query(F.data == "admin_unblock")
async def admin_unblock_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        return

    await state.set_state(AdminUnblock.user_id)

    await callback.message.answer(
        "🔓 Введи Telegram ID пользователя:"
    )

    await callback.answer()


@dp.message(AdminUnblock.user_id)
async def admin_unblock_process(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer(
            "❌ Telegram ID должен быть числом."
        )
        return

    user_id = int(text)

    set_blocked(user_id, False)

    await state.clear()

    await message.answer(
        f"🔓 Пользователь <code>{user_id}</code> разблокирован."
    )


# =========================================================
# BROADCAST
# =========================================================

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        return

    await state.set_state(AdminBroadcast.message)

    await callback.message.answer(
        "📢 Напиши сообщение для рассылки:"
    )

    await callback.answer()


@dp.message(AdminBroadcast.message)
async def admin_broadcast_process(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    text = (message.text or "").strip()

    if not text:
        await message.answer(
            "❌ Сообщение не может быть пустым."
        )
        return

    users = get_all_users()

    sent = 0
    failed = 0

    for user_id in users:
        try:
            await bot.send_message(
                user_id,
                text
            )

            sent += 1
            await asyncio.sleep(0.05)

        except Exception as e:
            failed += 1

            logger.warning(
                "Рассылка не отправлена пользователю %s: %s",
                user_id,
                e
            )

    await state.clear()

    await message.answer(
        "📢 <b>Рассылка завершена</b>\n\n"
        f"👥 Пользователей в базе: <b>{len(users)}</b>\n"
        f"✅ Отправлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>"
    )


# =========================================================
# ACCEPT / REJECT
# =========================================================

@dp.callback_query(
    F.data.regexp(r"^(accept|reject)_\d+$")
)
async def admin_decision_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        return

    action, app_id_text = callback.data.split("_")
    app_id = int(app_id_text)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, nickname
        FROM applications
        WHERE id = ?
          AND status = 'pending'
    """, (app_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        await callback.answer(
            "Заявка уже обработана или не найдена.",
            show_alert=True
        )
        return

    user_id, nickname = row

    await state.update_data(
        application_id=app_id,
        decision=(
            "accepted"
            if action == "accept"
            else "rejected"
        ),
        target_user_id=user_id,
        nickname=nickname
    )

    await state.set_state(AdminDecision.message)

    title = (
        "✅ Принятие заявки"
        if action == "accept"
        else "❌ Отклонение заявки"
    )

    await callback.message.answer(
        f"<b>{title}</b>\n\n"
        f"Заявка: <code>#{app_id}</code>\n"
        f"Игрок: <b>{escape(nickname)}</b>\n\n"
        "Напиши сообщение, которое будет отправлено игроку."
    )

    await callback.answer()


# =========================================================
# ADMIN DECISION MESSAGE
# =========================================================

@dp.message(AdminDecision.message)
async def admin_decision_process(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return

    decision_message = (message.text or "").strip()

    if not decision_message:
        await message.answer(
            "❌ Сообщение не может быть пустым."
        )
        return

    data = await state.get_data()

    app_id = data["application_id"]
    decision = data["decision"]
    user_id = data["target_user_id"]

    conn = get_db()
    cur = conn.cursor()

    now = datetime.now().isoformat()
    join_code = None

    if decision == "accepted":
        join_code = generate_join_code()

        cur.execute("""
            UPDATE applications
            SET status = ?,
                decided_at = ?,
                decision_message = ?,
                join_code = ?
            WHERE id = ?
        """, (
            "accepted",
            now,
            decision_message,
            join_code,
            app_id
        ))

    else:
        cur.execute("""
            UPDATE applications
            SET status = ?,
                decided_at = ?,
                decision_message = ?
            WHERE id = ?
        """, (
            "rejected",
            now,
            decision_message,
            app_id
        ))

    cur.execute("""
        SELECT
            nickname,
            email,
            reason,
            loyal,
            pvp,
            pve,
            age,
            username
        FROM applications
        WHERE id = ?
    """, (app_id,))

    application = cur.fetchone()

    conn.commit()
    conn.close()

    await state.clear()

    if decision == "accepted":

        user_text = (
            "🎉 <b>Твоя заявка принята!</b>\n\n"
            f"{escape(decision_message)}\n\n"
            "💗 Добро пожаловать в клан <b>Крутяшки</b>!\n\n"
            "🔑 Твой код вступления:\n"
            f"<code>{join_code}</code>\n\n"
            "Сохрани этот код."
        )

        try:
            await bot.send_message(
                user_id,
                user_text
            )
        except Exception as e:
            logger.error(
                "Не удалось уведомить пользователя: %s",
                e
            )

        (
            nickname,
            email,
            reason,
            loyal,
            pvp,
            pve,
            age,
            username
        ) = application

        email_text = (
            "📧 <b>Готовый текст для отправки на Gmail</b>\n\n"
            f"Кому: <code>{escape(email or '')}</code>\n\n"
            "Текст:\n"
            "<code>"
            "Здравствуйте! Вы были приняты в клан «Крутяшки».\n\n"
            f"Ваш Minecraft ник: {escape(nickname)}\n"
            f"Код вступления: {join_code}\n\n"
            "Сохраните этот код."
            "</code>"
        )

        await message.answer(
            "✅ <b>Заявка принята.</b>\n\n"
            f"Пользователь: <code>{user_id}</code>\n"
            f"Код: <code>{join_code}</code>\n\n"
            f"{email_text}"
        )

    else:

        try:
            await bot.send_message(
                user_id,
                "❌ <b>Заявка отклонена.</b>\n\n"
                f"{escape(decision_message)}\n\n"
                "Повторно подать заявку можно через "
                f"<b>{REAPPLY_COOLDOWN_HOURS} часа</b>."
            )
        except Exception as e:
            logger.error(
                "Не удалось уведомить пользователя: %s",
                e
            )

        await message.answer(
            f"❌ Заявка <code>#{app_id}</code> отклонена."
        )


# =========================================================
# CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel_handler(
    message: Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Текущее действие отменено."
    )


# =========================================================
# BLOCKED / OTHER
# =========================================================

@dp.message()
async def blocked_handler(message: Message):
    if message.from_user.id == ADMIN_ID:
        return

    save_user(message)

    if is_blocked(message.from_user.id):
        await message.answer(
            "🚫 <b>Доступ ограничен.</b>\n\n"
            "Вы не можете использовать этого бота."
        )


# =========================================================
# MAIN
# =========================================================

async def main():
    init_db()

    me = await bot.get_me()

    logger.info(
        "Бот запущен: @%s | ID: %s",
        me.username,
        me.id
    )

    logger.info(
        "SQLite database: %s",
        os.path.abspath(DB_FILE)
    )

    info = get_database_info()

    logger.info(
        "DB INFO | users=%s | applications=%s",
        info["users"],
        info["applications"]
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
      
