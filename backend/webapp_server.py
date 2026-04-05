"""
webapp_server.py — Веб-сервер FastAPI для Mini App
Дипломный проект: Telegram-бот для мебельного завода
Версия: 3.0 (Идеальная отдача React и статики)
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

BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# Пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

IMAGES_DIR = os.getenv('IMAGES_DIR', os.path.join(BASE_DIR, 'static', 'images'))

# --- АВТООПРЕДЕЛЕНИЕ ПАПКИ dist/ ---
POSSIBLE_DIST_PATHS = [
    os.path.join(PROJECT_ROOT, 'webapp', 'dist'),     # Идеально для Docker: /app/webapp/dist/
    os.path.join(PROJECT_ROOT, 'dist'),
    os.path.join(BASE_DIR, '..', 'webapp', 'dist'),
    os.path.join(BASE_DIR, '..', 'dist'),
]

DIST_DIR = None
for path in POSSIBLE_DIST_PATHS:
    resolved = os.path.abspath(path)
    if os.path.exists(resolved) and os.path.isfile(os.path.join(resolved, 'index.html')):
        DIST_DIR = resolved
        break

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

@app.middleware("http")
async def add_bypass_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["bypass-tunnel-reminder"] = "true"
    return response

# ==========================================
# API РОУТЫ
# ==========================================

@app.get("/api/products")
async def api_products(category: str = None):
    try:
        products = get_all_products()
        if category:
            products = [p for p in products if p['category'] == category]

        for p in products:
            if p.get('image'):
                p['image_url'] = f"/images/{p['image']}"
            else:
                p['image_url'] = None

            photo_ids = p.get('photo_ids', [])
            photos = [f"/api/photo/{fid}" for fid in photo_ids]

            if not photos and p.get('image_url'):
                photos.append(p['image_url'])

            p['photos'] = photos
            p.pop('photo_ids', None)
            p.pop('image', None)

        return JSONResponse(content=products)
    except Exception as e:
        logger.error(f"Ошибка /api/products: {e}")
        return JSONResponse(content=[], status_code=200)

@app.get("/api/categories")
async def api_categories():
    try:
        return JSONResponse(content=get_categories())
    except Exception as e:
        logger.error(f"Ошибка /api/categories: {e}")
        return JSONResponse(content=[], status_code=200)

@app.get("/api/my-orders")
async def api_my_orders(user_id: int = 0):
    try:
        if not user_id:
            return JSONResponse(content=[])
        return JSONResponse(content=get_user_orders_api(user_id))
    except Exception as e:
        logger.error(f"Ошибка /api/my-orders: {e}")
        return JSONResponse(content=[], status_code=200)

@app.get("/api/photo/{file_id}")
async def proxy_telegram_photo(file_id: str):
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        return Response(content=b"Bot token not configured", status_code=500)
    if httpx is None:
        return Response(content=b"httpx not installed", status_code=500)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            file_info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
            file_resp = await client.get(file_info_url)
            file_data = file_resp.json()

            if not file_data.get("ok"):
                return Response(content=b"File not found in Telegram", status_code=404)

            file_path = file_data["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            photo_resp = await client.get(download_url)

            if photo_resp.status_code != 200:
                return Response(content=b"Failed to download photo", status_code=502)

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
        return Response(content=f"Error: {str(e)}".encode(), status_code=500)

@app.get("/api/health")
async def health_check():
    return JSONResponse(content={
        "status": "ok",
        "dist_path": DIST_DIR,
        "dist_exists": DIST_DIR is not None and os.path.exists(DIST_DIR),
        "bot_token_set": BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE',
    })

# ==========================================
# РАЗДАЧА ФРОНТЕНДА И СТАТИКИ (Mini App)
# ==========================================

os.makedirs(IMAGES_DIR, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

if DIST_DIR and os.path.exists(DIST_DIR):
    assets_dir = os.path.join(DIST_DIR, 'assets')
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(DIST_DIR, 'index.html'))

    # Хитрый catch-all роут для React
    @app.get("/{catchall:path}")
    async def serve_spa(catchall: str):
        # 1. Если запрашивают реальный файл (например favicon.ico) из папки dist
        file_path = os.path.join(DIST_DIR, catchall)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)

        # 2. Если стучатся в несуществующее API - отдаем стандартную JSON ошибку 404
        if catchall.startswith("api/"):
            return JSONResponse({"detail": "Not Found API"}, status_code=404)

        # 3. Во всех остальных случаях (навигация React) - отдаем index.html
        return FileResponse(os.path.join(DIST_DIR, 'index.html'))
else:
    @app.get("/")
    @app.get("/{catchall:path}")
    async def no_dist(catchall: str = ""):
        if catchall.startswith("api/"):
            return JSONResponse({"detail": "Not Found API"}, status_code=404)
        return HTMLResponse("<h1>⚠️ Ошибка: Папка dist/ не найдена на сервере!</h1>", status_code=404)


# ==========================================
# ЗАПУСК
# ==========================================
if __name__ == "__main__":
    print("=" * 55)
    print("  🏭 Мебельный Завод — Веб-сервер v3.0")
    print("=" * 55)
    try:
        create_db()
        seed_initial_data()
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")

    print(f"📦 Папка фронтенда: {DIST_DIR if DIST_DIR else '❌ НЕ НАЙДЕНА'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)