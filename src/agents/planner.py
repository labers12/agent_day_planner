"""Планировщик — генерирует оптимальный план дня и распределяет задачи по неделе."""

from __future__ import annotations

import json
import logging

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Ты — агент-планировщик в системе ИИ-планировщика дня для студента ТГУ в Томске.
Твоя задача — составить оптимальный план дня, распределив задачи и привычки в свободные слоты.

## Жёсткие правила планирования

1. **Расписание пар — неподвижный каркас.** Пары нельзя двигать. Задачи ставятся ТОЛЬКО в свободные окна.

2. **Буферы на дорогу.** Если задача/привычка привязана к локации:
   - ДО события: слот «🚶 Дорога до [место]» длительностью travel_minutes
   - ПОСЛЕ события: слот «🚶 Дорога обратно» длительностью travel_minutes
   - После физической активности (зал): +15 мин буфер «🚿 Душ/отдых»
   Во время дороги и буферов НЕЛЬЗЯ ставить другие задачи.

3. **Когнитивная нагрузка:**
   - Утро (до 12:00): идеально для тяжёлых когнитивных задач (4-5)
   - День (12:00-17:00): средние задачи (2-3)
   - Вечер (после 17:00): лёгкие задачи (1-2) или физическая активность
   - ПОСЛЕ зала (1.5-2 часа): только бытовуха (cognitive_load ≤ 2)

4. **Перерывы:**
   - Между задачами: минимум 10 мин
   - После 2+ часов непрерывной умственной работы: 20 мин перерыв
   - Между парами (если есть перерыв): 10-15 мин

5. **Не пихать невпихуемое!**
   Если задач больше, чем бюджет позволяет — переноси менее срочные на другие дни.
   Объясни почему. Дедлайны КРИТИЧНЫ — задачи с дедлайном сегодня-завтра не переносить.

6. **Регулярные привычки:** если привычка запланирована на сегодня — она приоритетнее
   несрочных задач (важно для здоровья и антивыгорания).

7. **Сон:** не планировать ничего за 30 мин до sleep_time пользователя.

## Формат ответа — строго JSON:
{
  "plan": [
    {
      "slot_type": "university|task|habit|commute|buffer",
      "reference_id": null,
      "title": "📚 Матанализ (лекция)",
      "start_time": "09:00",
      "end_time": "10:30",
      "cognitive_cost": 10,
      "physical_cost": 2,
      "notes": ""
    }
  ],
  "deferred_tasks": [
    {
      "task_id": 5,
      "title": "Курсовая",
      "reason": "Сегодня 4 пары — ментальный бюджет исчерпан",
      "suggested_date": "2024-12-04"
    }
  ],
  "warnings": ["Дедлайн по лабе завтра — обязательно закрыть!"],
  "summary": "📋 Плотный день: 3 пары + лаба. Зал перенёс на среду, чтобы не умереть."
}
"""

_WEEKLY_PROMPT = """\
Ты — агент-планировщик. Распредели сеансы регулярных привычек по дням недели.

## Правила
1. Привычки не должны конфликтовать с парами.
2. Распределяй равномерно (не 3 тренировки подряд).
3. Учитывай preferred_time привычки (morning/afternoon/evening).
4. Оставляй дни «полегче» — не ставь зал в дни с 4+ парами.
5. Учитывай время на дорогу до/от локации привычки.

## Формат ответа — JSON:
{
  "slots": [
    {
      "habit_id": 1,
      "habit_title": "Зал",
      "date": "2024-12-02",
      "day_name": "понедельник",
      "start_time": "18:00",
      "end_time": "19:30",
      "reason": "Вечер свободен, всего 2 пары"
    }
  ]
}
"""

_RESCHEDULE_PROMPT = """\
Ты — агент-планировщик. Пользователь просит перенести задачу/привычку.
Найди новый подходящий слот, учитывая:
1. Дедлайн задачи (если есть)
2. Свободные слоты на ближайшие дни
3. Нагрузку в те дни
4. Если это привычка — норму за неделю нужно сохранить

Формат ответа — JSON:
{
  "new_date": "2024-12-04",
  "new_start": "18:00",
  "new_end": "19:30",
  "explanation": "Перенёс зал на среду — там всего 2 пары и вечер свободен."
}
"""


class PlannerAgent(BaseAgent):
    """Generates optimal daily plans and distributes tasks across the week."""

    def __init__(self):
        super().__init__(_SYSTEM_PROMPT)

    def generate_daily_plan(
        self,
        date: str,
        university_schedule: list[dict],
        tasks: list[dict],
        habits_to_schedule: list[dict],
        budget: dict,
        user_profile: dict,
        locations: dict[str, int],
    ) -> dict:
        """Generate an optimized plan for a specific date."""
        prompt = (
            f"Дата: {date}\n\n"
            f"Профиль пользователя:\n"
            f"  Подъём: {user_profile.get('wake_time', '07:00')}\n"
            f"  Сон: {user_profile.get('sleep_time', '23:00')}\n"
            f"  Подготовка к выходу: {user_profile.get('prep_before_exit_min', 30)} мин\n\n"
            f"Ментальный бюджет: {budget.get('mental_budget', 70)}\n"
            f"Физический бюджет: {budget.get('physical_budget', 70)}\n\n"
            f"Пары ТГУ:\n{_fmt_classes(university_schedule)}\n\n"
            f"Задачи для планирования:\n{_fmt_tasks(tasks)}\n\n"
            f"Привычки на сегодня:\n{_fmt_habits(habits_to_schedule)}\n\n"
            f"Известные локации (название → минуты в одну сторону):\n{json.dumps(locations, ensure_ascii=False)}\n"
        )
        return self.ask(prompt, expect_json=True)

    def reschedule_task(
        self,
        task: dict,
        week_free_slots: dict,
        reason: str,
    ) -> dict:
        """Find a new slot for a deferred or moved task."""
        agent = BaseAgent(_RESCHEDULE_PROMPT)
        prompt = (
            f"Задача для переноса:\n{json.dumps(task, ensure_ascii=False)}\n\n"
            f"Причина переноса: {reason}\n\n"
            f"Свободные слоты на неделю:\n{json.dumps(week_free_slots, ensure_ascii=False)}\n"
        )
        return agent.ask(prompt, expect_json=True)

    def generate_weekly_habit_slots(
        self,
        habits: list[dict],
        week_start: str,
        university_schedule: dict[int, list[dict]],
        user_profile: dict,
        locations: dict[str, int],
    ) -> list[dict]:
        """Distribute habit sessions across the week."""
        agent = BaseAgent(_WEEKLY_PROMPT)
        prompt = (
            f"Начало недели: {week_start}\n\n"
            f"Привычки:\n{_fmt_habits(habits)}\n\n"
            f"Расписание пар по дням (0=Пн..6=Вс):\n"
        )
        for day, classes in university_schedule.items():
            prompt += f"  День {day}: {_fmt_classes(classes)}\n"
        prompt += (
            f"\nПрофиль:\n"
            f"  Сон: {user_profile.get('sleep_time', '23:00')}\n\n"
            f"Локации (мин в одну сторону):\n{json.dumps(locations, ensure_ascii=False)}\n"
        )
        result = agent.ask(prompt, expect_json=True)
        return result.get("slots", result) if isinstance(result, dict) else result


# ── Formatting helpers ────────────────────────────────────

def _fmt_classes(classes: list[dict]) -> str:
    if not classes:
        return "  Пар нет"
    return "\n".join(
        f"  {c.get('start_time', '?')}-{c.get('end_time', '?')} "
        f"{c.get('subject', '?')} ({c.get('lecture_type', '')})"
        for c in classes
    )


def _fmt_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "  Задач нет"
    return "\n".join(
        f"  [id={t.get('id', '?')}] {t.get('title', '?')} "
        f"(~{t.get('estimated_hours', 1)}ч, cog={t.get('cognitive_load', 3)}, "
        f"дедлайн={t.get('deadline', 'нет')})"
        for t in tasks
    )


def _fmt_habits(habits: list[dict]) -> str:
    if not habits:
        return "  Привычек нет"
    return "\n".join(
        f"  [id={h.get('id', h.get('habit_id', '?'))}] {h.get('title', '?')} "
        f"({h.get('duration_minutes', 60)} мин, "
        f"phys={h.get('physical_load', 3)}, "
        f"место={h.get('location_name', '-')})"
        for h in habits
    )
