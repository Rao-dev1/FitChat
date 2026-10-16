import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import chat, data
from .config import get_settings
from .db import Base, SessionLocal, engine
from .seed.loader import seed_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fitchat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    # Printed at every start so you can see which database file is in use.
    log.info("Database: %s", engine.url.render_as_string(hide_password=True))
    log.info("Model: %s | API key loaded: %s", s.gemini_model, bool(s.gemini_api_key))
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_all(db)
    yield


app = FastAPI(title="FitChat", version="0.1.0", lifespan=lifespan)
# Personal/LAN app: open CORS so the phone UI can reach the laptop backend. Tighten before any public hosting.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(chat.router)
app.include_router(data.router)

# The phone UI is plain HTML/CSS/JS in app/static, served by this same server (no build step needed).
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
