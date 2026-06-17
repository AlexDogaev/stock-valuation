@echo off
REM DEV-запуск (с авто-перезагрузкой). Планировщик выключен,
REM чтобы --reload не плодил дублирующие задачи. Для прод см. run_prod.bat
cd /d "%~dp0"
set SCHEDULER_ENABLED=0
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099 --reload
