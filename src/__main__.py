"""CLI entry point for GitHub Actions & local execution.

Usage:
    python -m src <command>

Commands:
    init             Initialize database schema and seed group 932604 schedule
    poll             Fetch and process new Telegram updates
    morning          Send morning daily plan (08:00 Tomsk / 01:00 UTC)
    evening          Send evening review (21:30 Tomsk / 14:30 UTC)
    update-schedule  Fetch and cache latest TSU schedule from web
    seed             Seed/reset schedule from sample_schedule.json
    status           Print local diagnostics and DB state
"""

import asyncio
import logging
import sys

from src.config import check_required_env, TIMEZONE, TSU_GROUP
from src.db import init_db, fetchone, fetchall
from src.tsu_parser import seed_default_schedule_if_empty, update_schedule_cache, import_schedule_json
import json
import pathlib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def cmd_init():
    log.info("Initializing database schema...")
    init_db()
    seeded = seed_default_schedule_if_empty()
    log.info("Database initialized successfully. Default classes seeded: %d", seeded)
    print(f"✅ База данных успешно инициализирована. Загружено занятий: {seeded}")


async def cmd_poll():
    check_required_env()
    init_db()
    seed_default_schedule_if_empty()
    from src.commands.poll import poll_and_process
    log.info("Polling Telegram messages...")
    await poll_and_process()
    log.info("Poll completed.")


async def cmd_morning():
    check_required_env()
    init_db()
    seed_default_schedule_if_empty()
    from src.commands.morning import send_morning_brief
    log.info("Executing morning briefing...")
    await send_morning_brief()
    log.info("Morning briefing sent.")


async def cmd_evening():
    check_required_env()
    init_db()
    seed_default_schedule_if_empty()
    from src.commands.evening import send_evening_review
    log.info("Executing evening review...")
    await send_evening_review()
    log.info("Evening review sent.")


async def cmd_update_schedule():
    init_db()
    log.info("Updating TSU schedule for group %s...", TSU_GROUP)
    success = await update_schedule_cache()
    if not success:
        log.info("Web update failed or unaccessible. Ensuring default schedule is present...")
        seeded = seed_default_schedule_if_empty()
        print(f"⚠️ Парсинг веб-сайта недоступен. Используется кэш / базовое расписание ({seeded} записей).")
    else:
        print(f"✅ Расписание успешно обновлено из сети.")


async def cmd_seed():
    init_db()
    sample_path = pathlib.Path(__file__).resolve().parent / "sample_schedule.json"
    if sample_path.exists():
        data = json.loads(sample_path.read_text(encoding="utf-8"))
        count = import_schedule_json(data)
        print(f"✅ Успешно импортировано {count} пар из sample_schedule.json для группы {TSU_GROUP}")
    else:
        print("❌ Файл sample_schedule.json не найден")


async def cmd_status():
    init_db()
    profile = fetchone("SELECT * FROM user_profile LIMIT 1")
    classes_cnt = fetchone("SELECT COUNT(*) as c FROM university_schedule")
    tasks_cnt = fetchone("SELECT COUNT(*) as c FROM tasks WHERE status = 'pending'")
    habits_cnt = fetchone("SELECT COUNT(*) as c FROM habits WHERE active = 1")
    locations_cnt = fetchone("SELECT COUNT(*) as c FROM locations")

    print("=== ДИАГНОСТИКА СИСТЕМЫ ===")
    print(f"Часовой пояс: {TIMEZONE} (UTC+7)")
    print(f"Группа ТГУ: {TSU_GROUP}")
    print(f"Профиль настроен: {'Да' if profile and profile.get('onboarding_complete') else 'Нет (нужен онбординг)'}")
    print(f"Пар в расписании: {classes_cnt['c'] if classes_cnt else 0}")
    print(f"Активных задач: {tasks_cnt['c'] if tasks_cnt else 0}")
    print(f"Активных привычек: {habits_cnt['c'] if habits_cnt else 0}")
    print(f"Сохранённых локаций: {locations_cnt['c'] if locations_cnt else 0}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    commands = {
        "init": cmd_init,
        "poll": cmd_poll,
        "morning": cmd_morning,
        "evening": cmd_evening,
        "update-schedule": cmd_update_schedule,
        "seed": cmd_seed,
        "status": cmd_status,
    }

    handler = commands.get(cmd)
    if not handler:
        print(f"Неизвестная команда: {cmd}\n")
        print(__doc__)
        sys.exit(1)

    asyncio.run(handler())


if __name__ == "__main__":
    main()
