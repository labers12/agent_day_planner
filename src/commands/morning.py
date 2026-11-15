"""Morning brief — sends daily plan at 08:00 Tomsk time."""

from __future__ import annotations

import logging

from src.db import fetchone, fetchall, execute
from src.telegram import send_message, send_inline_keyboard
from src.tsu_parser import get_todays_schedule
from src.agents import AuditorAgent, PlannerAgent
from src.utils import today_tomsk, format_date_russian, get_week_start
from src.config import TELEGRAM_USER_ID

log = logging.getLogger(__name__)


async def send_morning_brief():
    """Generate and send the morning plan. Called at 08:00 Tomsk."""
    today = today_tomsk()
    log.info("Generating morning brief for %s", today)

    # Ensure habit slots exist for current week
    _ensure_weekly_habits(today)

    # ── Gather data ───────────────────────────────────────
    classes = get_todays_schedule()
    tasks = fetchall(
        "SELECT * FROM tasks WHERE status IN ('pending', 'moved') "
        "AND (scheduled_date = ? OR scheduled_date IS NULL) ORDER BY deadline",
        (today,),
    )
    habit_slots = fetchall(
        "SELECT hs.*, h.title, h.duration_minutes, h.location_name, "
        "h.cognitive_load, h.physical_load, h.preferred_time "
        "FROM habit_slots hs JOIN habits h ON hs.habit_id = h.id "
        "WHERE hs.scheduled_date = ? AND hs.status = 'pending'",
        (today,),
    )
    profile = fetchone(
        "SELECT * FROM user_profile WHERE telegram_id = ?",
        (str(TELEGRAM_USER_ID),),
    ) or {"wake_time": "07:00", "sleep_time": "23:00", "prep_before_exit_min": 30}

    locations_rows = fetchall("SELECT name, travel_minutes_one_way FROM locations")
    locations = {r["name"]: r["travel_minutes_one_way"] for r in locations_rows}

    # ── Preliminary plan (assume normal energy) ───────────
    auditor = AuditorAgent()
    budget = auditor.calculate_daily_budget("normal", classes)

    planner = PlannerAgent()
    plan_data = planner.generate_daily_plan(
        date=today,
        university_schedule=classes,
        tasks=tasks,
        habits_to_schedule=habit_slots,
        budget=budget,
        user_profile=profile,
        locations=locations,
    )

    # ── Save preliminary plan ─────────────────────────────
    execute("DELETE FROM daily_plan WHERE plan_date = ?", (today,))
    plan_items = plan_data.get("plan", [])
    for item in plan_items:
        execute(
            "INSERT INTO daily_plan "
            "(plan_date, slot_type, reference_id, title, start_time, end_time, "
            "cognitive_cost, physical_cost, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                today,
                item.get("slot_type", "task"),
                item.get("reference_id"),
                item.get("title", "?"),
                item.get("start_time", "?"),
                item.get("end_time", "?"),
                item.get("cognitive_cost", 0),
                item.get("physical_cost", 0),
                item.get("notes", ""),
            ),
        )

    # ── Format message ────────────────────────────────────
    msg = f"☀️ *Доброе утро! План на {format_date_russian(today)}:*\n\n"

    if classes:
        msg += "🏫 *Пары:*\n"
        for c in classes:
            msg += f"  {c['start_time']}-{c['end_time']} — {c.get('subject', '?')}"
            if c.get("lecture_type"):
                msg += f" ({c['lecture_type']})"
            if c.get("room"):
                msg += f", ауд. {c['room']}"
            msg += "\n"
        msg += "\n"

    # Show plan items (non-university)
    non_uni = [i for i in plan_items if i.get("slot_type") != "university"]
    if non_uni:
        msg += "📝 *Запланировано:*\n"
        for item in non_uni:
            icon = _slot_icon(item.get("slot_type", "task"))
            msg += f"  {icon} {item.get('start_time', '?')}-{item.get('end_time', '?')} — {item.get('title', '?')}\n"
        msg += "\n"

    # Deferred tasks
    deferred = plan_data.get("deferred_tasks", [])
    if deferred:
        msg += "📤 *Перенесено (не влезает):*\n"
        for d in deferred:
            msg += f"  ↪️ {d.get('title', '?')} → {d.get('suggested_date', '?')}"
            if d.get("reason"):
                msg += f"\n     _{d['reason']}_"
            msg += "\n"
        # Handle deferred in DB
        for d in deferred:
            tid = d.get("task_id")
            if tid:
                execute(
                    "UPDATE tasks SET scheduled_date = ?, status = 'moved', original_date = ? WHERE id = ?",
                    (d.get("suggested_date"), today, tid),
                )
        msg += "\n"

    # Warnings
    if plan_data.get("warnings"):
        msg += "⚠️ *Внимание:*\n"
        for w in plan_data["warnings"]:
            msg += f"  • {w}\n"
        msg += "\n"

    # Summary
    summary = plan_data.get("summary", "")
    if summary:
        msg += f"💡 {summary}\n\n"

    msg += "Как ты себя чувствуешь? Это поможет адаптировать план:"

    # ── Send with energy buttons ──────────────────────────
    buttons = [[
        {"text": "🔋 Высокий", "callback_data": "energy_high"},
        {"text": "😐 Норм", "callback_data": "energy_normal"},
        {"text": "🪫 На нуле", "callback_data": "energy_low"},
    ]]
    await send_inline_keyboard(msg, buttons)
    log.info("Morning brief sent for %s", today)


def _ensure_weekly_habits(today: str):
    """Make sure habit slots are generated for the current week."""
    week_start = get_week_start(today)
    existing = fetchone(
        "SELECT id FROM habit_slots WHERE week_start = ? LIMIT 1",
        (week_start,),
    )
    if existing:
        return  # Already generated

    habits = fetchall("SELECT * FROM habits WHERE active = 1")
    if not habits:
        return

    from src.tsu_parser import get_week_schedule
    from src.utils import get_week_dates

    uni_schedule = get_week_schedule()
    profile = fetchone(
        "SELECT * FROM user_profile WHERE telegram_id = ?",
        (str(TELEGRAM_USER_ID),),
    ) or {}
    locations_rows = fetchall("SELECT name, travel_minutes_one_way FROM locations")
    locations = {r["name"]: r["travel_minutes_one_way"] for r in locations_rows}

    try:
        planner = PlannerAgent()
        slots = planner.generate_weekly_habit_slots(
            habits=habits,
            week_start=week_start,
            university_schedule=uni_schedule,
            user_profile=profile,
            locations=locations,
        )

        for slot in slots:
            execute(
                "INSERT INTO habit_slots (habit_id, week_start, scheduled_date, "
                "scheduled_start, scheduled_end) VALUES (?, ?, ?, ?, ?)",
                (
                    slot.get("habit_id"),
                    week_start,
                    slot.get("date"),
                    slot.get("start_time"),
                    slot.get("end_time"),
                ),
            )
        log.info("Generated %d habit slots for week %s", len(slots), week_start)
    except Exception as e:
        log.error("Failed to generate weekly habit slots: %s", e)
        # Fallback: distribute evenly without AI
        _fallback_habit_distribution(habits, week_start)


def _fallback_habit_distribution(habits: list[dict], week_start: str):
    """Simple fallback: evenly distribute habits across weekdays."""
    from src.utils import get_week_dates

    dates = get_week_dates(week_start)
    for habit in habits:
        times = habit.get("times_per_week", 3)
        # Pick evenly spaced days (prefer Mon/Wed/Fri for 3x)
        if times >= 6:
            days = list(range(6))
        elif times == 5:
            days = [0, 1, 2, 3, 4]
        elif times == 4:
            days = [0, 1, 3, 4]
        elif times == 3:
            days = [0, 2, 4]
        elif times == 2:
            days = [1, 3]
        else:
            days = [2]

        pref = habit.get("preferred_time", "evening")
        start = {"morning": "09:00", "afternoon": "14:00", "evening": "18:00"}.get(pref, "18:00")
        dur = habit.get("duration_minutes", 60)
        end_h = int(start[:2]) + dur // 60
        end_m = int(start[3:]) + dur % 60
        if end_m >= 60:
            end_h += 1
            end_m -= 60
        end = f"{end_h:02d}:{end_m:02d}"

        for day_idx in days:
            if day_idx < len(dates):
                execute(
                    "INSERT INTO habit_slots (habit_id, week_start, scheduled_date, "
                    "scheduled_start, scheduled_end) VALUES (?, ?, ?, ?, ?)",
                    (habit["id"], week_start, dates[day_idx], start, end),
                )


def _slot_icon(slot_type: str) -> str:
    return {
        "university": "🏫",
        "task": "📝",
        "habit": "🏋️",
        "commute": "🚶",
        "buffer": "☕",
    }.get(slot_type, "▫️")
