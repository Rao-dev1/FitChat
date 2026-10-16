"""Tiny additive migration: SQLAlchemy's create_all makes new tables but never adds columns to existing ones, so
databases created by older versions get the new columns here. Only ever adds columns; never drops or rewrites."""
from sqlalchemy import inspect, text

ADDED_COLUMNS = [
    ("ingredients", "fibre_100g", "FLOAT DEFAULT 0"),
    ("foods", "fibre_g", "FLOAT DEFAULT 0"),
    ("meal_logs", "fibre_g", "FLOAT DEFAULT 0"),
    ("profile", "water_target_ml", "FLOAT DEFAULT 3000"),
    ("profile", "fibre_target_g", "FLOAT DEFAULT 30"),
    ("profile", "gym_days_goal", "INTEGER DEFAULT 4"),
]


def ensure_columns(engine) -> list[str]:
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, col, ddl in ADDED_COLUMNS:
            if table not in insp.get_table_names():
                continue
            if col in {c["name"] for c in insp.get_columns(table)}:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            added.append(f"{table}.{col}")
    return added
