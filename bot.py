import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta

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


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = 1541550837

DB_FILE = "krutyashki.sqlite3"
IMAGE_FILE = "alina.jpg"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =========================
# БАЗА ДАННЫХ
# =========================

def get_db():
    return sqlite3.connect(DB_FILE)


def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
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
            decision_message TEXT
        )
    """)

    db.commit()
    db.close()


def get_last_rejected(user_id: int):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT decided_at
        FROM applications
        WHERE user_id = ?
        AND status = 'rejected'
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))

    result = cur.fetchone()
    db.close()

    return result[0] if result else None


def has_pending_application(user_id: int):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT id
        FROM applications
        WHERE user_id = ?
        AND status = 'pending'
        LIMIT 1
    """, (user_id,))

    result = cur.fetchone()
    db.close()

    return result[0] if result else None


def create_application(
    user_id,
    username,
    nickname,
    reason,
    loyal,
    pvp,
    age
):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO applications
        (
            user_id,
            username,
            nickname,
            reason,
            loyal,
            pvp,
            age,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user_id,
        username,
        nickname,
        reason,
        loyal,
        pvp,
        age,
        datetime.now().isoformat()
    ))

    application_id = cur.lastrowid

    db.commit()
    db.close()

    return application_id


def get_application(application_id):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            username,
            nickname,
            reason,
            loyal,
            pvp,
            age,
            status
        FROM applications
        WHERE id = ?
    """, (application_id,))

    result = cur.fetchone()
    db.close()

    return result


def update_application(
    application_id,
    status,
    decision_message
):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        UPDATE applications
        SET
            status = ?,
            decided_at = ?,
            decision_message = ?
        WHERE id = ?
    """, (
        status,
        datetime.now().isoformat(),
        decision_message,
        application_id
    ))

    db.commit()
    db.close()


# =========================
# СОСТОЯНИЯ АНКЕТЫ
# =========================

class ApplicationForm(StatesGroup):
    nickname = State()
    reason = State()
    loyal = State()
    pvp = State()
    age = State()


class AdminDecision(StatesGroup):
    waiting_message = State()


# =========================
# КЛАВИАТУРЫ
# =========================

def main_menu():
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


def loyal_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💗 Да, клянусь!",
                    callback_data="loyal_yes"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤔 Я подумаю",
                    callback_data="loyal_no"
                )
            ]
        ]
    )


def pvp_keyboard():
    buttons = []

    row = []

    for number in range(1, 6):
        row.append(
            InlineKeyboardButton(
                text=str(number),
                callback_data=f"pvp_{number}"
            )
        )

    buttons.append(row)

    row = []

    for number in range(6, 11):
        row.append(
            InlineKeyboardButton(
                text=str(number),
                callback_data=f"pvp_{number}"
            )
        )

    buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_keyboard(application_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept_{application_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_{application_id}"
                )
            ]
        ]
    )


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    text = (
        "🌸 <b>Добро пожаловать в клан «Крутяшки»!</b> 🌸\n\n"
        "👑 Здесь начинается твой путь в нашей маленькой "
        "Minecraft-компании!\n\n"
        "💗 Хочешь попробовать попасть в клан? "
        "Заполни небольшую анкету.\n\n"
        "✨ Никаких сложных правил — просто отвечай честно "
        "и будь собой!\n\n"
        "👇 Выбирай действие:"
    )

    if os.path.exists(IMAGE_FILE):
        photo = FSInputFile(IMAGE_FILE)

        await message.answer_photo(
            photo=photo,
            caption=text,
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            text,
            reply_markup=main_menu(),
            parse_mode="HTML"
        )


# =========================
# ОБО МНЕ
# =========================

@dp.callback_query(F.data == "about")
async def about(callback: CallbackQuery):
    text = (
        "👑 <b>Немного обо мне</b>\n\n"
        "💗 Я — бот-помощник клана <b>«Крутяшки»</b>.\n\n"
        "Моя задача — помочь тебе оставить заявку "
        "на вступление в клан и передать её администрации.\n\n"
        "🌸 Оригинальная Алиночка-принцесса:\n"
        "👉 @alino4ka_princes\n\n"
        "✨ Я могу принять твою анкету, аккуратно передать "
        "её администрации и сообщить тебе результат.\n\n"
        "🏰 А дальше всё зависит от твоей анкеты!\n\n"
        "💞 Удачи!"
    )

    await callback.message.edit_caption(
        caption=text,
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# НАЧАЛО АНКЕТЫ
# =========================

@dp.callback_query(F.data == "join")
async def join(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    pending = has_pending_application(user_id)

    if pending:
        await callback.answer(
            "У тебя уже есть заявка на рассмотрении 💗",
            show_alert=True
        )
        return

    last_rejected = get_last_rejected(user_id)

    if last_rejected:
        try:
            rejected_time = datetime.fromisoformat(last_rejected)
            available_time = rejected_time + timedelta(hours=2)

            if datetime.now() < available_time:
                remaining = available_time - datetime.now()

                minutes = int(remaining.total_seconds() // 60)

                await callback.answer(
                    f"Повторная заявка будет доступна примерно через "
                    f"{minutes} мин. 💗",
                    show_alert=True
                )
                return

        except Exception:
            pass

    await state.set_state(ApplicationForm.nickname)

    await callback.message.answer(
        "💗 <b>Анкета в клан «Крутяшки»</b>\n\n"
        "Давай начнём!\n\n"
        "1️⃣ Напиши свой <b>никнейм в Minecraft</b>.",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# НИК
# =========================

@dp.message(ApplicationForm.nickname)
async def process_nickname(message: Message, state: FSMContext):
    nickname = message.text.strip()

    if len(nickname) < 2:
        await message.answer(
            "🌸 Ник слишком короткий. Напиши нормальный игровой ник."
        )
        return

    if len(nickname) > 32:
        await message.answer(
            "🌸 Ник слишком длинный. Постарайся уложиться в 32 символа."
        )
        return

    await state.update_data(nickname=nickname)

    await state.set_state(ApplicationForm.reason)

    await message.answer(
        "✨ <b>2️⃣ Зачем ты хочешь вступить в наш клан?</b>\n\n"
        "Напиши своими словами 💗",
        parse_mode="HTML"
    )


# =========================
# ПРИЧИНА
# =========================

@dp.message(ApplicationForm.reason)
async def process_reason(message: Message, state: FSMContext):
    reason = message.text.strip()

    if len(reason) < 3:
        await message.answer(
            "🌸 Напиши немного подробнее."
        )
        return

    if len(reason) > 1000:
        await message.answer(
            "🌸 Ответ получился слишком длинным. "
            "Пожалуйста, сократи его."
        )
        return

    await state.update_data(reason=reason)

    await state.set_state(ApplicationForm.loyal)

    await message.answer(
        "👑 <b>3️⃣ Готов ли ты быть верным клану "
        "«Крутяшки» и уважать Алину?</b>\n\n"
        "Выбирай честно 💗",
        reply_markup=loyal_keyboard(),
        parse_mode="HTML"
    )


# =========================
# ВЕРНОСТЬ
# =========================

@dp.callback_query(
    ApplicationForm.loyal,
    F.data.in_({"loyal_yes", "loyal_no"})
)
async def process_loyal(callback: CallbackQuery, state: FSMContext):
    if callback.data == "loyal_yes":
        loyal = "Да, клянусь!"
    else:
        loyal = "Я подумаю"

    await state.update_data(loyal=loyal)

    await state.set_state(ApplicationForm.pvp)

    await callback.message.answer(
        "⚔️ <b>4️⃣ Как ты оцениваешь своё PvP?</b>\n\n"
        "Выбери число от <b>1 до 10</b>.",
        reply_markup=pvp_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# PVP
# =========================

@dp.callback_query(
    ApplicationForm.pvp,
    F.data.startswith("pvp_")
)
async def process_pvp(callback: CallbackQuery, state: FSMContext):
    try:
        pvp = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer()
        return

    await state.update_data(pvp=pvp)

    await state.set_state(ApplicationForm.age)

    await callback.message.answer(
        "🌸 <b>5️⃣ Сколько тебе лет?</b>\n\n"
        "Напиши только свой возраст числом.",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# ВОЗРАСТ
# =========================

@dp.message(ApplicationForm.age)
async def process_age(message: Message, state: FSMContext):
    text = message.text.strip()

    if not text.isdigit():
        await message.answer(
            "🌸 Пожалуйста, напиши возраст только числом."
        )
        return

    age = int(text)

    if age < 1 or age > 100:
        await message.answer(
            "🌸 Укажи реальный возраст."
        )
        return

    data = await state.get_data()

    user = message.from_user

    application_id = create_application(
        user_id=user.id,
        username=user.username or "",
        nickname=data["nickname"],
        reason=data["reason"],
        loyal=data["loyal"],
        pvp=data["pvp"],
        age=age
    )

    await state.clear()

    username_text = (
        f"@{user.username}"
        if user.username
        else "нет username"
    )

    admin_text = (
        "🌸 <b>НОВАЯ АНКЕТА В КЛАН «КРУТЯШКИ»</b> 🌸\n\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"👤 <b>Username:</b> {username_text}\n\n"
        f"🎮 <b>Ник в Minecraft:</b>\n"
        f"{data['nickname']}\n\n"
        f"💭 <b>Зачем хочет вступить:</b>\n"
        f"{data['reason']}\n\n"
        f"👑 <b>Верность Алине:</b>\n"
        f"{data['loyal']}\n\n"
        f"⚔️ <b>PvP:</b> {data['pvp']}/10\n\n"
        f"🎂 <b>Возраст:</b> {age}\n\n"
        f"📋 <b>Номер анкеты:</b> #{application_id}"
    )

    await bot.send_message(
        ADMIN_ID,
        admin_text,
        reply_markup=admin_keyboard(application_id),
        parse_mode="HTML"
    )

    await message.answer(
        "💗 <b>Анкета отправлена!</b>\n\n"
        "✨ Спасибо за заявку в клан «Крутяшки».\n\n"
        "👑 Администрация рассмотрит её и сообщит тебе "
        "результат.\n\n"
        "🌸 Удачи!",
        parse_mode="HTML"
    )


# =========================
# ПРИНЯТИЕ
# =========================

@dp.callback_query(F.data.startswith("accept_"))
async def accept_application(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "У тебя нет доступа.",
            show_alert=True
        )
        return

    application_id = int(callback.data.split("_")[1])

    application = get_application(application_id)

    if not application:
        await callback.answer(
            "Анкета не найдена.",
            show_alert=True
        )
        return

    if application[8] != "pending":
        await callback.answer(
            "Эта анкета уже обработана.",
            show_alert=True
        )
        return

    await state.set_state(AdminDecision.waiting_message)

    await state.update_data(
        application_id=application_id,
        decision="accepted"
    )

    await callback.message.answer(
        "✅ <b>Анкета выбрана как ПРИНЯТА.</b>\n\n"
        "Теперь напиши сообщение, которое нужно отправить "
        "пользователю.\n\n"
        "Например:\n"
        "<i>«Поздравляем! Ты принят в клан Крутяшки 💗 "
        "Напиши админу для дальнейших действий!»</i>\n\n"
        "Для отмены используй /cancel",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# ОТКЛОНЕНИЕ
# =========================

@dp.callback_query(F.data.startswith("reject_"))
async def reject_application(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "У тебя нет доступа.",
            show_alert=True
        )
        return

    application_id = int(callback.data.split("_")[1])

    application = get_application(application_id)

    if not application:
        await callback.answer(
            "Анкета не найдена.",
            show_alert=True
        )
        return

    if application[8] != "pending":
        await callback.answer(
            "Эта анкета уже обработана.",
            show_alert=True
        )
        return

    await state.set_state(AdminDecision.waiting_message)

    await state.update_data(
        application_id=application_id,
        decision="rejected"
    )

    await callback.message.answer(
        "❌ <b>Анкета выбрана как ОТКЛОНЕНА.</b>\n\n"
        "Теперь напиши сообщение, которое нужно отправить "
        "пользователю.\n\n"
        "Например:\n"
        "<i>«Нам очень жаль, но сейчас анкета не прошла "
        "отбор 💔 Ты сможешь попробовать снова через 2 часа!»</i>\n\n"
        "Для отмены используй /cancel",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================
# СООБЩЕНИЕ ОТ АДМИНА
# =========================

@dp.message(AdminDecision.waiting_message)
async def admin_decision_message(
    message: Message,
    state: FSMContext
):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.startswith("/cancel"):
        await state.clear()

        await message.answer(
            "Отмена. Анкета пока не обработана."
        )
        return

    data = await state.get_data()

    application_id = data.get("application_id")
    decision = data.get("decision")

    if not application_id or not decision:
        await state.clear()
        await message.answer(
            "Не удалось определить анкету."
        )
        return

    application = get_application(application_id)

    if not application:
        await state.clear()
        await message.answer(
            "Анкета не найдена."
        )
        return

    if application[8] != "pending":
        await state.clear()
        await message.answer(
            "Эта анкета уже была обработана."
        )
        return

    user_id = application[1]

    decision_message = message.text or ""

    if decision == "accepted":
        update_application(
            application_id,
            "accepted",
            decision_message
        )

        user_text = (
            "🌸 <b>УРА! ТВОЯ АНКЕТА ПРИНЯТА! 💗</b> 🌸\n\n"
            "👑 Поздравляем!\n"
            "Ты прошёл отбор в клан <b>«Крутяшки»</b>.\n\n"
            "💌 Сообщение от администрации:\n\n"
            f"{decision_message}\n\n"
            "✨ Добро пожаловать!"
        )

        status_text = "✅ АНКЕТА ПРИНЯТА"

    else:
        update_application(
            application_id,
            "rejected",
            decision_message
        )

        user_text = (
            "💔 <b>Нам очень жаль...</b>\n\n"
            "Твоя анкета в клан <b>«Крутяшки»</b> "
            "в этот раз не прошла отбор.\n\n"
            "🌸 Но не расстраивайся!\n"
            "Ты сможешь отправить новую анкету примерно "
            "через <b>2 часа</b>.\n\n"
            "💌 Сообщение от администрации:\n\n"
            f"{decision_message}\n\n"
            "✨ Возможно, в следующий раз всё получится!"
        )

        status_text = "❌ АНКЕТА ОТКЛОНЕНА"

    try:
        await bot.send_message(
            user_id,
            user_text,
            parse_mode="HTML"
        )

        await message.answer(
            f"{status_text}\n\n"
            f"Сообщение отправлено пользователю."
        )

    except Exception as e:
        logging.error(
            f"Ошибка отправки пользователю {user_id}: {e}"
        )

        await message.answer(
            f"{status_text}\n\n"
            "⚠️ Решение сохранено, но сообщение "
            "пользователю отправить не удалось."
        )

    await state.clear()


# =========================
# КОМАНДА CANCEL
# =========================

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "🌸 Действие отменено.\n\n"
        "Если захочешь, можешь начать заново."
    )


# =========================
# ЗАПУСК
# =========================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден! "
            "Добавь BOT_TOKEN в Railway Variables."
        )

    init_db()

    logging.info("Бот запускается...")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
