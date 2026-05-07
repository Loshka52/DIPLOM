"""
database.py — Модуль работы с базой данных SQLite
Дипломный проект: Telegram-бот для мебельного завода
Версия: 2.1 (с product_photos, складским учётом, валидацией и ТОРГ-12)
"""
import sqlite3
import random
import re
import os
import logging
from datetime import datetime, timedelta
DB_NAME = os.getenv('DB_PATH', 'furniture_bot.db')
logger = logging.getLogger('[DATABASE]')


# ==========================================
# ПОДКЛЮЧЕНИЕ К БД
# ==========================================

def get_conn():
    """Получить подключение к БД с обработкой ошибок"""
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        raise


from contextlib import contextmanager

@contextmanager
def safe_conn():
    """Контекстный менеджер для безопасной работы с БД.
    Автоматически закрывает соединение даже при ошибке.
    Использование:
        with safe_conn() as conn:
            conn.execute(...)
            conn.commit()
    """
    conn = None
    try:
        conn = get_conn()
        yield conn
    except sqlite3.Error as e:
        logger.error(f"[DB] Ошибка БД: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ==========================================
# ОГРАНИЧЕНИЯ ДЛИНЫ ПОЛЕЙ (защита от переполнения)
# ==========================================

DB_MAX_NAME = 200
DB_MAX_TEXT = 2000
DB_MAX_PHONE = 30
DB_MAX_ADDRESS = 500
DB_MAX_COMMENT = 500


def _truncate(value, max_len):
    """Обрезать строку до максимальной длины"""
    if isinstance(value, str) and len(value) > max_len:
        logger.warning(f"[DB] Строка обрезана: {len(value)} → {max_len} символов")
        return value[:max_len]
    return value


# ==========================================
# ВАЛИДАЦИЯ ДАННЫХ
# ==========================================

def validate_fio(fio: str) -> tuple:
    """
    Валидация ФИО: минимум 2 слова, только кириллица, дефис, пробел.
    Возвращает (is_valid, error_message)
    """
    if not fio or not fio.strip():
        return False, "ФИО не может быть пустым"

    fio = fio.strip()
    if not re.match(r'^[А-ЯЁа-яё\s\-]+$', fio):
        return False, "ФИО должно содержать только кириллицу"

    words = [w for w in fio.split() if len(w) >= 2]
    if len(words) < 2:
        return False, "Введите минимум Имя и Фамилию (2 слова)"

    if len(fio) > 100:
        return False, "ФИО слишком длинное (максимум 100 символов)"

    return True, ""


def validate_phone(phone: str) -> tuple:
    """
    Валидация телефона: формат РФ (+79xxxxxxxxx или 89xxxxxxxxx).
    Возвращает (is_valid, error_message)
    """
    if not phone or not phone.strip():
        return False, "Телефон не может быть пустым"

    cleaned = re.sub(r'[\s\-\(\)]', '', phone.strip())

    if re.match(r'^(\+7|8|7)\d{10}$', cleaned):
        return True, ""

    return False, "Неверный формат. Введите номер в формате: +79001234567 или 89001234567"


def normalize_phone(phone: str) -> str:
    """Нормализация телефона к формату +7(XXX)XXX-XX-XX"""
    cleaned = re.sub(r'[\s\-\(\)]', '', phone.strip())
    if cleaned.startswith('8') and len(cleaned) == 11:
        cleaned = '+7' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 11:
        cleaned = '+7' + cleaned[1:]
    elif not cleaned.startswith('+'):
        cleaned = '+' + cleaned

    if len(cleaned) == 12:
        return f"{cleaned[:2]}({cleaned[2:5]}){cleaned[5:8]}-{cleaned[8:10]}-{cleaned[10:12]}"
    return cleaned


# ==========================================
# СОЗДАНИЕ БАЗЫ ДАННЫХ
# ==========================================

def create_db():
    """Создание всех таблиц"""
    try:
        conn = get_conn()
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            role TEXT DEFAULT 'guest',
            photo_id TEXT,
            registered_at TEXT DEFAULT (datetime('now', 'localtime'))
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS staff_credentials (
            login TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'manager', 'consultant')),
            full_name TEXT NOT NULL,
            photo_id TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL CHECK(price > 0),
            category TEXT NOT NULL,
            image_path TEXT,
            image_url TEXT,
            stock_quantity INTEGER DEFAULT 10 CHECK(stock_quantity >= 0),
            unit TEXT DEFAULT 'шт.',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )''')

        # === НОВАЯ ТАБЛИЦА: несколько фото для одного товара ===
        c.execute('''CREATE TABLE IF NOT EXISTS product_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Новый' CHECK(status IN (
                'Новый', 'Оплачено', 'В обработке',
                'Готов к отгрузке', 'Отгружен', 'Отменён'
            )),
            total REAL NOT NULL CHECK(total > 0),
            customer_name TEXT,
            customer_phone TEXT,
            customer_address TEXT,
            comment TEXT,
            payment_method TEXT DEFAULT 'Банковская карта (ЮKassa)',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        )''')

        # === МИГРАЦИЯ: добавляем недостающие колонки в старую БД ===
        try:
            c.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
            logger.info("[MIGRATION] Добавлена колонка image_path в products")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

        try:
            c.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
            logger.info("[MIGRATION] Добавлена колонка image_url в products")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE products ADD COLUMN stock_quantity INTEGER DEFAULT 10")
            logger.info("[MIGRATION] Добавлена колонка stock_quantity в products")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE products ADD COLUMN unit TEXT DEFAULT 'шт.'")
            logger.info("[MIGRATION] Добавлена колонка unit в products")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE products ADD COLUMN created_at TEXT DEFAULT (datetime('now', 'localtime'))")
            logger.info("[MIGRATION] Добавлена колонка created_at в products")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE users ADD COLUMN registered_at TEXT DEFAULT (datetime('now', 'localtime'))")
            logger.info("[MIGRATION] Добавлена колонка registered_at в users")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()
        logger.info("Таблицы БД созданы/проверены (включая product_photos + миграция)")
    except sqlite3.Error as e:
        logger.error(f"Ошибка создания БД: {e}")
        raise


def seed_initial_data():
    """Заполнение начальными данными"""
    try:
        conn = get_conn()
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM staff_credentials")
        if c.fetchone()[0] > 0:
            conn.close()
            return

        staff = [
            ('admin', 'admin123', 'admin', 'Иванов Иван Иванович'),
            ('manager', 'manager123', 'manager', 'Петрова Анна Сергеевна'),
            ('consultant', 'consult123', 'consultant', 'Сидоров Пётр Алексеевич'),
        ]
        for login, pwd, role, name in staff:
            c.execute("INSERT OR IGNORE INTO staff_credentials (login, password, role, full_name) VALUES (?, ?, ?, ?)",
                      (login, pwd, role, name))

        categories = ['Диваны', 'Кровати', 'Шкафы', 'Столы', 'Стулья', 'Кухни']
        for cat in categories:
            c.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))

        products = [
            ('Диван «Комфорт»',
             'Мягкий трёхместный диван с велюровой обивкой. Механизм раскладывания: еврокнижка. Размер: 230×95×85 см.',
             45000, 'Диваны', 8),
            ('Кровать «Сон»', 'Двуспальная кровать 160×200 с подъёмным механизмом и бельевым ящиком.', 35000, 'Кровати', 12),
            ('Шкаф-купе «Гардероб»', 'Трёхдверный шкаф-купе с зеркалом. Ширина 240 см, глубина 60 см.', 54000, 'Шкафы', 6),
            ('Стол обеденный «Дуб»', 'Раскладной стол из массива дуба. Размер: 160-200×90 см.', 38000, 'Столы', 9),
            ('Стул «Элегант»', 'Обеденный стул с мягким сиденьем. Каркас — массив бука.', 8500, 'Стулья', 20),
            ('Кухня «Стандарт»', 'Кухонный гарнитур 2.4 м. Фасады МДФ, столешница 38 мм. Цвет: белый.', 95000, 'Кухни', 3),
        ]
        for name, desc, price, cat, stock in products:
            c.execute(
                "INSERT OR IGNORE INTO products (name, description, price, category, stock_quantity) VALUES (?, ?, ?, ?, ?)",
                (name, desc, price, cat, stock)
            )

        conn.commit()
        conn.close()
        logger.info("✅ БД заполнена начальными данными (3 сотрудника, 6 категорий, 6 товаров)")
    except sqlite3.Error as e:
        logger.error(f"Ошибка заполнения начальных данных: {e}")


# ==========================================
# ПОЛЬЗОВАТЕЛИ
# ==========================================

def register_user(user_id, username, full_name, phone):
    try:
        full_name = _truncate(full_name, DB_MAX_NAME)
        phone = _truncate(phone, DB_MAX_PHONE)
        username = _truncate(username, 100) if username else None
        with safe_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, phone, role) VALUES (?, ?, ?, ?, 'client')",
                (user_id, username, full_name, phone)
            )
            conn.commit()
        logger.info(f"[USER] Зарегистрирован: {full_name} (ID: {user_id})")
    except sqlite3.Error as e:
        logger.error(f"[USER] Ошибка регистрации {user_id}: {e}")


def get_user(user_id):
    try:
        with safe_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row
    except sqlite3.Error as e:
        logger.error(f"[USER] Ошибка получения пользователя {user_id}: {e}")
        return None


def get_user_role(user_id):
    try:
        with safe_conn() as conn:
            row = conn.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else 'guest'
    except sqlite3.Error as e:
        logger.error(f"[USER] Ошибка получения роли {user_id}: {e}")
        return 'guest'


def set_user_role_and_info(user_id, role, full_name, photo_id):
    try:
        full_name = _truncate(full_name, DB_MAX_NAME)
        with safe_conn() as conn:
            existing = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if existing:
                conn.execute("UPDATE users SET role=?, full_name=?, photo_id=? WHERE user_id=?",
                             (role, full_name, photo_id, user_id))
            else:
                conn.execute("INSERT INTO users (user_id, role, full_name, photo_id) VALUES (?, ?, ?, ?)",
                             (user_id, role, full_name, photo_id))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"[USER] Ошибка обновления роли {user_id}: {e}")


def get_all_users_ids():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error as e:
        logger.error(f"[USER] Ошибка получения списка ID: {e}")
        return []


def get_managers_ids():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT user_id FROM users WHERE role IN ('manager', 'admin')").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error as e:
        logger.error(f"[USER] Ошибка получения менеджеров: {e}")
        return []


# ==========================================
# СОТРУДНИКИ
# ==========================================

def create_staff_account(login, password, role, full_name, photo_id=None):
    try:
        login = _truncate(login, 50)
        full_name = _truncate(full_name, DB_MAX_NAME)
        with safe_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO staff_credentials (login, password, role, full_name, photo_id) VALUES (?, ?, ?, ?, ?)",
                (login, password, role, full_name, photo_id)
            )
            conn.commit()
        logger.info(f"[STAFF] Создан аккаунт: {full_name} ({role})")
    except sqlite3.Error as e:
        logger.error(f"[STAFF] Ошибка создания аккаунта: {e}")


def check_staff_login(login, password):
    try:
        with safe_conn() as conn:
            row = conn.execute(
                "SELECT role, full_name, photo_id FROM staff_credentials WHERE login=? AND password=?",
                (login, password)
            ).fetchone()
        if row:
            logger.info(f"[AUTH] Успешный вход: {row[1]} ({row[0]})")
        else:
            logger.warning(f"[AUTH] Неудачная попытка входа: логин={login}")
        return row
    except sqlite3.Error as e:
        logger.error(f"[AUTH] Ошибка проверки логина: {e}")
        return None


def get_all_staff_credentials():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT login, full_name, role FROM staff_credentials").fetchall()
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"[STAFF] Ошибка получения списка: {e}")
        return []


def get_staff_info(login):
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT login, full_name, role, photo_id FROM staff_credentials WHERE login=?", (login,)
        ).fetchone()
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"[STAFF] Ошибка получения информации: {e}")
        return None


def update_staff_credential(login, field, value):
    allowed_fields = {'full_name', 'role', 'password'}
    if field not in allowed_fields:
        logger.warning(f"[STAFF] Попытка обновить запрещённое поле: {field}")
        return
    try:
        conn = get_conn()
        conn.execute(f"UPDATE staff_credentials SET {field}=? WHERE login=?", (value, login))
        conn.commit()
        conn.close()
        logger.info(f"[STAFF] Обновлено {field} для {login}")
    except sqlite3.Error as e:
        logger.error(f"[STAFF] Ошибка обновления: {e}")


def delete_staff_credential(login):
    try:
        conn = get_conn()
        conn.execute("DELETE FROM staff_credentials WHERE login=?", (login,))
        conn.commit()
        conn.close()
        logger.info(f"[STAFF] Удалён: {login}")
    except sqlite3.Error as e:
        logger.error(f"[STAFF] Ошибка удаления: {e}")


# ==========================================
# КАТЕГОРИИ
# ==========================================

def add_category(name):
    try:
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        conn.commit()
        conn.close()
        logger.info(f"[CATALOG] Категория создана: {name}")
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка создания категории: {e}")


def get_categories():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка получения категорий: {e}")
        return []


# ==========================================
# ФОТО ТОВАРОВ (НЕСКОЛЬКО ФОТО)
# ==========================================

def add_product_photo(product_id, file_id):
    """Добавить фото к товару (file_id из Telegram)"""
    try:
        conn = get_conn()
        # Определяем позицию (следующая по порядку)
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM product_photos WHERE product_id=?",
            (product_id,)
        ).fetchone()
        position = row[0] if row else 0
        conn.execute(
            "INSERT INTO product_photos (product_id, file_id, position) VALUES (?, ?, ?)",
            (product_id, file_id, position)
        )
        conn.commit()
        conn.close()
        logger.info(f"[PHOTO] Добавлено фото для товара #{product_id}, позиция {position}")
    except sqlite3.Error as e:
        logger.error(f"[PHOTO] Ошибка добавления фото: {e}")


def get_product_photos(product_id):
    """Получить список file_id фото товара"""
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT file_id FROM product_photos WHERE product_id=? ORDER BY position",
            (product_id,)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error as e:
        logger.error(f"[PHOTO] Ошибка получения фото: {e}")
        return []


# ==========================================
# ТОВАРЫ (с складским учётом)
# ==========================================

def add_product(name, description, price, category, image_path, stock_quantity=10):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO products (name, description, price, category, image_path, stock_quantity) VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, price, category, image_path, stock_quantity)
        )
        conn.commit()
        conn.close()
        logger.info(f"[CATALOG] Товар добавлен: {name} ({price}₽, фото: {image_path})")
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка добавления товара: {e}")


def get_products_by_category(category):
    """Товары по категории (с защитой от старой схемы БД)"""
    try:
        conn = get_conn()
        # Узнаём реальные колонки таблицы
        cursor = conn.execute("PRAGMA table_info(products)")
        columns = [col[1] for col in cursor.fetchall()]

        # Выбираем правильное имя колонки для фото
        if 'image_path' in columns:
            photo_col = 'image_path'
        elif 'photo_id' in columns:
            photo_col = 'photo_id'
        else:
            photo_col = 'NULL'

        # Проверяем наличие stock_quantity
        stock_col = 'stock_quantity' if 'stock_quantity' in columns else '10'

        rows = conn.execute(
            f"SELECT id, name, price, description, category, {photo_col}, {stock_col} FROM products WHERE category=?",
            (category,)
        ).fetchall()
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка получения товаров: {e}")
        return []


def get_all_products():
    """Все товары для API (с остатком, картинкой и массивом photos)"""
    try:
        conn = get_conn()
        # Узнаём реальные колонки таблицы
        cursor = conn.execute("PRAGMA table_info(products)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'image_path' in columns:
            photo_col = 'image_path'
        elif 'photo_id' in columns:
            photo_col = 'photo_id'
        else:
            photo_col = 'NULL'

        stock_col = 'stock_quantity' if 'stock_quantity' in columns else '10'

        rows = conn.execute(
            f"SELECT id, name, description, price, category, {photo_col}, {stock_col} FROM products ORDER BY category, name"
        ).fetchall()

        emoji_map = {
            'Диваны': '🛋️', 'Кровати': '🛏️', 'Шкафы': '🗄️',
            'Столы': '🪵', 'Стулья': '💺', 'Кухни': '🍳',
        }

        result = []
        for r in rows:
            product_id = r[0]
            # Получаем все фото товара
            photos_rows = conn.execute(
                "SELECT file_id FROM product_photos WHERE product_id=? ORDER BY position",
                (product_id,)
            ).fetchall()
            photo_ids = [pr[0] for pr in photos_rows]

            result.append({
                'id': product_id,
                'name': r[1],
                'description': r[2],
                'price': r[3],
                'category': r[4],
                'emoji': emoji_map.get(r[4], '📦'),
                'image': r[5],
                'stock': r[6],
                'photo_ids': photo_ids,  # file_id из Telegram (для проксирования)
            })

        conn.close()
        return result
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка получения всех товаров: {e}")
        return []


def get_product_by_id(product_id):
    """Получить товар по ID (с защитой от старой схемы БД)"""
    try:
        conn = get_conn()
        # Узнаём реальные колонки таблицы
        cursor = conn.execute("PRAGMA table_info(products)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'image_path' in columns:
            photo_col = 'image_path'
        elif 'photo_id' in columns:
            photo_col = 'photo_id'
        else:
            photo_col = 'NULL'

        stock_col = 'stock_quantity' if 'stock_quantity' in columns else '10'

        row = conn.execute(
            f"SELECT id, name, description, price, category, {photo_col}, {stock_col} FROM products WHERE id=?",
            (product_id,)
        ).fetchone()
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка получения товара #{product_id}: {e}")
        return None


def update_product(product_id, field, value):
    """Обновить поле товара (название, описание, цена, остаток)"""
    allowed_fields = {'name', 'description', 'price', 'category', 'stock_quantity', 'image_path'}
    if field not in allowed_fields:
        logger.warning(f"[CATALOG] Попытка обновить запрещённое поле товара: {field}")
        return False
    try:
        conn = get_conn()
        conn.execute(f"UPDATE products SET {field}=? WHERE id=?", (value, product_id))
        conn.commit()
        conn.close()
        logger.info(f"[CATALOG] Обновлено {field} для товара #{product_id}: {value}")
        return True
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка обновления товара #{product_id}: {e}")
        return False


def delete_product(product_id):
    try:
        conn = get_conn()
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.execute("DELETE FROM product_photos WHERE product_id=?", (product_id,))
        conn.commit()
        conn.close()
        logger.info(f"[CATALOG] Товар удалён: #{product_id}")
    except sqlite3.Error as e:
        logger.error(f"[CATALOG] Ошибка удаления товара: {e}")


def check_stock(product_id, quantity=1):
    """Проверить наличие товара на складе"""
    try:
        conn = get_conn()
        row = conn.execute("SELECT stock_quantity FROM products WHERE id=?", (product_id,)).fetchone()
        conn.close()
        if not row:
            return False
        return row[0] >= quantity
    except sqlite3.Error as e:
        logger.error(f"[STOCK] Ошибка проверки остатка: {e}")
        return False


def reserve_stock(items):
    """
    Списание товаров со склада при оформлении заказа.
    items = [{'id': ..., 'quantity': ...}, ...]
    Возвращает (success, error_message)
    """
    try:
        with safe_conn() as conn:
            c = conn.cursor()

            for item in items:
                pid = item.get('id')
                qty = item.get('quantity', 1)
                if pid:
                    row = c.execute("SELECT name, stock_quantity FROM products WHERE id=?", (pid,)).fetchone()
                    if not row:
                        return False, f"Товар #{pid} не найден"
                    if row[1] < qty:
                        return False, f"Недостаточно товара «{row[0]}» на складе (остаток: {row[1]}, запрошено: {qty})"

            for item in items:
                pid = item.get('id')
                qty = item.get('quantity', 1)
                if pid:
                    c.execute(
                        "UPDATE products SET stock_quantity = stock_quantity - ? WHERE id=? AND stock_quantity >= ?",
                        (qty, pid, qty)
                    )
                    logger.info(f"[STOCK] Списание: товар #{pid}, кол-во: {qty}")

            conn.commit()
        return True, ""
    except sqlite3.Error as e:
        logger.error(f"[STOCK] Ошибка списания: {e}")
        return False, f"Ошибка базы данных: {e}"


# ==========================================
# ЗАКАЗЫ
# ==========================================

def create_order(user_id, items, total, customer_name, customer_phone, customer_address, comment=''):
    """Создать заказ с резервированием товаров."""
    try:
        # Валидация входных данных
        customer_name = _truncate(customer_name, DB_MAX_NAME)
        customer_phone = _truncate(customer_phone, DB_MAX_PHONE)
        customer_address = _truncate(customer_address, DB_MAX_ADDRESS)
        comment = _truncate(comment, DB_MAX_COMMENT)

        if not isinstance(total, (int, float)) or total <= 0:
            return None, "Некорректная сумма заказа"
        if not items or len(items) > 50:
            return None, "Некорректное количество товаров"

        success, error = reserve_stock(items)
        if not success:
            logger.warning(f"[ORDER] Отказ в создании заказа: {error}")
            return None, error

        with safe_conn() as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO orders (user_id, total, customer_name, customer_phone, customer_address, comment)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, total, customer_name, customer_phone, customer_address, comment)
            )
            order_id = c.lastrowid
            for item in items:
                item_name = _truncate(str(item.get('name', '')), DB_MAX_NAME)
                c.execute(
                    """INSERT INTO order_items (order_id, product_id, product_name, price, quantity)
                       VALUES (?, ?, ?, ?, ?)""",
                    (order_id, item.get('id'), item_name, item['price'], item['quantity'])
                )
            conn.commit()
        logger.info(f"[ORDER] ✅ Заказ #{order_id} создан | Клиент: {customer_name} | Сумма: {total:,.0f}₽")
        return order_id, ""
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка создания заказа: {e}")
        return None, f"Ошибка базы данных: {e}"
    except Exception as e:
        logger.error(f"[ORDER] Непредвиденная ошибка создания заказа: {e}")
        return None, "Внутренняя ошибка сервера"


def get_order(order_id):
    try:
        conn = get_conn()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.close()
        return row
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка получения заказа #{order_id}: {e}")
        return None


def get_order_items(order_id):
    try:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка получения позиций заказа #{order_id}: {e}")
        return []


def get_user_orders(user_id):
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, status, total, created_at FROM orders WHERE user_id=? ORDER BY id DESC", (user_id,)
        ).fetchall()
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка получения заказов пользователя: {e}")
        return []


def get_user_orders_api(user_id):
    """Возвращает заказы конкретного пользователя (JSON)"""
    try:
        conn = get_conn()
        orders = conn.execute("SELECT id, status, total, created_at FROM orders WHERE user_id=? ORDER BY id DESC",
                              (user_id,)).fetchall()
        result = []
        for o in orders:
            items = conn.execute("SELECT product_name, quantity, price FROM order_items WHERE order_id=?",
                                 (o[0],)).fetchall()
            items_list = [{'name': i[0], 'qty': i[1], 'price': i[2]} for i in items]
            result.append({
                'id': o[0], 'status': o[1], 'total': o[2], 'date': o[3], 'items': items_list
            })
        conn.close()
        return result
    except sqlite3.Error as e:
        logger.error(f"[API] Ошибка получения заказов: {e}")
        return []


def get_user_profile_api(user_id):
    """Возвращает профиль пользователя для MiniApp (JSON)"""
    try:
        conn = get_conn()
        user = conn.execute(
            "SELECT user_id, username, full_name, phone, role, registered_at FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        if not user:
            conn.close()
            return None

        # Статистика заказов
        orders_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        total_spent = conn.execute(
            "SELECT COALESCE(SUM(total), 0) FROM orders WHERE user_id=? AND status NOT IN ('Отменён')",
            (user_id,)
        ).fetchone()[0]
        by_status = dict(conn.execute(
            "SELECT status, COUNT(*) FROM orders WHERE user_id=? GROUP BY status", (user_id,)
        ).fetchall())

        # Последний заказ
        last_order = conn.execute(
            "SELECT id, status, total, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()

        conn.close()

        return {
            'user_id': user[0],
            'username': user[1],
            'full_name': user[2],
            'phone': user[3],
            'role': user[4],
            'registered_at': user[5],
            'stats': {
                'orders_count': orders_count,
                'total_spent': total_spent,
                'by_status': by_status,
            },
            'last_order': {
                'id': last_order[0],
                'status': last_order[1],
                'total': last_order[2],
                'date': last_order[3],
            } if last_order else None,
        }
    except sqlite3.Error as e:
        logger.error(f"[API] Ошибка получения профиля: {e}")
        return None


def get_all_orders(status=None):
    try:
        conn = get_conn()
        if status:
            rows = conn.execute(
                "SELECT id, user_id, status, total, customer_name, created_at FROM orders WHERE status=? ORDER BY id DESC",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, status, total, customer_name, created_at FROM orders ORDER BY id DESC"
            ).fetchall()
        conn.close()
        return rows
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка получения списка заказов: {e}")
        return []


def update_order_status(order_id, new_status):
    try:
        conn = get_conn()
        conn.execute(
            "UPDATE orders SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_status, order_id)
        )
        conn.commit()
        conn.close()
        logger.info(f"[ORDER] Статус заказа #{order_id} → «{new_status}»")
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка обновления статуса: {e}")


# ==========================================
# СТАТИСТИКА
# ==========================================

def get_statistics():
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE status NOT IN ('Новый', 'Отменён')")
        revenue = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders")
        total_orders = c.fetchone()[0]
        c.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
        by_status = dict(c.fetchall())
        c.execute("SELECT COUNT(*) FROM users WHERE role='client'")
        clients = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM products")
        products = c.fetchone()[0]
        c.execute("SELECT COALESCE(SUM(stock_quantity), 0) FROM products")
        total_stock = c.fetchone()[0]
        conn.close()
        return {
            'revenue': revenue, 'orders': total_orders, 'by_status': by_status,
            'clients': clients, 'products': products, 'total_stock': total_stock,
        }
    except sqlite3.Error as e:
        logger.error(f"[STATS] Ошибка получения статистики: {e}")
        return {'revenue': 0, 'orders': 0, 'by_status': {}, 'clients': 0, 'products': 0, 'total_stock': 0}


def generate_fake_data():
    try:
        conn = get_conn()
        c = conn.cursor()
        statuses = ['Оплачено', 'В обработке', 'Готов к отгрузке', 'Отгружен']
        names = ['Козлов Андрей', 'Морозова Елена', 'Новикова Ольга', 'Волков Дмитрий', 'Лебедев Кирилл']
        phones = ['+7(900)111-22-33', '+7(900)444-55-66', '+7(900)777-88-99']
        for i in range(5):
            total = random.randint(15000, 200000)
            status = random.choice(statuses)
            name = random.choice(names)
            phone = random.choice(phones)
            days_ago = random.randint(1, 30)
            date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')
            c.execute(
                """INSERT INTO orders (user_id, status, total, customer_name, customer_phone,
                   customer_address, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (0, status, total, name, phone, 'г. Москва, ул. Примерная, д. 1', date, date)
            )
            order_id = c.lastrowid
            c.execute("SELECT id, name, price FROM products ORDER BY RANDOM() LIMIT ?", (random.randint(1, 3),))
            prods = c.fetchall()
            for p in prods:
                qty = random.randint(1, 2)
                c.execute(
                    "INSERT INTO order_items (order_id, product_id, product_name, price, quantity) VALUES (?, ?, ?, ?, ?)",
                    (order_id, p[0], p[1], p[2], qty)
                )
        conn.commit()
        conn.close()
        logger.info("[STATS] Демо-данные сгенерированы")
    except sqlite3.Error as e:
        logger.error(f"[STATS] Ошибка генерации демо-данных: {e}")


# ==========================================
# ГЕНЕРАЦИЯ НАКЛАДНОЙ ТОРГ-12 (HTML)
# ==========================================

def generate_invoice_html(order_id):
    """Генерирует HTML-накладную в стиле ТОРГ-12 с печатью"""
    order = get_order(order_id)
    items = get_order_items(order_id)
    if not order:
        return None

    rows_html = ""
    total_qty = 0
    for i, item in enumerate(items, 1):
        subtotal = item[4] * item[5]
        total_qty += item[5]
        rows_html += f"""
        <tr>
            <td class="tc">{i}</td>
            <td>{item[3]}</td>
            <td class="tc">шт.</td>
            <td class="tc">{item[5]}</td>
            <td class="tr">{item[4]:,.2f}</td>
            <td class="tr">{subtotal:,.2f}</td>
        </tr>"""

    now = datetime.now().strftime('%d.%m.%Y')
    order_date = order[8][:10] if order[8] else now

    try:
        dt = datetime.strptime(order_date, '%Y-%m-%d')
        order_date_formatted = dt.strftime('%d.%m.%Y')
    except Exception:
        order_date_formatted = order_date

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Накладная №{order[0]} от {order_date_formatted}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Times New Roman', serif; padding: 30px; color: #222; font-size: 13px; background: #fff; }}
        .doc-header {{ text-align: center; margin-bottom: 25px; }}
        .doc-header h1 {{ font-size: 16px; margin-bottom: 3px; letter-spacing: 2px; }}
        .doc-header h2 {{ font-size: 14px; font-weight: normal; color: #555; }}
        .org-info {{ border: 1px solid #999; padding: 12px; margin-bottom: 15px; font-size: 12px; }}
        .org-info b {{ display: inline-block; width: 120px; }}
        .section {{ margin-bottom: 15px; }}
        .section-title {{ font-weight: bold; font-size: 13px; margin-bottom: 5px; border-bottom: 1px solid #ccc; padding-bottom: 3px; }}
        table.items {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        table.items th {{ background: #f0ebe3; border: 1px solid #999; padding: 6px 8px; font-size: 12px; text-align: center; }}
        table.items td {{ border: 1px solid #999; padding: 5px 8px; font-size: 12px; }}
        .tc {{ text-align: center; }}
        .tr {{ text-align: right; }}
        .total-row {{ font-weight: bold; font-size: 14px; text-align: right; margin: 10px 0; }}
        .total-row span {{ font-size: 16px; color: #8B4513; }}
        .signatures {{ display: flex; justify-content: space-between; margin-top: 35px; padding-top: 15px; border-top: 1px solid #ccc; }}
        .sig-block {{ width: 45%; }}
        .sig-line {{ border-bottom: 1px solid #333; margin: 25px 0 5px; }}
        .sig-label {{ font-size: 11px; color: #666; }}
        .stamp {{ position: relative; display: inline-block; margin: 20px auto; }}
        .stamp-circle {{ width: 140px; height: 140px; border: 3px solid #1a5c2e; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; transform: rotate(-15deg); opacity: 0.8; position: relative; }}
        .stamp-circle::before {{ content: ''; position: absolute; inset: 5px; border: 1.5px solid #1a5c2e; border-radius: 50%; }}
        .stamp-outer {{ font-size: 9px; font-weight: bold; color: #1a5c2e; text-transform: uppercase; letter-spacing: 1px; }}
        .stamp-inner {{ font-size: 16px; font-weight: bold; color: #c0392b; margin: 4px 0; }}
        .stamp-date {{ font-size: 10px; color: #1a5c2e; }}
        .footer {{ margin-top: 30px; padding-top: 10px; border-top: 1px dashed #ccc; font-size: 10px; color: #888; text-align: center; }}
        .status-badge {{ display: inline-block; padding: 3px 12px; border-radius: 10px; font-size: 11px; font-weight: bold; color: #fff; background: #27ae60; }}
        @media print {{ body {{ padding: 15px; }} .footer {{ page-break-inside: avoid; }} }}
    </style>
</head>
<body>
    <div class="doc-header">
        <h1>ТОВАРНАЯ НАКЛАДНАЯ № {order[0]}</h1>
        <h2>от {order_date_formatted} г.</h2>
    </div>
    <div class="org-info">
        <p><b>Поставщик:</b> ООО «Мебельный Завод» | ИНН 7712345678 | КПП 771201001</p>
        <p><b>Адрес:</b> 115432, г. Москва, ул. Производственная, д. 15, стр. 2</p>
        <p><b>Р/с:</b> 40702810900000012345 | БИК: 044525225 | ПАО Сбербанк</p>
    </div>
    <div class="section">
        <div class="section-title">ПОКУПАТЕЛЬ</div>
        <p><b>ФИО:</b> {order[4] or 'Не указано'}</p>
        <p><b>Телефон:</b> {order[5] or 'Не указан'}</p>
        <p><b>Адрес доставки:</b> {order[6] or 'Не указан'}</p>
        <p><b>Комментарий:</b> {order[7] or '—'}</p>
        <p><b>Статус:</b> <span class="status-badge">{order[2]}</span></p>
    </div>
    <table class="items">
        <thead>
            <tr>
                <th style="width:35px;">№</th>
                <th>Наименование товара</th>
                <th style="width:45px;">Ед.</th>
                <th style="width:50px;">Кол-во</th>
                <th style="width:90px;">Цена, ₽</th>
                <th style="width:100px;">Сумма, ₽</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    <div class="total-row">
        Всего наименований: {len(items)}, на общую сумму: <span>{order[3]:,.2f} ₽</span>
    </div>
    <div class="total-row" style="font-size:12px; color:#555;">
        Общее количество единиц: {total_qty} шт.
    </div>
    <div style="text-align:center; margin: 25px 0;">
        <div class="stamp">
            <div class="stamp-circle">
                <span class="stamp-outer">ООО «Мебельный Завод»</span>
                <span class="stamp-inner">ОПЛАЧЕНО</span>
                <span class="stamp-date">{order_date_formatted}</span>
                <span class="stamp-outer">г. Москва</span>
            </div>
        </div>
    </div>
    <div class="signatures">
        <div class="sig-block">
            <p><b>Отпуск разрешил:</b></p>
            <div class="sig-line"></div>
            <p class="sig-label">Директор / Иванов И.И. / подпись</p>
        </div>
        <div class="sig-block">
            <p><b>Груз получил:</b></p>
            <div class="sig-line"></div>
            <p class="sig-label">{order[4] or '____________________'} / подпись</p>
        </div>
    </div>
    <div class="footer">
        <p>Документ сформирован автоматически информационной системой «FurnitureBot» {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
        <p>ООО «Мебельный Завод» | ОГРН 1027700132195 | Лицензия № 77-01-001234</p>
    </div>
</body>
</html>"""
    return html


# ==========================================
# УДАЛЕНИЕ ФОТО ТОВАРА
# ==========================================

def get_product_photos_with_ids(product_id):
    """Получить фото с их ID в БД (для удаления конкретного фото)"""
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, file_id, position FROM product_photos WHERE product_id=? ORDER BY position",
            (product_id,)
        ).fetchall()
        conn.close()
        return rows  # [(db_id, file_id, position), ...]
    except sqlite3.Error as e:
        logger.error(f"[PHOTO] Ошибка получения фото с ID: {e}")
        return []


def delete_product_photo_by_id(photo_db_id):
    """Удалить конкретное фото по ID записи в БД"""
    try:
        conn = get_conn()
        conn.execute("DELETE FROM product_photos WHERE id=?", (photo_db_id,))
        conn.commit()
        conn.close()
        logger.info(f"[PHOTO] Фото удалено: db_id={photo_db_id}")
        return True
    except sqlite3.Error as e:
        logger.error(f"[PHOTO] Ошибка удаления фото: {e}")
        return False


# ==========================================
# ОТМЕНА ЗАКАЗА (с возвратом на склад)
# ==========================================

def cancel_order(order_id):
    """Отменить заказ и вернуть товары на склад. Возвращает (success, error_message)"""
    try:
        with safe_conn() as conn:
            c = conn.cursor()

            order = c.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order:
                return False, "Заказ не найден"

            if order[0] in ('Отгружен', 'Отменён'):
                return False, f"Нельзя отменить заказ в статусе «{order[0]}»"

            # Возвращаем товары на склад
            items = c.execute("SELECT product_id, quantity FROM order_items WHERE order_id=?", (order_id,)).fetchall()
            for item in items:
                if item[0]:
                    c.execute("UPDATE products SET stock_quantity = stock_quantity + ? WHERE id=?", (item[1], item[0]))
                    logger.info(f"[STOCK] Возврат на склад: товар #{item[0]}, кол-во: +{item[1]}")

            c.execute("UPDATE orders SET status='Отменён', updated_at=datetime('now','localtime') WHERE id=?", (order_id,))
            conn.commit()
        logger.info(f"[ORDER] ❌ Заказ #{order_id} отменён, товары возвращены на склад")
        return True, ""
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка отмены заказа: {e}")
        return False, str(e)


# ==========================================
# ПАГИНАЦИЯ ЗАКАЗОВ
# ==========================================

def get_all_orders_paginated(page=1, per_page=10, status=None):
    """Заказы с пагинацией. Возвращает (orders, total_count, total_pages)"""
    try:
        conn = get_conn()
        offset = (page - 1) * per_page

        if status:
            count = conn.execute("SELECT COUNT(*) FROM orders WHERE status=?", (status,)).fetchone()[0]
            rows = conn.execute(
                "SELECT id, user_id, status, total, customer_name, created_at FROM orders WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, per_page, offset)
            ).fetchall()
        else:
            count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            rows = conn.execute(
                "SELECT id, user_id, status, total, customer_name, created_at FROM orders ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, offset)
            ).fetchall()

        conn.close()
        total_pages = max(1, (count + per_page - 1) // per_page)
        return rows, count, total_pages
    except sqlite3.Error as e:
        logger.error(f"[ORDER] Ошибка пагинации: {e}")
        return [], 0, 1


# ==========================================
# ЭКСПОРТ СТАТИСТИКИ (CSV)
# ==========================================

def get_statistics_csv():
    """Генерация CSV-отчёта для экспорта"""
    try:
        conn = get_conn()
        c = conn.cursor()

        orders = c.execute("""
            SELECT id, status, total, customer_name, customer_phone, customer_address, created_at
            FROM orders ORDER BY id DESC
        """).fetchall()

        products = c.execute("""
            SELECT id, name, category, price, stock_quantity FROM products ORDER BY category, name
        """).fetchall()

        stats = get_statistics()
        conn.close()

        lines = []
        lines.append("ОТЧЁТ МЕБЕЛЬНОГО ЗАВОДА")
        lines.append(f"Дата формирования;{datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append(f"Выручка;{stats['revenue']:,.0f} руб.")
        lines.append(f"Всего заказов;{stats['orders']}")
        lines.append(f"Клиентов;{stats['clients']}")
        lines.append(f"Товаров;{stats['products']}")
        lines.append(f"Единиц на складе;{stats.get('total_stock', 0)}")
        lines.append("")
        lines.append("=== ЗАКАЗЫ ===")
        lines.append("ID;Статус;Сумма;Клиент;Телефон;Адрес;Дата")
        for o in orders:
            lines.append(f"{o[0]};{o[1]};{o[2]};{o[3] or '-'};{o[4] or '-'};{o[5] or '-'};{o[6]}")

        lines.append("")
        lines.append("=== ТОВАРЫ НА СКЛАДЕ ===")
        lines.append("ID;Название;Категория;Цена;Остаток")
        for p in products:
            lines.append(f"{p[0]};{p[1]};{p[2]};{p[3]};{p[4]}")

        return "\n".join(lines)
    except sqlite3.Error as e:
        logger.error(f"[EXPORT] Ошибка экспорта: {e}")
        return "Ошибка экспорта данных"
