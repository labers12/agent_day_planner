"""Аудитор ресурса — считает ментальный и физический бюджет на день."""

from __future__ import annotations

import logging

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Ты — агент-аудитор когнитивного и физического ресурса в системе ИИ-планировщика дня.
Твоя задача — рассчитать, сколько ментальной и физической энергии доступно пользователю
на сегодня, и проверить, не перегружен ли план.

## Базовые бюджеты (максимум за день)
- Ментальный бюджет: 100 единиц
- Физический бюджет: 100 единиц

## Модификаторы на основе утреннего статуса
- «Ресурс: Высокий» (high)  → ментальный × 1.0, физический × 1.0
- «Норм» (normal)           → ментальный × 0.75, физический × 0.8
- «На нуле» (low)           → ментальный × 0.45, физический × 0.5

## Расход на университетские пары
- Лекция: 10 ментальных, 2 физических
- Практика/семинар: 15 ментальных, 3 физических
- Лабораторная: 18 ментальных, 3 физических

## Расход на задачи (за час работы)
cognitive_load × 4 ментальных единиц за час

## Расход на физическую активность
physical_load × 5 физических единиц за занятие
Но! Физическая активность РАЗГРУЖАЕТ голову: после зала ментальный бюджет восстанавливается
на 5 единиц (но нельзя ставить тяжёлую умственную работу сразу после зала — нужен буфер 1-2 часа).

## Критическое правило
Если оставшегося ментального бюджета < 15 — СТОП. Не добавлять задачи с cognitive_load > 2.
Если оставшегося физического бюджета < 10 — СТОП. Не добавлять физические активности.

## Формат ответа — строго JSON:
{
  "mental_budget": 67,
  "physical_budget": 72,
  "mental_spent": 33,
  "physical_spent": 28,
  "max_cognitive_load_remaining": 3,
  "recommendations": ["После 3 пар подряд нужен перерыв минимум 30 мин", "..."]
}
"""

_OVERLOAD_PROMPT = """\
Ты — агент-аудитор перегрузки. Проверь, не превышает ли план дня доступный бюджет.

## Правила
1. Посчитай суммарный cognitive_cost и physical_cost всех запланированных элементов.
2. Сравни с доступным бюджетом.
3. Если план перегружен — выбери, какие задачи ПЕРЕНЕСТИ на другой день.
   Приоритеты для переноса (переносить в первую очередь):
   - Задачи без близкого дедлайна
   - Задачи с cognitive_load ≤ 3 (их легче вставить в другой день)
   - НЕ переносить: привычки (зал) если они критичны для нормы недели
   - НЕ переносить: задачи с дедлайном сегодня-завтра

## Формат ответа — JSON:
{
  "is_overloaded": true,
  "total_cognitive_cost": 85,
  "total_physical_cost": 40,
  "budget_mental": 67,
  "budget_physical": 72,
  "items_to_defer": [
    {"reference_id": 5, "title": "...", "reason": "дедлайн через неделю, перенесём на среду"}
  ],
  "explanation": "Сегодня 4 пары + лаба — голова не потянет ещё и курсовую. Перенёс на среду."
}
"""


class AuditorAgent(BaseAgent):
    """Calculates daily mental & physical budgets and detects overload."""

    def __init__(self):
        super().__init__(_SYSTEM_PROMPT)

    def calculate_daily_budget(
        self,
        energy_level: str,
        university_classes: list[dict],
        existing_commitments: list[dict] | None = None,
    ) -> dict:
        """Calculate remaining mental and physical budget for the day.

        *energy_level*: 'high', 'normal', 'low'
        *university_classes*: today's uni schedule
        *existing_commitments*: already-scheduled tasks/habits
        """
        prompt = (
            f"Уровень энергии пользователя сегодня: {energy_level}\n\n"
            f"Пары в ТГУ сегодня:\n{_format_classes(university_classes)}\n\n"
        )
        if existing_commitments:
            prompt += f"Уже запланировано:\n{_format_items(existing_commitments)}\n"

        return self.ask(prompt, expect_json=True)

    def check_overload(self, planned_items: list[dict], budget: dict) -> dict:
        """Check if the planned items exceed the available budget."""
        agent = BaseAgent(_OVERLOAD_PROMPT)
        prompt = (
            f"Доступный бюджет:\n"
            f"- Ментальный: {budget.get('mental_budget', 70)}\n"
            f"- Физический: {budget.get('physical_budget', 70)}\n\n"
            f"Запланированные элементы:\n{_format_items(planned_items)}\n"
        )
        return agent.ask(prompt, expect_json=True)


def _format_classes(classes: list[dict]) -> str:
    if not classes:
        return "Пар нет"
    lines = []
    for c in classes:
        lines.append(
            f"  {c.get('start_time', '?')}-{c.get('end_time', '?')} "
            f"{c.get('subject', '?')} ({c.get('lecture_type', '?')})"
        )
    return "\n".join(lines)


def _format_items(items: list[dict]) -> str:
    if not items:
        return "Ничего"
    lines = []
    for it in items:
        lines.append(
            f"  [{it.get('slot_type', it.get('type', '?'))}] "
            f"{it.get('start_time', '?')}-{it.get('end_time', '?')} "
            f"{it.get('title', '?')} "
            f"(cog={it.get('cognitive_cost', it.get('cognitive_load', '?'))}, "
            f"phys={it.get('physical_cost', it.get('physical_load', '?'))})"
        )
    return "\n".join(lines)
