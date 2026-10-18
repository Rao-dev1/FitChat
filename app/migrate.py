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
    ("profile", "seed_version", "INTEGER DEFAULT 0"),
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


def upgrade_to_accounts(engine, owner: str = "local") -> list[str]:
    """Databases made before accounts existed (SQLite on a laptop) get a user_id on every personal table.
    Their primary keys / unique names change too, so each table is rebuilt: renamed aside, recreated, rows copied
    (all owned by `owner`), old table dropped. Nothing is lost. Fresh databases (and Postgres) skip this."""
    from .db import Base

    if engine.dialect.name != "sqlite":
        return []
    insp = inspect(engine)
    present = set(insp.get_table_names())
    todo = [t for t in Base.metadata.sorted_tables
            if "user_id" in t.c and t.name in present
            and "user_id" not in {c["name"] for c in insp.get_columns(t.name)}]
    if not todo:
        return []
    done = []
    with engine.begin() as conn:
        # Keep foreign keys in other tables pointing at the table NAME while we swap the tables underneath.
        conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        for table in todo:
            name = table.name
            old_cols = [c["name"] for c in insp.get_columns(name)]
            for ix in insp.get_indexes(name):
                conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{ix["name"]}"')
            conn.exec_driver_sql(f'ALTER TABLE "{name}" RENAME TO "{name}__old"')
            table.create(conn)
            keep = [c for c in old_cols if c in table.c]
            cols = ", ".join(f'"{c}"' for c in keep)
            conn.exec_driver_sql(f'INSERT INTO "{name}" ({cols}, "user_id") SELECT {cols}, ? FROM "{name}__old"',
                                 (owner,))
            conn.exec_driver_sql(f'DROP TABLE "{name}__old"')
            done.append(name)
        conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
    return done
