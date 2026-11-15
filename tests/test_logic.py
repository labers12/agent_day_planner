"""Logic test — verify onboarding transitions, free slot calculation, and command routing."""

import os
import sys
import unittest
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["TURSO_DATABASE_URL"] = ":memory:"
os.environ["TURSO_AUTH_TOKEN"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:dummy_token"
os.environ["TELEGRAM_USER_ID"] = "424242"
os.environ["GEMINI_API_KEY"] = "dummy_gemini_key"

from src.db import init_db, fetchone, fetchall, execute
from src.onboarding import (
    check_onboarding_needed,
    start_onboarding,
    get_current_onboarding_step,
    process_onboarding_answer,
)
from src.tsu_parser import seed_default_schedule_if_empty, get_todays_schedule
from src.utils import (
    find_free_slots,
    add_minutes_to_time,
    subtract_minutes_from_time,
    minutes_between,
)


class LogicTestSuite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db()

    async def test_onboarding_state_machine(self):
        # 1. Initially onboarding is needed
        needed = await check_onboarding_needed()
        self.assertTrue(needed)

        # 2. Start onboarding
        # Patch send_message to avoid network
        from unittest.mock import patch
        with patch("src.onboarding.send_message") as mock_send:
            await start_onboarding()
            mock_send.assert_called_once()

            step = await get_current_onboarding_step()
            self.assertEqual(step, 1)

            # Step 1: commute to TSU (25 min)
            done = await process_onboarding_answer(1, "25 минут")
            self.assertFalse(done)
            step = await get_current_onboarding_step()
            self.assertEqual(step, 2)

            # Verify location was saved
            loc = fetchone("SELECT * FROM locations WHERE name = ?", ("ТГУ главный корпус",))
            self.assertIsNotNone(loc)
            self.assertEqual(loc["travel_minutes_one_way"], 25)

            # Step 2: prep before exit (35 min)
            done = await process_onboarding_answer(2, "35")
            self.assertFalse(done)
            step = await get_current_onboarding_step()
            self.assertEqual(step, 3)

            # Step 3: sleep time (23:30)
            done = await process_onboarding_answer(3, "23:30")
            self.assertFalse(done)
            step = await get_current_onboarding_step()
            self.assertEqual(step, 4)

            # Step 4: wake time (07:30)
            done = await process_onboarding_answer(4, "07:30")
            self.assertTrue(done)
            step = await get_current_onboarding_step()
            self.assertEqual(step, 0)

            # Profile should now be marked complete
            needed_after = await check_onboarding_needed()
            self.assertFalse(needed_after)

            profile = fetchone("SELECT * FROM user_profile WHERE telegram_id = '424242'")
            self.assertEqual(profile["wake_time"], "07:30")
            self.assertEqual(profile["sleep_time"], "23:30")
            self.assertEqual(profile["prep_before_exit_min"], 35)

    def test_buffer_slot_calculations(self):
        # Activity at gym: 18:00 - 19:30
        # Travel time: 20 min one-way
        # Buffer after gym: 15 min shower
        travel_min = 20
        event_start = "18:00"
        event_end = "19:30"
        shower_buffer = 15

        commute_there_start = subtract_minutes_from_time(event_start, travel_min)
        self.assertEqual(commute_there_start, "17:40")

        shower_end = add_minutes_to_time(event_end, shower_buffer)
        self.assertEqual(shower_end, "19:45")

        commute_back_end = add_minutes_to_time(shower_end, travel_min)
        self.assertEqual(commute_back_end, "20:05")

        total_blocked = minutes_between(commute_there_start, commute_back_end)
        self.assertEqual(total_blocked, 20 + 90 + 15 + 20)  # 145 min


if __name__ == "__main__":
    unittest.main()
