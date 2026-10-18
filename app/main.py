import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .api import account, arc, body, daystats, mealprep, chat, data, day, myfoods, plan, recipes, routines, week, workouts
from .config import get_settings
from . import accounts
from .db import engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fitchat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    # Printed at every start so you can see which database file is in use.
    log.info("Database: %s", engine.url.render_as_string(hide_password=True))
    log.info("Model: %s | API key loaded: %s", s.gemini_model, bool(s.gemini_api_key))
    log.info("Sign-in mode: %s | time zone: %s", s.auth_mode, s.app_tz or "computer clock")
    accounts.ensure_initialised()  # tables, upgrades, shared exercise list (skipped when AUTO_MIGRATE=false)
    yield


app = FastAPI(title="FitChat", version="0.1.0", lifespan=lifespan)
# Personal/LAN app: open CORS so the phone UI can reach the laptop backend. Tighten before any public hosting.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(account.router)
app.include_router(chat.router)
app.include_router(data.router)
app.include_router(myfoods.router)
app.include_router(workouts.router)
app.include_router(week.router)
app.include_router(day.router)
app.include_router(recipes.router)
app.include_router(routines.router)
app.include_router(plan.router)
app.include_router(body.router)
app.include_router(daystats.router)
app.include_router(arc.router)
app.include_router(mealprep.router)

# The phone UI is plain HTML/CSS/JS in app/static, served by this same server (no build step needed).
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/static/{name:path}", include_in_schema=False)
def static_file(name: str):
    # A plain route instead of a mounted StaticFiles app: behaves the same locally and on Vercel.
    root = STATIC_DIR.resolve()
    target = (root / name).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(target)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the site root so it can cover the whole app; never cached so updates reach everyone.
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
