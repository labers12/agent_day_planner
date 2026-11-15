"""Poll command — fetches Telegram updates and routes them."""

from __future__ import annotations

import json
import logging

from src.db import get_bot_state, set_bot_state, fetchone, fetchall, execute
from src.telegram import (
    get_updates, send_message, send_inline_keyboard,
    is_authorized, extract_message_text, extract_callback_data,
    get_callback_query_id, answer_callback_query,
)
from src.onboarding import (
    check_onboarding_needed, start_onboarding,
    get_current_onboarding_step, process_onboarding_answer,
    ask_location_travel_time, process_location_answer, get_pending_question,
)
from src.agents import NormalizerAgent, PlannerAgent, AuditorAgent
from src.utils import today_tomsk, format_date_russian, get_week_start

log = logging.getLogger(__name__)


async def poll_and_process():
    """Main entry: poll Telegram and handle each update."""
    offset = int(get_bot_state("telegram_offset") or "0")
    log.info("Requesting updates from Telegram (offset=%d)...", offset)
    updates = await get_updates(offset=offset, timeout=5)
    log.info("Received %d update(s) from Telegram", len(updates))

    for update in updates:
        new_offset = update["update_id"] + 1
        set_bot_state("telegram_offset", str(new_offset))

        if not is_authorized(update):
            continue

        # Callback queries (button presses)
        cb = extract_callback_data(update)
        if cb:
            cq_id = get_callback_query_id(update)
            log.info("Handling callback query: %s", cb)
            await handle_callback(cb, cq_id)
            continue

        # Text messages
        text = extract_message_text(update)
        if text:
            log.info("Handling text message: '%s'", text)
            await handle_message(text)



# ── Message router ────────────────────────────────────────

async def handle_message(text: str):
    """Route incoming text message."""
    text_stripped = text.strip()

    # 1. Check onboarding
    step = await get_current_onboarding_step()
    if step > 0:
        await process_onboarding_answer(step, text_stripped)
        return

    # 2. Check pending location question
    pq = get_pending_question()
    if pq:
        await process_location_answer(pq["id"], text_stripped)
        return

    # 3. Slash commands
    cmd = text_stripped.lower().split()[0] if text_stripped else ""

    if cmd == "/start":
        if await check_onboarding_needed():
            await start_onboarding()
        else:
            await send_message(
                "👋 С возвращением! Напиши задачу, или:\n"
                "/plan — план на сегодня\n"
                "/tasks — список задач\n"
                "/habits — привычки\n"
                "/week — план на неделю"
            )
        return

    if cmd in ("/plan", "/today"):
        await _show_today_plan()
        return

    if cmd == "/week":
        await _show_week_overview()
        return

    if cmd == "/tasks":
        await _show_tasks()
        return

    if cmd == "/habits":
        await _show_habits()
        return

    if cmd.startswith("/done"):
        hint = text_stripped[5:].strip()
        await _mark_done_by_hint(hint)
        return

    if cmd == "/help":
        await send_message(
            "📖 *Команды:*\n"
            "/plan — план на сегодня\n"
            "/week — обзор недели\n"
            "/tasks — активные задачи\n"
            "/habits — привычки\n"
            "/done <описание> — отметить выполнение\n\n"
            "Или просто напиши задачу в свободной форме!"
        )
        return

    # 4. Free-text — use NormalizerAgent
    await _process_free_text(text_stripped)


# ── Callback handler ──────────────────────────────────────

async def handle_callback(callback_data: str, cq_id: str | None):
    """Handle inline keyboard button presses."""
    if cq_id:
        await answer_callback_query(cq_id)

    # Energy check-in
    if callback_data.startswith("energy_"):
        level = callback_data.replace("energy_", "")  # high/normal/low
        await _handle_energy_checkin(level)
        return

    # Task/habit done
    if callback_data.startswith("task_done_"):
        task_id = int(callback_data.replace("task_done_", ""))
        await _mark_task_done(task_id)
        return

    if callback_data.startswith("habit_done_"):
        slot_id = int(callback_data.replace("habit_done_", ""))
        await _mark_habit_done(slot_id)
        return

    if callback_data.startswith("plan_done_"):
        plan_id = int(callback_data.replace("plan_done_", ""))
        execute("UPDATE daily_plan SET status = 'done' WHERE id = ?", (plan_id,))
        await send_message("✅ Отмечено!")
        return

    log.warning("Unknown callback: %s", callback_data)


# ── Free-text processing ─────────────────────────────────

async def _process_free_text(text: str):
    """Use AI to understand and process user message."""
    normalizer = NormalizerAgent()

    # First, determine intent
    intent_data = normalizer.extract_intent(text)
    intent = intent_data.get("intent", "chitchat")

    if intent == "add_task":
        # Get known locations
        locations = [r["name"] for r in fetchall("SELECT name FROM locations")]
        normalized = normalizer.normalize_task(text, known_locations=locations)

        if normalized.get("type") == "habit":
            await _handle_new_habit(normalized)
        else:
            await _handle_new_task(normalized)

    elif intent == "reschedule":
        details = intent_data.get("details", {})
        hint = details.get("task_hint", "")
        await send_message(f"🔄 Ищу задачу по запросу «{hint}»... (в разработке)")

    elif intent == "mark_done":
        details = intent_data.get("details", {})
        hint = details.get("task_hint", "")
        await _mark_done_by_hint(hint)

    elif intent == "show_plan":
        await _show_today_plan()

    elif intent == "show_tasks":
        await _show_tasks()

    elif intent == "show_habits":
        await _show_habits()

    elif intent == "chitchat":
        details = intent_data.get("details", {})
        response = details.get("response_text", "🤖 Я планировщик! Напиши задачу или /help")
        await send_message(response)

    else:
        await send_message("🤔 Не совсем понял. Напиши /help для списка команд.")


# ── Task/Habit creation ──────────────────────────────────

async def _handle_new_task(data: dict):
    """Save a new task from normalized data."""
    execute(
        "INSERT INTO tasks (title, description, deadline, estimated_hours, cognitive_load, location_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            data.get("title", "Задача"),
            data.get("description", ""),
            data.get("deadline"),
            data.get("estimated_hours", 1.0),
            data.get("cognitive_load", 3),
            data.get("location_name"),
        ),
    )

    msg = f"✅ Задача добавлена: *{data.get('title', '?')}*\n"
    if data.get("deadline"):
        msg += f"📅 Дедлайн: {data['deadline']}\n"
    msg += f"⏱ Оценка: {data.get('estimated_hours', 1)}ч\n"
    msg += f"🧠 Сложность: {'🟢🟡🟠🔴💀'[data.get('cognitive_load', 3) - 1]} ({data.get('cognitive_load', 3)}/5)"
    await send_message(msg)

    # Check if new location needs travel time
    if data.get("needs_location_clarification") and data.get("location_name"):
        await ask_location_travel_time(data["location_name"])


async def _handle_new_habit(data: dict):
    """Save a new recurring habit."""
    execute(
        "INSERT INTO habits (title, description, times_per_week, duration_minutes, "
        "location_name, cognitive_load, physical_load, preferred_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data.get("title", "Привычка"),
            data.get("description", ""),
            data.get("times_per_week", 3),
            data.get("duration_minutes", 60),
            data.get("location_name"),
            data.get("cognitive_load", 2),
            data.get("physical_load", 3),
            data.get("preferred_time", "evening"),
        ),
    )

    msg = (
        f"✅ Привычка добавлена: *{data.get('title', '?')}*\n"
        f"📅 {data.get('times_per_week', 3)} раз(а) в неделю\n"
        f"⏱ {data.get('duration_minutes', 60)} мин\n"
        f"🕐 Предпочтительно: {_time_label(data.get('preferred_time', 'evening'))}"
    )
    await send_message(msg)

    # Check location
    if data.get("needs_location_clarification") and data.get("location_name"):
        await ask_location_travel_time(data["location_name"])


# ── Display commands ──────────────────────────────────────

async def _show_today_plan():
    """Show today's plan from the daily_plan table."""
    today = today_tomsk()
    items = fetchall(
        "SELECT * FROM daily_plan WHERE plan_date = ? ORDER BY start_time",
        (today,),
    )
    if not items:
        # Try to show raw schedule + tasks
        from src.tsu_parser import get_todays_schedule
        classes = get_todays_schedule()
        tasks = fetchall(
            "SELECT * FROM tasks WHERE status = 'pending' ORDER BY deadline",
        )
        if not classes and not tasks:
            await send_message(f"📋 План на {format_date_russian(today)}: пока пусто!\nНапиши задачу или дождись утреннего брифинга в 08:00.")
            return

        msg = f"📋 *{format_date_russian(today)}*\n\n"
        if classes:
            msg += "🏫 *Пары:*\n"
            for c in classes:
                msg += f"  {c['start_time']}-{c['end_time']} — {c['subject']}"
                if c.get("lecture_type"):
                    msg += f" ({c['lecture_type']})"
                if c.get("room"):
                    msg += f", ауд. {c['room']}"
                msg += "\n"
        if tasks:
            msg += "\n📝 *Задачи (не распланированы):*\n"
            for t in tasks[:5]:
                msg += f"  ▫️ {t['title']}"
                if t.get("deadline"):
                    msg += f" (до {t['deadline']})"
                msg += "\n"
        msg += "\n_Полный план появится в утреннем брифинге в 08:00_"
        await send_message(msg)
        return

    msg = f"📋 *План на {format_date_russian(today)}:*\n\n"
    for item in items:
        icon = _slot_icon(item["slot_type"])
        status_mark = "✅ " if item["status"] == "done" else ""
        msg += f"{status_mark}{icon} {item['start_time']}-{item['end_time']} — {item['title']}"
        if item.get("notes"):
            msg += f"\n   _{item['notes']}_"
        msg += "\n"
    await send_message(msg)


async def _show_tasks():
    """List all pending tasks."""
    tasks = fetchall(
        "SELECT * FROM tasks WHERE status IN ('pending', 'scheduled') ORDER BY deadline",
    )
    if not tasks:
        await send_message("📝 Нет активных задач. Напиши новую!")
        return

    msg = "📝 *Активные задачи:*\n\n"
    for t in tasks:
        status_icon = "📌" if t["status"] == "pending" else "📅"
        msg += f"{status_icon} *{t['title']}*\n"
        if t.get("deadline"):
            msg += f"   Дедлайн: {t['deadline']}\n"
        msg += f"   ~{t['estimated_hours']}ч, сложность: {t['cognitive_load']}/5\n\n"
    await send_message(msg)


async def _show_habits():
    """List all active habits."""
    habits = fetchall("SELECT * FROM habits WHERE active = 1")
    if not habits:
        await send_message(
            "🔁 Привычек пока нет.\n"
            "Напиши, например: *ходить в зал 3 раза в неделю по 1.5 часа*"
        )
        return

    msg = "🔁 *Привычки:*\n\n"
    for h in habits:
        msg += (
            f"• *{h['title']}* — {h['times_per_week']}×/нед по {h['duration_minutes']} мин"
        )
        if h.get("location_name"):
            msg += f" 📍{h['location_name']}"
        msg += "\n"
    await send_message(msg)


async def _show_week_overview():
    """Brief overview of the week."""
    today = today_tomsk()
    week_start = get_week_start(today)
    from src.utils import get_week_dates, format_date_russian
    dates = get_week_dates(week_start)

    msg = "📅 *Обзор недели:*\n\n"
    for d in dates:
        plan_items = fetchall(
            "SELECT * FROM daily_plan WHERE plan_date = ? ORDER BY start_time", (d,)
        )
        marker = "👈" if d == today else ""
        date_label = format_date_russian(d)
        count = len(plan_items)
        done = sum(1 for p in plan_items if p["status"] == "done")
        if count:
            msg += f"*{date_label}* {marker}\n  📊 {done}/{count} выполнено\n"
        else:
            msg += f"*{date_label}* {marker}\n  — план не сформирован\n"
    await send_message(msg)


# ── Mark done ─────────────────────────────────────────────

async def _mark_done_by_hint(hint: str):
    """Try to find and mark a task as done by keyword."""
    if not hint:
        # Show buttons for today's undone items
        today = today_tomsk()
        items = fetchall(
            "SELECT * FROM daily_plan WHERE plan_date = ? AND status != 'done' "
            "AND slot_type IN ('task', 'habit') ORDER BY start_time",
            (today,),
        )
        if not items:
            tasks = fetchall("SELECT * FROM tasks WHERE status = 'pending' LIMIT 5")
            if tasks:
                buttons = [
                    [{"text": f"✅ {t['title']}", "callback_data": f"task_done_{t['id']}"}]
                    for t in tasks
                ]
                await send_inline_keyboard("Что закрыл?", buttons)
            else:
                await send_message("📝 Нет задач для закрытия.")
            return

        buttons = [
            [{"text": f"✅ {i['title']}", "callback_data": f"plan_done_{i['id']}"}]
            for i in items
        ]
        await send_inline_keyboard("Что закрыл?", buttons)
        return

    # Search by hint
    task = fetchone(
        "SELECT * FROM tasks WHERE status = 'pending' AND title LIKE ? LIMIT 1",
        (f"%{hint}%",),
    )
    if task:
        await _mark_task_done(task["id"])
    else:
        await send_message(f"🤔 Не нашёл задачу «{hint}». Попробуй /done без аргументов.")


async def _mark_task_done(task_id: int):
    execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    task = fetchone("SELECT title FROM tasks WHERE id = ?", (task_id,))
    name = task["title"] if task else "?"
    await send_message(f"✅ *{name}* — выполнено! 🎉")


async def _mark_habit_done(slot_id: int):
    execute("UPDATE habit_slots SET status = 'done' WHERE id = ?", (slot_id,))
    await send_message("✅ Привычка отмечена! 💪")


# ── Energy check-in ──────────────────────────────────────

async def _handle_energy_checkin(level: str):
    """Process energy level callback and regenerate plan."""
    today = today_tomsk()

    # Save daily status
    existing = fetchone("SELECT id FROM daily_status WHERE status_date = ?", (today,))
    if existing:
        execute(
            "UPDATE daily_status SET energy_level = ? WHERE status_date = ?",
            (level, today),
        )
    else:
        execute(
            "INSERT INTO daily_status (status_date, energy_level) VALUES (?, ?)",
            (today, level),
        )

    emoji = {"high": "🔋", "normal": "😐", "low": "🪫"}.get(level, "❓")
    label = {"high": "Высокий", "normal": "Норм", "low": "На нуле"}.get(level, "?")
    await send_message(f"{emoji} Статус: *{label}*. Адаптирую план...")

    # Regenerate plan with this energy level
    await _regenerate_plan(today, level)


async def _regenerate_plan(date: str, energy_level: str):
    """Re-generate daily plan with agents."""
    from src.tsu_parser import get_todays_schedule

    classes = get_todays_schedule()
    tasks = fetchall("SELECT * FROM tasks WHERE status = 'pending' ORDER BY deadline")
    habit_slots = fetchall(
        "SELECT hs.*, h.title, h.duration_minutes, h.location_name, h.cognitive_load, h.physical_load "
        "FROM habit_slots hs JOIN habits h ON hs.habit_id = h.id "
        "WHERE hs.scheduled_date = ? AND hs.status = 'pending'",
        (date,),
    )
    profile = fetchone(
        "SELECT * FROM user_profile WHERE telegram_id = ?", (str(TELEGRAM_USER_ID),)
    ) or {"wake_time": "07:00", "sleep_time": "23:00", "prep_before_exit_min": 30}

    locations_rows = fetchall("SELECT name, travel_minutes_one_way FROM locations")
    locations = {r["name"]: r["travel_minutes_one_way"] for r in locations_rows}

    # 1. Auditor calculates budget
    auditor = AuditorAgent()
    budget = auditor.calculate_daily_budget(energy_level, classes)

    # 2. Planner generates plan
    planner = PlannerAgent()
    plan_data = planner.generate_daily_plan(
        date=date,
        university_schedule=classes,
        tasks=tasks,
        habits_to_schedule=habit_slots,
        budget=budget,
        user_profile=profile,
        locations=locations,
    )

    # 3. Save plan to DB
    execute("DELETE FROM daily_plan WHERE plan_date = ?", (date,))
    plan_items = plan_data.get("plan", [])
    for item in plan_items:
        execute(
            "INSERT INTO daily_plan "
            "(plan_date, slot_type, reference_id, title, start_time, end_time, "
            "cognitive_cost, physical_cost, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date,
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

    # 4. Handle deferred tasks
    for deferred in plan_data.get("deferred_tasks", []):
        tid = deferred.get("task_id")
        if tid:
            execute(
                "UPDATE tasks SET scheduled_date = ?, original_date = ?, status = 'moved' WHERE id = ?",
                (deferred.get("suggested_date"), date, tid),
            )

    # 5. Save budget to daily_status
    execute(
        "UPDATE daily_status SET mental_budget = ?, physical_budget = ? WHERE status_date = ?",
        (budget.get("mental_budget", 70), budget.get("physical_budget", 70), date),
    )

    # 6. Format and send plan
    msg = f"📋 *План на {format_date_russian(date)}:*\n\n"
    for item in plan_items:
        icon = _slot_icon(item.get("slot_type", "task"))
        msg += f"{icon} {item.get('start_time', '?')}-{item.get('end_time', '?')} — {item.get('title', '?')}\n"

    if plan_data.get("deferred_tasks"):
        msg += "\n📤 *Перенесено:*\n"
        for d in plan_data["deferred_tasks"]:
            msg += f"  ↪️ {d.get('title', '?')} → {d.get('suggested_date', '?')}\n"
            if d.get("reason"):
                msg += f"     _{d['reason']}_\n"

    if plan_data.get("warnings"):
        msg += "\n⚠️ *Внимание:*\n"
        for w in plan_data["warnings"]:
            msg += f"  • {w}\n"

    summary = plan_data.get("summary", "")
    if summary:
        msg += f"\n💡 {summary}"

    await send_message(msg)


from src.config import TELEGRAM_USER_ID  # noqa: E402


# ── Helpers ───────────────────────────────────────────────

def _slot_icon(slot_type: str) -> str:
    return {
        "university": "🏫",
        "task": "📝",
        "habit": "🏋️",
        "commute": "🚶",
        "buffer": "☕",
    }.get(slot_type, "▫️")


def _time_label(pref: str) -> str:
    return {"morning": "утро", "afternoon": "день", "evening": "вечер"}.get(pref, pref)
