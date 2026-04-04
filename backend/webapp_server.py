"""
webapp_server.py — Веб-сервер FastAPI для Mini App
Дипломный проект: Telegram-бот для мебельного завода
Версия: 2.2 (автоопределение dist/, исправлены пути)
"""
import os
import sys
import logging
import glob

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('WebApp')

try:
    import httpx
except ImportError:
    logger.warning("⚠️  httpx не установлен. Установите: pip install httpx")
    httpx = None

try:
    import uvicorn
    from fastapi import FastAPI, Request, Response
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    logger.error("❌ FastAPI/uvicorn не установлены. Установите: pip install fastapi uvicorn")
    sys.exit(1)

# Добавляем backend в sys.path чтобы импорт database работал
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from database import create_db, seed_initial_data, get_all_products, get_categories, get_user_orders_api
except ImportError as e:
    logger.error(f"❌ Ошибка импорта database.py: {e}")
    sys.exit(1)

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================

# ВАЖНО: Вставьте сюда тот же токен, что и в bot.py!
BOT_TOKEN = os.getenv('BOT_TOKEN', '8144160800:AAH6UuM2oDzeZ_0yrcKKQ-8PgvExStZ8q5g')

# Пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if os.getenv('AMVERA'):
    IMAGES_DIR = '/data/images'
else:
    IMAGES_DIR = os.path.join(BASE_DIR, 'static', 'images')

# Пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if os.getenv('AMVERA'):
    IMAGES_DIR = '/data/images'
else:
    IMAGES_DIR = os.path.join(BASE_DIR, 'static', 'images')

# --- АВТООПРЕДЕЛЕНИЕ ПАПКИ dist/ ---
# Ищем dist/ в нескольких возможных местах
POSSIBLE_DIST_PATHS = [
    os.path.join(PROJECT_ROOT, 'dist'),              # /project/dist/
    os.path.join(PROJECT_ROOT, 'webapp', 'dist'),     # /project/webapp/dist/
    os.path.join(BASE_DIR, '..', 'webapp', 'dist'),   # относительно backend/
    os.path.join(BASE_DIR, '..', 'dist'),             # относительно backend/
]

DIST_DIR = None
for path in POSSIBLE_DIST_PATHS:
    resolved = os.path.abspath(path)
    if os.path.exists(resolved) and os.path.isfile(os.path.join(resolved, 'index.html')):
        DIST_DIR = resolved
        break

if DIST_DIR is None:
    # Попробуем найти любой dist/ с index.html рекурсивно
    for root, dirs, files in os.walk(PROJECT_ROOT):
        if 'node_modules' in root:
            continue
        if 'index.html' in files and os.path.basename(root) == 'dist':
            DIST_DIR = root
            break

if DIST_DIR is None:
    DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')  # Fallback

# Порт сервера
PORT = int(os.getenv('PORT', '8080'))

app = FastAPI(title="Мебельный Завод API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# MIDDLEWARE: bypass-tunnel-reminder для localtunnel
# ==========================================

@app.middleware("http")
async def add_bypass_header(request: Request, call_next):
    """Добавляет заголовок для обхода страницы localtunnel"""
    response = await call_next(request)
    response.headers["bypass-tunnel-reminder"] = "true"
    return response


# ==========================================
# API: Товары
# ==========================================

@app.get("/api/products")
async def api_products(category: str = None):
    """Получить все товары (с фото и остатками)"""
    try:
        products = get_all_products()
        if category:
            products = [p for p in products if p['category'] == category]

        # Формируем URL для фото
        for p in products:
            # Статическое фото (загруженное на сервер)
            if p.get('image'):
                p['image_url'] = f"/images/{p['image']}"
            else:
                p['image_url'] = None

            # Массив фото из Telegram (проксируемых через /api/photo/)
            photo_ids = p.get('photo_ids', [])
            photos = []
            for fid in photo_ids:
                photos.append(f"/api/photo/{fid}")

            # Если нет фото из product_photos, но есть image — добавляем его
            if not photos and p.get('image_url'):
                photos.append(p['image_url'])

            p['photos'] = photos

            # Убираем внутренние поля
            p.pop('photo_ids', None)
            p.pop('image', None)

        return JSONResponse(content=products)
    except Exception as e:
        logger.error(f"Ошибка /api/products: {e}")
        return JSONResponse(content=[], status_code=200)


# ==========================================
# API: Категории
# ==========================================

@app.get("/api/categories")
async def api_categories():
    """Получить список категорий"""
    try:
        return JSONResponse(content=get_categories())
    except Exception as e:
        logger.error(f"Ошибка /api/categories: {e}")
        return JSONResponse(content=[], status_code=200)


# ==========================================
# API: Заказы пользователя
# ==========================================

@app.get("/api/my-orders")
async def api_my_orders(user_id: int = 0):
    """Получить заказы конкретного пользователя"""
    try:
        if not user_id:
            return JSONResponse(content=[])
        return JSONResponse(content=get_user_orders_api(user_id))
    except Exception as e:
        logger.error(f"Ошибка /api/my-orders: {e}")
        return JSONResponse(content=[], status_code=200)


# ==========================================
# API: Проксирование фото из Telegram
# ==========================================

@app.get("/api/photo/{file_id}")
async def proxy_telegram_photo(file_id: str):
    """
    Проксирует фото из Telegram API.
    Telegram хранит фото на своих серверах, и для их получения нужен BOT_TOKEN.
    """
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("BOT_TOKEN не установлен! Фото не будут загружаться.")
        return Response(content=b"Bot token not configured", status_code=500)

    if httpx is None:
        return Response(content=b"httpx not installed", status_code=500)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Получаем путь к файлу
            file_info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
            file_resp = await client.get(file_info_url)
            file_data = file_resp.json()

            if not file_data.get("ok"):
                logger.warning(f"Telegram API: файл не найден. file_id={file_id}")
                return Response(content=b"File not found in Telegram", status_code=404)

            file_path = file_data["result"]["file_path"]

            # 2. Скачиваем файл
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            photo_resp = await client.get(download_url)

            if photo_resp.status_code != 200:
                return Response(content=b"Failed to download photo", status_code=502)

            # 3. Определяем content-type
            content_type = "image/jpeg"
            if file_path.endswith(".png"):
                content_type = "image/png"
            elif file_path.endswith(".webp"):
                content_type = "image/webp"

            return Response(
                content=photo_resp.content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"}
            )

    except Exception as e:
        logger.error(f"Ошибка проксирования фото: {e}")
        return Response(content=f"Error: {str(e)}".encode(), status_code=500)


# ==========================================
# API: Проверка здоровья сервера
# ==========================================

@app.get("/api/health")
async def health_check():
    """Проверка что сервер работает"""
    return JSONResponse(content={
        "status": "ok",
        "dist_path": DIST_DIR,
        "dist_exists": os.path.exists(DIST_DIR),
        "index_exists": os.path.exists(os.path.join(DIST_DIR, 'index.html')) if DIST_DIR else False,
        "bot_token_set": BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE',
        "httpx_installed": httpx is not None,
    })


# ==========================================
# Раздача статических файлов
# ==========================================

# Картинки товаров (загруженные через бота)
os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

# Mini App (собранный React)
if DIST_DIR and os.path.exists(DIST_DIR):
    # Раздаём assets (CSS, JS)
    assets_dir = os.path.join(DIST_DIR, 'assets')
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    async def serve_index():
        """Главная страница Mini App"""
        index_path = os.path.join(DIST_DIR, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return HTMLResponse("<h1>index.html не найден в dist/</h1>", status_code=404)

    # Для любых других статических файлов в dist/ (favicon и т.д.)
    @app.get("/{file_path:path}")
    async def serve_static(file_path: str):
        """Раздача любых файлов из dist/"""
        full_path = os.path.join(DIST_DIR, file_path)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            return FileResponse(full_path)
        # Для SPA - возвращаем index.html для любых маршрутов
        index_path = os.path.join(DIST_DIR, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return HTMLResponse("Not found", status_code=404)
else:
    @app.get("/")
    async def no_dist():
        """Заглушка если dist/ не существует"""
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:50px'>"
            "<h1>⚠️ Папка dist/ не найдена!</h1>"
            "<p>Выполните команду в папке webapp:</p>"
            "<pre style='background:#f0f0f0;padding:15px;border-radius:8px'>cd webapp\nnpm run build</pre>"
            "<p>Затем перезапустите сервер.</p>"
            f"<p style='color:gray'>Искали в: {', '.join(POSSIBLE_DIST_PATHS)}</p>"
            "</body></html>",
            status_code=200
        )


# ==========================================
# ЗАПУСК
# ==========================================

if __name__ == "__main__":
    print("=" * 55)
    print("  🏭 Мебельный Завод — Веб-сервер v2.2")
    print("=" * 55)

    # Инициализация БД
    try:
        create_db()
        seed_initial_data()
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
        sys.exit(1)

    print(f"📁 Картинки:  {IMAGES_DIR}")
    print(f"📦 Mini App:  {DIST_DIR}")

    if DIST_DIR and os.path.exists(DIST_DIR):
        index_path = os.path.join(DIST_DIR, 'index.html')
        assets_dir = os.path.join(DIST_DIR, 'assets')
        print(f"   ✅ dist/ найден")
        print(f"   ✅ index.html: {'Есть' if os.path.exists(index_path) else '❌ НЕТ!'}")
        if os.path.exists(assets_dir):
            css_files = glob.glob(os.path.join(assets_dir, '*.css'))
            js_files = glob.glob(os.path.join(assets_dir, '*.js'))
            print(f"   ✅ assets/: {len(css_files)} CSS, {len(js_files)} JS")
        else:
            print(f"   ⚠️  assets/ не найден!")
    else:
        print("   ⚠️  dist/ НЕ НАЙДЕН!")
        print(f"   Искали в:")
        for p in POSSIBLE_DIST_PATHS:
            exists = "✅" if os.path.exists(os.path.abspath(p)) else "❌"
            print(f"     {exists} {os.path.abspath(p)}")
        print("   Выполните: cd webapp && npm run build")

    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("\n⚠️  BOT_TOKEN не задан! Фото из Telegram не будут работать.")
        print("   Вставьте токен в строку BOT_TOKEN в этом файле.")
    else:
        print(f"\n✅ BOT_TOKEN установлен (***{BOT_TOKEN[-6:]})")

    if httpx is None:
        print("⚠️  httpx не установлен! Выполните: pip install httpx")
    else:
        print("✅ httpx установлен")

    print(f"\n🌐 Сервер: http://localhost:{PORT}")
    print(f"   Откройте в браузере: http://localhost:{PORT}")
    print(f"   Проверка здоровья:   http://localhost:{PORT}/api/health")
    print("   (НЕ используйте 0.0.0.0 в браузере!)\n")

    uvicorn.run(app, host="0.0.0.0", port=PORT)
