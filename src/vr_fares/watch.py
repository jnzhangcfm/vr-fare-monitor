"""Build the compact fare watch payload used by ChatGPT alerts."""

from datetime import datetime, time
from typing import Any

PRICE_THRESHOLD_SEK = 500

WATCH_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "id": "goteborg-stockholm-2026-10-19",
        "travel_date": "2026-10-19",
        "direction": "outbound",
        "origin": "Göteborg C",
        "destination": "Stockholm C",
        "earliest_departure": None,
    },
    {
        "id": "stockholm-goteborg-2026-10-23",
        "travel_date": "2026-10-23",
        "direction": "return",
        "origin": "Stockholm C",
        "destination": "Göteborg C",
        "earliest_departure": "11:00",
    },
)


def _departure_is_allowed(value: Any, earliest: str | None) -> bool:
    if not isinstance(value, str):
        return False
    if earliest is None:
        return True
    try:
        departure = datetime.fromisoformat(value)
        earliest_time = time.fromisoformat(earliest)
    except ValueError:
        return False
    return departure.timetz().replace(tzinfo=None) >= earliest_time


def _compact_match(journey: dict[str, Any]) -> dict[str, Any] | None:
    prices = journey.get("prices")
    if not isinstance(prices, dict):
        return None
    fix_price = prices.get("FIX")
    if isinstance(fix_price, bool) or not isinstance(fix_price, int):
        return None
    return {
        "journey_id": journey.get("journey_id"),
        "departure_at": journey.get("departure_at"),
        "arrival_at": journey.get("arrival_at"),
        "duration_minutes": journey.get("duration_minutes"),
        "fix_price_sek": fix_price,
        "seats_left": journey.get("seats_left"),
        "schedule_references": journey.get("schedule_references", []),
    }


def build_watch_payload(raw_scan: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    dates = {
        entry.get("date"): entry
        for entry in raw_scan.get("dates", [])
        if isinstance(entry, dict) and isinstance(entry.get("date"), str)
    }

    targets: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for target in WATCH_TARGETS:
        entry = dates.get(target["travel_date"])
        matches: list[dict[str, Any]] = []
        if not isinstance(entry, dict):
            status = "date_not_scanned"
        elif entry.get("status") == "source_failure":
            status = "source_failure"
        else:
            journeys = entry.get("journeys")
            if not isinstance(journeys, dict):
                journeys = {}
            direction_journeys = journeys.get(target["direction"])
            if not isinstance(direction_journeys, list):
                direction_journeys = []

            for journey in direction_journeys:
                if not isinstance(journey, dict):
                    continue
                if journey.get("available") is not True or journey.get("bookable") is not True:
                    continue
                if not _departure_is_allowed(
                    journey.get("departure_at"), target["earliest_departure"]
                ):
                    continue
                compact = _compact_match(journey)
                if compact is None or compact["fix_price_sek"] >= PRICE_THRESHOLD_SEK:
                    continue
                matches.append(compact)

            matches.sort(key=lambda item: (item["fix_price_sek"], item["departure_at"] or ""))
            status = "match_found" if matches else "no_match"

        target_result = {
            **target,
            "price_rule": f"< {PRICE_THRESHOLD_SEK} SEK",
            "status": status,
            "match_count": len(matches),
            "best_price_sek": matches[0]["fix_price_sek"] if matches else None,
            "matches": matches,
        }
        targets.append(target_result)
        alerts.extend(
            {
                "target_id": target["id"],
                "travel_date": target["travel_date"],
                "origin": target["origin"],
                "destination": target["destination"],
                **match,
            }
            for match in matches
        )

    alerts.sort(
        key=lambda item: (
            item["travel_date"],
            item["fix_price_sek"],
            item["departure_at"] or "",
        )
    )
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": "official_vr_api",
        "currency": "SEK",
        "price_threshold_sek": PRICE_THRESHOLD_SEK,
        "expires_after": "2026-10-23",
        "has_alerts": bool(alerts),
        "alert_count": len(alerts),
        "targets": targets,
        "alerts": alerts,
    }
