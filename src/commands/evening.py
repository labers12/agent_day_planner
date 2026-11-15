"""Evening review — sends daily summary at 21:30 Tomsk time."""

from __future__ import annotations

import logging

from src.db import fetchall, fetchone, execute
from src.telegram import send_message, send_inline_keyboard
from src.utils import today_tomsk, format_date_russian, get_week_start
from src.config import TELEGRAM_USER_ID

log = logging.getLogger(__name__)


async def send_evening_review():
    """Send evening summary and handle incomplete items. Called at 21:30 Tomsk."""
    today = today_tomsk()
    log.info("Sending evening review for %s", today)

    # ── Gather today's plan ───────────────────────────────
    plan_items = fetchall(
        "SELECT * FROM daily_plan WHERE plan_date = ? ORDER BY start_time",
        (today,),
    )

    if not plan_items:
        await send_message(
            f"🌙 *Итоги дня ({format_date_russian(today)})*\n\n"
            "Сегодня не было сформированного плана.\n"
            "Спокойной ночи! 😴"
        )
        return

    # ── Separate done / not done ──────────────────────────
    done_items = [i for i in plan_items if i["status"] == "done"]
    not_done = [
        i for i in plan_items
        if i["status"] != "done" and i["slot_type"] in ("task", "habit")
    ]
    total_actionable = len([
        i for i in plan_items if i["slot_type"] in ("task", "habit", "university")
    ])
    done_count = len(done_items)

    # ── Format message ────────────────────────────────────
    msg = f"🌙 *Итоги дня — {format_date_russian(today)}*\n\n"

    if total_actionable > 0:
        pct = round(done_count / total_actionable * 100) if total_actionable else 0
        msg += f"📊 Выполнено: *{done_count}/{total_actionable}* ({pct}%)\n\n"

    if done_items:
        msg += "✅ *Сделано:*\n"
        for item in done_items:
            msg += f"  ✅ {item['title']}\n"
        msg += "\n"

    # Auto-reschedule incomplete tasks
    rescheduled = []
    if not_done:
        msg += "❌ *Не выполнено:*\n"
        for item in not_done:
            msg += f"  ❌ {item['title']}\n"

            # Auto-reschedule: find next free day
            if item["slot_type"] == "task" and item.get("reference_id"):
                new_date = _find_next_free_date(today, item.get("reference_id"))
                if new_date:
                    execute(
                        "UPDATE tasks SET scheduled_date = ?, original_date = ?, status = 'moved' "
                        "WHERE id = ?",
                        (new_date, today, item["reference_id"]),
                    )
                    rescheduled.append((item["title"], new_date))
                    msg += f"     ↪️ Перенесено на {format_date_russian(new_date)}\n"

            elif item["slot_type"] == "habit" and item.get("reference_id"):
                # Check if habit norm for the week will be missed
                slot = fetchone(
                    "SELECT * FROM habit_slots WHERE id = ?", (item["reference_id"],)
                )
                if slot:
                    habit_id = slot["habit_id"]
                    week_start = slot["week_start"]
                    # Count done slots this week
                    done_this_week = fetchone(
                        "SELECT COUNT(*) as cnt FROM habit_slots "
                        "WHERE habit_id = ? AND week_start = ? AND status = 'done'",
                        (habit_id, week_start),
                    )
                    remaining = fetchone(
                        "SELECT COUNT(*) as cnt FROM habit_slots "
                        "WHERE habit_id = ? AND week_start = ? AND status = 'pending' AND scheduled_date > ?",
                        (habit_id, week_start, today),
                    )
                    habit = fetchone("SELECT * FROM habits WHERE id = ?", (habit_id,))
                    if habit and remaining:
                        done_cnt = done_this_week["cnt"] if done_this_week else 0
                        rem_cnt = remaining["cnt"] if remaining else 0
                        target = habit["times_per_week"]
                        if done_cnt + rem_cnt < target:
                            # Need to add extra slot
                            new_date = _find_next_free_date(today)
                            if new_date:
                                execute(
                                    "INSERT INTO habit_slots (habit_id, week_start, scheduled_date, "
                                    "scheduled_start, scheduled_end, status) "
                                    "VALUES (?, ?, ?, ?, ?, 'pending')",
                                    (habit_id, week_start, new_date,
                                     slot.get("scheduled_start", "18:00"),
                                     slot.get("scheduled_end", "19:30")),
                                )
                                msg += f"     ↪️ Доп. слот добавлен на {format_date_russian(new_date)}\n"

                    execute(
                        "UPDATE habit_slots SET status = 'skipped' WHERE id = ?",
                        (item["reference_id"],),
                    )
        msg += "\n"

    # ── Completion prompt if there are undone items ───────
    undone_buttons = []
    for item in not_done:
        undone_buttons.append([
            {"text": f"✅ Всё-таки сделал: {item['title'][:30]}", "callback_data": f"plan_done_{item['id']}"}
        ])

    # ── Statistics ────────────────────────────────────────
    daily_status = fetchone(
        "SELECT * FROM daily_status WHERE status_date = ?", (today,)
    )
    if daily_status:
        energy = {"high": "🔋 Высокий", "normal": "😐 Норм", "low": "🪫 На нуле"}.get(
            daily_status.get("energy_level", ""), ""
        )
        if energy:
            msg += f"Энергия сегодня: {energy}\n"

    msg += "\nСпокойной ночи! 😴💤"

    if undone_buttons:
        await send_inline_keyboard(msg, undone_buttons)
    else:
        await send_message(msg)

    log.info("Evening review sent for %s", today)


def _find_next_free_date(after_date: str, task_id: int | None = None) -> str | None:
    """Find the next date with fewer planned items (simple heuristic)."""
    from datetime import datetime, timedelta
    from src.utils import TOMSK_TZ

    base = datetime.strptime(after_date, "%Y-%m-%d")
    for offset in range(1, 8):
        candidate = (base + timedelta(days=offset)).strftime("%Y-%m-%d")
        count = fetchone(
            "SELECT COUNT(*) as cnt FROM daily_plan WHERE plan_date = ?",
            (candidate,),
        )
        n = count["cnt"] if count else 0
        if n < 6:  # Day is not too packed
            # Check deadline
            if task_id:
                task = fetchone("SELECT deadline FROM tasks WHERE id = ?", (task_id,))
                if task and task.get("deadline") and candidate > task["deadline"]:
                    continue  # Would miss deadline
            return candidate
    return None
