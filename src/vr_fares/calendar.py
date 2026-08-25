from datetime import date, timedelta

import holidays


def scan_window(checked_on: date, calendar_days: int) -> tuple[date, date]:
    if calendar_days not in (7, 30):
        raise ValueError("calendar_days must be 7 or 30")
    start = checked_on + timedelta(days=1)
    return start, start + timedelta(days=calendar_days - 1)


def eligible_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end must be on or after start")
    swedish_holidays = holidays.country_holidays("SE", years=range(start.year, end.year + 1))
    current = start
    result: list[date] = []
    while current <= end:
        if current.weekday() < 5 and current not in swedish_holidays:
            result.append(current)
        current += timedelta(days=1)
    return result
