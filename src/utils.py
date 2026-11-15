"""Utility functions for the day planner bot."""

from datetime import datetime, timedelta, timezone

# Asia/Tomsk = UTC+7
TOMSK_TZ = timezone(timedelta(hours=7))


def now_tomsk() -> datetime:
    """Get current datetime in Asia/Tomsk timezone."""
    return datetime.now(TOMSK_TZ)


def today_tomsk() -> str:
    """Get today's date string in Asia/Tomsk timezone (YYYY-MM-DD)."""
    return now_tomsk().strftime('%Y-%m-%d')


def current_time_tomsk() -> str:
    """Get current time string in Asia/Tomsk timezone (HH:MM)."""
    return now_tomsk().strftime('%H:%M')


def day_of_week_tomsk() -> int:
    """Get current day of week in Tomsk (0=Monday, 6=Sunday)."""
    return now_tomsk().weekday()


def parse_time(time_str: str) -> datetime:
    """Parse HH:MM time string to datetime (today, Tomsk tz)."""
    h, m = map(int, time_str.split(':'))
    today = now_tomsk().date()
    return datetime(today.year, today.month, today.day, h, m, tzinfo=TOMSK_TZ)


def time_slot_overlaps(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Check if two time slots (HH:MM format) overlap."""
    s1, e1 = parse_time(start1), parse_time(end1)
    s2, e2 = parse_time(start2), parse_time(end2)
    return s1 < e2 and s2 < e1


def add_minutes_to_time(time_str: str, minutes: int) -> str:
    """Add minutes to a HH:MM time string, return HH:MM."""
    t = parse_time(time_str)
    t += timedelta(minutes=minutes)
    return t.strftime('%H:%M')


def subtract_minutes_from_time(time_str: str, minutes: int) -> str:
    """Subtract minutes from a HH:MM time string, return HH:MM."""
    t = parse_time(time_str)
    t -= timedelta(minutes=minutes)
    return t.strftime('%H:%M')


def minutes_between(time1: str, time2: str) -> int:
    """Calculate minutes between two HH:MM time strings."""
    t1 = parse_time(time1)
    t2 = parse_time(time2)
    delta = t2 - t1
    return int(delta.total_seconds() / 60)


def find_free_slots(
    busy_slots: list[dict],
    day_start: str = '08:00',
    day_end: str = '22:00',
    min_duration_minutes: int = 30
) -> list[dict]:
    """
    Find free time slots between busy periods.
    
    busy_slots: list of {"start_time": "HH:MM", "end_time": "HH:MM"}
    Returns: list of {"start_time": "HH:MM", "end_time": "HH:MM", "duration_minutes": int}
    """
    if not busy_slots:
        duration = minutes_between(day_start, day_end)
        if duration >= min_duration_minutes:
            return [{"start_time": day_start, "end_time": day_end, "duration_minutes": duration}]
        return []
    
    # Sort by start time
    sorted_slots = sorted(busy_slots, key=lambda s: s['start_time'])
    
    free = []
    
    # Gap before first busy slot
    if sorted_slots[0]['start_time'] > day_start:
        gap = minutes_between(day_start, sorted_slots[0]['start_time'])
        if gap >= min_duration_minutes:
            free.append({
                "start_time": day_start,
                "end_time": sorted_slots[0]['start_time'],
                "duration_minutes": gap
            })
    
    # Gaps between busy slots
    for i in range(len(sorted_slots) - 1):
        gap_start = sorted_slots[i]['end_time']
        gap_end = sorted_slots[i + 1]['start_time']
        if gap_start < gap_end:
            gap = minutes_between(gap_start, gap_end)
            if gap >= min_duration_minutes:
                free.append({
                    "start_time": gap_start,
                    "end_time": gap_end,
                    "duration_minutes": gap
                })
    
    # Gap after last busy slot
    if sorted_slots[-1]['end_time'] < day_end:
        gap = minutes_between(sorted_slots[-1]['end_time'], day_end)
        if gap >= min_duration_minutes:
            free.append({
                "start_time": sorted_slots[-1]['end_time'],
                "end_time": day_end,
                "duration_minutes": gap
            })
    
    return free


def format_date_russian(date_str: str) -> str:
    """Format YYYY-MM-DD to Russian date string."""
    months = {
        1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
        5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
        9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
    }
    days = {
        0: 'понедельник', 1: 'вторник', 2: 'среда', 3: 'четверг',
        4: 'пятница', 5: 'суббота', 6: 'воскресенье'
    }
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return f"{dt.day} {months[dt.month]}, {days[dt.weekday()]}"


def format_duration(minutes: int) -> str:
    """Format duration in minutes to human-readable Russian string."""
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        if hours == 1:
            return "1 час"
        elif hours < 5:
            return f"{hours} часа"
        else:
            return f"{hours} часов"
    return f"{hours}ч {mins}мин"


def get_week_start(date_str: str = None) -> str:
    """Get Monday of the current week (or week containing date_str)."""
    if date_str:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    else:
        dt = now_tomsk()
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime('%Y-%m-%d')


def get_week_dates(week_start: str = None) -> list[str]:
    """Get list of 7 date strings for the week starting from week_start (Monday)."""
    if not week_start:
        week_start = get_week_start()
    start = datetime.strptime(week_start, '%Y-%m-%d')
    return [(start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]


def cognitive_load_emoji(load: int) -> str:
    """Get emoji representation of cognitive load (1-5)."""
    emojis = {1: '🟢', 2: '🟡', 3: '🟠', 4: '🔴', 5: '💀'}
    return emojis.get(load, '⚪')


def energy_emoji(level: str) -> str:
    """Get emoji for energy level."""
    return {'high': '🔋', 'normal': '😐', 'low': '🪫'}.get(level, '❓')
