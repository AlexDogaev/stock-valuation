"""FastAPI-приложение. Локальный single-user сервис оценки акций MOEX."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import DISCLAIMER
from app.data.db import init_db, get_db
from app.data.seed import seed_static
from app.web.api import router as api_router

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "web" / "templates"))

app = FastAPI(title="Оценка справедливой стоимости акций (MOEX)")


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    """Прод-доступ ограниченного круга: HTTP Basic, если есть .auth (иначе открыто)."""
    from fastapi.responses import Response
    from app.web import auth as _auth
    users = _auth.load_users()
    if users and not _auth.check_basic(request.headers.get("Authorization"), users):
        return Response(status_code=401, content="Authorization required",
                        headers={"WWW-Authenticate": 'Basic realm="MOEX Stocks (beta)"'})
    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(BASE / "web" / "static")), name="static")
app.include_router(api_router)


@app.on_event("startup")
def _startup():
    init_db()
    with get_db() as db:
        n = db.execute("SELECT COUNT(*) AS c FROM issuers").fetchone()["c"]
    if n == 0:
        seed_static()  # статический seed без сети; живые данные — POST /api/refresh
    from app.scheduler import start_scheduler
    start_scheduler()  # автономное обновление; выкл. через SCHEDULER_ENABLED=0


@app.on_event("shutdown")
def _shutdown():
    from app.scheduler import shutdown_scheduler
    shutdown_scheduler()


def _page(request: Request, name: str, **ctx):
    resp = templates.TemplateResponse(request, name, {"disclaimer": DISCLAIMER, **ctx})
    resp.headers["Cache-Control"] = "no-cache"  # HTML всегда ревалидируется → не залипает старая ссылка на CSS
    return resp


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return _page(request, "dashboard.html", title="Скринер")


@app.get("/issuer/{secid}", response_class=HTMLResponse)
def issuer_page(request: Request, secid: str):
    return _page(request, "issuer.html", title=secid.upper(), secid=secid.upper())


@app.get("/portfolio", response_class=HTMLResponse)
def portfolio_page(request: Request):
    return _page(request, "portfolio.html", title="Портфель")


@app.get("/bonds", response_class=HTMLResponse)
def bonds_page(request: Request):
    return _page(request, "bonds.html", title="Облигации")


@app.get("/build", response_class=HTMLResponse)
def build_page(request: Request):
    return _page(request, "build.html", title="Что купить")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return _page(request, "settings.html", title="Настройки")


@app.get("/calculators", response_class=HTMLResponse)
def calculators_page(request: Request):
    return _page(request, "calculators.html", title="Калькуляторы")


@app.get("/backtest", response_class=HTMLResponse)
def backtest_page(request: Request):
    return _page(request, "backtest.html", title="Backtest")
