"""Append-only journey observations for the bounded fare-learning period."""

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vr_fares.config import LEARNING

STOCKHOLM_TIMEZONE = ZoneInfo("Europe/Stockholm")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def logical_journey_identity(journey: dict[str, Any], direction: str) -> str:
    """Identify a logical service without trusting source journey IDs across scans."""
    references = journey.get("schedule_references")
    primary_reference = references[0] if isinstance(references, list) and references else "unknown"
    travel_date = journey.get("travel_date") or "unknown"
    departure_at = journey.get("departure_at") or "unknown"
    return f"{travel_date}|{direction}|{primary_reference}|{departure_at}"


def _transport_fields(journey: dict[str, Any]) -> tuple[list[int | str], list[int | str]]:
    transport_types: list[int | str] = []
    vehicle_types: list[int | str] = []
    legs = journey.get("legs")
    for leg in legs if isinstance(legs, list) else []:
        if not isinstance(leg, dict):
            continue
        transport_type = leg.get("transport_type")
        if transport_type is not None and transport_type not in transport_types:
            transport_types.append(transport_type)
        leg_vehicle_types = leg.get("vehicle_types")
        for vehicle_type in leg_vehicle_types if isinstance(leg_vehicle_types, list) else []:
            if vehicle_type not in vehicle_types:
                vehicle_types.append(vehicle_type)
    return transport_types, vehicle_types


def observations_from_scan(
    scan: dict[str, Any], *, observed_at: datetime, observation_key: str
) -> list[dict[str, Any]]:
    """Convert all returned raw journeys into observations, including non-fare states."""
    observed_at_utc = _as_utc(observed_at).isoformat()
    observations: list[dict[str, Any]] = []
    for date_entry in scan.get("dates", []):
        if not isinstance(date_entry, dict):
            continue
        journeys_by_direction = date_entry.get("journeys")
        if not isinstance(journeys_by_direction, dict):
            continue
        for direction in ("outbound", "return"):
            journeys = journeys_by_direction.get(direction)
            for journey in journeys if isinstance(journeys, list) else []:
                if not isinstance(journey, dict):
                    continue
                prices = journey.get("prices")
                fix_price = prices.get("FIX") if isinstance(prices, dict) else None
                identity = logical_journey_identity(journey, direction)
                references = journey.get("schedule_references")
                schedule_references = references if isinstance(references, list) else []
                transport_types, vehicle_types = _transport_fields(journey)
                observations.append(
                    {
                        "schema_version": LEARNING.schema_version,
                        "observation_id": f"{observation_key}|{identity}",
                        "observed_at": observed_at_utc,
                        "logical_journey_identity": identity,
                        "travel_date": journey.get("travel_date") or date_entry.get("date"),
                        "direction": direction,
                        "schedule_reference": schedule_references[0]
                        if schedule_references
                        else None,
                        "schedule_references": schedule_references,
                        "departure_at": journey.get("departure_at"),
                        "arrival_at": journey.get("arrival_at"),
                        "duration_minutes": journey.get("duration_minutes"),
                        "fix_price_sek": fix_price,
                        "fix_price_state": "available" if fix_price is not None else "missing",
                        "available": journey.get("available"),
                        "bookable": journey.get("bookable"),
                        "seats_left": journey.get("seats_left"),
                        "has_disruption": journey.get("has_disruption"),
                        "had_rebooked_disruption": journey.get("had_rebooked_disruption"),
                        "transport_types": transport_types,
                        "vehicle_types": vehicle_types,
                        "journey_id": journey.get("journey_id"),
                    }
                )
    return observations


def _history_date(record: dict[str, Any]) -> str:
    observed_at = datetime.fromisoformat(record["observed_at"])
    return _as_utc(observed_at).astimezone(STOCKHOLM_TIMEZONE).date().isoformat()


def _existing_observation_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    identifiers: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("observation_id"), str):
            identifiers.add(value["observation_id"])
    return identifiers


def append_observations(history_dir: Path, records: Iterable[dict[str, Any]]) -> int:
    """Append new observations to their Stockholm-local daily JSONL partitions."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_history_date(record)].append(record)
    appended = 0
    for history_date, date_records in grouped.items():
        path = history_dir / f"{history_date}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_ids = _existing_observation_ids(path)
        new_records = [
            record
            for record in date_records
            if isinstance(record.get("observation_id"), str)
            and record["observation_id"] not in existing_ids
        ]
        if not new_records:
            continue
        with path.open("a", encoding="utf-8") as history_file:
            for record in new_records:
                history_file.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                )
                history_file.write("\n")
        appended += len(new_records)
    return appended


def load_observations(history_dir: Path) -> list[dict[str, Any]]:
    """Read valid records from date-partitioned history in deterministic order."""
    observations: list[dict[str, Any]] = []
    if not history_dir.exists():
        return observations
    for path in sorted(history_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                observations.append(value)
    return observations
