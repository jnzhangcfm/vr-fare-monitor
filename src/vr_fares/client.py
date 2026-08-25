import json
from collections.abc import Callable
from datetime import date as Date
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

DEPARTURES_ENDPOINT = "https://api.vrresa.se/api/v1.0/departures/"
STATIONS = {
    "GOTEBORG": "b9501164-fbb4-454a-8918-38a042780795",
    "GOTHENBURG": "b9501164-fbb4-454a-8918-38a042780795",
    "GÖTEBORG": "b9501164-fbb4-454a-8918-38a042780795",
    "STOCKHOLM": "b9501164-fbb4-454a-8918-38a042780790",
}

Transport = Callable[[str, dict[str, Any]], list[dict[str, Any]]]


def _post_json(endpoint: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "vr-fares/0.1 (read-only fare research client)",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, list):
        raise ValueError("VR departures response was not a JSON array")
    return result


def search(
    from_code: str,
    to_code: str,
    date: str,
    *,
    transport: Transport = _post_json,
) -> dict[str, Any]:
    normalized_from = from_code.strip().upper()
    normalized_to = to_code.strip().upper()
    try:
        origin_id = STATIONS[normalized_from]
        destination_id = STATIONS[normalized_to]
    except KeyError as error:
        raise ValueError(f"unsupported station: {error.args[0]}") from None
    if origin_id == destination_id:
        raise ValueError("origin and destination must be different")
    Date.fromisoformat(date)

    payload = {
        "origin_id": origin_id,
        "destination_id": destination_id,
        "date": date,
        "for_outbound": True,
        "passengers": [1],
        "has_stroller": False,
        "has_pet": False,
        "wheelchairs": 0,
        "walkers": 0,
    }
    raw_journeys = transport(DEPARTURES_ENDPOINT, payload)
    return {
        "query": {
            "from": normalized_from,
            "to": normalized_to,
            "date": date,
            "operator": "VR",
            "passenger": "ADULT",
            "ticket_type": "FIX",
            "currency": "SEK",
        },
        "journeys": [normalize_journey(journey) for journey in raw_journeys],
    }


def normalize_journey(raw: dict[str, Any]) -> dict[str, Any]:
    departure_at = raw["departure_at"]
    arrival_at = raw["arrival_at"]
    duration = datetime.fromisoformat(arrival_at) - datetime.fromisoformat(departure_at)

    departures = raw.get("departures", [])
    train_numbers = [
        f"VR {departure['schedule_reference']}"
        for departure in departures
        if departure.get("schedule_reference") is not None
    ]
    legs = []
    for departure in departures:
        segments = departure.get("legs", [])
        vehicle_types = sorted(
            {
                vehicle_type
                for segment in segments
                for vehicle_type in segment.get("vehicle_types", [])
            }
        )
        train_number = departure.get("schedule_reference")
        legs.append(
            {
                "train_number": f"VR {train_number}" if train_number is not None else None,
                "departure_at": departure.get("departure_at"),
                "arrival_at": departure.get("arrival_at"),
                "transport_type": departure.get("transport_type"),
                "traffic_provider": departure.get("traffic_provider"),
                "vehicle_types": vehicle_types,
                "event": departure.get("event"),
                "messages": departure.get("messages", []),
                "segments": segments,
            }
        )

    fix_amount = raw.get("prices", {}).get("FIX")
    adult_fix = None
    if fix_amount is not None:
        adult_fix = {
            "amount": fix_amount,
            "currency": "SEK",
            "passenger": "ADULT",
            "ticket_type": "FIX",
        }

    return {
        "journey_id": raw.get("id"),
        "operator": "VR",
        "train_numbers": train_numbers,
        "departure_at": departure_at,
        "arrival_at": arrival_at,
        "duration_minutes": int(duration.total_seconds() // 60),
        "available": raw.get("available"),
        "bookable": raw.get("bookable"),
        "adult_fix": adult_fix,
        "has_disruption": raw.get("has_disruption", False),
        "had_rebooked_disruption": raw.get("had_rebooked_disruption", False),
        "legs": legs,
    }
