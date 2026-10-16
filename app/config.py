from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# Always anchor files to the backend folder, never to the directory the server was launched from.
BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    database_url: str = f"sqlite:///{(BASE_DIR / 'fitchat.db').as_posix()}"
    exercise_image_base_url: str = (
        "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
    )
    photos_dir: str = str(BASE_DIR / "photos")
    max_tool_rounds: int = 6
    history_messages: int = 12

    @field_validator("database_url")
    @classmethod
    def _anchor_sqlite_path(cls, v: str) -> str:
        """A relative sqlite path (e.g. sqlite:///./fitchat.db) would silently create a NEW empty
        database whenever the server is started from a different folder. Make it absolute."""
        url = make_url(v)
        if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
            path = Path(url.database)
            if not path.is_absolute():
                return url.set(database=(BASE_DIR / path).resolve().as_posix()).render_as_string(
                    hide_password=False
                )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
