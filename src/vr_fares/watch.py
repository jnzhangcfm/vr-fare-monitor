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
        "latest_arrival_inclusive": "16:10",
        "latest_arrival_exclusive": None,
        "strategy": "standard",
        "stop_loss_date": "2026-10-17",
    },
    {
        "id": "stockholm-goteborg-2026-10-23",
        "travel_date": "2026-10-23",
        "direction": "return",
        "origin": "Stockholm C",
        "destination": "Göteborg C",
        "earliest_departure": "11:00",
        "latest_arrival_exclusive": None,
        "strategy": "standard",
    },
    {
        "id": "goteborg-stockholm-2026-10-28",
        "travel_date": "2026-10-28",
        "direction": "outbound",
        "origin": "Göteborg C",
        "destination": "Stockholm C",
        "earliest_departure": None,
        "latest_arrival_exclusive": "18:00",
        "strategy": "standard",
    },
)


def _parse_local_clock(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timetz().replace(tzinfo=None)
    except ValueError:
        return None


def _departure_is_allowed(value: Any, earliest: str | None) -> bool:
    local_clock = _parse_local_clock(value)
    if local_clock is None:
        return False
    if earliest is None:
        return True
    return local_clock >= time.fromisoformat(earliest)


def _arrival_is_allowed(
    value: Any,
    latest_exclusive: str | None,
    latest_inclusive: str | None = None,
) -> bool:
    local_clock = _parse_local_clock(value)
    if local_clock is None:
        return False
    if latest_inclusive is not None:
        return local_clock <= time.fromisoformat(latest_inclusive)
    if latest_exclusive is None:
        return True
    return local_clock < time.fromisoformat(latest_exclusive)


def _clock_in_window(value: Any, start: str, end: str) -> bool:
    local_clock = _parse_local_clock(value)
    if local_clock is None:
        return False
    return time.fromisoformat(start) <= local_clock <= time.fromisoformat(end)


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
        stop_loss_candidates: list[dict[str, Any]] = []

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
                    journey.get("departure_at"), target.get("earliest_departure")
                ):
                    continue
                if not _arrival_is_allowed(
                    journey.get("arrival_at"),
                    target.get("latest_arrival_exclusive"),
                    target.get("latest_arrival_inclusive"),
                ):
                    continue

                compact = _compact_match(journey)
                if compact is None:
                    continue

                if target["id"] == "goteborg-stockholm-2026-10-19":
                    stop_loss_candidates.append(compact)

                if compact["fix_price_sek"] >= PRICE_THRESHOLD_SEK:
                    continue
                compact = {**compact, "alert_tier": "standard"}

                matches.append(compact)

            tier_order = {"preferred": 0, "backup": 1, "bargain": 2, "standard": 0}
            matches.sort(
                key=lambda item: (
                    tier_order.get(item.get("alert_tier"), 9),
                    item["fix_price_sek"],
                    item["departure_at"] or "",
                )
            )
            stop_loss_candidates.sort(
                key=lambda item: (item["fix_price_sek"], item["arrival_at"] or "")
            )
            status = "match_found" if matches else "no_match"

        target_result = {
            **target,
            "price_rule": f"< {PRICE_THRESHOLD_SEK} SEK",
            "status": status,
            "match_count": len(matches),
            "best_price_sek": min(
                (item["fix_price_sek"] for item in matches), default=None
            ),
            "matches": matches,
        }

        if target["id"] == "goteborg-stockholm-2026-10-19":
            target_result["stop_loss_candidates"] = stop_loss_candidates[:3]
            target_result["best_stop_loss_candidate"] = (
                stop_loss_candidates[0] if stop_loss_candidates else None
            )

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
            {"preferred": 0, "backup": 1, "bargain": 2, "standard": 0}.get(
                item.get("alert_tier"), 9
            ),
            item["fix_price_sek"],
            item["departure_at"] or "",
        )
    )
    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "source": "official_vr_api",
        "currency": "SEK",
        "price_threshold_sek": PRICE_THRESHOLD_SEK,
        "expires_after": "2026-10-28",
        "has_alerts": bool(alerts),
        "alert_count": len(alerts),
        "targets": targets,
        "alerts": alerts,
    }
