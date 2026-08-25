"""Deterministic descriptive analysis for append-only fare observations."""

from collections import defaultdict
from datetime import UTC, date, datetime
from statistics import fmean, median
from typing import Any
from zoneinfo import ZoneInfo

from vr_fares.config import LEARNING

STOCKHOLM_TIMEZONE = ZoneInfo("Europe/Stockholm")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _observed_at(record: dict[str, Any]) -> datetime:
    return _as_utc(datetime.fromisoformat(record["observed_at"]))


def _local_date(record: dict[str, Any]) -> date:
    return _observed_at(record).astimezone(STOCKHOLM_TIMEZONE).date()


def learning_is_active(now: datetime) -> bool:
    local_date = _as_utc(now).astimezone(STOCKHOLM_TIMEZONE).date()
    return LEARNING.start_date <= local_date <= LEARNING.end_date


def _price_transitions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        identity = record.get("logical_journey_identity")
        if isinstance(identity, str):
            by_identity[identity].append(record)
    transitions: list[dict[str, Any]] = []
    for identity_records in by_identity.values():
        identity_records.sort(key=_observed_at)
        for previous, current in zip(identity_records, identity_records[1:], strict=False):
            previous_price = previous.get("fix_price_sek")
            current_price = current.get("fix_price_sek")
            if not isinstance(previous_price, int) or not isinstance(current_price, int):
                continue
            transitions.append(
                {
                    "previous": previous,
                    "current": current,
                    "delta": current_price - previous_price,
                }
            )
    return transitions


def _matched_journeys(transitions: list[dict[str, Any]]) -> set[str]:
    return {
        transition["current"]["logical_journey_identity"]
        for transition in transitions
        if isinstance(transition["current"].get("logical_journey_identity"), str)
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _lead_time_bin(days_before_travel: int) -> str | None:
    for label, lower, upper in LEARNING.lead_time_bins:
        if lower <= days_before_travel <= upper:
            return label
    return None


def _pearson(x_values: list[int], y_values: list[int]) -> float | None:
    if len(x_values) < 2 or len(x_values) != len(y_values):
        return None
    x_mean = fmean(x_values)
    y_mean = fmean(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    x_scale = sum((x - x_mean) ** 2 for x in x_values)
    y_scale = sum((y - y_mean) ** 2 for y in y_values)
    if x_scale == 0 or y_scale == 0:
        return None
    return round(numerator / (x_scale * y_scale) ** 0.5, 4)


def recommend_frequency(
    *,
    successful_scan_count: int,
    price_transition_count: int,
    intraday_change_rate: float | None,
    any_change_rate: float | None,
) -> dict[str, Any]:
    """Return an advisory frequency using intentionally conservative, visible thresholds."""
    evidence = {
        "successful_scan_count": successful_scan_count,
        "price_transition_count": price_transition_count,
        "intraday_change_rate": intraday_change_rate,
        "any_change_rate": any_change_rate,
    }
    if (
        successful_scan_count < LEARNING.minimum_successful_scans
        or price_transition_count < LEARNING.minimum_price_transitions
    ):
        return {
            "recommended_long_term_frequency": "insufficient_data",
            "confidence": "low",
            "evidence": evidence,
        }
    intraday_rate = intraday_change_rate or 0.0
    total_rate = any_change_rate or 0.0
    if intraday_rate >= LEARNING.four_times_daily_intraday_change_rate:
        frequency = "four_times_daily"
    elif (
        intraday_rate >= LEARNING.twice_daily_intraday_change_rate
        or total_rate >= LEARNING.twice_daily_any_change_rate
    ):
        frequency = "twice_daily"
    else:
        frequency = "once_daily"
    confidence = "moderate" if successful_scan_count >= 14 else "low"
    return {
        "recommended_long_term_frequency": frequency,
        "confidence": confidence,
        "evidence": evidence,
    }


def build_learning_summary(
    records: list[dict[str, Any]], *, now: datetime, failed_scan_count: int = 0
) -> dict[str, Any]:
    """Summarize observations without treating gaps or missing prices as price events."""
    now_local_date = _as_utc(now).astimezone(STOCKHOLM_TIMEZONE).date()
    observations = sorted(records, key=_observed_at)
    transitions = _price_transitions(observations)
    matched = _matched_journeys(transitions)
    unique_journeys = {
        record["logical_journey_identity"]
        for record in observations
        if isinstance(record.get("logical_journey_identity"), str)
    }
    changed_journeys = {
        transition["current"]["logical_journey_identity"]
        for transition in transitions
        if transition["delta"] != 0
    }
    deltas = [transition["delta"] for transition in transitions]
    absolute_changes = [abs(delta) for delta in deltas if delta != 0]
    increases = [delta for delta in deltas if delta > 0]
    decreases = [delta for delta in deltas if delta < 0]
    unchanged = [delta for delta in deltas if delta == 0]
    missing_journeys = {
        record["logical_journey_identity"]
        for record in observations
        if record.get("fix_price_sek") is None
        and isinstance(record.get("logical_journey_identity"), str)
    }
    scan_times = {record.get("observed_at") for record in observations}
    elapsed_days = max(
        0,
        (min(now_local_date, LEARNING.end_date) - LEARNING.start_date).days + 1,
    )

    intraday: dict[str, dict[str, int]] = defaultdict(
        lambda: {"transition_count": 0, "change_events": 0}
    )
    intraday_transitions = 0
    intraday_changes = 0
    lead_time: dict[str, dict[str, int]] = {
        label: {"transition_count": 0, "change_events": 0}
        for label, _, _ in LEARNING.lead_time_bins
    }
    seat_deltas: list[int] = []
    price_deltas_for_seats: list[int] = []
    for transition in transitions:
        previous = transition["previous"]
        current = transition["current"]
        previous_local = _observed_at(previous).astimezone(STOCKHOLM_TIMEZONE)
        current_local = _observed_at(current).astimezone(STOCKHOLM_TIMEZONE)
        if previous_local.date() == current_local.date():
            interval = f"{previous_local:%H:%M}-{current_local:%H:%M}"
            intraday[interval]["transition_count"] += 1
            intraday_transitions += 1
            if transition["delta"] != 0:
                intraday[interval]["change_events"] += 1
                intraday_changes += 1
        travel_date = current.get("travel_date")
        if isinstance(travel_date, str):
            days_before_travel = (date.fromisoformat(travel_date) - current_local.date()).days
            bucket = _lead_time_bin(days_before_travel)
            if bucket is not None:
                lead_time[bucket]["transition_count"] += 1
                if transition["delta"] != 0:
                    lead_time[bucket]["change_events"] += 1
        previous_seats = previous.get("seats_left")
        current_seats = current.get("seats_left")
        if isinstance(previous_seats, int) and isinstance(current_seats, int):
            seat_deltas.append(current_seats - previous_seats)
            price_deltas_for_seats.append(transition["delta"])

    seat_status = "available" if len(seat_deltas) >= 5 else "insufficient_data"
    intraday_change_rate = _rate(intraday_changes, intraday_transitions)
    any_change_rate = _rate(len(absolute_changes), len(transitions))
    recommendation = recommend_frequency(
        successful_scan_count=len(scan_times),
        price_transition_count=len(transitions),
        intraday_change_rate=intraday_change_rate,
        any_change_rate=any_change_rate,
    )
    return {
        "schema_version": LEARNING.schema_version,
        "generated_at": _as_utc(now).isoformat(),
        "learning_period": {
            "start_date": LEARNING.start_date.isoformat(),
            "end_date": LEARNING.end_date.isoformat(),
            "elapsed_learning_days": elapsed_days,
            "active": learning_is_active(now),
        },
        "coverage": {
            "observation_count": len(observations),
            "successful_scan_count": len(scan_times),
            "failed_scan_count": failed_scan_count,
            "unique_travel_date_count": len(
                {record.get("travel_date") for record in observations if record.get("travel_date")}
            ),
            "unique_journey_count": len(unique_journeys),
        },
        "price_change_behavior": {
            "matched_journey_count": len(matched),
            "never_changed_count": len(matched - changed_journeys),
            "never_changed_proportion": _rate(len(matched - changed_journeys), len(matched)),
            "changed_at_least_once_count": len(changed_journeys),
            "changed_at_least_once_proportion": _rate(len(changed_journeys), len(matched)),
            "total_price_change_events": len(absolute_changes),
            "increases": len(increases),
            "decreases": len(decreases),
            "unchanged_transitions": len(unchanged),
            "median_absolute_change_sek": median(absolute_changes) if absolute_changes else None,
            "mean_absolute_change_sek": round(fmean(absolute_changes), 2)
            if absolute_changes
            else None,
            "maximum_increase_sek": max(increases) if increases else None,
            "maximum_decrease_sek": min(decreases) if decreases else None,
            "journeys_with_missing_fix_price": len(missing_journeys),
        },
        "intraday_behavior": {
            "transition_count": intraday_transitions,
            "price_change_events": intraday_changes,
            "change_rate": intraday_change_rate,
            "intervals": dict(sorted(intraday.items())),
        },
        "lead_time_behavior": lead_time,
        "seats_left_relationship": {
            "status": seat_status,
            "paired_transition_count": len(seat_deltas),
            "price_change_vs_seats_left_change_correlation": _pearson(
                seat_deltas, price_deltas_for_seats
            )
            if seat_status == "available"
            else None,
        },
        "recommendation": recommendation,
        "recommendation_policy": {
            "minimum_successful_scans": LEARNING.minimum_successful_scans,
            "minimum_price_transitions": LEARNING.minimum_price_transitions,
            "four_times_daily_intraday_change_rate": LEARNING.four_times_daily_intraday_change_rate,
            "twice_daily_intraday_change_rate": LEARNING.twice_daily_intraday_change_rate,
            "twice_daily_any_change_rate": LEARNING.twice_daily_any_change_rate,
        },
    }
