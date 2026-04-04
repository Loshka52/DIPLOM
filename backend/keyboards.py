"""
keyboards.py — Клавиатуры для Telegram-бота
Дипломный проект: Telegram-бот для мебельного завода
Версия: 2.1 (добавлен функционал консультанта)
"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)

# URL вашего Mini App (устанавливается при запуске через localtunnel)
WEBAPP_URL = ""


def set_webapp_url(url: str):
    """Установить URL WebApp (вызывается из bot.py)"""
    global WEBAPP_URL
    WEBAPP_URL = url


# ==========================================
# ГЛАВНЫЕ КЛАВИАТУРЫ ПО РОЛЯМ
# ==========================================

def get_main_kb(role: str) -> ReplyKeyboardMarkup:
    """Главная клавиатура в зависимости от роли"""
    if role == 'admin':
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="👥 Управление персоналом"), KeyboardButton(text="🏭 Склад (Каталог)")],
            [KeyboardButton(text="📋 Заказы"), KeyboardButton(text="📊 Статистика / Финансы")],
            [KeyboardButton(text="📢 Общая рассылка"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="👤 Мой профиль")]
        ], resize_keyboard=True)

    elif role == 'manager':
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📋 Заказы"), KeyboardButton(text="🏭 Склад")],
            [KeyboardButton(text="👤 Мой профиль")]
        ], resize_keyboard=True)

    elif role == 'consultant':
        # ИСПРАВЛЕНО: добавлены кнопки "Заказы (просмотр)" и "Помощь клиенту"
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="📋 Заказы (просмотр)"), KeyboardButton(text="🏭 Склад")],
            [KeyboardButton(text="💬 Помощь клиенту"), KeyboardButton(text="👤 Мой профиль")]
        ], resize_keyboard=True)

    elif role == 'client':
        kb_buttons = [
            [KeyboardButton(text="👤 Личный кабинет"), KeyboardButton(text="📦 Мои заказы")]
        ]
        if WEBAPP_URL:
            kb_buttons.insert(0, [
                KeyboardButton(text="🛍 Открыть каталог", web_app=WebAppInfo(url=WEBAPP_URL))
            ])
        else:
            kb_buttons.insert(0, [KeyboardButton(text="🛍 Каталог товаров")])
        return ReplyKeyboardMarkup(keyboard=kb_buttons, resize_keyboard=True)

    else:  # guest
        kb_buttons = [
            # НОВОЕ: Быстрая регистрация одной кнопкой (контакт из Telegram)
            [KeyboardButton(text="📱 Быстрая регистрация", request_contact=True)],
        ]
        if WEBAPP_URL:
            kb_buttons.insert(0, [
                KeyboardButton(text="🛍 Смотреть Каталог", web_app=WebAppInfo(url=WEBAPP_URL))
            ])
        else:
            kb_buttons.insert(0, [KeyboardButton(text="🛍 Смотреть Каталог (Гость)")])
        return ReplyKeyboardMarkup(keyboard=kb_buttons, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    """Клавиатура отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


# ==========================================
# ИНЛАЙН-КЛАВИАТУРЫ
# ==========================================

def staff_login_kb() -> InlineKeyboardMarkup:
    """Выбор роли при служебном входе"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Администратор", callback_data="login_admin")],
        [InlineKeyboardButton(text="👔 Менеджер", callback_data="login_manager")],
        [InlineKeyboardButton(text="🎧 Консультант", callback_data="login_consultant")]
    ])


def order_actions_kb(order_id: int, current_status: str) -> InlineKeyboardMarkup:
    """Кнопки управления заказом для менеджера"""
    buttons = []

    status_flow = {
        'Новый': 'Оплачено',
        'Оплачено': 'В обработке',
        'В обработке': 'Готов к отгрузке',
        'Готов к отгрузке': 'Отгружен',
    }

    next_status = status_flow.get(current_status)
    if next_status:
        buttons.append([InlineKeyboardButton(
            text=f"➡️ Перевести в «{next_status}»",
            callback_data=f"setstatus_{order_id}_{next_status}"
        )])

    buttons.append([InlineKeyboardButton(
        text="📄 Сформировать накладную",
        callback_data=f"invoice_{order_id}"
    )])
    buttons.append([InlineKeyboardButton(
        text="🔙 Назад к списку",
        callback_data="orders_list"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_kb(order_id: int) -> InlineKeyboardMarkup:
    """Кнопка фейковой оплаты для клиента"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить картой (ЮKassa)", callback_data=f"pay_{order_id}")],
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders")]
    ])


def profile_kb() -> InlineKeyboardMarkup:
    """Кнопки в профиле"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚪 Выйти из аккаунта", callback_data="logout")]
    ])


def orders_filter_kb() -> InlineKeyboardMarkup:
    """Фильтр заказов для менеджера"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Новые", callback_data="filter_Новый"),
         InlineKeyboardButton(text="💰 Оплаченные", callback_data="filter_Оплачено")],
        [InlineKeyboardButton(text="⚙️ В обработке", callback_data="filter_В обработке"),
         InlineKeyboardButton(text="📦 Готовы", callback_data="filter_Готов к отгрузке")],
        [InlineKeyboardButton(text="🚛 Отгружены", callback_data="filter_Отгружен")],
        [InlineKeyboardButton(text="📋 Все заказы", callback_data="filter_all")]
    ])
