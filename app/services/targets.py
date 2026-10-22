"""BMI, daily calorie need and protein target from a person's body details, plus the extra calories that a
workout or a day of walking earns. Estimates only: they get you started, and you adjust from how you actually change."""
from __future__ import annotations

MIN_AGE_FOR_TARGETS = 18  # the formulas are for adults; under 18 we show BMI-free guidance only

SEXES = ("male", "female", "other")
ACTIVITY = {  # everyday life BEFORE workouts and logged steps (those are added on the day)
    "sedentary": (1.2, "Mostly sitting (classes, desk, studying)"),
    "light": (1.35, "On my feet part of the day"),
    "moderate": (1.5, "On my feet most of the day"),
}
GOAL_ADJUST = {"fat_loss": -0.18, "maintain": 0.0, "muscle_gain": 0.10}
PROTEIN_PER_KG = {"fat_loss": 2.0, "maintain": 1.5, "muscle_gain": 1.8}
FLOOR_KCAL = {"male": 1600, "female": 1300, "other": 1450}

LIMITS = {"weight_kg": (25.0, 300.0), "height_cm": (100.0, 250.0), "age": (10, 100)}

# Extra calories earned on the day (eat-back kept modest on purpose: estimates run high).
TRAIN_FLOOR = 150          # any counted workout is worth at least this
TRAIN_PER_SET = 15
TRAIN_CAP = 350
STEPS_BASELINE = 4000      # everyday walking is already inside the activity level above
STEPS_KCAL_PER_STEP = 0.035
STEPS_CAP = 300


def _weight_factor(weight_kg: float | None) -> float:
    if not weight_kg:
        return 1.0
    return max(0.8, min(1.4, weight_kg / 70.0))


def _round10(x: float) -> int:
    return int(round(x / 10.0) * 10)


def training_bonus(sets: int, weight_kg: float | None, min_sets: int = 6) -> int:
    """Extra kcal for a day with `sets` logged working sets (0 below the minimum)."""
    if sets < min_sets:
        return 0
    base = min(TRAIN_CAP, max(TRAIN_FLOOR, TRAIN_PER_SET * sets))
    return _round10(base * _weight_factor(weight_kg))


def steps_bonus(steps: int | None, weight_kg: float | None) -> int:
    """Extra kcal for walking beyond the everyday baseline (0 when steps were not logged)."""
    if not steps or steps <= STEPS_BASELINE:
        return 0
    return _round10(min(STEPS_CAP, (steps - STEPS_BASELINE) * STEPS_KCAL_PER_STEP * _weight_factor(weight_kg)))


def bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Healthy range"
    if bmi < 30:
        return "Overweight"
    return "Obese range"


def validate(field: str, value):
    lo, hi = LIMITS[field]
    if not (lo <= float(value) <= hi):
        raise ValueError(f"{field.replace('_', ' ')} must be between {lo:g} and {hi:g}")
    return value


def suggest(*, weight_kg, height_cm, age, sex, activity, goal) -> dict:
    """Everything the Account screen shows. Never raises: missing details are listed instead."""
    missing = [name for name, v in (("weight", weight_kg), ("height", height_cm), ("age", age), ("sex", sex))
               if not v]
    out: dict = {"ready": False, "missing": missing, "notes": []}
    if weight_kg and height_cm:
        bmi = weight_kg / ((height_cm / 100.0) ** 2)
        out["bmi"] = round(bmi, 1)
        if age and age >= MIN_AGE_FOR_TARGETS:
            out["bmi_category"] = bmi_category(bmi)
            out["notes"].append("BMI ignores muscle, so a lifter can read high while being lean. Use it as a rough guide.")
    if missing:
        return out
    if age < MIN_AGE_FOR_TARGETS:
        out["notes"].append("Calorie and protein suggestions are only for adults. Ask a doctor or dietitian for yours.")
        return out
    sex = sex if sex in SEXES else "other"
    offset = {"male": 5, "female": -161, "other": -78}[sex]  # Mifflin-St Jeor
    bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + offset
    factor = ACTIVITY.get(activity or "light", ACTIVITY["light"])[0]
    maintenance = bmr * factor
    adj = GOAL_ADJUST.get(goal or "maintain", 0.0)
    calories = maintenance * (1 + adj)
    floor = FLOOR_KCAL[sex]
    if calories < floor:
        calories = floor
        out["notes"].append(f"Raised to {floor} kcal, the lowest this tool will suggest. Go lower only with a doctor.")
    protein = PROTEIN_PER_KG.get(goal or "maintain", 1.5) * weight_kg
    out.update(ready=True, bmr=round(bmr), maintenance=_round10(maintenance), calories=_round10(calories),
               protein_g=int(round(protein / 5.0) * 5))
    out["notes"].append("Workouts and steps you log add calories on the day, on top of this.")
    return out
