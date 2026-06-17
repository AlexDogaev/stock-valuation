# Деплой на Linux (Docker) — бета с доступом по ссылке

Стек: **FastAPI + SQLite** в Docker, **Caddy** (авто-HTTPS), **per-user Basic Auth**.
Наружу торчит только Caddy (80/443). Доступ — логины из `.env` (`APP_AUTH`). Ссылку даёшь лично.

## Предпосылки
- Linux-сервер с **публичным IP** и открытыми портами **80 и 443**.
- **Docker + docker compose** (plugin). Проверка: `docker --version && docker compose version`.
  Если нет: `curl -fsSL https://get.docker.com | sh`.
- (Если сервер за NAT, без публичного IP/портов — см. «Вариант без публичного IP» внизу.)

## Шаги
```bash
# 1. Код
git clone https://github.com/AlexDogaev/stock-valuation.git
cd stock-valuation

# 2. Конфиг
cp .env.example .env
nano .env
#   PUBLIC_HOST  — свой домен (A-запись на сервер) ИЛИ без домена: <IP-через-дефисы>.sslip.io
#                  напр. IP 203.0.113.5 →  203-0-113-5.sslip.io
#   APP_AUTH     — бета-логины: beta1:пароль1,beta2:пароль2,...  (смени пароли!)
#   ANTHROPIC_API_KEY — ключ Opus (для LLM-кнопок); без него кнопки выключены, данные остаются

# 3. Данные: положить ЗАПОЛНЕННУЮ БД (50 эмитентов) в том ./data/
#    (с dev-машины, где сейчас всё посчитано; секретов внутри НЕТ)
mkdir -p data
#    с dev (Windows) — например:
#    scp "C:\Users\user\Desktop\stock-valuation\data.sqlite3" user@SERVER:~/stock-valuation/data/data.sqlite3

# 4. Запуск
docker compose up -d --build

# 5. Проверка
docker compose ps
docker compose logs -f app        # Ctrl+C выйти
curl -I https://$PUBLIC_HOST      # ждём 401 (Basic Auth) — значит работает
```
Открой `https://PUBLIC_HOST` в браузере → логин/пароль из `APP_AUTH` → приложение.
Раздай тестерам **URL + их логин** лично.

## Эксплуатация
- **Обновить код:** `git pull && docker compose up -d --build`.
- **Сменить/отозвать доступ:** правишь `APP_AUTH` в `.env` → `docker compose up -d` (пересоздаст app).
- **Данные:** живут в томе `./data/` (переживают перезапуски/redeploy). LLM-кнопки/обновления пишут туда же.
- **Логи:** `docker compose logs -f app` (приложение), `... caddy` (HTTPS/сертификаты).

## Важные нюансы
- **HTTPS без покупки домена:** `sslip.io` резолвит `<ip>.sslip.io` в этот IP, Let's Encrypt выдаёт на него сертификат. Нужны открытые 80/443.
- **T-Invest** (`TINVEST_TOKEN`) из не-РФ egress может гео-блокироваться — обновление фундаментала упадёт gracefully. Данные уже в БД, для беты не критично. Opus и MOEX работают отовсюду.
- **Секреты** — только в `.env` (в git нет). В БД секретов нет.
- **Опус-расходы:** LLM-кнопки доступны залогиненным; круг бета-логинов ограничен — лишнего жора не будет.

## Вариант без публичного IP (сервер за NAT)
Вместо проброса 80/443 — Cloudflare Tunnel (бесплатно, без домена):
```bash
docker compose up -d app                     # только приложение (Caddy не нужен)
# на сервере:
cloudflared tunnel --url http://localhost:8099   # выдаст https://<random>.trycloudflare.com
```
URL рандомный (меняется при перезапуске cloudflared) — для беты ок, ссылку перешлёшь.
Basic Auth всё так же из `.env`/`.auth` защищает.
