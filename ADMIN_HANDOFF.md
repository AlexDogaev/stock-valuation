# Хендофф админу — деплой «Оценка акций MOEX» (бета)

Сервис: **FastAPI + SQLite**, в Docker. Доступ по ссылке ограниченному кругу
(**per-user Basic Auth + HTTPS**). Пошаговый рантбук — в **`DEPLOY.md`** (в этом же пакете).
Ниже — что владелец передаёт отдельно и чек-лист по серверу.

## От владельца получишь ОТДЕЛЬНО (в пакете/репо этого НЕТ, по защищённому каналу):
1. **`ANTHROPIC_API_KEY`** — ключ Opus для LLM-кнопок (впишешь в `.env`). Без него кнопки выключены, остальное работает.
2. **`APP_AUTH`** — бета-логины `user:pass,user2:pass2,...` (в `.env`).
3. **`data.sqlite3`** — заполненная БД (50 эмитентов, ~МБ). Кладётся в `./data/data.sqlite3`. **Секретов внутри нет.**

## Предпосылки на сервере:
- Linux + **Docker + docker compose** (`docker --version && docker compose version`; если нет — `curl -fsSL https://get.docker.com | sh`).
- **Публичный IP + открытые порты 80 и 443** (авто-HTTPS Caddy/Let's Encrypt).
  - Без своего домена: `PUBLIC_HOST=<IP-через-дефисы>.sslip.io` (напр. `203-0-113-5.sslip.io`).
  - Сервер **за NAT** (нет публичного IP) → вместо Caddy — Cloudflare Tunnel (секция в `DEPLOY.md`).

## Деплой (кратко; детали и команды — в `DEPLOY.md`):
1. Распаковать пакет (или `git clone` приватного репо, если дадут доступ).
2. `cp .env.example .env` → заполнить `PUBLIC_HOST`, `APP_AUTH`, `ANTHROPIC_API_KEY`.
3. `mkdir -p data` → положить полученный `data.sqlite3` в `./data/`.
4. `docker compose up -d --build`.
5. Проверка: `curl -I https://PUBLIC_HOST` → **401** (Basic Auth) = работает; в браузере логин из `APP_AUTH`.
6. Отдать владельцу рабочий `https://PUBLIC_HOST`.

## Безопасность / эксплуатация:
- Секреты — только в `.env` (в пакете и git их НЕТ; не коммить `.env`).
- Наружу торчит только Caddy (TLS); приложение — за ним. Доступ — Basic Auth (логины из `.env`).
- Сменить/отозвать доступ: правка `APP_AUTH` в `.env` → `docker compose up -d`.
- Обновление версии: новый пакет / `git pull` → `docker compose up -d --build`. Данные в томе `./data/` переживают перезапуск.
- T-Invest (`TINVEST_TOKEN`) из не-РФ может гео-блокироваться — не критично (данные уже в БД). Opus и MOEX работают отовсюду.
