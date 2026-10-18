"""Who am I, site config for the sign-in screen, the admin pause switch, the user's own Gemini key, export and delete."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import accounts
from ..config import get_settings
from ..db import SessionLocal, get_db

router = APIRouter(prefix="/api", tags=["account"])


def _user(db: Session):
    return db.info["user"]


@router.get("/config")
def public_config():
    """Everything the sign-in screen needs before anyone is signed in. The anon key is public by design."""
    s = get_settings()
    paused = False
    try:
        with SessionLocal() as db:
            paused = accounts.is_paused(db)
    except Exception:
        pass  # database not reachable or not set up yet: never block the sign-in screen
    return {"auth": s.auth_mode, "supabase_url": s.supabase_url if s.auth_mode == "supabase" else "",
            "supabase_anon_key": s.supabase_anon_key if s.auth_mode == "supabase" else "",
            "paused": paused, "photos": s.auth_mode != "supabase"}


@router.get("/me")
def me(db: Session = Depends(get_db)):
    u = _user(db)
    return {"email": u.email, "admin": u.is_admin, "hosted": get_settings().auth_mode == "supabase",
            "chat": accounts.chat_allowance(db, u), "paused": accounts.is_paused(db, fresh=True) if u.is_admin else False}


class PauseIn(BaseModel):
    paused: bool


@router.post("/admin/pause")
def pause(body: PauseIn, db: Session = Depends(get_db)):
    if not _user(db).is_admin:
        raise HTTPException(403, "Only the site owner can do that.")
    accounts.set_paused(db, body.paused)
    return {"paused": body.paused}


class KeyIn(BaseModel):
    key: str = Field(min_length=20, max_length=200)


@router.put("/me/gemini-key")
def put_key(body: KeyIn, db: Session = Depends(get_db)):
    accounts.save_own_key(db, body.key)
    return {"ok": True}


@router.delete("/me/gemini-key", status_code=204)
def drop_key(db: Session = Depends(get_db)):
    accounts.clear_own_key(db)


@router.get("/export")
def export(db: Session = Depends(get_db)):
    return accounts.export_data(db)


class ImportIn(BaseModel):
    data: dict
    confirm: str


@router.post("/me/import")
def import_data(body: ImportIn, db: Session = Depends(get_db)):
    if body.confirm != "REPLACE":
        raise HTTPException(422, "Type REPLACE to confirm.")
    try:
        return accounts.import_data(db, body.data)
    except ValueError as e:
        raise HTTPException(422, str(e))


class DeleteIn(BaseModel):
    confirm: str


@router.post("/me/delete-data")
def delete_data(body: DeleteIn, db: Session = Depends(get_db)):
    if body.confirm != "DELETE":
        raise HTTPException(422, "Type DELETE to confirm.")
    return {"deleted_rows": accounts.delete_data(db)}
