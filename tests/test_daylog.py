from datetime import date, timedelta

from app.models import MealLog, WorkoutSession, WorkoutSet
from app.services import workouts as wk


def seed_day(db, day):
    db.add_all([MealLog(day=day, meal_type="dinner", food_name="Dal", calories=150, protein_g=8, fibre_g=4),
                MealLog(day=day, meal_type="breakfast", food_name="Oats", calories=156, protein_g=7, fibre_g=4),
                MealLog(day=day, food_name="Banana", calories=105, protein_g=1)])
    ex = wk.find_exercise(db, "Barbell Bench Press - Medium Grip")
    s = WorkoutSession(day=day)
    s.sets = [WorkoutSet(exercise_id=ex.id, set_number=i + 1, reps=10, weight_kg=40) for i in range(6)]
    db.add(s)
    db.commit()


def test_yesterday_shows_meals_in_order_with_workout_and_targets(client, db):
    y = date.today() - timedelta(days=1)
    seed_day(db, y)
    client.post("/api/water", json={"ml": 750, "day": y.isoformat()})
    client.post("/api/bowel", json={"bristol": 4, "day": y.isoformat()})
    j = client.get(f"/api/day/{y.isoformat()}").json()
    assert [m["meal_type"] for m in j["meals"]] == ["breakfast", "dinner", "other"]
    assert j["totals"]["calories"] == 411 and j["totals"]["fibre_g"] == 8
    assert j["workout"]["total_sets"] == 6 and j["trained"] and j["targets"]["training_day_bonus"] == 150
    assert j["water"]["ml"] == 750 and j["bowel"][0]["bristol"] == 4
    assert j["is_today"] is False and j["next_day"] == date.today().isoformat()
    assert j["prev_day"] == (y - timedelta(days=1)).isoformat()


def test_today_has_no_next_and_empty_day_is_valid(client):
    j = client.get(f"/api/day/{date.today().isoformat()}").json()
    assert j["is_today"] and j["next_day"] is None and j["meals"] == [] and j["workout"]["exercises"] == []


def test_future_and_ancient_days_refused(client):
    assert client.get(f"/api/day/{(date.today() + timedelta(days=1)).isoformat()}").status_code == 422
    assert client.get("/api/day/1990-01-01").status_code == 422
    assert client.get("/api/day/not-a-date").status_code == 422


def test_recent_days_lists_only_days_with_data_newest_first(client, db):
    seed_day(db, date.today() - timedelta(days=3))
    seed_day(db, date.today() - timedelta(days=1))
    days = client.get("/api/days").json()
    assert [d["day"] for d in days] == [(date.today() - timedelta(days=1)).isoformat(), (date.today() - timedelta(days=3)).isoformat()]
    assert days[0]["sets"] == 6 and days[0]["calories"] == 411


def test_deleting_from_a_past_day_works(client, db):
    y = date.today() - timedelta(days=1)
    seed_day(db, y)
    mid = client.get(f"/api/day/{y.isoformat()}").json()["meals"][0]["items"][0]["id"]
    assert client.delete(f"/api/meals/{mid}").status_code == 204
    assert client.get(f"/api/day/{y.isoformat()}").json()["totals"]["entries"] == 2


def test_meal_can_be_logged_for_a_past_day_and_stays_out_of_today(client, db):
    y = (date.today() - timedelta(days=1)).isoformat()
    r = client.post("/api/meals", json={"name": "Dal", "quantity": 1, "day": y})
    assert r.status_code == 201 and r.json()["remaining"]["day"] == y
    assert client.get(f"/api/day/{y}").json()["totals"]["entries"] == 1
    assert client.get("/api/day/" + date.today().isoformat()).json()["totals"]["entries"] == 0
    ing = client.get("/api/ingredients?q=paneer").json()[0]["id"]
    assert client.post("/api/meals/weighed", json={"ingredient_id": ing, "grams": 100, "day": y}).status_code == 201
    assert client.get(f"/api/day/{y}").json()["totals"]["entries"] == 2


def test_past_day_logging_limits(client):
    fut = (date.today() + timedelta(days=1)).isoformat()
    old = (date.today() - timedelta(days=61)).isoformat()
    assert client.post("/api/meals", json={"name": "Dal", "day": fut}).status_code == 422
    assert client.post("/api/meals", json={"name": "Dal", "day": old}).status_code == 422
    assert client.post("/api/meals", json={"name": "Dal", "day": "garbage"}).status_code == 422


def test_coach_logs_food_for_yesterday(client, db):
    from app.llm.fake import ScriptedLLM, call, say
    client.set_llm(ScriptedLLM([call("log_food", days_ago=1, items=[{"name": "Dal", "quantity": 2}]), say("ok")]))
    client.post("/api/chat", json={"message": "yesterday I had 2 dal"})
    y = (date.today() - timedelta(days=1)).isoformat()
    assert client.get(f"/api/day/{y}").json()["totals"]["entries"] == 1
    assert client.get("/api/day/" + date.today().isoformat()).json()["totals"]["entries"] == 0
