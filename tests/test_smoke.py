"""Smoke test — verify schema initialization, models, and utility calculations."""

import os
import sys
import unittest

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Use in-memory SQLite for testing
os.environ["TURSO_DATABASE_URL"] = ":memory:"
os.environ["TURSO_AUTH_TOKEN"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:dummy_token"
os.environ["TELEGRAM_USER_ID"] = "999999"
os.environ["GEMINI_API_KEY"] = "dummy_gemini_key"

from src.db import init_db, fetchone, fetchall, execute
from src.models import Task, Habit, UserProfile, UniversityClass
from src.utils import (
    now_tomsk,
    today_tomsk,
    time_slot_overlaps,
    add_minutes_to_time,
    find_free_slots,
    format_date_russian,
    cognitive_load_emoji,
)
from src.tsu_parser import seed_default_schedule_if_empty, get_cached_schedule, determine_week_parity


class SmokeTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_schema_tables_exist(self):
        tables = fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [t["name"] for t in tables]
        required = [
            "user_profile",
            "locations",
            "university_schedule",
            "tasks",
            "habits",
            "habit_slots",
            "daily_plan",
            "daily_status",
            "bot_state",
            "pending_questions",
        ]
        for req in required:
            self.assertIn(req, table_names, f"Table {req} missing in database schema")

    def test_seed_sample_schedule(self):
        seeded = seed_default_schedule_if_empty()
        self.assertGreaterEqual(seeded, 1, "Default schedule was not seeded")
        schedule = get_cached_schedule()
        self.assertGreaterEqual(len(schedule), 5, "Cached schedule has too few classes")

    def test_models_serialization(self):
        task = Task(
            title="Лаба по Си",
            description="Сделать до пятницы",
            deadline="2026-11-20",
            estimated_hours=3.0,
            cognitive_load=4,
        )
        d = task.to_dict()
        self.assertEqual(d["title"], "Лаба по Си")
        self.assertEqual(d["cognitive_load"], 4)

        reconstructed = Task.from_row(d)
        self.assertEqual(reconstructed.title, "Лаба по Си")

    def test_utils_tomsk_time(self):
        now = now_tomsk()
        self.assertEqual(now.tzinfo.utcoffset(now).total_seconds(), 7 * 3600)
        today = today_tomsk()
        self.assertRegex(today, r"^\d{4}-\d{2}-\d{2}$")

    def test_utils_slot_logic(self):
        self.assertTrue(time_slot_overlaps("09:00", "10:30", "10:00", "11:30"))
        self.assertFalse(time_slot_overlaps("09:00", "10:00", "10:00", "11:00"))
        self.assertEqual(add_minutes_to_time("09:30", 45), "10:15")

        busy = [{"start_time": "10:00", "end_time": "12:00"}]
        free = find_free_slots(busy, day_start="09:00", day_end="14:00", min_duration_minutes=30)
        self.assertEqual(len(free), 2)
        self.assertEqual(free[0]["start_time"], "09:00")
        self.assertEqual(free[0]["end_time"], "10:00")
        self.assertEqual(free[1]["start_time"], "12:00")
        self.assertEqual(free[1]["end_time"], "14:00")

    def test_week_parity(self):
        parity = determine_week_parity()
        self.assertIn(parity, ["odd", "even"])

    def test_list_parameters_converted_to_tuple(self):
        # Must accept list parameters without raising TypeError
        res = fetchall("SELECT * FROM university_schedule WHERE day_of_week = ?", [0])
        self.assertIsInstance(res, list)
        res2 = fetchall("SELECT * FROM university_schedule WHERE day_of_week = ? AND week_parity = ?", [0, "any"])
        self.assertIsInstance(res2, list)



if __name__ == "__main__":
    unittest.main()
