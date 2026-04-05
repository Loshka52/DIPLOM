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

# Создаём папку для картинок
RUN mkdir -p /data/images
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/app.conf"]