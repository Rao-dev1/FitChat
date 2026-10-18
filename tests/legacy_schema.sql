CREATE TABLE body_measures (
	day DATE NOT NULL, 
	waist_cm FLOAT, 
	chest_cm FLOAT, 
	hips_cm FLOAT, 
	arm_cm FLOAT, 
	thigh_cm FLOAT, 
	PRIMARY KEY (day)
);
CREATE TABLE bowel_log (
	id INTEGER NOT NULL, 
	day DATE NOT NULL, 
	logged_at DATETIME NOT NULL, 
	bristol INTEGER NOT NULL, 
	warning_signs BOOLEAN NOT NULL, 
	note VARCHAR(200), 
	PRIMARY KEY (id)
);
CREATE TABLE chat_messages (
	id INTEGER NOT NULL, 
	role VARCHAR(10) NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE daily_state (
	day DATE NOT NULL, 
	energy INTEGER NOT NULL, 
	soreness INTEGER NOT NULL, 
	note TEXT, 
	PRIMARY KEY (day)
);
CREATE TABLE day_stats (
	day DATE NOT NULL, 
	sleep_h FLOAT, 
	steps INTEGER, 
	PRIMARY KEY (day)
);
CREATE TABLE equipment_unavailable (
	equipment VARCHAR(40) NOT NULL, 
	marked_at DATETIME NOT NULL, 
	PRIMARY KEY (equipment)
);
CREATE TABLE exercise_suggestions (
	id INTEGER NOT NULL, 
	exercise_id VARCHAR(120) NOT NULL, 
	suggested_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE exercises (
	id VARCHAR(120) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	equipment VARCHAR(40), 
	level VARCHAR(20), 
	force VARCHAR(20), 
	mechanic VARCHAR(20), 
	primary_muscles JSON NOT NULL, 
	secondary_muscles JSON NOT NULL, 
	instructions JSON NOT NULL, 
	images JSON NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE foods (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	aliases JSON NOT NULL, 
	serving VARCHAR(60) NOT NULL, 
	calories FLOAT NOT NULL, 
	protein_g FLOAT NOT NULL, 
	carbs_g FLOAT NOT NULL, 
	fat_g FLOAT NOT NULL, 
	fibre_g FLOAT NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE ingredients (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	aliases JSON NOT NULL, 
	calories_100g FLOAT NOT NULL, 
	protein_100g FLOAT NOT NULL, 
	carbs_100g FLOAT NOT NULL, 
	fat_100g FLOAT NOT NULL, 
	fibre_100g FLOAT NOT NULL, 
	serving_g FLOAT, 
	serving_label VARCHAR(40), 
	source VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE injuries (
	id INTEGER NOT NULL, 
	area VARCHAR(30) NOT NULL, 
	severity VARCHAR(10) NOT NULL, 
	note TEXT, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE meal_logs (
	id INTEGER NOT NULL, 
	logged_at DATETIME NOT NULL, 
	day DATE NOT NULL, 
	meal_type VARCHAR(20), 
	food_name VARCHAR(120) NOT NULL, 
	quantity FLOAT NOT NULL, 
	calories FLOAT NOT NULL, 
	protein_g FLOAT NOT NULL, 
	carbs_g FLOAT NOT NULL, 
	fat_g FLOAT NOT NULL, 
	fibre_g FLOAT NOT NULL, 
	estimated BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE meal_plans (
	id INTEGER NOT NULL, 
	start_day DATE NOT NULL, 
	created_at DATETIME NOT NULL, 
	data JSON NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE profile (
	id INTEGER NOT NULL, 
	goal VARCHAR(20) NOT NULL, 
	calorie_target FLOAT NOT NULL, 
	protein_target_g FLOAT NOT NULL, 
	weight_kg FLOAT, 
	experience VARCHAR(20) NOT NULL, 
	water_target_ml FLOAT NOT NULL, 
	fibre_target_g FLOAT NOT NULL, 
	gym_days_goal INTEGER NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE progress_photos (
	id INTEGER NOT NULL, 
	day DATE NOT NULL, 
	pose VARCHAR(10) NOT NULL, 
	filename VARCHAR(80) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE recipes (
	id INTEGER NOT NULL, 
	food_id INTEGER NOT NULL, 
	servings FLOAT NOT NULL, 
	cooked_weight_g FLOAT, 
	ingredients JSON NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(food_id) REFERENCES foods (id)
);
CREATE TABLE routine_exercises (
	id INTEGER NOT NULL, 
	routine_id INTEGER NOT NULL, 
	exercise_id VARCHAR(120) NOT NULL, 
	position INTEGER NOT NULL, 
	sets INTEGER NOT NULL, 
	rep_min INTEGER NOT NULL, 
	rep_max INTEGER NOT NULL, 
	rest_s INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(routine_id) REFERENCES routines (id), 
	FOREIGN KEY(exercise_id) REFERENCES exercises (id)
);
CREATE TABLE routines (
	id INTEGER NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	notes VARCHAR(300), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE water_log (
	id INTEGER NOT NULL, 
	day DATE NOT NULL, 
	logged_at DATETIME NOT NULL, 
	ml FLOAT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE weight_log (
	day DATE NOT NULL, 
	weight_kg FLOAT NOT NULL, 
	PRIMARY KEY (day)
);
CREATE TABLE workout_sessions (
	id INTEGER NOT NULL, 
	day DATE NOT NULL, 
	notes TEXT, 
	PRIMARY KEY (id)
);
CREATE TABLE workout_sets (
	id INTEGER NOT NULL, 
	session_id INTEGER NOT NULL, 
	exercise_id VARCHAR(120) NOT NULL, 
	set_number INTEGER NOT NULL, 
	reps INTEGER NOT NULL, 
	weight_kg FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES workout_sessions (id), 
	FOREIGN KEY(exercise_id) REFERENCES exercises (id)
);
CREATE INDEX ix_bowel_log_day ON bowel_log (day);
CREATE INDEX ix_chat_messages_created_at ON chat_messages (created_at);
CREATE INDEX ix_exercise_suggestions_exercise_id ON exercise_suggestions (exercise_id);
CREATE INDEX ix_exercise_suggestions_suggested_at ON exercise_suggestions (suggested_at);
CREATE INDEX ix_exercises_category ON exercises (category);
CREATE INDEX ix_exercises_equipment ON exercises (equipment);
CREATE INDEX ix_exercises_name ON exercises (name);
CREATE UNIQUE INDEX ix_foods_name ON foods (name);
CREATE UNIQUE INDEX ix_ingredients_name ON ingredients (name);
CREATE INDEX ix_injuries_area ON injuries (area);
CREATE INDEX ix_meal_logs_day ON meal_logs (day);
CREATE INDEX ix_meal_logs_logged_at ON meal_logs (logged_at);
CREATE INDEX ix_progress_photos_day ON progress_photos (day);
CREATE UNIQUE INDEX ix_routines_name ON routines (name);
CREATE INDEX ix_water_log_day ON water_log (day);
CREATE INDEX ix_workout_sessions_day ON workout_sessions (day);
