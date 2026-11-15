-- Day Planner Bot — Database Schema (Turso / SQLite)

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT UNIQUE NOT NULL,
    display_name TEXT,
    wake_time TEXT DEFAULT '07:00',
    sleep_time TEXT DEFAULT '23:00',
    prep_before_exit_min INTEGER DEFAULT 30,
    onboarding_complete INTEGER DEFAULT 0,
    onboarding_step INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    travel_minutes_one_way INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS university_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week INTEGER NOT NULL,        -- 0=Mon .. 6=Sun
    week_parity TEXT DEFAULT 'any',      -- 'odd', 'even', 'any'
    start_time TEXT NOT NULL,            -- HH:MM
    end_time TEXT NOT NULL,              -- HH:MM
    subject TEXT NOT NULL,
    lecture_type TEXT,                    -- лекция, практика, лаб. работа, семинар
    building TEXT,
    room TEXT,
    teacher TEXT,
    cached_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    deadline TEXT,                        -- YYYY-MM-DD
    estimated_hours REAL DEFAULT 1.0,
    cognitive_load INTEGER DEFAULT 3,    -- 1 (бытовуха) .. 5 (тяжёлая учёба/код)
    status TEXT DEFAULT 'pending',       -- pending, scheduled, done, moved
    scheduled_date TEXT,                 -- YYYY-MM-DD
    scheduled_start TEXT,                -- HH:MM
    scheduled_end TEXT,                  -- HH:MM
    original_date TEXT,                  -- for tracking when task was moved
    location_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    times_per_week INTEGER DEFAULT 3,
    duration_minutes INTEGER DEFAULT 60,
    location_name TEXT,
    cognitive_load INTEGER DEFAULT 2,
    physical_load INTEGER DEFAULT 3,
    preferred_time TEXT DEFAULT 'evening',  -- morning, afternoon, evening
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS habit_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER NOT NULL REFERENCES habits(id),
    week_start TEXT NOT NULL,             -- YYYY-MM-DD (Monday)
    scheduled_date TEXT NOT NULL,         -- YYYY-MM-DD
    scheduled_start TEXT,                 -- HH:MM
    scheduled_end TEXT,                   -- HH:MM
    status TEXT DEFAULT 'pending',        -- pending, done, skipped, moved
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date TEXT NOT NULL,              -- YYYY-MM-DD
    slot_type TEXT NOT NULL,              -- university, task, habit, commute, buffer
    reference_id INTEGER,                -- FK to tasks/habits/habit_slots depending on slot_type
    title TEXT NOT NULL,
    start_time TEXT NOT NULL,             -- HH:MM
    end_time TEXT NOT NULL,               -- HH:MM
    cognitive_cost INTEGER DEFAULT 0,
    physical_cost INTEGER DEFAULT 0,
    notes TEXT,
    status TEXT DEFAULT 'planned',        -- planned, done, skipped
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status_date TEXT UNIQUE NOT NULL,     -- YYYY-MM-DD
    energy_level TEXT DEFAULT 'normal',   -- high, normal, low
    mental_budget INTEGER DEFAULT 70,
    physical_budget INTEGER DEFAULT 70,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_type TEXT NOT NULL,           -- location_travel, clarify_task, etc.
    context_json TEXT,                     -- JSON with additional context
    asked_at TEXT DEFAULT (datetime('now')),
    answered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,                    -- user, assistant
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indices for performance
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON tasks(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_habit_slots_week ON habit_slots(week_start);
CREATE INDEX IF NOT EXISTS idx_habit_slots_date ON habit_slots(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_daily_plan_date ON daily_plan(plan_date);
CREATE INDEX IF NOT EXISTS idx_daily_status_date ON daily_status(status_date);
CREATE INDEX IF NOT EXISTS idx_university_day ON university_schedule(day_of_week);
