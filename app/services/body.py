"""Tape measurements and progress photos. The scale hides fat loss while you build muscle, so these show the rest."""
import base64
import binascii
import secrets
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..tenancy import key_get

from ..config import get_settings
from ..models import BodyMeasure, ProgressPhoto
from .. import clock

FIELDS = {"waist_cm": "Waist", "chest_cm": "Chest", "hips_cm": "Hips", "arm_cm": "Arm", "thigh_cm": "Thigh"}
MIN_CM, MAX_CM = 10.0, 250.0
POSES = ("front", "side", "back")
MAX_PHOTOS = 300
MAX_PHOTO_BYTES = 4 * 1024 * 1024
PHOTOS_DIR = Path(get_settings().photos_dir)  # tests point this at a temp folder


class BodyError(ValueError):
    """Bad input; the message is shown to the user as is."""


def _past(day: date | None) -> date:
    day = day or clock.today()
    if day > clock.today():
        raise BodyError("Can't log for a future date.")
    return day


def log_measures(db: Session, day: date | None = None, **values) -> dict:
    day = _past(day)
    given = {k: v for k, v in values.items() if k in FIELDS and v is not None}
    if not given:
        raise BodyError("Give at least one measurement (waist, chest, hips, arm or thigh).")
    for k, v in given.items():
        if not (MIN_CM <= float(v) <= MAX_CM):
            raise BodyError(f"{FIELDS[k]} must be between {MIN_CM:g} and {MAX_CM:g} cm.")
    row = key_get(db, BodyMeasure, day=day) or BodyMeasure(day=day)
    for k, v in given.items():
        setattr(row, k, round(float(v), 1))
    db.add(row)
    db.commit()
    return {"day": day.isoformat(), **_measure_json(row),
            "summary": "Saved " + ", ".join(f"{FIELDS[k].lower()} {getattr(row, k):g} cm" for k in given) + f" for {day.isoformat()}."}


def delete_measures(db: Session, day: date) -> bool:
    row = key_get(db, BodyMeasure, day=day)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def _measure_json(r: BodyMeasure) -> dict:
    return {"day": r.day.isoformat(), **{k: getattr(r, k) for k in FIELDS}}


def _decode(image: str) -> tuple[bytes, str]:
    raw = image.split(",", 1)[1] if image.startswith("data:") and "," in image else image
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise BodyError("That image could not be read.") from None
    if len(data) > MAX_PHOTO_BYTES:
        raise BodyError("That photo is too large. Try a smaller one.")
    if data[:3] == b"\xff\xd8\xff":
        return data, "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data, "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, "webp"
    raise BodyError("Only JPEG, PNG or WebP photos are supported.")


def add_photo(db: Session, image: str, pose: str = "front", day: date | None = None) -> dict:
    day = _past(day)
    if pose not in POSES:
        raise BodyError("Pose must be front, side or back.")
    if db.query(ProgressPhoto).count() >= MAX_PHOTOS:
        raise BodyError(f"You have {MAX_PHOTOS} photos already. Delete some first.")
    data, ext = _decode(image)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}.{ext}"
    (PHOTOS_DIR / name).write_bytes(data)
    row = ProgressPhoto(day=day, pose=pose, filename=name)
    db.add(row)
    db.commit()
    return photo_json(row)


def photo_json(p: ProgressPhoto) -> dict:
    return {"id": p.id, "day": p.day.isoformat(), "pose": p.pose, "url": f"/api/body/photos/{p.id}/image"}


def photo_path(db: Session, photo_id: int) -> Path | None:
    p = db.get(ProgressPhoto, photo_id)
    if not p:
        return None
    path = PHOTOS_DIR / Path(p.filename).name  # name only: never trust a path from the database
    return path if path.is_file() else None


def delete_photo(db: Session, photo_id: int) -> bool:
    p = db.get(ProgressPhoto, photo_id)
    if not p:
        return False
    (PHOTOS_DIR / Path(p.filename).name).unlink(missing_ok=True)
    db.delete(p)
    db.commit()
    return True


def overview(db: Session) -> dict:
    rows = db.scalars(select(BodyMeasure).order_by(BodyMeasure.day)).all()
    photos = db.scalars(select(ProgressPhoto).order_by(ProgressPhoto.day.desc(), ProgressPhoto.id.desc())).all()
    changes = {}
    for k, label in FIELDS.items():
        pts = [(r.day, getattr(r, k)) for r in rows if getattr(r, k) is not None]
        if pts:
            first, last = pts[0], pts[-1]
            changes[k] = {"label": label, "first": first[1], "first_day": first[0].isoformat(), "latest": last[1],
                          "latest_day": last[0].isoformat(), "change_cm": round(last[1] - first[1], 1) if len(pts) > 1 else None}
    last_day = rows[-1].day if rows else None
    return {"measures": [_measure_json(r) for r in rows], "changes": changes, "photos": [photo_json(p) for p in photos],
            "days_since_measure": (clock.today() - last_day).days if last_day else None,
            "summary": _summary(changes)}


def _summary(changes: dict) -> str:
    if not changes:
        return "No measurements logged yet."
    parts = []
    for c in changes.values():
        if c["change_cm"] is None:
            parts.append(f"{c['label']} {c['latest']:g} cm")
        else:
            parts.append(f"{c['label']} {c['latest']:g} cm ({c['change_cm']:+g} since {c['first_day']})")
    return "; ".join(parts) + ". Waist down with weight steady or up is the best sign of fat loss while building muscle."
