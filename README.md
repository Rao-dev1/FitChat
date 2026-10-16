# FitChat

A free, self-hosted, chat-style **food and gym coach** that runs on your own computer and is used from your phone.
Built for a 92-day "Winter Arc" challenge (Oct 1 to Dec 31), but works for any training and diet routine.

Food and workout data live in one database, so the advice on one side uses the other (protein left after training,
lighter volume on a low-energy day).

```
Phone (installable web app)  ->  FastAPI  ->  Gemini (free tier, tool calling)
                                     |
                                 SQLite (foods, meals, exercises, sets, body, sleep, plans)
```

## Features

- **Coach chat**: talk in plain words ("2 rotis and dal for lunch", "my waist is 96 cm", "slept 7 hours, 9000 steps").
- **Food**: built-in nutrition table (about 90 common Indian and gym foods), your own foods and recipes, per-gram logging,
  Open Food Facts search, fibre tracking, and past-day entry.
- **Meal planning**: plan the rest of today, or a full week with a grocery list sorted by aisle.
- **Gym**: routines, per-exercise targets, set logging with progression hints and estimated 1-rep max, rest timer,
  injury-aware exercise swaps, exercise pictures.
- **Progress**: weekly summary, bodyweight trend, body measurements, progress photos (stored locally), sleep and steps.
- **Winter Arc dashboard**: day count, streaks, weekly gym goal, and a labelled weight projection.
- **Reminders**: rule-based nudges shown on the Home screen.

## Design principles

- **The model never does math or holds state.** It calls tools (`app/tools/registry.py`); plain, tested Python reads and
  writes the database and the model only words the result.
- **Filter in code, rank with the model.** Equipment, injuries and readiness remove exercises before the model sees options.
- **Provider-neutral LLM layer** (`app/llm/`): swapping Gemini for another provider means writing one adapter.
- **Free-quota friendly.** Quick logging and dashboards use plain REST endpoints with no model call.
- **Estimates are labelled** as estimates.

## Setup

Requires Python 3.11 or newer (developed on 3.13) and a free [Google AI Studio](https://aistudio.google.com/) API key.

```bat
git clone https://github.com/Rao-dev1/FitChat.git
cd FitChat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and put your own key in `GEMINI_API_KEY`. **Never commit `.env`**; it is already in `.gitignore`.

On macOS or Linux, use `source .venv/bin/activate` and `cp .env.example .env`.

## Run

```bat
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` on the computer. The web app is served by the backend itself, so there is no build step.
API docs for debugging are at `http://localhost:8000/docs`.

The database (`fitchat.db`) and photos (`photos/`) are created next to the code on first start and are not part of this repo.

## Use it on your phone

1. Put the phone and computer on the same Wi-Fi.
2. Find the computer's IPv4 address (`ipconfig` on Windows) and allow Python through the firewall if asked.
3. On the phone, open `http://<computer-ip>:8000`.
4. In Chrome, use menu, then Add to Home screen.

## Tests

```bat
pip install pytest
pytest
```

The suite runs fully offline with a scripted fake model, so it needs no API key.

## Project layout

```
app/
  api/        REST endpoints (data, plan, body, arc, mealprep, ...)
  services/   plain-Python logic: nutrition, planner, arc, nudges, workouts
  tools/      the functions the coach model is allowed to call
  llm/        provider adapters (Gemini) and a scripted fake for tests
  seed/       nutrition table and shopping data
  static/     the phone UI (plain HTML, CSS and JS)
data/         exercise database
tests/
```

## Known limits

- Nutrition values are rounded typical figures (roughly 5 to 15 percent off real life). Edit rows to match your portions.
- Injury filtering is a keyword heuristic, not medical advice.
- Weight projections are estimates from recent trend and are labelled as such.
- Exercise pictures and fonts need internet on the phone.
- Over plain http on a LAN, Chrome offers a shortcut rather than a full install; background notifications need HTTPS.
- **There is no login.** Keep it on your home network or behind a private network such as Tailscale. Do not expose it to
  the public internet without adding authentication.
- Free-tier Gemini limits and terms can change; check Google AI Studio.

## Back up your data

Copy `fitchat.db` and the `photos/` folder somewhere safe now and then. They hold everything you have logged.
