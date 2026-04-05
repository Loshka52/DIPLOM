# Идеальный и быстрый Dockerfile для твоего проекта
FROM python:3.11-slim
WORKDIR /app

# Supervisor для запуска
RUN apt-get update && \
    apt-get install -y --no-install-recommends supervisor && \
    rm -rf /var/lib/apt/lists/*

# Установка зависимостей Python
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем бэкенд
COPY backend/ ./backend/

# Копируем УЖЕ СОБРАННЫЙ локально фронтенд
COPY webapp/dist/ ./webapp/dist/

# Конфиги для запуска
COPY deploy/supervisord.conf /etc/supervisor/conf.d/app.conf

# Создаём папку для данных
RUN mkdir -p /data/images

# Переменные окружения (пути по умолчанию для Docker/Amvera)
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/furniture_bot.db
ENV IMAGES_DIR=/data/images

EXPOSE 80

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/app.conf"]