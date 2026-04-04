# ==========================================
# Dockerfile — Мебельный Завод (Amvera Cloud)
# ==========================================

# --- Этап 1: сборка React фронтенда ---
FROM node:20-alpine AS frontend
WORKDIR /build
COPY webapp/package.json webapp/package-lock.json* ./
RUN npm install
COPY webapp/ ./
RUN npm run build

# --- Этап 2: финальный образ (только Python) ---
FROM python:3.11-slim
WORKDIR /app

# Supervisor для запуска двух процессов
RUN apt-get update && \
    apt-get install -y --no-install-recommends supervisor && \
    rm -rf /var/lib/apt/lists/*

# Python зависимости
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем бэкенд
COPY backend/ ./backend/

# Копируем собранный фронтенд из этапа 1
COPY --from=frontend /build/dist ./webapp/dist

# Конфиги для запуска
COPY deploy/supervisord.conf /etc/supervisor/conf.d/app.conf

# Создаём папку для постоянного хранилища (БД + фото)
RUN mkdir -p /data/images

# Чтобы логи print() были видны в Amvera
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/app.conf"]
