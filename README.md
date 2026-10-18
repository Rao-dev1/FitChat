# FitChat

A free, chat-style **food and gym coach** you use from your phone. Run it on your own computer, or host it free on the web
so you and other people can each sign in to their own private account.

Built for a 92-day "Winter Arc" challenge (Oct 1 to Dec 31), but it works for any training and diet routine.
Food and workout data live in one database, so advice on one side uses the other (protein left after training,
lighter volume on a low-energy day).

```
Phone (installable web app)  ->  FastAPI  ->  Gemini (free tier, tool calling)
                                     |
                       SQLite on a laptop  /  Postgres (Supabase) when hosted
```

## Features

- **Coach chat**: talk in plain words ("2 rotis and dal for lunch", "my waist is 96 cm", "slept 7 hours, 9000 steps").
- **Food**: built-in nutrition table (about 90 common Indian and gym foods), your own foods and recipes, per-gram logging,
  Open Food Facts search, fibre tracking, and past-day entry.
- **Meal planning**: plan the rest of today, or a full week with a grocery list sorted by aisle.
- **Gym**: routines, per-exercise targets, set logging with progression hints and estimated 1-rep max, rest timer,
  injury-aware exercise swaps, exercise pictures.
- **Progress**: weekly summary, bodyweight trend, body measurements, sleep and steps, progress photos (laptop mode).
- **Winter Arc dashboard**: day count, streaks, weekly gym goal, and a labelled weight projection.
- **Reminders**: rule-based nudges shown on the Home screen.
- **Accounts (hosted mode)**: email sign-up, every person's data is separate, optional own Gemini key, daily coach limit,
  data export and restore, and an owner switch to pause the whole site from a phone.

## Design principles

- **The model never does math or holds state.** It calls tools (`app/tools/registry.py`); plain, tested Python reads and
  writes the database and the model only words the result.
- **Filter in code, rank with the model.** Equipment, injuries and readiness remove exercises before the model sees options.
- **Provider-neutral LLM layer** (`app/llm/`): swapping Gemini for another provider means writing one adapter.
- **Free-quota friendly.** Quick logging and dashboards use plain REST endpoints with no model call.
- **Privacy enforced in one place.** Every personal table has a `user_id`, and a database-session hook (`app/tenancy.py`)
  adds the user filter to every query and stamps every new row, so no endpoint can forget it.

## Run it on your computer

Requires Python 3.11 or newer (developed on 3.13) and a free [Google AI Studio](https://aistudio.google.com/) API key.

```bat
git clone https://github.com/Rao-dev1/FitChat.git
cd FitChat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and put your key in `GEMINI_API_KEY`. **Never commit `.env`**; it is already in `.gitignore`.
On macOS or Linux use `source .venv/bin/activate` and `cp .env.example .env`.

```bat
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. On your phone (same Wi-Fi) open `http://<computer-ip>:8000`
(`ipconfig` shows the IPv4 address). In this mode there is one local user and no sign-in.
The database `fitchat.db` and the `photos/` folder are created next to the code and are not part of the repo.

**Upgrading an older copy:** the first start after an update upgrades your existing `fitchat.db` automatically and keeps
all your data. Copy `fitchat.db` somewhere safe first if you like.

## Host it on the web (free)

FitChat runs on **Vercel** (the website) with **Supabase** (database and sign-in). Step-by-step instructions, written
for a first deploy, are in [DEPLOY.md](DEPLOY.md). Moving the data you already have on your laptop is covered there too.

## Tests

```bat
pip install -r requirements-dev.txt
pytest
```

The suite runs offline with a scripted fake model, so it needs no API key. To run it against a real Postgres instead of
in-memory SQLite, set `TEST_DATABASE_URL=postgresql://user@host/dbname` first.

## Project layout

```
api/          Vercel entry point
app/
  api/        REST endpoints (data, plan, body, arc, mealprep, account, ...)
  services/   plain-Python logic: nutrition, planner, arc, nudges, workouts
  tools/      the functions the coach model is allowed to call
  llm/        provider adapters (Gemini) and a scripted fake for tests
  seed/       nutrition table and shopping data
  static/     the phone UI (plain HTML, CSS and JS, no build step)
  auth.py     who is making a request (local user, or a Supabase sign-in)
  tenancy.py  per-user data isolation
  accounts.py database setup, pause switch, own-key storage, export and restore
data/         exercise database
tests/
```

## Known limits

- Nutrition values are rounded typical figures (roughly 5 to 15 percent off real life). Edit rows to match your portions.
- Injury filtering is a keyword heuristic, not medical advice.
- Weight projections are estimates from recent trend and are labelled as such.
- Exercise pictures and fonts need internet on the phone.
- Progress photos work only in laptop mode for now (a hosted server has no disk to keep them on).
- Free-tier Gemini limits and terms can change, and on the free tier Google may use prompts to improve its products;
  check Google AI Studio. In hosted mode everyone shares your key unless they add their own.
- Never open laptop mode to the internet: it has no sign-in. Use the hosted mode for that.
