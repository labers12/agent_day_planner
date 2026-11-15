"""Онбординг — первоначальная настройка и вопросы о новых локациях."""

from __future__ import annotations

import json
import logging
import re

from src.db import fetchone, execute, fetchall, get_bot_state, set_bot_state
from src.telegram import send_message, send_inline_keyboard
from src.config import TELEGRAM_USER_ID

log = logging.getLogger(__name__)

# ── Onboarding flow ──────────────────────────────────────

ONBOARDING_QUESTIONS = [
    {
        "step": 1,
        "text": (
            "👋 Привет! Я — твой ИИ-планировщик дня с защитой от выгорания.\n\n"
            "Давай быстро настроимся. Сколько *минут* обычно занимает дорога "
            "до главного корпуса ТГУ? (напиши число, например: 25)"
        ),
        "field": "tsu_commute",
    },
    {
        "step": 2,
        "text": (
            "🚶 Отлично! А за сколько *минут* до первой пары ты обычно "
            "выходишь из дома? (например: 40)"
        ),
        "field": "prep_before_exit",
    },
    {
        "step": 3,
        "text": (
            "🌙 Во сколько тебе комфортно *ложиться спать*? "
            "(формат ЧЧ:ММ, например: 23:00)"
        ),
        "field": "sleep_time",
    },
    {
        "step": 4,
        "text": (
            "☀️ Во сколько обычно *просыпаешься*? "
            "(формат ЧЧ:ММ, например: 07:30)"
        ),
        "field": "wake_time",
    },
]


async def check_onboarding_needed() -> bool:
    """Return True if onboarding is not yet complete."""
    profile = fetchone(
        "SELECT onboarding_complete FROM user_profile WHERE telegram_id = ?",
        (str(TELEGRAM_USER_ID),),
    )
    if profile is None:
        return True
    return not bool(profile["onboarding_complete"])


async def start_onboarding():
    """Begin the onboarding questionnaire — create profile & ask Q1."""
    # Upsert user profile
    existing = fetchone(
        "SELECT id FROM user_profile WHERE telegram_id = ?",
        (str(TELEGRAM_USER_ID),),
    )
    if not existing:
        execute(
            "INSERT INTO user_profile (telegram_id, onboarding_step) VALUES (?, 1)",
            (str(TELEGRAM_USER_ID),),
        )
    else:
        execute(
            "UPDATE user_profile SET onboarding_step = 1, onboarding_complete = 0 "
            "WHERE telegram_id = ?",
            (str(TELEGRAM_USER_ID),),
        )
    set_bot_state("onboarding_active", "1")
    await send_message(ONBOARDING_QUESTIONS[0]["text"])


async def get_current_onboarding_step() -> int:
    """Return current onboarding step (1-based), or 0 if done."""
    profile = fetchone(
        "SELECT onboarding_step, onboarding_complete FROM user_profile WHERE telegram_id = ?",
        (str(TELEGRAM_USER_ID),),
    )
    if not profile:
        return 0
    if profile["onboarding_complete"]:
        return 0
    return profile.get("onboarding_step", 0)


async def process_onboarding_answer(step: int, answer: str) -> bool:
    """Process an answer for the given onboarding step.

    Returns True when onboarding is complete.
    """
    answer = answer.strip()

    if step == 1:  # TSU commute minutes
        minutes = _extract_number(answer)
        if minutes is None:
            await send_message("🤔 Напиши число минут, например: 25")
            return False
        # Save location
        _upsert_location("ТГУ главный корпус", minutes)
        execute(
            "UPDATE user_profile SET onboarding_step = 2 WHERE telegram_id = ?",
            (str(TELEGRAM_USER_ID),),
        )

    elif step == 2:  # Prep before exit
        minutes = _extract_number(answer)
        if minutes is None:
            await send_message("🤔 Напиши число минут, например: 40")
            return False
        execute(
            "UPDATE user_profile SET prep_before_exit_min = ?, onboarding_step = 3 "
            "WHERE telegram_id = ?",
            (minutes, str(TELEGRAM_USER_ID)),
        )

    elif step == 3:  # Sleep time
        time_str = _extract_time(answer)
        if not time_str:
            await send_message("🤔 Напиши время в формате ЧЧ:ММ, например: 23:00")
            return False
        execute(
            "UPDATE user_profile SET sleep_time = ?, onboarding_step = 4 "
            "WHERE telegram_id = ?",
            (time_str, str(TELEGRAM_USER_ID)),
        )

    elif step == 4:  # Wake time
        time_str = _extract_time(answer)
        if not time_str:
            await send_message("🤔 Напиши время в формате ЧЧ:ММ, например: 07:30")
            return False
        execute(
            "UPDATE user_profile SET wake_time = ?, onboarding_step = 0, onboarding_complete = 1 "
            "WHERE telegram_id = ?",
            (time_str, str(TELEGRAM_USER_ID)),
        )
        set_bot_state("onboarding_active", "0")
        await send_message(
            "✅ Настройка завершена! Я готов к работе.\n\n"
            "Теперь ты можешь:\n"
            "• Написать мне задачу в свободной форме\n"
            "• Добавить регулярную привычку (например: *ходить в зал 3 раза в неделю*)\n"
            "• Написать /plan — посмотреть план на сегодня\n"
            "• Написать /tasks — список задач\n"
            "• Написать /habits — список привычек\n\n"
            "Каждое утро в 08:00 я пришлю план дня, "
            "а в 21:30 — итоги. 💪"
        )
        return True

    # Send next question
    if step < 4:
        next_q = ONBOARDING_QUESTIONS[step]  # step is 1-based, next is at index=step
        await send_message(next_q["text"])

    return False


# ── Location clarification ───────────────────────────────

async def ask_location_travel_time(location_name: str, context: str = ""):
    """Ask user how long it takes to get to a new location."""
    # Check if already asked
    existing = fetchone(
        "SELECT id FROM pending_questions WHERE question_type = 'location_travel' "
        "AND context_json LIKE ? AND answered = 0",
        (f'%"{location_name}"%',),
    )
    if existing:
        return

    execute(
        "INSERT INTO pending_questions (question_type, context_json) VALUES (?, ?)",
        ("location_travel", json.dumps({"location_name": location_name, "context": context})),
    )
    await send_message(
        f"📍 Новая локация — *{location_name}*.\n"
        f"Сколько минут занимает дорога туда в одну сторону? (напиши число)"
    )


async def process_location_answer(question_id: int, answer: str) -> bool:
    """Process answer about travel time. Returns True on success."""
    minutes = _extract_number(answer)
    if minutes is None:
        await send_message("🤔 Напиши число минут, например: 20")
        return False

    row = fetchone(
        "SELECT context_json FROM pending_questions WHERE id = ?", (question_id,)
    )
    if not row:
        return False

    ctx = json.loads(row["context_json"])
    location_name = ctx["location_name"]

    _upsert_location(location_name, minutes)
    execute(
        "UPDATE pending_questions SET answered = 1 WHERE id = ?", (question_id,)
    )
    await send_message(
        f"✅ Запомнил: дорога до *{location_name}* — {minutes} мин в одну сторону."
    )
    return True


def get_pending_question() -> dict | None:
    """Get the oldest unanswered question, or None."""
    return fetchone(
        "SELECT * FROM pending_questions WHERE answered = 0 ORDER BY id LIMIT 1"
    )


# ── Helpers ───────────────────────────────────────────────

def _extract_number(text: str) -> int | None:
    """Extract first integer from text."""
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _extract_time(text: str) -> str | None:
    """Extract HH:MM from text."""
    m = re.search(r"(\d{1,2})[:\.](\d{2})", text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return f"{h:02d}:{mn:02d}"
    return None


def _upsert_location(name: str, minutes: int):
    """Insert or update a location's travel time."""
    existing = fetchone("SELECT id FROM locations WHERE name = ?", (name,))
    if existing:
        execute(
            "UPDATE locations SET travel_minutes_one_way = ? WHERE name = ?",
            (minutes, name),
        )
    else:
        execute(
            "INSERT INTO locations (name, travel_minutes_one_way) VALUES (?, ?)",
            (name, minutes),
        )
