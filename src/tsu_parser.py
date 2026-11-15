"""TSU schedule parser — fetches and caches university timetable for group 932604."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from src.db import execute, fetchall, fetchone
from src.config import TSU_GROUP
from src.utils import TOMSK_TZ

log = logging.getLogger(__name__)

# ── Known API patterns for intime.tsu.ru (reverse-engineered) ─────
_BASE = "https://intime.tsu.ru"
_SEARCH_URL = f"{_BASE}/api/web/v1/schedule/group/search"
_SCHEDULE_URL = f"{_BASE}/api/web/v1/schedule/group"   # + /{group_uuid}


async def _find_group_uuid() -> str | None:
    """Search for the group by number and return its UUID."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(_SEARCH_URL, params={"name": TSU_GROUP})
            if resp.status_code != 200:
                log.warning("Group search HTTP %s", resp.status_code)
                return None
            data = resp.json()
            # Response is typically a list of matching groups
            groups = data if isinstance(data, list) else data.get("data", data.get("results", []))
            for g in groups:
                gname = str(g.get("name", g.get("title", g.get("number", ""))))
                if TSU_GROUP in gname:
                    return g.get("id", g.get("uuid", g.get("groupId")))
    except Exception as e:
        log.error("Group search failed: %s", e)
    return None


async def _fetch_week_schedule(group_uuid: str, date_from: str | None = None) -> list[dict] | None:
    """Fetch weekly schedule for a group UUID."""
    try:
        import httpx
        url = f"{_SCHEDULE_URL}/{group_uuid}"
        params = {}
        if date_from:
            params["dateFrom"] = date_from
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(url, params=params)
            if resp.status_code != 200:
                log.warning("Schedule fetch HTTP %s", resp.status_code)
                return None
            return resp.json()
    except Exception as e:
        log.error("Schedule fetch failed: %s", e)
    return None


def _parse_api_response(raw: list | dict) -> list[dict]:
    """Normalize the API response into our internal schedule format."""
    classes = []
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("lessons", []))
    for item in items:
        try:
            # Try multiple possible key structures
            start = item.get("startTime", item.get("start_time", item.get("timeStart", "")))
            end = item.get("endTime", item.get("end_time", item.get("timeEnd", "")))
            # Normalize time to HH:MM
            if "T" in str(start):
                dt = datetime.fromisoformat(start)
                start = dt.strftime("%H:%M")
                dt2 = datetime.fromisoformat(end)
                end = dt2.strftime("%H:%M")
            day_of_week = item.get("dayOfWeek", item.get("day", item.get("weekDay")))
            if isinstance(day_of_week, str):
                dow_map = {"Понедельник": 0, "Вторник": 1, "Среда": 2,
                           "Четверг": 3, "Пятница": 4, "Суббота": 5, "Воскресенье": 6}
                day_of_week = dow_map.get(day_of_week, 0)
            # Week parity
            parity = item.get("weekParity", item.get("parity", "any"))
            if parity in (None, "", "all", "0"):
                parity = "any"
            elif parity in ("1", "нечётная", "odd"):
                parity = "odd"
            elif parity in ("2", "чётная", "even"):
                parity = "even"

            cls_dict = {
                "day_of_week": int(day_of_week) if day_of_week is not None else 0,
                "week_parity": parity,
                "start_time": str(start)[:5],
                "end_time": str(end)[:5],
                "subject": item.get("subject", item.get("discipline", item.get("name", ""))),
                "lecture_type": item.get("type", item.get("lessonType", "")),
                "building": item.get("building", item.get("corpus", "")),
                "room": str(item.get("room", item.get("auditorium", item.get("audience", "")))),
                "teacher": item.get("teacher", item.get("lecturer", "")),
            }
            if isinstance(cls_dict["teacher"], dict):
                cls_dict["teacher"] = cls_dict["teacher"].get("name", "")
            if isinstance(cls_dict["teacher"], list) and cls_dict["teacher"]:
                cls_dict["teacher"] = cls_dict["teacher"][0].get("name", str(cls_dict["teacher"][0]))

            classes.append(cls_dict)
        except Exception as e:
            log.warning("Failed to parse schedule item: %s — %s", item, e)
    return classes


# ── Public API ────────────────────────────────────────────

async def fetch_schedule_from_web() -> list[dict] | None:
    """Attempt to fetch schedule from intime.tsu.ru. Returns None on failure."""
    group_uuid = await _find_group_uuid()
    if not group_uuid:
        log.warning("Could not find group UUID for %s", TSU_GROUP)
        return None

    raw = await _fetch_week_schedule(group_uuid)
    if raw is None:
        return None

    classes = _parse_api_response(raw)
    if classes:
        log.info("Fetched %d classes from web", len(classes))
    return classes or None


async def update_schedule_cache() -> bool:
    """Fetch schedule from web and cache in DB. Returns True if updated."""
    classes = await fetch_schedule_from_web()
    if not classes:
        log.info("Web fetch failed; keeping cached schedule")
        return False

    # Clear old cache and insert new
    execute("DELETE FROM university_schedule")
    for c in classes:
        execute(
            "INSERT INTO university_schedule "
            "(day_of_week, week_parity, start_time, end_time, subject, lecture_type, building, room, teacher, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (c["day_of_week"], c["week_parity"], c["start_time"], c["end_time"],
             c["subject"], c["lecture_type"], c["building"], c["room"], c["teacher"]),
        )
    log.info("Cached %d schedule entries", len(classes))
    return True


def get_cached_schedule(day_of_week: int | None = None, week_parity: str | None = None) -> list[dict]:
    """Return cached schedule, optionally filtered."""
    sql = "SELECT * FROM university_schedule WHERE 1=1"
    params: list = []
    if day_of_week is not None:
        sql += " AND day_of_week = ?"
        params.append(day_of_week)
    if week_parity:
        sql += " AND (week_parity = ? OR week_parity = 'any')"
        params.append(week_parity)
    sql += " ORDER BY start_time"
    return fetchall(sql, params if params else None)


def get_todays_schedule() -> list[dict]:
    """Get classes for today (Tomsk timezone), considering week parity."""
    now = datetime.now(TOMSK_TZ)
    dow = now.weekday()  # 0 = Monday
    parity = determine_week_parity()
    return get_cached_schedule(day_of_week=dow, week_parity=parity)


def get_week_schedule() -> dict[int, list[dict]]:
    """Return full week schedule grouped by day_of_week."""
    parity = determine_week_parity()
    all_classes = get_cached_schedule(week_parity=parity)
    result: dict[int, list[dict]] = {i: [] for i in range(7)}
    for c in all_classes:
        result[c["day_of_week"]].append(c)
    return result


def determine_week_parity() -> str:
    """Determine if current week is 'odd' or 'even' (academic calendar, Sep 1 = week 1 = odd)."""
    now = datetime.now(TOMSK_TZ)
    year = now.year if now.month >= 9 else now.year - 1
    semester_start = datetime(year, 9, 1, tzinfo=TOMSK_TZ)
    # Align to Monday
    semester_start -= timedelta(days=semester_start.weekday())
    delta = now - semester_start
    week_num = delta.days // 7 + 1
    return "odd" if week_num % 2 == 1 else "even"


def import_schedule_json(schedule_data: list[dict]) -> int:
    """Manually import schedule from a list of dicts. Returns count."""
    execute("DELETE FROM university_schedule")
    count = 0
    for c in schedule_data:
        execute(
            "INSERT INTO university_schedule "
            "(day_of_week, week_parity, start_time, end_time, subject, lecture_type, building, room, teacher, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (c.get("day_of_week", 0), c.get("week_parity", "any"),
             c.get("start_time", ""), c.get("end_time", ""),
             c.get("subject", ""), c.get("lecture_type", ""),
             c.get("building", ""), c.get("room", ""),
             c.get("teacher", "")),
        )
        count += 1
    return count


def seed_default_schedule_if_empty() -> int:
    """If DB timetable is empty, seed from sample_schedule.json."""
    row = fetchone("SELECT COUNT(*) as cnt FROM university_schedule")
    if not row or row["cnt"] == 0:
        import pathlib
        sample_path = pathlib.Path(__file__).resolve().parent / "sample_schedule.json"
        if sample_path.exists():
            data = json.loads(sample_path.read_text(encoding="utf-8"))
            count = import_schedule_json(data)
            log.info("Seeded %d sample schedule entries for group %s", count, TSU_GROUP)
            return count
    return 0

