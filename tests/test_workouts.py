import pytest

from app.services import injuries as inj
from app.services import workouts as wk


def names(res):
    return [o["name"].lower() for o in res["options"]]


def test_dataset_loaded(db):
    assert len(wk.search_exercises(db, limit=1000)) > 800
    assert wk.search_exercises(db, category="stretching", limit=5)


def test_options_respect_unavailable_equipment(db):
    wk.set_equipment_unavailable(db, ["barbell"])
    res = wk.exercise_options(db, "chest", limit=50)
    assert res["options"] and all(o["equipment"] != "barbell" for o in res["options"])
    assert res["excluded_counts"]["unavailable_equipment"] > 0


def test_machine_name_keyword_unavailable(db):
    wk.set_equipment_unavailable(db, ["leg press"])
    assert not any("leg press" in n for n in names(wk.exercise_options(db, "quadriceps", limit=100)))


def test_knee_injury_removes_squats_and_lunges(db):
    inj.set_injury(db, "knees", "mild")
    res = wk.exercise_options(db, "quadriceps", limit=100)
    assert not any(k in n for n in names(res) for k in ("squat", "lunge", "jump"))
    assert res["excluded_counts"]["injury"] > 0


def test_moderate_injury_blocks_whole_muscle_group(db):
    inj.set_injury(db, "shoulder", "moderate")
    assert wk.exercise_options(db, "shoulders")["options"] == []


def test_severity_and_area_validation(db):
    with pytest.raises(ValueError):
        inj.set_injury(db, "pinky", "mild")
    with pytest.raises(ValueError):
        inj.set_injury(db, "knee", "catastrophic")


def test_clear_injury_restores_options(db):
    inj.set_injury(db, "shoulder", "moderate")
    inj.clear_injury(db, "shoulder")
    assert wk.exercise_options(db, "shoulders")["options"]


def test_low_readiness_limits_to_beginner_and_advises_lighter(db):
    wk.set_daily_state(db, energy=1, soreness=5)
    res = wk.exercise_options(db, "chest", limit=100)
    assert res["readiness"]["level"] == "low"
    assert res["options"] and all(o["level"] == "beginner" for o in res["options"])


def test_log_workout_numbers_sets_and_tracks_muscles(db):
    wk.log_workout(db, "Barbell Curl", [{"reps": 10, "weight_kg": 20}])
    wk.log_workout(db, "Barbell Curl", [{"reps": 8, "weight_kg": 22.5}])
    rt = wk.recent_training(db)
    assert rt["sets_per_muscle"]["biceps"] == 2
    assert rt["days_since_muscle_trained"]["biceps"] == 0


def test_log_unknown_exercise(db):
    assert wk.log_workout(db, "zzz not real", [{"reps": 5}])["logged"] is False


def test_card_has_images_and_steps(db):
    card = wk.exercise_card(wk.find_exercise(db, "Barbell Curl"))
    assert len(card["images"]) == 2 and card["images"][0].startswith("https://") and card["steps"]


# ---- variety, muscle groups, equipment mix ----
def _ids(res):
    return [o["id"] for o in res["options"]]


def test_repeat_requests_rotate_instead_of_repeating(db):
    first = wk.exercise_options(db, "biceps", limit=3)
    wk.record_suggestions(db, _ids(first))
    second = wk.exercise_options(db, "biceps", limit=3)
    assert len(set(_ids(first))) == 3 and len(set(_ids(second))) == 3
    assert not set(_ids(first)) & set(_ids(second))


def test_recently_logged_exercises_are_offered_last(db):
    wk.log_workout(db, "Barbell Curl", [{"reps": 10, "weight_kg": 20}])
    for _ in range(10):
        assert "Barbell_Curl" not in _ids(wk.exercise_options(db, "biceps", limit=3))


def test_recent_exercises_still_returned_when_nothing_else_is_left(db):
    everything = wk.exercise_options(db, "biceps", limit=100)
    wk.record_suggestions(db, _ids(everything))
    again = wk.exercise_options(db, "biceps", limit=3)
    assert len(again["options"]) == 3 and again["fresh_matching"] == 0


def test_back_group_covers_lats_and_middle_back(db):
    res = wk.exercise_options(db, "back", limit=30)
    assert res["options"]
    assert all({"lats", "middle back"} & set(o["primary"]) for o in res["options"])
    assert {m for o in res["options"] for m in o["primary"]} >= {"lats", "middle back"}


def test_muscle_aliases(db):
    assert wk.resolve_muscles("bicep") == ["biceps"]
    assert wk.resolve_muscles("arms") == ["biceps", "triceps"]
    assert wk.resolve_muscles("Back and Biceps") == ["lats", "middle back", "biceps"]
    assert wk.exercise_options(db, "legs", limit=10)["options"]


def test_unknown_muscle_gives_error_not_empty_list(db):
    res = wk.exercise_options(db, "pinky", limit=3)
    assert "error" in res and "options" not in res


def test_options_mix_equipment_and_movement_types(db):
    res = wk.exercise_options(db, "chest", limit=6)
    assert len({o["equipment"] for o in res["options"]}) >= 2
    assert {o["mechanic"] for o in res["options"]} >= {"compound"}
    assert len(res["options"]) == 6


def test_rotation_never_breaks_injury_or_equipment_filters(db):
    inj.set_injury(db, "shoulder", "mild")
    wk.set_equipment_unavailable(db, ["barbell"])
    for _ in range(15):
        res = wk.exercise_options(db, "chest", limit=6)
        assert all(o["equipment"] != "barbell" for o in res["options"])
        assert not any(k in o["name"].lower() for o in res["options"] for k in ("overhead", "dip", "military"))
        wk.record_suggestions(db, _ids(res))


def test_plural_and_punctuation_insensitive_matching(db):
    assert wk.find_exercise(db, "barbell curls").name == "Barbell Curl"
    assert wk.norm_text("Seated Cable Rows!") == wk.norm_text("seated cable row")


def test_advanced_movements_never_suggested(db):
    for muscle in ("back", "chest", "biceps", "shoulders", "legs", "arms"):
        res = wk.exercise_options(db, muscle, limit=100)
        bad = [o["name"] for o in res["options"] if any(k in o["name"].lower() for k in wk.ADVANCED_KEYWORDS)]
        assert not bad, bad
    assert wk.find_exercise(db, "Muscle Up")  # still available when asked for by name


def test_beginner_gets_beginner_gym_exercises_first(db):
    for _ in range(5):  # 15 exercises, fewer than the ~28 beginner back exercises available
        res = wk.exercise_options(db, "back", limit=3)
        assert all(o["level"] == "beginner" and o["equipment"] in wk.GYM_EQUIPMENT for o in res["options"])
        wk.record_suggestions(db, _ids(res))


def test_pool_widens_to_intermediate_once_beginner_ones_run_out(db):
    seen_levels = set()
    for _ in range(14):  # 42 picks, more than the beginner back exercises that exist
        res = wk.exercise_options(db, "back", limit=3)
        seen_levels |= {o["level"] for o in res["options"]}
        wk.record_suggestions(db, _ids(res))
    assert "beginner" in seen_levels and "intermediate" in seen_levels


def test_pool_widens_gracefully_for_thin_muscles(db):
    for _ in range(8):  # lower back has very few beginner exercises
        res = wk.exercise_options(db, "lower back", limit=3)
        assert res["options"]
        wk.record_suggestions(db, _ids(res))
