"""Body measurements and progress photos for the phone UI. Photos arrive as base64 (no multipart dependency)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import body as bd

router = APIRouter(prefix="/api/body", tags=["body"])


class MeasureIn(BaseModel):
    day: date | None = None
    waist_cm: float | None = Field(default=None, gt=0)
    chest_cm: float | None = Field(default=None, gt=0)
    hips_cm: float | None = Field(default=None, gt=0)
    arm_cm: float | None = Field(default=None, gt=0)
    thigh_cm: float | None = Field(default=None, gt=0)


class PhotoIn(BaseModel):
    day: date | None = None
    pose: str = "front"
    image: str = Field(min_length=20, max_length=7_000_000)


def _wrap(fn, *a, **k):
    try:
        return fn(*a, **k)
    except bd.BodyError as e:
        raise HTTPException(422, str(e)) from None


@router.get("")
def overview(db: Session = Depends(get_db)):
    return bd.overview(db)


@router.post("/measures")
def add_measures(b: MeasureIn, db: Session = Depends(get_db)):
    return _wrap(bd.log_measures, db, b.day, **b.model_dump(exclude={"day"}))


@router.delete("/measures/{day}")
def del_measures(day: date, db: Session = Depends(get_db)):
    if not bd.delete_measures(db, day):
        raise HTTPException(404, "No measurements on that day.")
    return {"ok": True}


@router.post("/photos")
def add_photo(b: PhotoIn, db: Session = Depends(get_db)):
    return _wrap(bd.add_photo, db, b.image, b.pose, b.day)


@router.get("/photos/{photo_id}/image")
def photo_image(photo_id: int, db: Session = Depends(get_db)):
    path = bd.photo_path(db, photo_id)
    if not path:
        raise HTTPException(404, "Photo not found.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/photos/{photo_id}")
def del_photo(photo_id: int, db: Session = Depends(get_db)):
    if not bd.delete_photo(db, photo_id):
        raise HTTPException(404, "Photo not found.")
    return {"ok": True}
