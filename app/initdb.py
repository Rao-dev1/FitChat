"""One-time database setup for a hosted database:  python -m app.initdb
Reads DATABASE_URL from .env / the environment, creates the tables and loads the exercise list."""
from . import accounts
from .db import engine

if __name__ == "__main__":
    print("Setting up:", engine.url.render_as_string(hide_password=True))
    accounts.init_database()
    print("Done.")
