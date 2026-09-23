import asyncio
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from html import escape

import aiohttp

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

# Railway Variable:
# DB_FILE=/data/krutyashki.sqlite3
#
# ВАЖНО:
# Эта программа НЕ удаляет и НЕ пересоздаёт существующую базу.
DB_FILE = os.getenv("DB_FILE", "krutyashki.sqlite3")

IMAGE_FILE = "alina.jpg"

OFFICIAL_CHANNEL = "https://t.me/alino4kaprincssss"
OFFICIAL_BOT = "https://t.me/krytyashki_clan_bot"
ALINA_USERNAME = "@alino4ka_princes"

REAPPLY_COOLDOWN_HOURS = 2


# =========================================================
# BREVO API
# =========================================================

BREVO_API_KEY = os.getenv(
    "BREVO_API_KEY",
    ""
).strip()

BREVO_FROM_EMAIL = os.getenv(
    "BREVO_FROM_EMAIL",
    ""
).strip()

BREVO_FROM_NAME = os.getenv(
    "BREVO_FROM_NAME",
    "Крутяшки"
).strip()

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

EMAIL_CODE_EXPIRE_MINUTES = 10
EMAIL_REQUEST_TIMEOUT = 15


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
    """
    Создаёт таблицы только если их нет.
    Существующие данные НЕ удаляются.
    """

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


# =========================================================
# UNIQUE JOIN CODE
# =========================================================

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


def generate_unique_join_code(conn):
    cur = conn.cursor()

    for _ in range(100):

        code = generate_join_code()

        cur.execute("""
            SELECT id
            FROM applications
            WHERE join_code = ?
            LIMIT 1
        """, (code,))

        if cur.fetchone() is None:
            return code

    raise RuntimeError(
        "Не удалось создать уникальный код вступления."
    )


# =========================================================
# EMAIL — BREVO
# =========================================================

async def send_brevo_email(
    to_email: str,
    subject: str,
    text_content: str
):

    if not BREVO_API_KEY:
        raise RuntimeError(
            "BREVO_API_KEY не указан в Railway Variables."
        )

    if not BREVO_FROM_EMAIL:
        raise RuntimeError(
            "BREVO_FROM_EMAIL не указан в Railway Variables."
        )

    if not BREVO_FROM_NAME:
        raise RuntimeError(
            "BREVO_FROM_NAME не указан в Railway Variables."
        )

    payload = {
        "sender": {
            "name": BREVO_FROM_NAME,
            "email": BREVO_FROM_EMAIL
        },
        "to": [
            {
                "email": to_email
            }
        ],
        "subject": subject,
        "textContent": text_content
    }

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    timeout = aiohttp.ClientTimeout(
        total=EMAIL_REQUEST_TIMEOUT
    )

    logger.info(
        "Brevo: отправка письма на %s | subject=%s",
        to_email,
        subject
    )

    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                BREVO_API_URL,
                headers=headers,
                json=payload
            ) as response:

                response_text = await response.text()

                if response.status not in (200, 201, 202):

                    logger.error(
                        "Brevo ошибка | HTTP %s | %s",
                        response.status,
                        response_text[:1000]
                    )

                    raise RuntimeError(
                        f"Brevo API вернул HTTP {response.status}."
                    )

                try:
                    response_json = await response.json()
                except Exception:
                    response_json = {}

                message_id = response_json.get(
                    "messageId",
                    "unknown"
                )

                logger.info(
                    "Brevo: письмо отправлено | messageId=%s",
                    message_id
                )

                return message_id

    except asyncio.TimeoutError as error:

        logger.exception(
            "Brevo: таймаут"
        )

        raise RuntimeError(
            "Brevo API не ответил вовремя."
        ) from error

    except aiohttp.ClientError as error:

        logger.exception(
            "Brevo: ошибка HTTPS-соединения"
        )

        raise RuntimeError(
            "Не удалось подключиться к Brevo API."
        ) from error


# =========================================================
# EMAIL VERIFICATION
# =========================================================

async def send_email_verification_code(
    email: str,
    code: str
):

    text_content = f"""💗 КРУТЯШКИ
━━━━━━━━━━━━━━━━━━━━━━━━

📧 ПОДТВЕРЖДЕНИЕ GMAIL

Вы указали этот Gmail при подаче
заявки в клан «Крутяшки».

Ваш код подтверждения:

━━━━━━━━━━━━━━━━━━━━━━━━
        {code}
━━━━━━━━━━━━━━━━━━━━━━━━

⏱ Код действует {EMAIL_CODE_EXPIRE_MINUTES} минут.

Если вы не подавали заявку,
просто проигнорируйте это письмо.

💗 Клан «Крутяшки»
"""

    return await send_brevo_email(
        email,
        "📧 Подтверждение Gmail — Крутяшки",
        text_content
    )


# =========================================================
# EMAIL ACCEPTANCE
# =========================================================

async def send_acceptance_email(
    email: str,
    nickname: str,
    join_code: str,
    decision_message: str
):

    text_content = f"""💗 КРУТЯШКИ
━━━━━━━━━━━━━━━━━━━━━━━━

🎉 ВАША ЗАЯВКА ОДОБРЕНА!

Здравствуйте, {nickname}!

Поздравляем! Ваша заявка на вступление
в клан «Крутяшки» была успешно одобрена.

👤 ВАШ MINECRAFT НИК
{nickname}


🔐 ВАШ УНИКАЛЬНЫЙ КОД
━━━━━━━━━━━━━━━━━━━━━━━━
        {join_code}
━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ Обязательно сохраните этот код.
Он понадобится для вступления в клан.


💬 СООБЩЕНИЕ АДМИНИСТРАЦИИ

{decision_message}


📢 ОФИЦИАЛЬНЫЙ КАНАЛ
{OFFICIAL_CHANNEL}

🤖 ОФИЦИАЛЬНЫЙ БОТ
{OFFICIAL_BOT}


💗 Добро пожаловать в «Крутяшки»!

Желаем приятной игры и хорошего общения
с участниками клана.

━━━━━━━━━━━━━━━━━━━━━━━━
Это автоматическое сообщение
официального бота «Крутяшки».
"""

    return await send_brevo_email(
        email,
        "💗 Крутяшки — ваша заявка одобрена!",
        text_content
    )


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💗  Вступить в клан",
                    callback_data="join"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👑  Обо мне",
                    callback_data="about"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔐  Проверить официальный бот",
                    callback_data="official_bot"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢  Официальный канал",
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
# MAIN TEXT
# =========================================================

def main_menu_text():
    return (
        "💗 <b>КРУТЯШКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✨ Добро пожаловать в официальный бот клана!\n\n"
        "Здесь ты можешь:\n"
        "💗 подать заявку на вступление\n"
        "👑 узнать информацию о клане\n"
        "🔐 проверить официальность бота\n"
        "📢 перейти в официальный канал\n\n"
        f"👑 <b>Создатель:</b> {ALINA_USERNAME}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💗 <i>Рады видеть тебя здесь!</i>"
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
            "🚫 <b>ДОСТУП ОГРАНИЧЕН</b>\n\n"
            "Вы не можете использовать этого бота."
        )

        return

    splash = await message.answer(
        "✓ <b>Официальный бот Алины</b>\n\n"
        "Подключение..."
    )

    await asyncio.sleep(2)

    loading_frames = [
        "Подключение.\n\n▫️▫️▫️▫️▫️",
        "Проверка.\n\n🟩▫️▫️▫️▫️",
        "Загрузка.\n\n🟩🟩▫️▫️▫️",
        "Подготовка.\n\n🟩🟩🟩▫️▫️",
        "Почти готово.\n\n🟩🟩🟩🟩▫️",
        "Готово!\n\n🟩🟩🟩🟩🟩",
    ]

    for frame in loading_frames:

        try:

            await splash.edit_text(
                "✓ <b>Официальный бот Алины</b>\n\n"
                f"{frame}"
            )

        except Exception:
            pass

        await asyncio.sleep(
            3 / len(loading_frames)
        )

    text = main_menu_text()

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
async def official_bot_handler(
    callback: CallbackQuery
):

    text = (
        "🔐 <b>ПРОВЕРКА ОФИЦИАЛЬНОСТИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Ты находишься в официальном боте "
        "клана <b>«Крутяшки»</b>.\n\n"
        "🤖 <b>Официальный бот:</b>\n"
        "<code>@krytyashki_clan_bot</code>\n\n"
        "📢 <b>Официальный канал:</b>\n"
        "<code>@alino4kaprincssss</code>\n\n"
        "🛡️ Используй только официальные ссылки "
        "клана, чтобы не попасть к мошенникам."
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
async def back_main_handler(
    callback: CallbackQuery
):

    text = main_menu_text()

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
async def about_handler(
    callback: CallbackQuery
):

    text = (
        "👑 <b>О КЛАНЕ «КРУТЯШКИ»</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💗 Это официальный бот клана <b>Крутяшки</b>.\n\n"
        "Здесь принимаются заявки новых участников "
        "и предоставляется официальная информация.\n\n"
        "✨ <b>НАШИ РЕСУРСЫ</b>\n\n"
        f"👑 Создатель: {ALINA_USERNAME}\n"
        "🤖 Бот: <code>@krytyashki_clan_bot</code>\n"
        "📢 Канал: <code>@alino4kaprincssss</code>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💗 <i>Добро пожаловать в нашу команду!</i>"
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

    last_rejected = get_last_rejected_application(
        user_id
    )

    if last_rejected:

        try:

            rejected_time = datetime.fromisoformat(
                last_rejected
            )

            cooldown_end = (
                rejected_time
                + timedelta(
                    hours=REAPPLY_COOLDOWN_HOURS
                )
            )

            if datetime.now() < cooldown_end:

                remaining = (
                    cooldown_end
                    - datetime.now()
                )

                minutes = max(
                    1,
                    int(
                        remaining.total_seconds()
                        // 60
                    )
                )

                await callback.answer(
                    f"Повторная заявка будет доступна "
                    f"примерно через {minutes} мин.",
                    show_alert=True
                )

                return

        except Exception:
            pass

    await state.set_state(
        ApplicationForm.nickname
    )

    await callback.message.answer(
        "💗 <b>ВСТУПЛЕНИЕ В КЛАН</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✨ Отлично! Давай познакомимся.\n\n"
        "Тебе нужно пройти небольшую анкету "
        "из <b>7 шагов</b>.\n\n"
        "🎮 <b>ШАГ 1 ИЗ 7</b>\n\n"
        "Напиши свой <b>Minecraft ник</b>:\n\n"
        "💡 <i>Например: Steve123</i>"
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

        await message.answer(
            "🚫 <b>Доступ ограничен.</b>"
        )

        await state.clear()

        return

    nickname = (
        message.text or ""
    ).strip()

    if len(nickname) < 2 or len(nickname) > 32:

        await message.answer(
            "❌ <b>Некорректный ник.</b>\n\n"
            "Ник должен содержать от 2 до 32 символов.\n\n"
            "Попробуй ещё раз:"
        )

        return

    await state.update_data(
        nickname=nickname
    )

    await state.set_state(
        ApplicationForm.reason
    )

    await message.answer(
        "📝 <b>ШАГ 2 ИЗ 7</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Почему ты хочешь вступить в "
        "<b>«Крутяшки»</b>?\n\n"
        "💡 Расскажи немного о себе и почему "
        "тебе интересен наш клан."
    )


# =========================================================
# REASON
# =========================================================

@dp.message(ApplicationForm.reason)
async def reason_handler(
    message: Message,
    state: FSMContext
):

    reason = (
        message.text or ""
    ).strip()

    if len(reason) < 3:

        await message.answer(
            "📝 Напиши немного подробнее, "
            "почему хочешь вступить:"
        )

        return

    await state.update_data(
        reason=reason
    )

    await state.set_state(
        ApplicationForm.loyal
    )

    await message.answer(
        "💗 <b>ШАГ 3 ИЗ 7</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Готов ли ты быть верным клану "
        "и уважать его участников и Алину?\n\n"
        "Выбери подходящий вариант:",
        reply_markup=loyal_keyboard()
    )


# =========================================================
# LOYAL
# =========================================================

@dp.callback_query(
    ApplicationForm.loyal,
    F.data.in_({
        "loyal_yes",
        "loyal_no"
    })
)
async def loyal_handler(
    callback: CallbackQuery,
    state: FSMContext
):

    loyal = (
        "Да"
        if callback.data == "loyal_yes"
        else "Нет"
    )

    await state.update_data(
        loyal=loyal
    )

    await state.set_state(
        ApplicationForm.pvp
    )

    await callback.message.answer(
        "⚔️ <b>ШАГ 4 ИЗ 7 — PvP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Как бы ты оценил свои навыки в PvP?\n\n"
        "🟢 1 — только начинаю\n"
        "🔥 10 — очень сильный игрок\n\n"
        "Выбери число:",
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

    pvp = int(
        callback.data.split("_")[1]
    )

    await state.update_data(
        pvp=pvp
    )

    await state.set_state(
        ApplicationForm.pve
    )

    await callback.message.answer(
        "⛏️ <b>ШАГ 5 ИЗ 7 — PvE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Как бы ты оценил свои навыки в PvE?\n\n"
        "🟢 1 — только начинаю\n"
        "🔥 10 — очень сильный игрок\n\n"
        "Выбери число:",
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

    pve = int(
        callback.data.split("_")[1]
    )

    await state.update_data(
        pve=pve
    )

    await state.set_state(
        ApplicationForm.age
    )

    await callback.message.answer(
        "🎂 <b>ШАГ 6 ИЗ 7</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Сколько тебе лет?\n\n"
        "🔢 Напиши только число."
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

    text = (
        message.text or ""
    ).strip()

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

    await state.update_data(
        age=age
    )

    await state.set_state(
        ApplicationForm.email
    )

    await message.answer(
        "📧 <b>ШАГ 7 ИЗ 7</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Остался последний шаг!\n\n"
        "Укажи свой <b>Gmail</b> — на него мы "
        "отправим код подтверждения.\n\n"
        "📩 Например:\n"
        "<code>example@gmail.com</code>\n\n"
        "🔒 Твой адрес используется только для "
        "связи по заявке."
    )


# =========================================================
# EMAIL
# =========================================================

@dp.message(ApplicationForm.email)
async def email_handler(
    message: Message,
    state: FSMContext
):

    email = (
        message.text or ""
    ).strip().lower()

    if not re.fullmatch(
        r"[a-zA-Z0-9._%+-]+@gmail\.com",
        email
    ):

        await message.answer(
            "❌ <b>Нужен именно адрес Gmail.</b>\n\n"
            "Например:\n"
            "<code>example@gmail.com</code>"
        )

        return

    if not BREVO_API_KEY:

        logger.error(
            "BREVO_API_KEY не настроен."
        )

        await message.answer(
            "❌ Система подтверждения Gmail сейчас "
            "не настроена администрацией.\n\n"
            "Попробуй позже."
        )

        return

    if not BREVO_FROM_EMAIL:

        logger.error(
            "BREVO_FROM_EMAIL не настроен."
        )

        await message.answer(
            "❌ Система отправки Gmail сейчас "
            "не настроена администрацией.\n\n"
            "Попробуй позже."
        )

        return

    code = str(
        secrets.randbelow(900000) + 100000
    )

    status_message = await message.answer(
        "📨 <b>ОТПРАВЛЯЮ КОД</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Отправляем код подтверждения "
        "на твой Gmail.\n\n"
        "⏳ Это может занять несколько секунд..."
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
                "Проверь правильность Gmail и попробуй "
                "ещё раз.\n\n"
                "Если проблема повторяется — "
                "сообщи администрации."
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
            "📨 <b>КОД ОТПРАВЛЕН!</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Мы отправили код на:\n"
            f"<code>{escape(email)}</code>\n\n"
            "🔢 Введи 6-значный код из письма сюда.\n\n"
            f"⏱ Код действует "
            f"{EMAIL_CODE_EXPIRE_MINUTES} минут."
        )

    except Exception:

        await message.answer(
            "📨 <b>Код отправлен!</b>\n\n"
            "Введи код из письма.\n\n"
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

    code = (
        message.text or ""
    ).strip()

    if not re.fullmatch(
        r"\d{6}",
        code
    ):

        await message.answer(
            "❌ Код должен состоять из 6 цифр.\n\n"
            "Попробуй ещё раз:"
        )

        return

    data = await state.get_data()

    saved_code = data.get(
        "verification_code"
    )

    created_at_text = data.get(
        "verification_created_at"
    )

    email = data.get(
        "verification_email"
    )

    if (
        not saved_code
        or not created_at_text
        or not email
    ):

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
            "⌛ <b>КОД ИСТЁК</b>\n\n"
            "Начни заявку заново, чтобы получить "
            "новый код."
        )

        return

    if code != saved_code:

        await message.answer(
            "❌ <b>Неверный код.</b>\n\n"
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
        "📥 <b>НОВАЯ ЗАЯВКА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
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
        "━━━━━━━━━━━━━━━━━━\n"
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
        "💗 <b>ЗАЯВКА ОТПРАВЛЕНА!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Gmail успешно подтверждён.\n\n"
        "📥 Заявка передана администрации "
        "клана на рассмотрение.\n\n"
        "⏳ Теперь остаётся дождаться решения.\n\n"
        "💗 Спасибо за заявку!"
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_handler(
    message: Message
):

    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "👑 <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите нужный раздел:",
        reply_markup=admin_keyboard()
    )


# =========================================================
# DB INFO
# =========================================================

@dp.message(Command("dbinfo"))
async def dbinfo_handler(
    message: Message
):

    if message.from_user.id != ADMIN_ID:
        return

    info = get_database_info()

    if not info["exists"]:

        await message.answer(
            "❌ <b>Файл базы данных не найден.</b>\n\n"
            f"Путь:\n"
            f"<code>{escape(os.path.abspath(DB_FILE))}</code>"
        )

        return

    size_kb = info["size"] / 1024

    await message.answer(
        "📊 <b>БАЗА ДАННЫХ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователей: <b>{info['users']}</b>\n"
        f"🚫 Заблокировано: <b>{info['blocked']}</b>\n\n"
        f"📨 Всего заявок: <b>{info['applications']}</b>\n"
        f"📥 На рассмотрении: <b>{info['pending']}</b>\n"
        f"✅ Принято: <b>{info['accepted']}</b>\n"
        f"❌ Отклонено: <b>{info['rejected']}</b>\n\n"
        f"💾 Размер: <b>{size_kb:.2f} KB</b>\n"
        f"📁 Файл:\n"
        f"<code>{escape(os.path.abspath(DB_FILE))}</code>"
    )


# =========================================================
# BACKUP
# =========================================================

@dp.message(Command("backupdb"))
async def backupdb_handler(
    message: Message
):

    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "💾 <b>Создаю резервную копию...</b>"
    )

    try:

        backup_file = create_database_backup()

        if (
            not backup_file
            or not os.path.exists(backup_file)
        ):

            await message.answer(
                "❌ Не удалось создать резервную копию."
            )

            return

        info = get_database_info()

        await message.answer_document(
            FSInputFile(backup_file),
            caption=(
                "💾 <b>РЕЗЕРВНАЯ КОПИЯ «КРУТЯШКИ»</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 Пользователей: {info['users']}\n"
                f"📨 Заявок: {info['applications']}\n\n"
                "🔐 Сохрани этот файл в безопасном месте."
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
async def admin_stats(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM applications"
    )
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

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )
    users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM users
        WHERE blocked = 1
    """)
    blocked = cur.fetchone()[0]

    conn.close()

    await callback.message.answer(
        "📊 <b>СТАТИСТИКА КЛАНА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
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
async def admin_pending(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            nickname,
            pvp,
            pve,
            created_at
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:

        await callback.message.answer(
            "📥 <b>Новых заявок нет.</b>\n\n"
            "Когда появится новая заявка, "
            "она будет показана здесь."
        )

        await callback.answer()

        return

    text = (
        "📥 <b>ЗАЯВКИ НА РАССМОТРЕНИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    for row in rows:

        (
            app_id,
            user_id,
            nickname,
            pvp,
            pve,
            created_at
        ) = row

        text += (
            f"🆔 <code>#{app_id}</code>\n"
            f"🎮 <b>{escape(nickname)}</b>\n"
            f"⚔️ PvP: {pvp}/10\n"
            f"⛏️ PvE: {pve}/10\n"
            f"👤 ID: <code>{user_id}</code>\n"
            f"🕐 {created_at[:16]}\n\n"
        )

    await callback.message.answer(text)

    await callback.answer()


# =========================================================
# ADMIN RECENT
# =========================================================

@dp.callback_query(F.data == "admin_recent")
async def admin_recent(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            nickname,
            status,
            created_at
        FROM applications
        ORDER BY id DESC
        LIMIT 15
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:

        await callback.message.answer(
            "🗂 <b>Заявок пока нет.</b>"
        )

        await callback.answer()

        return

    text = (
        "🗂 <b>ПОСЛЕДНИЕ ЗАЯВКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    status_names = {
        "pending": "📥 На рассмотрении",
        "accepted": "✅ Принята",
        "rejected": "❌ Отклонена"
    }

    for (
        app_id,
        nickname,
        status,
        created_at
    ) in rows:

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

    await state.set_state(
        AdminSearch.application_id
    )

    await callback.message.answer(
        "🔎 <b>ПОИСК ЗАЯВКИ</b>\n\n"
        "Введи ID заявки.\n\n"
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

    text = (
        message.text or ""
    ).strip()

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
        "🔎 <b>ЗАЯВКА НАЙДЕНА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Заявка: <code>#{app_id}</code>\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"👤 Username: @{escape(username or 'нет')}\n\n"
        f"🎮 Minecraft: <b>{escape(nickname)}</b>\n"
        f"📝 Причина: {escape(reason)}\n"
        f"💗 Верность: {escape(loyal)}\n"
        f"⚔️ PvP: {pvp}/10\n"
        f"⛏️ PvE: {pve}/10\n"
        f"🎂 Возраст: {age}\n"
        f"📧 Gmail: <code>{escape(email or 'нет')}</code>\n\n"
        f"🔐 Код: <code>{escape(join_code or 'ещё нет')}</code>\n"
        f"📌 Статус: <b>{escape(status)}</b>\n"
        f"🕐 Создана: {created_at}"
    )


# =========================================================
# ADMIN USERS
# =========================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            first_name,
            blocked
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

    text = (
        "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    for (
        user_id,
        username,
        first_name,
        blocked
    ) in rows:

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

    await state.set_state(
        AdminBlock.user_id
    )

    await callback.message.answer(
        "🚫 <b>БЛОКИРОВКА</b>\n\n"
        "Введи Telegram ID пользователя:"
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

    text = (
        message.text or ""
    ).strip()

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

    set_blocked(
        user_id,
        True
    )

    await state.clear()

    await message.answer(
        "🚫 <b>Пользователь заблокирован.</b>\n\n"
        f"ID: <code>{user_id}</code>"
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

    await state.set_state(
        AdminUnblock.user_id
    )

    await callback.message.answer(
        "🔓 <b>РАЗБЛОКИРОВКА</b>\n\n"
        "Введи Telegram ID пользователя:"
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

    text = (
        message.text or ""
    ).strip()

    if not text.isdigit():

        await message.answer(
            "❌ Telegram ID должен быть числом."
        )

        return

    user_id = int(text)

    set_blocked(
        user_id,
        False
    )

    await state.clear()

    await message.answer(
        "🔓 <b>Пользователь разблокирован.</b>\n\n"
        f"ID: <code>{user_id}</code>"
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

    await state.set_state(
        AdminBroadcast.message
    )

    await callback.message.answer(
        "📢 <b>РАССЫЛКА</b>\n\n"
        "Напиши сообщение, которое нужно "
        "отправить пользователям:"
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

    text = (
        message.text or ""
    ).strip()

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
                "Рассылка не отправлена пользователю "
                "%s: %s",
                user_id,
                e
            )

    await state.clear()

    await message.answer(
        "📢 <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
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

    action, app_id_text = (
        callback.data.split("_")
    )

    app_id = int(app_id_text)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            user_id,
            nickname
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

    await state.set_state(
        AdminDecision.message
    )

    title = (
        "✅ ПРИНЯТИЕ ЗАЯВКИ"
        if action == "accept"
        else "❌ ОТКЛОНЕНИЕ ЗАЯВКИ"
    )

    await callback.message.answer(
        f"<b>{title}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Заявка: <code>#{app_id}</code>\n"
        f"🎮 Игрок: <b>{escape(nickname)}</b>\n\n"
        "Напиши сообщение, которое будет "
        "отправлено игроку."
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

    decision_message = (
        message.text or ""
    ).strip()

    if not decision_message:

        await message.answer(
            "❌ Сообщение не может быть пустым."
        )

        return

    data = await state.get_data()

    app_id = data["application_id"]
    decision = data["decision"]
    user_id = data["target_user_id"]

    # =====================================================
    # ПРИНЯТИЕ
    # =====================================================

    if decision == "accepted":

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute("""
                SELECT
                    nickname,
                    email
                FROM applications
                WHERE id = ?
                  AND status = 'pending'
            """, (app_id,))

            application = cur.fetchone()

            if not application:

                conn.close()

                await state.clear()

                await message.answer(
                    "❌ Заявка уже обработана или не найдена."
                )

                return

            nickname, email = application

            join_code = generate_unique_join_code(
                conn
            )

            now = datetime.now().isoformat()

            cur.execute("""
                UPDATE applications
                SET status = ?,
                    decided_at = ?,
                    decision_message = ?,
                    join_code = ?
                WHERE id = ?
                  AND status = 'pending'
            """, (
                "accepted",
                now,
                decision_message,
                join_code,
                app_id
            ))

            if cur.rowcount != 1:

                conn.rollback()
                conn.close()

                await state.clear()

                await message.answer(
                    "❌ Не удалось изменить статус заявки."
                )

                return

            conn.commit()

        except Exception:

            conn.rollback()
            conn.close()

            raise

        conn.close()

        await state.clear()

        # =================================================
        # TELEGRAM
        # =================================================

        user_text = (
            "💗 <b>КРУТЯШКИ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🎉 <b>ТВОЯ ЗАЯВКА ОДОБРЕНА!</b>\n\n"
            f"Здравствуйте, <b>{escape(nickname)}</b>!\n\n"
            "Поздравляем! Теперь ты официально принят "
            "в клан <b>«Крутяшки»</b>. 🥳\n\n"
            "💬 <b>Сообщение администрации:</b>\n"
            f"<i>{escape(decision_message)}</i>\n\n"
            "🔐 <b>ТВОЙ УНИКАЛЬНЫЙ КОД:</b>\n\n"
            f"<code>{escape(join_code)}</code>\n\n"
            "⚠️ <b>Сохрани этот код!</b>\n"
            "Он понадобится для вступления.\n\n"
            "📧 Копия кода отправлена на твой Gmail.\n\n"
            "📢 <b>Официальный канал:</b>\n"
            f"{OFFICIAL_CHANNEL}\n\n"
            "💗 <b>Добро пожаловать в «Крутяшки»!</b>"
        )

        telegram_sent = False

        try:

            await bot.send_message(
                user_id,
                user_text
            )

            telegram_sent = True

        except Exception as e:

            logger.error(
                "Не удалось уведомить пользователя %s: %s",
                user_id,
                e
            )

        # =================================================
        # EMAIL
        # =================================================

        email_sent = False
        email_error = None

        if email:

            try:

                await send_acceptance_email(
                    email=email,
                    nickname=nickname,
                    join_code=join_code,
                    decision_message=decision_message
                )

                email_sent = True

            except Exception as e:

                email_error = str(e)

                logger.exception(
                    "Не удалось отправить письмо "
                    "о принятии заявки #%s: %s",
                    app_id,
                    e
                )

        else:

            email_error = (
                "У заявки отсутствует Gmail."
            )

        # =================================================
        # ADMIN RESULT
        # =================================================

        result_lines = [
            "💗 <b>ЗАЯВКА ПРИНЯТА</b>",
            "━━━━━━━━━━━━━━━━━━",
            "",
            f"🆔 Заявка: <code>#{app_id}</code>",
            f"👤 Пользователь: <code>{user_id}</code>",
            f"🎮 Minecraft: <b>{escape(nickname)}</b>",
            "",
            f"🔐 Код: <code>{escape(join_code)}</code>",
            ""
        ]

        if telegram_sent:

            result_lines.append(
                "📱 Telegram: ✅ отправлено"
            )

        else:

            result_lines.append(
                "📱 Telegram: ❌ не удалось отправить"
            )

        if email_sent:

            result_lines.append(
                "📧 Gmail: "
                f"✅ отправлено на "
                f"<code>{escape(email)}</code>"
            )

        else:

            result_lines.append(
                "📧 Gmail: ❌ письмо не отправлено"
            )

            if email_error:

                result_lines.extend([
                    "",
                    "⚠️ Причина:",
                    f"<code>{escape(email_error[:500])}</code>"
                ])

        result_lines.extend([
            "",
            "💾 Код сохранён в базе данных."
        ])

        if not email_sent:

            result_lines.extend([
                "",
                "📋 <b>Резервный текст письма:</b>",
                "<code>",
                escape(
                    f"""💗 КРУТЯШКИ
━━━━━━━━━━━━━━━━━━━━━━━━

🎉 ВАША ЗАЯВКА ОДОБРЕНА!

Здравствуйте, {nickname}!

Поздравляем! Ваша заявка на вступление
в клан «Крутяшки» была успешно одобрена.

👤 ВАШ MINECRAFT НИК
{nickname}

🔐 ВАШ УНИКАЛЬНЫЙ КОД
━━━━━━━━━━━━━━━━━━━━━━━━
        {join_code}
━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ Обязательно сохраните этот код.

💬 СООБЩЕНИЕ АДМИНИСТРАЦИИ

{decision_message}

📢 ОФИЦИАЛЬНЫЙ КАНАЛ
{OFFICIAL_CHANNEL}

🤖 ОФИЦИАЛЬНЫЙ БОТ
{OFFICIAL_BOT}

💗 Добро пожаловать в «Крутяшки»!"""
                ),
                "</code>"
            ])

        await message.answer(
            "\n".join(result_lines)
        )

    # =====================================================
    # ОТКЛОНЕНИЕ
    # =====================================================

    else:

        conn = get_db()
        cur = conn.cursor()

        now = datetime.now().isoformat()

        cur.execute("""
            UPDATE applications
            SET status = ?,
                decided_at = ?,
                decision_message = ?
            WHERE id = ?
              AND status = 'pending'
        """, (
            "rejected",
            now,
            decision_message,
            app_id
        ))

        changed = cur.rowcount

        conn.commit()
        conn.close()

        await state.clear()

        if changed != 1:

            await message.answer(
                "❌ Заявка уже была обработана."
            )

            return

        try:

            await bot.send_message(
                user_id,
                "💗 <b>КРУТЯШКИ</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "❌ <b>Заявка отклонена.</b>\n\n"
                "💬 <b>Сообщение администрации:</b>\n"
                f"<i>{escape(decision_message)}</i>\n\n"
                "⏳ Повторно подать заявку можно через "
                f"<b>{REAPPLY_COOLDOWN_HOURS} часа</b>.\n\n"
                "💗 Спасибо за интерес к нашему клану!"
            )

        except Exception as e:

            logger.error(
                "Не удалось уведомить пользователя: %s",
                e
            )

        await message.answer(
            "❌ <b>Заявка отклонена.</b>\n\n"
            f"🆔 Заявка: <code>#{app_id}</code>"
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
        "↩️ <b>Текущее действие отменено.</b>\n\n"
        "Можешь начать заново."
    )


# =========================================================
# BLOCKED / OTHER
# =========================================================

@dp.message()
async def blocked_handler(
    message: Message
):

    if message.from_user.id == ADMIN_ID:
        return

    save_user(message)

    if is_blocked(message.from_user.id):

        await message.answer(
            "🚫 <b>ДОСТУП ОГРАНИЧЕН</b>\n\n"
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

    logger.info(
        "Brevo API: %s",
        "настроен"
        if BREVO_API_KEY and BREVO_FROM_EMAIL
        else "НЕ НАСТРОЕН"
    )

    await dp.start_polling(bot)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
