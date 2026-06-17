# Образ сервиса оценки акций MOEX (FastAPI + SQLite). Прод-деплой на Linux.
FROM python:3.12-slim

WORKDIR /app

# зависимости отдельным слоем (кэш)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# код приложения (данные/секреты НЕ копируем — том + env, см. .dockerignore)
COPY app ./app

# БД — на смонтированном томе; планировщик включён в проде
ENV DB_PATH=/data/data.sqlite3 \
    SCHEDULER_ENABLED=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8099
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
