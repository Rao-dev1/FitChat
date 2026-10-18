"""Water, fibre and stool tracking. Rule-based hints only: this is a habit aid, not medical advice."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import BowelLog, Food, WaterLog
from . import nutrition as nut
from .. import clock

MIN_ML, MAX_ML = 50.0, 2000.0
MAX_WATER_DAY_ML = 10000.0
BRISTOL = {
    1: "Separate hard lumps (constipated)", 2: "Lumpy, sausage-shaped (mild constipation)",
    3: "Sausage with cracks (normal)", 4: "Smooth, soft sausage (ideal)", 5: "Soft blobs, easy to pass (normal, low fibre side)",
    6: "Mushy, ragged edges (loose)", 7: "Watery, no solid pieces (diarrhoea)",
}


def _check_day(day: date | None) -> date:
    day = day or clock.today()
    if day > clock.today():
        raise ValueError("Can't log for a future date.")
    return day


def water_total(db: Session, day: date) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(WaterLog.ml), 0)).where(WaterLog.day == day)) or 0)


def add_water(db: Session, ml: float, day: date | None = None) -> dict:
    day = _check_day(day)
    ml = float(ml)
    if not MIN_ML <= ml <= MAX_ML:
        raise ValueError(f"Enter between {MIN_ML:g} and {MAX_ML:g} ml at a time.")
    if water_total(db, day) + ml > MAX_WATER_DAY_ML:
        raise ValueError("That would be more than 10 litres in a day. Check the amount.")
    db.add(WaterLog(day=day, ml=ml))
    db.commit()
    total, target = water_total(db, day), nut.get_profile(db).water_target_ml or 3000
    return {"logged": True, "ml": ml, "water_ml": total, "water_target_ml": target,
            "summary": f"Logged {ml:g} ml water. Today: {total:g} of {target:g} ml."}


def delete_water(db: Session, water_id: int) -> bool:
    row = db.get(WaterLog, water_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def add_bowel(db: Session, bristol: int, warning_signs: bool = False, note: str | None = None,
              day: date | None = None) -> dict:
    day = _check_day(day)
    if int(bristol) != bristol or not 1 <= int(bristol) <= 7:
        raise ValueError("Stool type must be 1 to 7 on the Bristol scale.")
    note = (note or "").strip()[:200] or None
    row = BowelLog(day=day, bristol=int(bristol), warning_signs=bool(warning_signs), note=note)
    db.add(row)
    db.commit()
    return {"logged": True, "id": row.id, "bristol": row.bristol, "meaning": BRISTOL[row.bristol],
            "summary": f"Logged stool type {row.bristol} ({BRISTOL[row.bristol]})."}


def delete_bowel(db: Session, bowel_id: int) -> bool:
    row = db.get(BowelLog, bowel_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def bowel_entries(db: Session, day: date) -> list[dict]:
    rows = db.scalars(select(BowelLog).where(BowelLog.day == day).order_by(BowelLog.logged_at)).all()
    return [{"id": r.id, "time": r.logged_at.strftime("%H:%M"), "bristol": r.bristol, "meaning": BRISTOL[r.bristol],
             "warning_signs": r.warning_signs, "note": r.note} for r in rows]


def water_entries(db: Session, day: date) -> list[dict]:
    rows = db.scalars(select(WaterLog).where(WaterLog.day == day).order_by(WaterLog.logged_at)).all()
    return [{"id": r.id, "time": r.logged_at.strftime("%H:%M"), "ml": r.ml} for r in rows]


def fibre_foods(db: Session, limit: int = 5) -> list[dict]:
    """Table foods that are good fibre sources per serving, for 'what should I eat' hints."""
    rows = db.scalars(select(Food).where(Food.fibre_g >= 3).order_by(Food.fibre_g.desc()).limit(limit)).all()
    return [{"food": f.name, "serving": f.serving, "fibre_g": f.fibre_g, "kcal": f.calories, "protein_g": f.protein_g}
            for f in rows]


def status(db: Session, day: date | None = None) -> dict:
    day = day or clock.today()
    p = nut.get_profile(db)
    water_target, fibre_target = p.water_target_ml or 3000, p.fibre_target_g or 30
    water = water_total(db, day)
    fibre = nut.daily_totals(db, day)["fibre_g"]
    bowel = bowel_entries(db, day)
    last = db.scalar(select(BowelLog).order_by(BowelLog.logged_at.desc()))
    since = (clock.today() - last.day).days if last else None
    recent = db.scalars(select(BowelLog).where(BowelLog.day > clock.today() - timedelta(days=7))
                        .order_by(BowelLog.logged_at.desc())).all()
    out = {"day": day.isoformat(), "water_ml": water, "water_target_ml": water_target,
           "water_remaining_ml": max(0.0, water_target - water), "fibre_g": fibre, "fibre_target_g": fibre_target,
           "fibre_remaining_g": round(max(0.0, fibre_target - fibre), 1), "bowel_today": bowel,
           "water_entries": water_entries(db, day), "days_since_bowel": since,
           "last_bowel": ({"day": last.day.isoformat(), "bristol": last.bristol} if last else None)}
    out["alert"], out["hints"] = _hints(recent, since, water, water_target, fibre, fibre_target, day == clock.today(),
                                        nut.daily_totals(db, day)["protein_g"], p.protein_target_g)
    out["fibre_foods"] = fibre_foods(db) if fibre < fibre_target else []
    out["summary"] = (f"Water {water:g} of {water_target:g} ml. Fibre {fibre:g} of {fibre_target:g} g. "
                      + (f"Last bowel movement: {'today' if since == 0 else f'{since} days ago'}. " if since is not None
                         else "No bowel movements logged yet. ")
                      + " ".join(out["hints"]))
    return out


def _hints(recent, since, water, water_target, fibre, fibre_target, is_today, protein, protein_target):
    alert, hints = "none", []
    if any(r.warning_signs for r in recent):
        alert = "see_doctor"
        hints.append("You marked warning signs (blood, black stool or severe pain). Please see a doctor rather than "
                     "adjusting food yourself.")
    types = [r.bristol for r in recent[:4]]
    hard = sum(t <= 2 for t in types) >= 2 or (since is not None and since >= 3)
    loose = sum(t >= 6 for t in types) >= 2
    if since is not None and since >= 3 and alert == "none":
        hints.append(f"No bowel movement logged for {since} days. Drink water through the day, add fibre-rich food "
                     "(dal, rajma, vegetables, fruit, oats) and take a walk after meals." +
                     (" Five or more days, or pain and bloating, is a reason to see a doctor or pharmacist." if since >= 5 else ""))
    elif hard:
        hints.append("Recent stools were hard. Raise water and fibre together, and add fibre gradually (about 5 g more "
                     "a day) so your gut can adjust. Fibre without enough water makes constipation worse.")
    if loose:
        hints.append("Recent stools were loose. Keep water up (add ORS or salted buttermilk if it continues), and go "
                     "easy on whey, very spicy or oily food and sudden big fibre jumps. If it lasts more than 2 days, or comes "
                     "with fever or blood, see a doctor.")
    if types and not hard and not loose and all(3 <= t <= 5 for t in types[:2]):
        hints.append("Your recent stools look normal. Keep the same water and fibre routine.")
    if is_today:
        if fibre_target and fibre < 0.5 * fibre_target:
            hints.append(f"Fibre is low today ({fibre:g} of {fibre_target:g} g). A bowl of dal or rajma, vegetables or a fruit helps.")
        if protein_target and protein >= 0.9 * protein_target and fibre < 0.6 * fibre_target:
            hints.append("High protein with low fibre is a common cause of constipation. Pair protein meals with vegetables or dal.")
        if water_target and water < 0.4 * water_target:
            hints.append(f"Water is behind ({water:g} of {water_target:g} ml). Sip regularly rather than all at once.")
    return alert, hints
