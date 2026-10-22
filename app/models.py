"""Database schema. Food and gym data share one database so each side can inform the other."""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, PrimaryKeyConstraint, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from . import clock


def _now() -> datetime:
    return clock.now()


class UserOwned:
    """Mixin for every table that holds one person's data. user_id is filled in and enforced automatically
    (see tenancy.py): a query can only ever see the rows of the user the session belongs to."""

    user_id: Mapped[str] = mapped_column(String(64), index=True)


class Profile(UserOwned, Base):
    """Single-row table holding the user's goal and daily targets."""

    __tablename__ = "profile"
    __table_args__ = (UniqueConstraint("user_id", name="uq_profile_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    seed_version: Mapped[int] = mapped_column(Integer, default=0)  # which starter-food table this user has
    goal: Mapped[str] = mapped_column(String(20), default="maintain")  # fat_loss | muscle_gain | maintain
    calorie_target: Mapped[float] = mapped_column(Float, default=2200)
    protein_target_g: Mapped[float] = mapped_column(Float, default=100)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience: Mapped[str] = mapped_column(String(20), default="beginner")  # beginner | intermediate | expert
    water_target_ml: Mapped[float] = mapped_column(Float, default=3000)
    fibre_target_g: Mapped[float] = mapped_column(Float, default=30)
    gym_days_goal: Mapped[int] = mapped_column(Integer, default=4)
    # Body details for the target calculator (all optional).
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(10), nullable=True)  # male | female | other
    activity: Mapped[str] = mapped_column(String(12), default="light")  # sedentary | light | moderate
    auto_targets: Mapped[bool] = mapped_column(Boolean, default=False)  # keep calorie/protein targets calculated


class Food(UserOwned, Base):
    """Reference nutrition values per serving (your usual foods, IFCT/OpenFoodFacts imports)."""

    __tablename__ = "foods"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_foods_user_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    serving: Mapped[str] = mapped_column(String(60), default="1 serving")
    calories: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float, default=0)
    fat_g: Mapped[float] = mapped_column(Float, default=0)
    fibre_g: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(30), default="seed")


class Ingredient(UserOwned, Base):
    """Built-in nutrition per 100 g of the food as eaten (cooked unless named dry/raw). Used to compute
    calories/protein from grams in code, so the language model never has to guess them."""

    __tablename__ = "ingredients"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_ingredients_user_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    calories_100g: Mapped[float] = mapped_column(Float)
    protein_100g: Mapped[float] = mapped_column(Float)
    carbs_100g: Mapped[float] = mapped_column(Float, default=0)
    fat_100g: Mapped[float] = mapped_column(Float, default=0)
    fibre_100g: Mapped[float] = mapped_column(Float, default=0)
    serving_g: Mapped[float | None] = mapped_column(Float, nullable=True)  # one countable piece, e.g. 1 egg = 50
    serving_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="seed_approx")


class MealLog(UserOwned, Base):
    __tablename__ = "meal_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    day: Mapped[date] = mapped_column(Date, default=clock.today, index=True)
    meal_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    food_name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[float] = mapped_column(Float, default=1)
    calories: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float, default=0)
    fat_g: Mapped[float] = mapped_column(Float, default=0)
    fibre_g: Mapped[float] = mapped_column(Float, default=0)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)  # True = model guess, not from the food table


class Exercise(Base):
    __tablename__ = "exercises"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # free-exercise-db id
    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)  # strength | stretching | cardio ...
    equipment: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    force: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mechanic: Mapped[str | None] = mapped_column(String(20), nullable=True)
    primary_muscles: Mapped[list] = mapped_column(JSON, default=list)
    secondary_muscles: Mapped[list] = mapped_column(JSON, default=list)
    instructions: Mapped[list] = mapped_column(JSON, default=list)
    images: Mapped[list] = mapped_column(JSON, default=list)


class WorkoutSession(UserOwned, Base):
    __tablename__ = "workout_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, default=clock.today, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sets: Mapped[list["WorkoutSet"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class WorkoutSet(UserOwned, Base):
    __tablename__ = "workout_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id"))
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"))
    set_number: Mapped[int] = mapped_column(Integer, default=1)
    reps: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[float] = mapped_column(Float, default=0)
    session: Mapped[WorkoutSession] = relationship(back_populates="sets")
    exercise: Mapped[Exercise] = relationship()


class Injury(UserOwned, Base):
    __tablename__ = "injuries"
    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[str] = mapped_column(String(30), index=True)  # see services/injuries.py
    severity: Mapped[str] = mapped_column(String(10), default="mild")  # mild | moderate | severe
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DailyState(UserOwned, Base):
    __tablename__ = "daily_state"
    __table_args__ = (PrimaryKeyConstraint("user_id", "day"),)
    day: Mapped[date] = mapped_column(Date, default=clock.today)
    energy: Mapped[int] = mapped_column(Integer, default=3)  # 1 (drained) .. 5 (great)
    soreness: Mapped[int] = mapped_column(Integer, default=1)  # 1 (none) .. 5 (very sore)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class EquipmentStatus(UserOwned, Base):
    """Equipment currently unavailable at the gym (busy/broken). Cleared with set_equipment_available."""

    __tablename__ = "equipment_unavailable"
    __table_args__ = (PrimaryKeyConstraint("user_id", "equipment"),)
    equipment: Mapped[str] = mapped_column(String(40))
    marked_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ChatMessage(UserOwned, Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class ExerciseSuggestion(UserOwned, Base):
    """Which exercises were shown to the user and when, so the next request can offer fresh ones."""

    __tablename__ = "exercise_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[str] = mapped_column(String(120), index=True)
    suggested_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class WeightLog(UserOwned, Base):
    """One bodyweight reading per day (a second reading the same day replaces the first)."""

    __tablename__ = "weight_log"
    __table_args__ = (PrimaryKeyConstraint("user_id", "day"),)
    day: Mapped[date] = mapped_column(Date)
    weight_kg: Mapped[float] = mapped_column(Float)


class WaterLog(UserOwned, Base):
    __tablename__ = "water_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, default=clock.today, index=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ml: Mapped[float] = mapped_column(Float)


class BowelLog(UserOwned, Base):
    """One bowel movement, rated on the Bristol stool scale (1 hard lumps .. 7 watery)."""

    __tablename__ = "bowel_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, default=clock.today, index=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    bristol: Mapped[int] = mapped_column(Integer)
    warning_signs: Mapped[bool] = mapped_column(Boolean, default=False)  # blood, black stool or severe pain
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Recipe(UserOwned, Base):
    """A saved home recipe. Its nutrition per serving lives in the linked Food row, so logging by name just works;
    the ingredient lines are kept so the recipe can be viewed and edited later."""

    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    servings: Mapped[float] = mapped_column(Float, default=1)
    cooked_weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)  # whole pot, for "I ate 300 g of it"
    ingredients: Mapped[list] = mapped_column(JSON, default=list)  # [{name, grams, raw_text}]
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    food: Mapped["Food"] = relationship()


class Routine(UserOwned, Base):
    """A saved workout (e.g. Push day): an ordered list of exercises with target sets, reps and rest."""

    __tablename__ = "routines"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_routines_user_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    items: Mapped[list["RoutineExercise"]] = relationship(
        back_populates="routine", cascade="all, delete-orphan", order_by="RoutineExercise.position")


class RoutineExercise(UserOwned, Base):
    __tablename__ = "routine_exercises"
    id: Mapped[int] = mapped_column(primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id"))
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    sets: Mapped[int] = mapped_column(Integer, default=3)
    rep_min: Mapped[int] = mapped_column(Integer, default=8)
    rep_max: Mapped[int] = mapped_column(Integer, default=12)
    rest_s: Mapped[int] = mapped_column(Integer, default=90)
    routine: Mapped[Routine] = relationship(back_populates="items")
    exercise: Mapped[Exercise] = relationship()


class BodyMeasure(UserOwned, Base):
    """Tape measurements in cm, one row per day. Every field is optional; a new entry for the same day merges."""

    __tablename__ = "body_measures"
    __table_args__ = (PrimaryKeyConstraint("user_id", "day"),)
    day: Mapped[date] = mapped_column(Date)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    chest_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hips_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    arm_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    thigh_cm: Mapped[float | None] = mapped_column(Float, nullable=True)


class ProgressPhoto(UserOwned, Base):
    """Metadata for a progress photo; the picture itself is a file in the photos folder."""

    __tablename__ = "progress_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, default=clock.today, index=True)
    pose: Mapped[str] = mapped_column(String(10), default="front")  # front | side | back
    filename: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DayStat(UserOwned, Base):
    """Sleep and steps, one row per day (typed in by hand)."""

    __tablename__ = "day_stats"
    __table_args__ = (PrimaryKeyConstraint("user_id", "day"),)
    day: Mapped[date] = mapped_column(Date)
    sleep_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MealPlan(UserOwned, Base):
    """The latest generated weekly plan, kept so the plan and grocery list are still there tomorrow."""

    __tablename__ = "meal_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    start_day: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    data: Mapped[dict] = mapped_column(JSON)


class SiteSetting(Base):
    """Site-wide switches shared by everyone (not per user), e.g. 'paused'."""

    __tablename__ = "site_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class UserSecret(UserOwned, Base):
    """A user's own Gemini key, encrypted. One row per user."""

    __tablename__ = "user_secrets"
    __table_args__ = (PrimaryKeyConstraint("user_id"),)
    gemini_key_enc: Mapped[str] = mapped_column(String(500), default="")


from . import tenancy  # noqa: E402,F401  (registers the per-user filter on import)
