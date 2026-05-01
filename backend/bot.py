"""
bot.py — Основной файл Telegram-бота (Aiogram 3.x)
Дипломный проект: Telegram-бот для мебельного завода
Версия: 2.1 (с фото-каруселью, консультантом, валидацией)

Запуск: python bot.py
"""
import asyncio
import json
import logging
import time
import os
import uuid
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from database import (
    create_db, seed_initial_data,
    register_user, get_user, get_user_role, set_user_role_and_info,
    check_staff_login, get_all_staff_credentials, get_staff_info,
    create_staff_account, update_staff_credential, delete_staff_credential,
    add_category, get_categories,
    add_product, get_products_by_category, get_product_by_id, delete_product,
    update_product,
    create_order, get_order, get_order_items, get_user_orders, get_all_orders,
    update_order_status, get_statistics, generate_fake_data,
    get_managers_ids, get_all_users_ids, generate_invoice_html,
    validate_fio, validate_phone, normalize_phone,
    add_product_photo, get_product_photos,
    get_product_photos_with_ids, delete_product_photo_by_id,
    cancel_order, get_all_orders_paginated, get_statistics_csv
)
from keyboards import (
    get_main_kb, cancel_kb, staff_login_kb,
    order_actions_kb, payment_kb, profile_kb, orders_filter_kb,
    set_webapp_url
)

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не задана! Укажите токен бота через переменную окружения.")

IMAGES_DIR = os.getenv('IMAGES_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'images'))
os.makedirs(IMAGES_DIR, exist_ok=True)

WEBAPP_URL = os.getenv('WEBAPP_URL', '')
PAYMENT_TOKEN = os.getenv('PAYMENT_TOKEN', '')


# ==========================================
# ЛОГИРОВАНИЕ
# ==========================================

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m', 'INFO': '\033[32m',
        'WARNING': '\033[33m', 'ERROR': '\033[31m',
        'CRITICAL': '\033[41m',
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger('FurnitureBot')

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('aiogram').setLevel(logging.WARNING)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==========================================
# АНТИ-СПАМ
# ==========================================

user_last_action: dict = defaultdict(float)
THROTTLE_SECONDS = 1.5


def is_throttled(user_id: int) -> bool:
    now = time.time()
    if now - user_last_action[user_id] < THROTTLE_SECONDS:
        return True
    user_last_action[user_id] = now
    return False


# ==========================================
# ЗАЩИТА ОТ ПОЛОМОК — ЛИМИТЫ И САНИТИЗАЦИЯ
# ==========================================

MAX_TEXT_LENGTH = 1000        # Максимум символов в текстовом вводе
MAX_NAME_LENGTH = 200         # Максимум для имён/названий
MAX_DESCRIPTION_LENGTH = 2000 # Максимум для описаний
MAX_ADDRESS_LENGTH = 500      # Максимум для адреса
MAX_COMMENT_LENGTH = 500      # Максимум для комментария
MAX_PHOTOS_PER_PRODUCT = 10   # Максимум фото на один товар
MAX_BROADCAST_LENGTH = 3000   # Максимум текста рассылки
MAX_CART_ITEMS = 50           # Максимум товаров в одном заказе


def safe_markdown(text: str) -> str:
    """Экранирование спецсимволов Markdown v1 чтобы бот не падал от пользовательского текста"""
    if not text:
        return ""
    for char in ['*', '_', '`', '[']:
        text = text.replace(char, '')
    return text


# ==========================================
# НАДЁЖНЫЕ УВЕДОМЛЕНИЯ (с retry)
# ==========================================

async def send_notification(user_id: int, text: str, reply_markup=None, retries=3):
    """Отправка уведомления с повторными попытками при ошибке"""
    for attempt in range(1, retries + 1):
        try:
            await bot.send_message(
                user_id, text, parse_mode="Markdown",
                reply_markup=reply_markup
            )
            logger.info(f"[NOTIFY] ✅ Уведомление доставлено: user={user_id} (попытка {attempt})")
            return True
        except Exception as e:
            logger.warning(f"[NOTIFY] ⚠️ Попытка {attempt}/{retries} не удалась для user={user_id}: {e}")
            if attempt < retries:
                await asyncio.sleep(1.0 * attempt)  # Увеличивающаяся задержка
    logger.error(f"[NOTIFY] ❌ Не удалось доставить уведомление user={user_id} после {retries} попыток")
    return False


# ==========================================
# FSM СОСТОЯНИЯ
# ==========================================

class ClientReg(StatesGroup):
    name = State()
    phone = State()


class StaffLogin(StatesGroup):
    login = State()
    password = State()


class CreateStaff(StatesGroup):
    login = State()
    password = State()
    full_name = State()
    role = State()
    photo = State()


class EditStaff(StatesGroup):
    login = State()
    field = State()
    waiting_new_value = State()


class NewCategory(StatesGroup):
    name = State()


class NewProduct(StatesGroup):
    category = State()
    name = State()
    description = State()
    price = State()
    stock = State()
    photo = State()


class Broadcast(StatesGroup):
    text = State()


# === НОВОЕ: FSM для добавления фото к товару ===
class AddPhotos(StatesGroup):
    waiting_photos = State()


# === НОВОЕ: FSM для редактирования товара ===
class EditProduct(StatesGroup):
    waiting_value = State()


# ==========================================
# ГЛОБАЛЬНАЯ ОТМЕНА
# ==========================================

@dp.message(F.text == "❌ Отмена")
async def global_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    role = get_user_role(message.from_user.id)
    await message.answer("❌ Действие отменено.", reply_markup=get_main_kb(role, user_id=message.from_user.id))


# ==========================================
# КОМАНДА /help
# ==========================================

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    role = get_user_role(message.from_user.id)
    text = (
        "📖 *Справка — Мебельный Завод*\n\n"
        "🤖 *Основные команды:*\n"
        "  /start — Главное меню\n"
        "  /help — Эта справка\n"
        "  /staff — Вход для сотрудников\n"
        "  /logout — Выйти из аккаунта\n\n"
        "🛍 *Для покупателей:*\n"
        "  • Откройте каталог через кнопку меню\n"
        "  • Выберите товары и оформите заказ\n"
        "  • Отслеживайте статус в «📦 Мои заказы»\n\n"
        "👔 *Для сотрудников:*\n"
        "  • Используйте /staff для входа\n"
        "  • Менеджеры: управление заказами\n"
        "  • Администраторы: каталог + статистика\n\n"
        "❓ По вопросам: info@mebel-zavod.ru"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_kb(role, user_id=message.from_user.id))


# ==========================================
# КОМАНДА /logout
# ==========================================

@dp.message(Command("logout"))
async def cmd_logout(message: types.Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Вы не авторизованы. Нажмите /start")
        return

    old_role = user[4]
    if old_role in ('admin', 'manager', 'consultant'):
        set_user_role_and_info(message.from_user.id, 'guest', user[2], None)
        logger.info(f"[LOGOUT] Сотрудник {user[2]} ({old_role}) вышел из аккаунта")
        await message.answer(
            f"🚪 *Вы вышли из аккаунта*\n\n"
            f"Роль: {old_role} → guest\n"
            f"Для повторного входа используйте /staff",
            parse_mode="Markdown",
            reply_markup=get_main_kb('guest', user_id=message.from_user.id)
        )
    else:
        await message.answer(
            "ℹ️ Вы вошли как клиент. Выход из аккаунта не требуется.\n"
            "Нажмите /start для главного меню.",
            reply_markup=get_main_kb(old_role, user_id=message.from_user.id)
        )


# ==========================================
# 1. СТАРТ И РЕГИСТРАЦИЯ КЛИЕНТА
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)

    # ИСПРАВЛЕНО: Если юзер уже зарегистрирован — сразу меню (без повторной регистрации)
    if user:
        role = user[4]
        await message.answer(
            f"👋 С возвращением, {safe_markdown(user[2])}!",
            reply_markup=get_main_kb(role, user_id=message.from_user.id)
        )
    else:
        role = 'guest'
        logger.info(f"[START] Новый пользователь {message.from_user.id}")
        await message.answer(
            "🏭 *Добро пожаловать на Мебельный Завод!*\n\n"
            "Здесь вы можете заказать мебель напрямую от производителя.\n\n"
            "🛍 Откройте каталог, выберите товары и оформите заказ!",
            reply_markup=get_main_kb(role, user_id=message.from_user.id),
            parse_mode="Markdown"
        )


@dp.message(F.text.in_({"🛍 Смотреть Каталог (Гость)", "🛍 Каталог товаров"}))
async def guest_catalog_fallback(message: types.Message):
    await show_catalog_inline(message)


# === НОВОЕ: Быстрая регистрация одной кнопкой ===
@dp.message(F.contact)
async def quick_registration(message: types.Message, state: FSMContext):
    """Быстрая регистрация: пользователь нажимает 1 кнопку, бот берёт данные из Telegram"""
    try:
        await state.clear()
        contact = message.contact

        # Проверяем что контакт принадлежит отправителю (защита от спуфинга)
        if contact.user_id and contact.user_id != message.from_user.id:
            await message.answer("❌ Отправьте *свой* контакт, а не чужой.", parse_mode="Markdown")
            return

        # Проверяем, может уже зарегистрирован
        user = get_user(message.from_user.id)
        if user and user[4] == 'client':
            await message.answer(
                f"✅ Вы уже зарегистрированы как *{user[2]}*!\n\n"
                f"📱 Телефон: {user[3]}\n\n"
                f"Используйте меню ниже 👇",
                reply_markup=get_main_kb('client', user_id=message.from_user.id),
                parse_mode="Markdown"
            )
            return

        # Берём имя из Telegram контакта
        first = contact.first_name or message.from_user.first_name or ''
        last = contact.last_name or message.from_user.last_name or ''
        full_name = f"{last} {first}".strip() if last else first.strip()

        if not full_name or len(full_name) < 2:
            full_name = message.from_user.full_name or f"Пользователь {message.from_user.id}"

        # Берём телефон из контакта
        phone = contact.phone_number
        if not phone:
            await message.answer("❌ Не удалось получить номер телефона. Попробуйте ещё раз.")
            return

        formatted_phone = normalize_phone(phone)

        # Регистрируем!
        register_user(message.from_user.id, message.from_user.username, full_name, formatted_phone)
        set_user_role_and_info(message.from_user.id, 'client', full_name, None)

        logger.info(f"[REG] ✅ Быстрая регистрация: {full_name} ({formatted_phone})")

        await message.answer(
            f"✅ *Регистрация за 1 секунду!*\n\n"
            f"👋 Добро пожаловать, *{full_name}*!\n"
            f"📱 Телефон: {formatted_phone}\n\n"
            f"Данные взяты из вашего Telegram-профиля.\n"
            f"Нажмите «🛍 Открыть каталог» чтобы выбрать мебель!",
            reply_markup=get_main_kb('client', user_id=message.from_user.id),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[REG] Ошибка быстрой регистрации: {e}")
        await message.answer("⚠️ Ошибка регистрации. Попробуйте ещё раз.")


@dp.message(F.text == "🔑 Войти (Регистрация)")
async def guest_login(message: types.Message, state: FSMContext):
    # ИСПРАВЛЕНО: проверяем, может пользователь уже зарегистрирован
    user = get_user(message.from_user.id)
    if user and user[4] == 'client':
        await message.answer(
            f"✅ Вы уже зарегистрированы как *{user[2]}*!\n\n"
            f"📱 Телефон: {user[3]}\n\n"
            f"Используйте меню ниже 👇",
            reply_markup=get_main_kb('client', user_id=message.from_user.id),
            parse_mode="Markdown"
        )
        return

    await message.answer(
        "📝 *Регистрация клиента*\n\n"
        "Введите ваше ФИО (кириллицей):\n"
        "_Например: Иванов Иван Иванович_",
        reply_markup=cancel_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(ClientReg.name)


@dp.message(ClientReg.name)
async def reg_name(message: types.Message, state: FSMContext):
    try:
        if not message.text:
            await message.answer("❌ Отправьте ФИО *текстом*, а не фото/стикер.", parse_mode="Markdown")
            return
        fio = message.text.strip()[:MAX_NAME_LENGTH]
        is_valid, error = validate_fio(fio)

        if not is_valid:
            logger.warning(f"[REG] Невалидное ФИО от {message.from_user.id}: '{fio}' — {error}")
            await message.answer(
                f"❌ *Ошибка:* {error}\n\n"
                "Введите корректное ФИО на кириллице:\n"
                "_Например: Иванов Иван или Иванов Иван Иванович_",
                parse_mode="Markdown"
            )
            return

        await state.update_data(name=fio)
        await state.set_state(ClientReg.phone)
        await message.answer(
            "📱 *Введите номер телефона:*\n\n"
            "Формат: +79001234567 или 89001234567\n\n"
            "_Или нажмите кнопку «📱 Отправить контакт»_",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📱 Отправить контакт", request_contact=True)],
                    [KeyboardButton(text="❌ Отмена")]
                ],
                resize_keyboard=True
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[REG] Ошибка обработки ФИО: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуйте ещё раз.")


@dp.message(ClientReg.phone)
async def reg_phone(message: types.Message, state: FSMContext):
    try:
        if message.contact:
            phone = message.contact.phone_number
        else:
            if not message.text:
                await message.answer("❌ Введите номер телефона текстом или нажмите «📱 Отправить контакт».")
                return
            phone = message.text.strip()[:30]
            is_valid, error = validate_phone(phone)

            if not is_valid:
                logger.warning(f"[REG] Невалидный телефон от {message.from_user.id}: '{phone}' — {error}")
                await message.answer(
                    f"❌ *Ошибка:* {error}\n\n"
                    "Введите номер телефона в формате:\n"
                    "• +79001234567\n"
                    "• 89001234567",
                    parse_mode="Markdown"
                )
                return

        formatted_phone = normalize_phone(phone)

        data = await state.get_data()
        register_user(message.from_user.id, message.from_user.username, data['name'], formatted_phone)
        set_user_role_and_info(message.from_user.id, 'client', data['name'], None)
        await state.clear()

        logger.info(f"[REG] ✅ Клиент зарегистрирован: {data['name']} ({formatted_phone})")

        await message.answer(
            f"✅ *Вы успешно зарегистрированы!*\n\n"
            f"👋 Добро пожаловать, *{data['name']}*!\n"
            f"📱 Телефон: {formatted_phone}\n\n"
            f"Нажмите «🛍 Открыть каталог» чтобы выбрать мебель!",
            reply_markup=get_main_kb('client', user_id=message.from_user.id),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[REG] Ошибка обработки телефона: {e}")
        await message.answer("⚠️ Произошла ошибка. Попробуйте ещё раз.")


# ==========================================
# 2. СЛУЖЕБНЫЙ ВХОД (/staff)
# ==========================================

@dp.message(Command("staff"))
async def staff_start(message: types.Message):
    await message.answer(
        "🔐 *Служебный вход*\nВыберите вашу должность:",
        reply_markup=staff_login_kb(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("login_"))
async def staff_login_step1(callback: types.CallbackQuery, state: FSMContext):
    role = callback.data.split("_")[1]
    role_names = {'admin': 'Администратор', 'manager': 'Менеджер', 'consultant': 'Консультант'}
    await state.update_data(target_role=role)
    await state.set_state(StaffLogin.login)
    await callback.message.answer(
        f"Вход: *{role_names.get(role, role)}*\n\n👤 Введите логин:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    await callback.answer()


@dp.message(StaffLogin.login)
async def staff_login_step2(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите логин текстом.")
        return
    await state.update_data(login=message.text.strip()[:50])
    await state.set_state(StaffLogin.password)
    await message.answer("🔑 Введите пароль:")


@dp.message(StaffLogin.password)
async def staff_login_step3(message: types.Message, state: FSMContext):
    try:
        if not message.text:
            await message.answer("❌ Введите пароль текстом.")
            return
        data = await state.get_data()
        cred = check_staff_login(data['login'], message.text.strip()[:100])
        if cred:
            real_role, full_name, photo_id = cred
            set_user_role_and_info(message.from_user.id, real_role, full_name, photo_id)
            await state.clear()
            text = f"✅ Вход выполнен!\n\nЗдравствуйте, *{full_name}*!"
            if photo_id:
                await message.answer_photo(photo_id, caption=text,
                                           reply_markup=get_main_kb(real_role, user_id=message.from_user.id), parse_mode="Markdown")
            else:
                await message.answer(text, reply_markup=get_main_kb(real_role, user_id=message.from_user.id), parse_mode="Markdown")
        else:
            await message.answer(
                "⛔ *Неверный логин или пароль.*\n\n"
                "Попробуйте снова. Введите логин:",
                parse_mode="Markdown"
            )
            await state.set_state(StaffLogin.login)
    except Exception as e:
        logger.error(f"[AUTH] Ошибка входа: {e}")
        await message.answer("⚠️ Ошибка авторизации. Попробуйте позже.")
        await state.clear()


# ==========================================
# 3. ПРОФИЛЬ И НАСТРОЙКИ
# ==========================================

@dp.message(F.text.in_({"👤 Мой профиль", "👤 Личный кабинет"}))
async def cmd_profile(message: types.Message):
    try:
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("Вы не зарегистрированы. Нажмите /start")
            return
        role_map = {
            'admin': '👑 Директор', 'manager': '👔 Менеджер',
            'consultant': '🎧 Консультант', 'client': '👤 Клиент'
        }
        role_str = role_map.get(user[4], user[4])
        text = (
            f"🪪 *Карточка пользователя*\n\n"
            f"👤 *ФИО:* {user[2] or 'Не указано'}\n"
            f"🔑 *Роль:* {role_str}\n"
            f"📱 *Телефон:* {user[3] or 'Не указан'}\n"
            f"🆔 *ID:* `{user[0]}`"
        )
        if user[5]:
            await message.answer_photo(user[5], caption=text, parse_mode="Markdown", reply_markup=profile_kb())
        else:
            await message.answer(text, parse_mode="Markdown", reply_markup=profile_kb())
    except Exception as e:
        logger.error(f"[PROFILE] Ошибка: {e}")
        await message.answer("⚠️ Ошибка загрузки профиля.")


@dp.callback_query(F.data == "logout")
async def logout_handler(callback: types.CallbackQuery):
    set_user_role_and_info(callback.from_user.id, 'guest', callback.from_user.full_name, None)
    await callback.message.delete()
    await callback.message.answer("👋 Вы вышли из аккаунта.", reply_markup=get_main_kb('guest', user_id=callback.from_user.id))
    logger.info(f"[AUTH] Выход: {callback.from_user.id}")


@dp.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: types.Message):
    if get_user_role(message.from_user.id) != 'admin':
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Создать бэкап (Демо)", callback_data="do_backup")],
        [InlineKeyboardButton(text="ℹ️ О системе", callback_data="about_system")]
    ])
    await message.answer("⚙️ *Настройки системы*", parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "do_backup")
async def do_backup(callback: types.CallbackQuery):
    await callback.answer("✅ Бэкап базы данных создан!", show_alert=True)


@dp.callback_query(F.data == "about_system")
async def about_system(callback: types.CallbackQuery):
    await callback.answer(
        "FurnitureBot v2.1\nAiogram 3.x + SQLite + Mini App\nС валидацией, складским учётом и фото-каруселью\nДипломный проект",
        show_alert=True
    )


# ==========================================
# 4. УПРАВЛЕНИЕ ПЕРСОНАЛОМ (АДМИН)
# ==========================================

@dp.message(F.text == "👥 Управление персоналом")
async def admin_staff_menu(message: types.Message):
    if get_user_role(message.from_user.id) != 'admin':
        return
    try:
        creds = get_all_staff_credentials()
        text = "📂 *Сотрудники компании:*\n"
        buttons = []
        for c in creds:
            icon = {"admin": "👑", "manager": "👔", "consultant": "🎧"}.get(c[2], "👤")
            buttons.append([InlineKeyboardButton(text=f"{icon} {c[1]} ({c[0]})", callback_data=f"viewstaff_{c[0]}")])
        buttons.append([InlineKeyboardButton(text="➕ Добавить сотрудника", callback_data="add_staff_manual")])
        await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        logger.error(f"[STAFF] Ошибка списка сотрудников: {e}")
        await message.answer("⚠️ Ошибка загрузки списка сотрудников.")


@dp.callback_query(F.data.startswith("viewstaff_"))
async def view_staff_card(callback: types.CallbackQuery):
    try:
        login = callback.data.split("_", 1)[1]
        info = get_staff_info(login)
        if not info:
            await callback.answer("Сотрудник не найден")
            return
        role_names = {'admin': 'Администратор', 'manager': 'Менеджер', 'consultant': 'Консультант'}
        text = (
            f"👤 *{info[1]}*\n\n"
            f"🔑 Логин: `{info[0]}`\n"
            f"💼 Роль: {role_names.get(info[2], info[2])}"
        )
        btns = [
            [InlineKeyboardButton(text="✏️ Изменить ФИО", callback_data=f"editst_{login}_fullname")],
            [InlineKeyboardButton(text="✏️ Изменить Роль", callback_data=f"editst_{login}_role")],
        ]
        if info[2] != 'admin':
            btns.append([InlineKeyboardButton(text="❌ УВОЛИТЬ", callback_data=f"kill_{login}")])
        btns.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_staff")])

        if info[3]:
            await callback.message.answer_photo(info[3], caption=text, parse_mode="Markdown",
                                                reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
        else:
            try:
                await callback.message.edit_text(text, parse_mode="Markdown",
                                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
            except Exception:
                await callback.message.answer(text, parse_mode="Markdown",
                                              reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
        await callback.answer()
    except Exception as e:
        logger.error(f"[STAFF] Ошибка просмотра карточки: {e}")
        await callback.answer("Ошибка загрузки")


@dp.callback_query(F.data == "back_staff")
async def back_staff(callback: types.CallbackQuery):
    await callback.message.delete()
    await admin_staff_menu(callback.message)


@dp.callback_query(F.data == "add_staff_manual")
async def add_staff_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(CreateStaff.login)
    await callback.message.answer("1️⃣ Введите *логин* для нового сотрудника:", parse_mode="Markdown",
                                  reply_markup=cancel_kb())
    await callback.answer()


@dp.message(CreateStaff.login)
async def add_staff_login(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите логин текстом.")
        return
    login = message.text.strip()[:50]
    if len(login) < 3:
        await message.answer("❌ Логин должен содержать минимум 3 символа. Попробуйте ещё:")
        return
    await state.update_data(login=login)
    await state.set_state(CreateStaff.password)
    await message.answer("2️⃣ Введите *пароль* (минимум 4 символа):", parse_mode="Markdown")


@dp.message(CreateStaff.password)
async def add_staff_password(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите пароль текстом.")
        return
    pwd = message.text.strip()[:100]
    if len(pwd) < 4:
        await message.answer("❌ Пароль должен содержать минимум 4 символа. Попробуйте ещё:")
        return
    await state.update_data(password=pwd)
    await state.set_state(CreateStaff.full_name)
    await message.answer("3️⃣ Введите *ФИО* сотрудника (кириллицей):", parse_mode="Markdown")


@dp.message(CreateStaff.full_name)
async def add_staff_name(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите ФИО текстом.")
        return
    fio = message.text.strip()[:MAX_NAME_LENGTH]
    is_valid, error = validate_fio(fio)
    if not is_valid:
        await message.answer(f"❌ *Ошибка:* {error}\n\nВведите корректное ФИО:", parse_mode="Markdown")
        return
    await state.update_data(full_name=fio)
    await state.set_state(CreateStaff.role)
    await message.answer(
        "4️⃣ Выберите *роль*:\n\n"
        "• `manager` — Менеджер\n"
        "• `consultant` — Консультант\n"
        "• `admin` — Администратор",
        parse_mode="Markdown"
    )


@dp.message(CreateStaff.role)
async def add_staff_role(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите роль текстом: `manager`, `consultant` или `admin`", parse_mode="Markdown")
        return
    role = message.text.strip().lower()[:20]
    if role not in ('manager', 'consultant', 'admin'):
        await message.answer("❌ Укажите одну из ролей: `manager`, `consultant`, `admin`", parse_mode="Markdown")
        return
    await state.update_data(role=role)
    await state.set_state(CreateStaff.photo)
    await message.answer(
        "5️⃣ Отправьте *фото* сотрудника или нажмите «Нет»:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Нет")]], resize_keyboard=True)
    )


@dp.message(CreateStaff.photo, F.photo)
async def add_staff_with_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    create_staff_account(data['login'], data['password'], data['role'], data['full_name'], photo_id)
    await state.clear()
    await message.answer(
        f"✅ Сотрудник *{data['full_name']}* создан!\n"
        f"🔑 Логин: `{data['login']}`\n💼 Роль: {data['role']}",
        parse_mode="Markdown", reply_markup=get_main_kb('admin', user_id=message.from_user.id)
    )


@dp.message(CreateStaff.photo)
async def add_staff_no_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    create_staff_account(data['login'], data['password'], data['role'], data['full_name'], None)
    await state.clear()
    await message.answer(
        f"✅ Сотрудник *{data['full_name']}* создан!\n"
        f"🔑 Логин: `{data['login']}`\n💼 Роль: {data['role']}",
        parse_mode="Markdown", reply_markup=get_main_kb('admin', user_id=message.from_user.id)
    )


@dp.callback_query(F.data.startswith("editst_"))
async def edit_staff_start(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    login = parts[1]
    field = parts[2]
    await state.update_data(login=login, field=field)
    await state.set_state(EditStaff.waiting_new_value)
    field_name = "ФИО" if field == "fullname" else "роль (manager/consultant/admin)"
    await callback.message.answer(f"✏️ Введите новое значение для *{field_name}*:", parse_mode="Markdown",
                                  reply_markup=cancel_kb())
    await callback.answer()


@dp.message(EditStaff.waiting_new_value)
async def edit_staff_finish(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите значение текстом, а не фото/стикер.")
        return
    data = await state.get_data()
    value = message.text.strip()[:MAX_NAME_LENGTH]

    if data['field'] == 'fullname':
        is_valid, error = validate_fio(value)
        if not is_valid:
            await message.answer(f"❌ *Ошибка:* {error}", parse_mode="Markdown")
            return
        db_field = "full_name"
    else:
        if value not in ('manager', 'consultant', 'admin'):
            await message.answer("❌ Роль должна быть: `manager`, `consultant` или `admin`", parse_mode="Markdown")
            return
        db_field = "role"

    update_staff_credential(data['login'], db_field, value)
    await state.clear()
    await message.answer("✅ Данные обновлены!", reply_markup=get_main_kb('admin', user_id=message.from_user.id))


@dp.callback_query(F.data.startswith("kill_"))
async def kill_staff(callback: types.CallbackQuery):
    login = callback.data.split("_", 1)[1]
    delete_staff_credential(login)
    await callback.answer("Сотрудник уволен", show_alert=True)
    await callback.message.edit_text("❌ Сотрудник уволен.")


# ==========================================
# 5. КАТАЛОГ (СКЛАД) — inline-режим
# ==========================================

@dp.message(F.text.in_({"🏭 Склад (Каталог)", "🏭 Склад"}))
async def show_catalog_inline(message: types.Message):
    try:
        cats = get_categories()
        role = get_user_role(message.from_user.id)
        buttons = []
        for cat in cats:
            buttons.append([InlineKeyboardButton(text=f"📂 {cat}", callback_data=f"cat_{cat}")])
        if role == 'admin':
            buttons.append([InlineKeyboardButton(text="➕ Новая категория", callback_data="add_cat")])
        await message.answer("📦 *Каталог товаров*\n\nВыберите категорию:", parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        logger.error(f"[CATALOG] Ошибка каталога: {e}")
        await message.answer("⚠️ Ошибка загрузки каталога.")


@dp.callback_query(F.data.startswith("cat_"))
async def show_category(callback: types.CallbackQuery):
    try:
        cat = callback.data.split("_", 1)[1]
        prods = get_products_by_category(cat)
        role = get_user_role(callback.from_user.id)
        buttons = []
        for p in prods:
            stock_icon = "✅" if (len(p) > 6 and p[6] > 0) else "❌"
            stock_text = f" [{p[6]} шт.]" if (len(p) > 6) else ""
            buttons.append([InlineKeyboardButton(
                text=f"{stock_icon} {p[1]} — {p[2]:,.0f}₽{stock_text}",
                callback_data=f"p_{p[0]}"
            )])
        if role == 'admin':
            buttons.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data=f"add_pr_{cat}")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_cat")])
        try:
            await callback.message.edit_text(f"📂 *{cat}*", parse_mode="Markdown",
                                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception:
            await callback.message.answer(f"📂 *{cat}*", parse_mode="Markdown",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()
    except Exception as e:
        logger.error(f"[CATALOG] Ошибка категории: {e}")
        await callback.answer("Ошибка загрузки")


@dp.callback_query(F.data.startswith("p_"))
async def show_product(callback: types.CallbackQuery):
    try:
        pid = int(callback.data.split("_")[1])
        p = get_product_by_id(pid)
        if not p:
            await callback.answer("Товар не найден")
            return
        role = get_user_role(callback.from_user.id)
        stock = p[6] if len(p) > 6 else 0
        stock_status = f"✅ В наличии: {stock} шт." if stock > 0 else "❌ Нет в наличии"

        # Получаем количество фото
        photos = get_product_photos(pid)
        photos_info = f"\n📷 Фотографий: {len(photos)}" if photos else "\n📷 Фото не загружены"

        text = f"📦 *{p[1]}*\n\n📝 {p[2]}\n\n💰 Цена: *{p[3]:,.0f} ₽*\n📦 {stock_status}{photos_info}"
        buttons = []
        if role == 'admin':
            # Кнопки редактирования товара
            buttons.append([
                InlineKeyboardButton(text="✏️ Название", callback_data=f"editpr_{pid}_name"),
                InlineKeyboardButton(text="✏️ Цена", callback_data=f"editpr_{pid}_price"),
            ])
            buttons.append([
                InlineKeyboardButton(text="✏️ Описание", callback_data=f"editpr_{pid}_description"),
                InlineKeyboardButton(text="✏️ Остаток", callback_data=f"editpr_{pid}_stock_quantity"),
            ])
            buttons.append([
                InlineKeyboardButton(text="📷 Добавить фото", callback_data=f"addphoto_{pid}"),
                InlineKeyboardButton(text="🗑 Управление фото", callback_data=f"managephotos_{pid}"),
            ])
            buttons.append([InlineKeyboardButton(text="❌ Удалить товар", callback_data=f"delp_{pid}")])
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"cat_{p[4]}")])

        if p[5]:  # image_path
            try:
                await callback.message.answer_photo(
                    p[5], caption=text, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
                await callback.message.delete()
            except Exception:
                try:
                    await callback.message.edit_text(text, parse_mode="Markdown",
                                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
                except Exception:
                    await callback.message.answer(text, parse_mode="Markdown",
                                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            try:
                await callback.message.edit_text(text, parse_mode="Markdown",
                                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            except Exception:
                await callback.message.answer(text, parse_mode="Markdown",
                                              reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()
    except Exception as e:
        logger.error(f"[CATALOG] Ошибка товара: {e}")
        await callback.answer("Ошибка загрузки")


@dp.callback_query(F.data == "back_cat")
async def back_to_catalog(callback: types.CallbackQuery):
    await callback.message.delete()
    await show_catalog_inline(callback.message)


# --- Добавление категории ---
@dp.callback_query(F.data == "add_cat")
async def add_category_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(NewCategory.name)
    await callback.message.answer("📁 Введите название новой категории:", reply_markup=cancel_kb())
    await callback.answer()


@dp.message(NewCategory.name)
async def add_category_finish(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите название категории текстом.")
        return
    name = message.text.strip()[:100]
    if len(name) < 2:
        await message.answer("❌ Название слишком короткое. Минимум 2 символа:")
        return
    add_category(name)
    await state.clear()
    await message.answer(f"✅ Категория «{name}» создана!", reply_markup=get_main_kb('admin', user_id=message.from_user.id))


# --- Добавление товара ---
@dp.callback_query(F.data.startswith("add_pr_"))
async def add_product_start(callback: types.CallbackQuery, state: FSMContext):
    cat = callback.data.split("_", 2)[2]
    await state.update_data(category=cat)
    await state.set_state(NewProduct.name)
    await callback.message.answer(f"📦 Новый товар в *{cat}*\n\n1️⃣ Введите *название*:",
                                  parse_mode="Markdown", reply_markup=cancel_kb())
    await callback.answer()


@dp.message(NewProduct.name)
async def add_product_name(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите название товара текстом.")
        return
    name = message.text.strip()[:MAX_NAME_LENGTH]
    if len(name) < 3:
        await message.answer("❌ Название слишком короткое. Минимум 3 символа:")
        return
    await state.update_data(name=name)
    await state.set_state(NewProduct.description)
    await message.answer("2️⃣ Введите *описание* товара:", parse_mode="Markdown")


@dp.message(NewProduct.description)
async def add_product_desc(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите описание товара текстом.")
        return
    await state.update_data(description=message.text.strip()[:MAX_DESCRIPTION_LENGTH])
    await state.set_state(NewProduct.price)
    await message.answer("3️⃣ Введите *цену* (число, в рублях):", parse_mode="Markdown")


@dp.message(NewProduct.price)
async def add_product_price(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите цену числом.")
        return
    try:
        price = float(message.text.replace(',', '.').replace(' ', '')[:20])
        if price <= 0:
            raise ValueError("Цена должна быть положительной")
    except ValueError:
        await message.answer("❌ Введите корректное положительное число (например: 45000):")
        return
    await state.update_data(price=price)
    await state.set_state(NewProduct.stock)
    await message.answer("4️⃣ Введите *количество на складе* (число):", parse_mode="Markdown")


@dp.message(NewProduct.stock)
async def add_product_stock(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Введите количество числом.")
        return
    try:
        stock = int(message.text.strip()[:10])
        if stock < 0:
            raise ValueError("Кол-во не может быть отрицательным")
    except ValueError:
        await message.answer("❌ Введите корректное неотрицательное целое число (например: 10):")
        return
    await state.update_data(stock=stock)
    await state.set_state(NewProduct.photo)
    await message.answer(
        "5️⃣ Отправьте *фото* товара или нажмите «Нет»:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Нет")]], resize_keyboard=True)
    )


@dp.message(NewProduct.photo, F.photo)
async def add_product_with_photo(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    ext = file_info.file_path.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    destination = os.path.join(IMAGES_DIR, filename)
    await bot.download_file(file_info.file_path, destination)

    data = await state.get_data()
    add_product(data['name'], data['description'], data['price'], data['category'], filename, data.get('stock', 10))

    await state.clear()
    await message.answer(
        f"✅ Товар «{data['name']}» добавлен!\n"
        f"💰 Цена: {data['price']:,.0f}₽ | 📦 На складе: {data.get('stock', 10)} шт.\n"
        f"🖼 Фото сохранено: {filename}",
        reply_markup=get_main_kb('admin', user_id=message.from_user.id)
    )


@dp.message(NewProduct.photo)
async def add_product_no_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    add_product(data['name'], data['description'], data['price'], data['category'], None, data.get('stock', 10))
    await state.clear()
    await message.answer(
        f"✅ Товар «{data['name']}» добавлен!\n"
        f"💰 Цена: {data['price']:,.0f}₽ | 📦 На складе: {data.get('stock', 10)} шт.",
        reply_markup=get_main_kb('admin', user_id=message.from_user.id)
    )


@dp.callback_query(F.data.startswith("delp_"))
async def delete_product_confirm(callback: types.CallbackQuery):
    """Показывает подтверждение перед удалением товара"""
    pid = callback.data.split("_")[1]
    product = get_product_by_id(int(pid))
    name = product[1] if product else "Неизвестный"
    await callback.message.edit_text(
        f"⚠️ *Вы уверены, что хотите удалить товар?*\n\n"
        f"📦 «{safe_markdown(name)}»\n\n"
        f"Это действие необратимо!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirmdel_{pid}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"p_{pid}"),
            ]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("confirmdel_"))
async def delete_product_execute(callback: types.CallbackQuery):
    """Удаляет товар после подтверждения"""
    pid = callback.data.split("_")[1]
    delete_product(pid)
    logger.info(f"[CATALOG] Товар #{pid} удалён пользователем {callback.from_user.id}")
    await callback.answer("Товар удалён", show_alert=True)
    await callback.message.edit_text("❌ Товар удалён из каталога.")


# ==========================================
# 5.3 РЕДАКТИРОВАНИЕ ТОВАРА (НОВОЕ!)
# ==========================================

@dp.callback_query(F.data.startswith("editpr_"))
async def edit_product_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало редактирования поля товара"""
    parts = callback.data.split("_")
    pid = int(parts[1])
    field = parts[2]

    # Для stock_quantity callback_data = editpr_ID_stock_quantity
    if len(parts) > 3:
        field = '_'.join(parts[2:])

    product = get_product_by_id(pid)
    if not product:
        await callback.answer("Товар не найден")
        return

    field_names = {
        'name': 'название',
        'description': 'описание',
        'price': 'цену (число в рублях)',
        'stock_quantity': 'количество на складе (целое число)',
    }

    # Текущее значение
    field_values = {
        'name': product[1],
        'description': product[2],
        'price': f"{product[3]:,.0f} ₽",
        'stock_quantity': f"{product[6]} шт." if len(product) > 6 else "N/A",
    }

    await state.set_state(EditProduct.waiting_value)
    await state.update_data(product_id=pid, field=field, product_name=product[1], category=product[4])

    await callback.message.answer(
        f"✏️ *Редактирование товара «{product[1]}»*\n\n"
        f"Поле: *{field_names.get(field, field)}*\n"
        f"Текущее значение: `{field_values.get(field, '—')}`\n\n"
        f"Введите новое значение:",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@dp.message(EditProduct.waiting_value)
async def edit_product_finish(message: types.Message, state: FSMContext):
    """Применение нового значения для товара"""
    try:
        if not message.text:
            await message.answer("❌ Введите значение текстом.")
            return
        data = await state.get_data()
        pid = data['product_id']
        field = data['field']
        value = message.text.strip()[:MAX_DESCRIPTION_LENGTH]

        # Валидация в зависимости от поля
        if field == 'price':
            try:
                value = float(value.replace(',', '.').replace(' ', '').replace('₽', ''))
                if value <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("❌ Введите корректную цену (положительное число, например: 45000):")
                return

        elif field == 'stock_quantity':
            try:
                value = int(value.replace(' ', ''))
                if value < 0:
                    raise ValueError
            except ValueError:
                await message.answer("❌ Введите корректное количество (целое неотрицательное число, например: 10):")
                return

        elif field == 'name':
            if len(value) < 3:
                await message.answer("❌ Название должно быть минимум 3 символа:")
                return

        elif field == 'description':
            if len(value) < 5:
                await message.answer("❌ Описание должно быть минимум 5 символов:")
                return

        # Обновляем в БД
        success = update_product(pid, field, value)
        await state.clear()

        if success:
            field_names = {'name': 'Название', 'description': 'Описание', 'price': 'Цена', 'stock_quantity': 'Остаток'}
            await message.answer(
                f"✅ *Товар обновлён!*\n\n"
                f"📦 «{data['product_name']}»\n"
                f"📝 {field_names.get(field, field)}: `{value}`",
                parse_mode="Markdown",
                reply_markup=get_main_kb('admin', user_id=message.from_user.id)
            )
            logger.info(f"[CATALOG] ✏️ Товар #{pid} обновлён: {field} = {value}")
        else:
            await message.answer("❌ Ошибка обновления. Попробуйте позже.", reply_markup=get_main_kb('admin', user_id=message.from_user.id))
    except Exception as e:
        logger.error(f"[CATALOG] Ошибка редактирования товара: {e}")
        await state.clear()
        await message.answer("⚠️ Ошибка. Попробуйте позже.", reply_markup=get_main_kb('admin', user_id=message.from_user.id))


# ==========================================
# 5.1 ДОБАВЛЕНИЕ ФОТО К ТОВАРУ (НОВОЕ!)
# ==========================================

@dp.callback_query(F.data.startswith("addphoto_"))
async def add_photo_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало загрузки фотографий для товара"""
    pid = int(callback.data.split("_")[1])
    product = get_product_by_id(pid)
    if not product:
        await callback.answer("Товар не найден")
        return

    existing_photos = get_product_photos(pid)
    await state.set_state(AddPhotos.waiting_photos)
    await state.update_data(product_id=pid, product_name=product[1], photos_added=0)

    await callback.message.answer(
        f"📷 *Загрузка фото для «{product[1]}»*\n\n"
        f"Текущее кол-во фото: {len(existing_photos)}\n\n"
        f"Отправляйте фотографии *по одной*.\n"
        f"Когда закончите — нажмите «✅ Завершить».",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="✅ Завершить загрузку")], [KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )
    )
    await callback.answer()


@dp.message(AddPhotos.waiting_photos, F.photo)
async def receive_product_photo(message: types.Message, state: FSMContext):
    """Приём одного фото для товара (с лимитом)"""
    data = await state.get_data()
    pid = data['product_id']

    # Проверяем лимит фотографий
    existing = get_product_photos(pid)
    if len(existing) >= MAX_PHOTOS_PER_PRODUCT:
        await message.answer(
            f"⚠️ Достигнут лимит — максимум *{MAX_PHOTOS_PER_PRODUCT} фото* на товар.\n"
            f"Нажмите «✅ Завершить загрузку» или удалите старые фото.",
            parse_mode="Markdown"
        )
        return

    file_id = message.photo[-1].file_id

    # Сохраняем file_id в таблицу product_photos
    add_product_photo(pid, file_id)

    photos_added = data.get('photos_added', 0) + 1
    await state.update_data(photos_added=photos_added)

    await message.answer(
        f"✅ Фото #{photos_added} сохранено для «{data['product_name']}»\n\n"
        f"Отправьте ещё фото или нажмите «✅ Завершить загрузку»."
    )
    logger.info(f"[PHOTO] Фото добавлено: товар #{pid}, file_id={file_id[:20]}...")


@dp.message(AddPhotos.waiting_photos, F.text == "✅ Завершить загрузку")
async def finish_photo_upload(message: types.Message, state: FSMContext):
    """Завершение загрузки фотографий"""
    data = await state.get_data()
    photos_added = data.get('photos_added', 0)
    total_photos = len(get_product_photos(data['product_id']))

    await state.clear()
    await message.answer(
        f"📷 *Загрузка завершена!*\n\n"
        f"Товар: «{data['product_name']}»\n"
        f"Добавлено за сессию: {photos_added} фото\n"
        f"Всего фото у товара: {total_photos}",
        parse_mode="Markdown",
        reply_markup=get_main_kb('admin', user_id=message.from_user.id)
    )
    logger.info(f"[PHOTO] Загрузка завершена: товар #{data['product_id']}, добавлено {photos_added}")


@dp.message(AddPhotos.waiting_photos)
async def add_photo_invalid(message: types.Message):
    """Если отправили не фото"""
    await message.answer(
        "📷 Отправьте *фотографию* (не файл!)\n\n"
        "Или нажмите «✅ Завершить загрузку».",
        parse_mode="Markdown"
    )


# ==========================================
# 5.2 КОНСУЛЬТАНТ: ЗАКАЗЫ И ПОМОЩЬ (НОВОЕ!)
# ==========================================

@dp.message(F.text == "📋 Заказы (просмотр)")
async def consultant_orders_view(message: types.Message):
    """Консультант: просмотр всех заказов (только чтение)"""
    role = get_user_role(message.from_user.id)
    if role != 'consultant':
        return

    try:
        orders = get_all_orders()
        if not orders:
            await message.answer("📋 Заказов пока нет.")
            return

        text = "📋 *Все заказы (только просмотр):*\n\n"
        for o in orders[:15]:  # Показываем последние 15
            status_icon = {
                'Новый': '🆕', 'Оплачено': '💰', 'В обработке': '⚙️',
                'Готов к отгрузке': '📦', 'Отгружен': '🚛', 'Отменён': '❌'
            }.get(o[2], '❓')
            text += f"{status_icon} *#{o[0]}* | {o[4] or 'Клиент'} | {o[3]:,.0f}₽ | {o[2]}\n"
            text += f"   📅 {o[5]}\n\n"

        if len(orders) > 15:
            text += f"_...и ещё {len(orders) - 15} заказов_"

        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[CONSULTANT] Ошибка просмотра заказов: {e}")
        await message.answer("⚠️ Ошибка загрузки заказов.")


@dp.message(F.text == "💬 Помощь клиенту")
async def consultant_help(message: types.Message):
    """Консультант: информация для помощи клиентам"""
    role = get_user_role(message.from_user.id)
    if role != 'consultant':
        return

    try:
        from database import get_statistics
        stats = get_statistics()

        text = (
            "💬 *Информация для консультирования клиентов:*\n\n"
            "📦 *Каталог:*\n"
            f"  • Товаров в каталоге: {stats['products']}\n"
            f"  • Единиц на складе: {stats.get('total_stock', 0)}\n\n"
            "💳 *Способы оплаты:*\n"
            "  • Банковская карта (ЮKassa)\n"
            "  • Наличные при получении\n\n"
            "🚚 *Доставка:*\n"
            "  • По Москве: 1-3 рабочих дня\n"
            "  • По МО: 2-5 рабочих дней\n"
            "  • Регионы: 5-14 рабочих дней\n\n"
            "📞 *Контакты:*\n"
            "  • Телефон: +7 (495) 123-45-67\n"
            "  • Email: info@mebel-zavod.ru\n"
            "  • Адрес: г. Москва, ул. Производственная, 15\n\n"
            "🔄 *Возврат и обмен:*\n"
            "  • Возврат в течение 14 дней\n"
            "  • Обмен при обнаружении брака\n"
            "  • Гарантия: 12 месяцев"
        )
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[CONSULTANT] Ошибка помощи: {e}")
        await message.answer("⚠️ Ошибка загрузки информации.")


# ==========================================
# 6. ПРИЁМ ЗАКАЗА ИЗ MINI APP
# ==========================================

@dp.message(F.web_app_data)
async def handle_webapp_order(message: types.Message):
    """Обработка данных из Mini App с валидацией"""
    try:
        if is_throttled(message.from_user.id):
            logger.warning(f"[ORDER] Throttled: {message.from_user.id}")
            await message.answer("⏳ Подождите несколько секунд...")
            return

        data = json.loads(message.web_app_data.data)
        logger.info(f"[ORDER] Данные из WebApp от {message.from_user.id}: {len(data.get('items', []))} товаров")

        items = data.get('items', [])
        customer = data.get('customer', {})
        total = data.get('total', 0)

        if not items:
            await message.answer("⚠️ Корзина пуста. Добавьте товары!")
            return

        # Защита от слишком большого заказа
        if len(items) > MAX_CART_ITEMS:
            await message.answer(f"⚠️ Слишком много товаров. Максимум {MAX_CART_ITEMS} позиций в одном заказе.")
            return

        # Защита от некорректной суммы
        if not isinstance(total, (int, float)) or total <= 0 or total > 100_000_000:
            await message.answer("⚠️ Некорректная сумма заказа.")
            return

        name = customer.get('name', '').strip()[:MAX_NAME_LENGTH]
        phone = customer.get('phone', '').strip()[:30]
        address = customer.get('address', '').strip()[:MAX_ADDRESS_LENGTH]

        is_valid_name, name_error = validate_fio(name)
        if not is_valid_name:
            await message.answer(f"❌ *Ошибка ФИО:* {name_error}\n\nПопробуйте оформить заказ заново.",
                                 parse_mode="Markdown")
            return

        is_valid_phone, phone_error = validate_phone(phone)
        if not is_valid_phone:
            await message.answer(f"❌ *Ошибка телефона:* {phone_error}\n\nПопробуйте оформить заказ заново.",
                                 parse_mode="Markdown")
            return

        if len(address) < 5:
            await message.answer("❌ *Ошибка:* Введите полный адрес доставки (минимум 5 символов).",
                                 parse_mode="Markdown")
            return

        formatted_phone = normalize_phone(phone)

        # ИСПРАВЛЕНО: заказ привязан к user_id текущего пользователя
        order_id, error = create_order(
            user_id=message.from_user.id,
            items=items,
            total=total,
            customer_name=name,
            customer_phone=formatted_phone,
            customer_address=address,
            comment=customer.get('comment', '')[:MAX_COMMENT_LENGTH]
        )

        if not order_id:
            await message.answer(
                f"❌ *Не удалось создать заказ:*\n\n{error}\n\n"
                f"Возможно, товар закончился на складе. Попробуйте обновить каталог.",
                parse_mode="Markdown"
            )
            return

        items_text = "\n".join([f"  • {i['name']} × {i['quantity']} = {i['price'] * i['quantity']:,.0f}₽"
                                for i in items])
        text = (
            f"✅ *Заказ #{order_id} оформлен!*\n\n"
            f"📦 *Товары:*\n{items_text}\n\n"
            f"💰 *Итого:* {total:,.0f} ₽\n\n"
            f"👤 {name}\n"
            f"📱 {formatted_phone}\n"
            f"📍 {address}\n\n"
            f"Для оплаты нажмите кнопку ниже 👇"
        )

        await message.answer(text, parse_mode="Markdown", reply_markup=payment_kb(order_id))

    except json.JSONDecodeError:
        logger.error(f"[ORDER] Ошибка JSON: {message.web_app_data.data[:200]}")
        await message.answer("⚠️ Ошибка обработки данных заказа.")
    except Exception as e:
        logger.error(f"[ORDER] Критическая ошибка: {e}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при оформлении заказа. Попробуйте позже.")


# ==========================================
# 7. ФЕЙКОВАЯ ОПЛАТА
# ==========================================

@dp.callback_query(F.data.startswith("pay_"))
async def process_payment_click(callback: types.CallbackQuery):
    try:
        if is_throttled(callback.from_user.id):
            await callback.answer("⏳ Подождите...", show_alert=False)
            return

        order_id = int(callback.data.split("_")[1])
        order = get_order(order_id)

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        if order[2] != 'Новый':
            await callback.answer("Заказ уже оплачен или обрабатывается!", show_alert=True)
            return

        if PAYMENT_TOKEN:
            # Настоящая тестовая оплата через Telegram API
            prices = [LabeledPrice(label=f"Заказ #{order_id}", amount=int(order[3] * 100))] # Цена в копейках
            await bot.send_invoice(
                chat_id=callback.message.chat.id,
                title=f"Оплата заказа #{order_id}",
                description="Оплата готовой мебели и доставки.",
                payload=f"invoice_{order_id}",
                provider_token=PAYMENT_TOKEN,
                currency="RUB",
                prices=prices,
                start_parameter="test-payment"
            )
            await callback.answer()
        else:
            # Фейковая оплата (заглушка)
            update_order_status(order_id, 'Оплачено')
            logger.info(f"[PAYMENT] ✅ ФЕЙК. Оплата заказа #{order_id} | Сумма: {order[3]:,.0f}₽")

            await callback.message.edit_text(
                f"✅ *Оплата прошла успешно!* (Фейк-режим)\n\n"
                f"🧾 Заказ #{order_id}\n"
                f"💰 Сумма: {order[3]:,.0f} ₽\n"
                f"💳 Способ: Тестовая оплата\n"
                f"📋 Статус: *Оплачено*\n\n"
                f"📦 Ваш заказ передан в обработку.",
                parse_mode="Markdown"
            )
            await notify_managers_payment(order_id, order)
            await callback.answer("✅ Оплата успешна!", show_alert=True)
            
    except Exception as e:
        logger.error(f"[PAYMENT] Ошибка генерации оплаты: {e}")
        await callback.answer("Ошибка обработки оплаты", show_alert=True)


@dp.pre_checkout_query()
async def pre_checkout_process(pre_checkout: PreCheckoutQuery):
    """Подтверждение готовности принять платеж"""
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    """Когда телеграм подтверждает оплату картой"""
    payload = message.successful_payment.invoice_payload
    order_id = int(payload.split("_")[1])
    order = get_order(order_id)
    
    update_order_status(order_id, 'Оплачено')
    logger.info(f"[PAYMENT] ✅ РЕАЛЬНАЯ ТЕСТОВАЯ оплата #{order_id}")

    await message.answer(
        f"✅ *Оплата прошла успешно!*\n\n"
        f"🧾 Заказ #{order_id}\n"
        f"💰 Сумма: {message.successful_payment.total_amount / 100:,.0f} ₽\n"
        f"💳 Способ: {message.successful_payment.provider_payment_charge_id}\n"
        f"📋 Статус: *Оплачено*\n\n"
        f"📦 Ваш заказ передан в обработку. Ожидайте уведомления!",
        parse_mode="Markdown"
    )
    await notify_managers_payment(order_id, order)


async def notify_managers_payment(order_id: int, order: tuple):
    managers = get_managers_ids()
    items = get_order_items(order_id)
    items_text = "\n".join([f"  • {i[3]} × {i[5]} = {i[4] * i[5]:,.0f}₽" for i in items])
    manager_text = (
        f"🔔 *НОВЫЙ ОПЛАЧЕННЫЙ ЗАКАЗ!*\n\n"
        f"🧾 Заказ #{order_id}\n"
        f"👤 {order[4]}\n"
        f"📱 {order[5]}\n"
        f"📍 {order[6]}\n\n"
        f"📦 Товары:\n{items_text}\n\n"
        f"💰 Сумма: *{order[3]:,.0f} ₽*\n\n"
        f"⚡ Необходимо сформировать накладную!"
    )
    for mid in managers:
        try:
            await bot.send_message(
                mid, manager_text, parse_mode="Markdown",
                reply_markup=order_actions_kb(order_id, 'Оплачено')
            )
        except Exception as e:
            logger.warning(f"[PAYMENT] Уведомление менеджеру {mid} не доставлено: {e}")


# ==========================================
# 8. ЗАКАЗЫ (Менеджер / Админ)
# ==========================================

@dp.message(F.text == "📋 Заказы")
async def orders_menu(message: types.Message):
    role = get_user_role(message.from_user.id)
    if role not in ('admin', 'manager'):
        return
    await message.answer("📋 *Управление заказами*\n\nВыберите фильтр:",
                         parse_mode="Markdown", reply_markup=orders_filter_kb())


@dp.callback_query(F.data.startswith("filter_"))
async def filter_orders(callback: types.CallbackQuery):
    """Фильтр заказов с ПАГИНАЦИЕЙ (по 10 на страницу)"""
    try:
        raw = callback.data.split("_", 1)[1]
        # Формат: filter_STATUS или filter_STATUS_PAGE
        parts = raw.rsplit("_pg", 1)
        status_filter = parts[0]
        page = int(parts[1]) if len(parts) > 1 else 1

        per_page = 10

        if status_filter == 'all':
            orders, total_count, total_pages = get_all_orders_paginated(page, per_page)
            title = "Все заказы"
        else:
            orders, total_count, total_pages = get_all_orders_paginated(page, per_page, status=status_filter)
            title = f"Заказы: {status_filter}"

        if not orders:
            try:
                await callback.message.edit_text(f"📋 *{title}*\n\nЗаказов не найдено.",
                                                 parse_mode="Markdown", reply_markup=orders_filter_kb())
            except Exception:
                pass
            await callback.answer()
            return

        buttons = []
        for o in orders:
            status_icon = {
                'Новый': '🆕', 'Оплачено': '💰', 'В обработке': '⚙️',
                'Готов к отгрузке': '📦', 'Отгружен': '🚛', 'Отменён': '❌'
            }.get(o[2], '❓')
            buttons.append([InlineKeyboardButton(
                text=f"{status_icon} #{o[0]} | {o[4] or 'Клиент'} | {o[3]:,.0f}₽",
                callback_data=f"vieworder_{o[0]}"
            )])

        # Кнопки пагинации
        pagination_row = []
        if page > 1:
            pagination_row.append(InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"filter_{status_filter}_pg{page - 1}"
            ))
        pagination_row.append(InlineKeyboardButton(
            text=f"📄 {page}/{total_pages}", callback_data="noop"
        ))
        if page < total_pages:
            pagination_row.append(InlineKeyboardButton(
                text="Вперёд ➡️", callback_data=f"filter_{status_filter}_pg{page + 1}"
            ))
        if len(pagination_row) > 1 or total_pages > 1:
            buttons.append(pagination_row)

        buttons.append([InlineKeyboardButton(text="🔙 Фильтры", callback_data="orders_list")])

        try:
            await callback.message.edit_text(
                f"📋 *{title}* ({total_count} шт., стр. {page}/{total_pages})",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        except Exception:
            await callback.message.answer(
                f"📋 *{title}* ({total_count} шт., стр. {page}/{total_pages})",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        await callback.answer()
    except Exception as e:
        logger.error(f"[ORDER] Ошибка фильтра: {e}")
        await callback.answer("Ошибка загрузки")


@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "orders_list")
async def orders_list(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(
            "📋 *Управление заказами*\n\nВыберите фильтр:",
            parse_mode="Markdown", reply_markup=orders_filter_kb()
        )
    except Exception:
        await callback.message.answer(
            "📋 *Управление заказами*\n\nВыберите фильтр:",
            parse_mode="Markdown", reply_markup=orders_filter_kb()
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("vieworder_"))
async def view_order(callback: types.CallbackQuery):
    try:
        order_id = int(callback.data.split("_")[1])
        order = get_order(order_id)
        if not order:
            await callback.answer("Заказ не найден")
            return

        items = get_order_items(order_id)
        items_text = "\n".join([f"  • {i[3]} × {i[5]} = {i[4] * i[5]:,.0f}₽" for i in items])

        status_icon = {
            'Новый': '🆕', 'Оплачено': '💰', 'В обработке': '⚙️',
            'Готов к отгрузке': '📦', 'Отгружен': '🚛', 'Отменён': '❌'
        }.get(order[2], '❓')

        text = (
            f"🧾 *Заказ #{order[0]}*\n\n"
            f"📋 Статус: {status_icon} *{order[2]}*\n"
            f"📅 Дата: {order[8]}\n"
            f"🔄 Обновлён: {order[9]}\n\n"
            f"👤 *Клиент:*\n"
            f"  ФИО: {order[4] or 'Не указано'}\n"
            f"  📱 {order[5] or 'Не указан'}\n"
            f"  📍 {order[6] or 'Не указан'}\n"
            f"  💬 {order[7] or '—'}\n\n"
            f"📦 *Товары:*\n{items_text}\n\n"
            f"💰 *Итого: {order[3]:,.0f} ₽*"
        )

        try:
            await callback.message.edit_text(
                text, parse_mode="Markdown",
                reply_markup=order_actions_kb(order_id, order[2])
            )
        except Exception:
            await callback.message.answer(
                text, parse_mode="Markdown",
                reply_markup=order_actions_kb(order_id, order[2])
            )
        await callback.answer()
    except Exception as e:
        logger.error(f"[ORDER] Ошибка просмотра заказа: {e}")
        await callback.answer("Ошибка загрузки")


@dp.callback_query(F.data.startswith("setstatus_"))
async def set_order_status(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_", 2)
        order_id = int(parts[1])
        new_status = parts[2]
        update_order_status(order_id, new_status)

        order = get_order(order_id)
        if order and order[1]:
            status_icon = {'Оплачено': '💰', 'В обработке': '⚙️',
                           'Готов к отгрузке': '📦', 'Отгружен': '🚛'}.get(new_status, '📋')
            # НАДЁЖНОЕ уведомление с retry
            delivered = await send_notification(
                order[1],
                f"{status_icon} *Обновление заказа #{order_id}*\n\n"
                f"Новый статус: *{new_status}*"
            )
            if not delivered:
                logger.warning(f"[ORDER] Уведомление клиенту {order[1]} о заказе #{order_id} НЕ доставлено!")

        await callback.answer(f"Статус → «{new_status}»", show_alert=True)
        await view_order(callback)
    except Exception as e:
        logger.error(f"[ORDER] Ошибка смены статуса: {e}")
        await callback.answer("Ошибка обновления")


# ==========================================
# 9. НАКЛАДНАЯ
# ==========================================

@dp.callback_query(F.data.startswith("invoice_"))
async def generate_invoice(callback: types.CallbackQuery):
    try:
        order_id = int(callback.data.split("_")[1])
        html = generate_invoice_html(order_id)

        if not html:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        doc = BufferedInputFile(
            html.encode('utf-8'),
            filename=f"Накладная_{order_id}.html"
        )
        await callback.message.answer_document(
            doc,
            caption=(
                f"📄 *Товарная накладная к заказу #{order_id}*\n\n"
                f"Откройте файл в браузере для просмотра и печати.\n"
                f"Документ содержит печать и подписи."
            ),
            parse_mode="Markdown"
        )
        logger.info(f"[DOCS] Накладная сформирована: заказ #{order_id}")
        await callback.answer("Накладная сформирована ✅")
    except Exception as e:
        logger.error(f"[DOCS] Ошибка генерации накладной: {e}")
        await callback.answer("Ошибка формирования документа", show_alert=True)


# ==========================================
# 10. МОИ ЗАКАЗЫ (Клиент) — ИСПРАВЛЕНО
# ==========================================

@dp.message(F.text == "📦 Мои заказы")
@dp.callback_query(F.data == "my_orders")
async def my_orders(event):
    """Показывает заказы текущего user_id с кнопкой отмены"""
    try:
        if isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            message = event.message
            await event.answer()
        else:
            user_id = event.from_user.id
            message = event

        orders = get_user_orders(user_id)
        if not orders:
            await message.answer("📦 У вас пока нет заказов.\n\nОткройте каталог и выберите товары!")
            return

        text = "📦 *Ваши заказы:*\n\n"
        cancel_buttons = []
        for o in orders:
            status_icon = {
                'Новый': '🆕', 'Оплачено': '💰', 'В обработке': '⚙️',
                'Готов к отгрузке': '📦', 'Отгружен': '🚛', 'Отменён': '❌'
            }.get(o[1], '❓')
            text += f"{status_icon} Заказ #{o[0]} — {o[2]:,.0f}₽ — *{o[1]}*\n   📅 {o[3]}\n\n"

            # Кнопка отмены для заказов, которые ещё можно отменить
            if o[1] not in ('Отгружен', 'Отменён'):
                cancel_buttons.append([InlineKeyboardButton(
                    text=f"❌ Отменить заказ #{o[0]}",
                    callback_data=f"cancelorder_{o[0]}"
                )])

        kb = InlineKeyboardMarkup(inline_keyboard=cancel_buttons) if cancel_buttons else None
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"[ORDER] Ошибка 'мои заказы': {e}")


# ==========================================
# 11. СТАТИСТИКА И РАССЫЛКА (АДМИН)
# ==========================================

@dp.message(F.text == "📊 Статистика / Финансы")
async def show_statistics(message: types.Message):
    if get_user_role(message.from_user.id) != 'admin':
        return
    try:
        stats = get_statistics()
        by_status = stats.get('by_status', {})
        status_text = "\n".join([f"  • {s}: {c}" for s, c in by_status.items()]) or "  Нет заказов"

        text = (
            f"📊 *Статистика системы*\n\n"
            f"💰 Выручка: *{stats['revenue']:,.0f} ₽*\n"
            f"📦 Всего заказов: *{stats['orders']}*\n"
            f"👥 Клиентов: *{stats['clients']}*\n"
            f"🏭 Товаров: *{stats['products']}*\n"
            f"📦 Единиц на складе: *{stats.get('total_stock', 0)}*\n\n"
            f"📋 *По статусам:*\n{status_text}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Экспорт в CSV (Excel)", callback_data="export_stats")],
            [InlineKeyboardButton(text="🎲 Сгенерировать демо-данные", callback_data="gen_fake")]
        ])
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"[STATS] Ошибка статистики: {e}")
        await message.answer("⚠️ Ошибка загрузки статистики.")


@dp.callback_query(F.data == "gen_fake")
async def gen_fake_data(callback: types.CallbackQuery):
    generate_fake_data()
    await callback.answer("Демо-данные сгенерированы! ✅", show_alert=True)
    await show_statistics(callback.message)


@dp.message(F.text == "📢 Общая рассылка")
async def broadcast_start(message: types.Message, state: FSMContext):
    if get_user_role(message.from_user.id) != 'admin':
        return
    await state.set_state(Broadcast.text)
    await message.answer("📢 Введите текст рассылки:", reply_markup=cancel_kb())


@dp.message(Broadcast.text)
async def broadcast_send(message: types.Message, state: FSMContext):
    try:
        if not message.text:
            await message.answer("❌ Отправьте текст рассылки, а не фото/стикер.")
            return

        broadcast_text = message.text.strip()[:MAX_BROADCAST_LENGTH]
        if len(broadcast_text) < 3:
            await message.answer("❌ Текст рассылки слишком короткий. Минимум 3 символа.")
            return

        ids = get_all_users_ids()
        sent = 0
        for uid in ids:
            try:
                await bot.send_message(uid, f"📢 *Рассылка от Мебельного Завода:*\n\n{safe_markdown(broadcast_text)}",
                                       parse_mode="Markdown")
                sent += 1
            except Exception:
                pass
        await state.clear()
        logger.info(f"[BROADCAST] Рассылка: {sent}/{len(ids)} доставлено")
        await message.answer(f"✅ Рассылка отправлена *{sent}* из {len(ids)} пользователей.",
                             reply_markup=get_main_kb('admin', user_id=message.from_user.id), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[BROADCAST] Ошибка рассылки: {e}")
        await state.clear()
        await message.answer("⚠️ Ошибка рассылки.", reply_markup=get_main_kb('admin', user_id=message.from_user.id))


# ==========================================
# 12. УДАЛЕНИЕ ФОТОГРАФИЙ ТОВАРА (НОВОЕ!)
# ==========================================

@dp.callback_query(F.data.startswith("managephotos_"))
async def manage_photos(callback: types.CallbackQuery):
    """Просмотр и удаление фотографий товара"""
    try:
        pid = int(callback.data.split("_")[1])
        product = get_product_by_id(pid)
        if not product:
            await callback.answer("Товар не найден")
            return

        photos = get_product_photos_with_ids(pid)
        if not photos:
            await callback.answer("У товара нет фотографий", show_alert=True)
            return

        buttons = []
        for photo in photos:
            db_id, file_id, position = photo
            buttons.append([InlineKeyboardButton(
                text=f"🗑 Удалить фото #{position + 1}",
                callback_data=f"delphoto_{db_id}_{pid}"
            )])
        buttons.append([InlineKeyboardButton(text="🔙 Назад к товару", callback_data=f"p_{pid}")])

        await callback.message.edit_text(
            f"📷 *Фотографии товара «{product[1]}»*\n\n"
            f"Всего фото: {len(photos)}\n"
            f"Выберите фото для удаления:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[PHOTO] Ошибка управления фото: {e}")
        await callback.answer("Ошибка загрузки")


@dp.callback_query(F.data.startswith("delphoto_"))
async def delete_photo_handler(callback: types.CallbackQuery):
    """Удаление конкретной фотографии"""
    try:
        parts = callback.data.split("_")
        photo_db_id = int(parts[1])
        pid = int(parts[2])

        success = delete_product_photo_by_id(photo_db_id)
        if success:
            await callback.answer("✅ Фото удалено!", show_alert=True)
            logger.info(f"[PHOTO] Удалено фото db_id={photo_db_id} товара #{pid}")
        else:
            await callback.answer("❌ Ошибка удаления", show_alert=True)

        # Обновляем список фото
        photos = get_product_photos_with_ids(pid)
        product = get_product_by_id(pid)
        if not photos:
            await callback.message.edit_text(
                f"📷 *Все фотографии товара «{product[1] if product else '?'}» удалены.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 К товару", callback_data=f"p_{pid}")]
                ])
            )
        else:
            buttons = []
            for photo in photos:
                db_id, file_id, position = photo
                buttons.append([InlineKeyboardButton(
                    text=f"🗑 Удалить фото #{position + 1}",
                    callback_data=f"delphoto_{db_id}_{pid}"
                )])
            buttons.append([InlineKeyboardButton(text="🔙 К товару", callback_data=f"p_{pid}")])
            await callback.message.edit_text(
                f"📷 *Фотографии ({len(photos)} шт.)*\nВыберите для удаления:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
    except Exception as e:
        logger.error(f"[PHOTO] Ошибка удаления фото: {e}")
        await callback.answer("Ошибка")


# ==========================================
# 13. ОТМЕНА ЗАКАЗА КЛИЕНТОМ (НОВОЕ!)
# ==========================================

@dp.callback_query(F.data.startswith("cancelorder_"))
async def cancel_order_handler(callback: types.CallbackQuery):
    """Клиент отменяет свой заказ — товары возвращаются на склад"""
    try:
        order_id = int(callback.data.split("_")[1])
        order = get_order(order_id)

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        # Проверяем, что заказ принадлежит этому пользователю
        if order[1] != callback.from_user.id:
            await callback.answer("Это не ваш заказ!", show_alert=True)
            return

        success, error = cancel_order(order_id)

        if success:
            await callback.message.edit_text(
                f"❌ *Заказ #{order_id} отменён*\n\n"
                f"💰 Сумма: {order[3]:,.0f} ₽\n"
                f"📦 Товары возвращены на склад.\n\n"
                f"Если была оплата — средства будут возвращены в течение 3-5 рабочих дней.",
                parse_mode="Markdown"
            )
            logger.info(f"[ORDER] Клиент {callback.from_user.id} отменил заказ #{order_id}")

            # Уведомляем менеджеров
            managers = get_managers_ids()
            for mid in managers:
                await send_notification(
                    mid,
                    f"⚠️ *Клиент отменил заказ #{order_id}*\n\n"
                    f"👤 {order[4] or 'Клиент'}\n"
                    f"💰 Сумма: {order[3]:,.0f} ₽\n"
                    f"📦 Товары возвращены на склад."
                )

            await callback.answer("Заказ отменён ✅", show_alert=True)
        else:
            await callback.answer(f"❌ {error}", show_alert=True)
    except Exception as e:
        logger.error(f"[ORDER] Ошибка отмены заказа: {e}")
        await callback.answer("Ошибка отмены", show_alert=True)


# ==========================================
# 14. ЭКСПОРТ СТАТИСТИКИ (НОВОЕ!)
# ==========================================

@dp.callback_query(F.data == "export_stats")
async def export_statistics(callback: types.CallbackQuery):
    """Экспорт статистики в CSV-файл"""
    try:
        csv_data = get_statistics_csv()
        doc = BufferedInputFile(
            csv_data.encode('utf-8-sig'),  # utf-8-sig для корректного открытия в Excel
            filename=f"Отчёт_МебельныйЗавод_{time.strftime('%Y%m%d_%H%M')}.csv"
        )
        await callback.message.answer_document(
            doc,
            caption=(
                "📊 *Экспорт статистики*\n\n"
                "Файл содержит:\n"
                "• Сводную информацию\n"
                "• Все заказы с деталями\n"
                "• Товары на складе\n\n"
                "Откройте в Excel (разделитель: точка с запятой)"
            ),
            parse_mode="Markdown"
        )
        logger.info(f"[EXPORT] Статистика экспортирована пользователем {callback.from_user.id}")
        await callback.answer("Отчёт сформирован ✅")
    except Exception as e:
        logger.error(f"[EXPORT] Ошибка экспорта: {e}")
        await callback.answer("Ошибка экспорта", show_alert=True)


# ==========================================
# ЗАПУСК БОТА
# ==========================================

async def main():
    try:
        create_db()
        seed_initial_data()

        if WEBAPP_URL:
            set_webapp_url(WEBAPP_URL)
            logger.info(f"Mini App URL: {WEBAPP_URL}")
        else:
            logger.warning("⚠️ WEBAPP_URL не задан! Mini App будет недоступен.")
            logger.warning("   Запустите localtunnel и укажите URL в bot.py")

        logger.info("🏭 FurnitureBot v2.1 запускается...")
        logger.info("   Валидация: ✅ | Складской учёт: ✅ | Фото-карусель: ✅ | Консультант: ✅")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка запуска: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
