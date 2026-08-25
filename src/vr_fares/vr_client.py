import random
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from vr_fares.config import SCAN
from vr_fares.domain import Journey, JourneyLeg

DEPARTURES_ENDPOINT = "https://api.vrresa.se/api/v1.0/departures/"
STOCKHOLM_C = "b9501164-fbb4-454a-8918-38a042780790"
GOTEBORG_C = "b9501164-fbb4-454a-8918-38a042780795"


class VRClientError(Exception):
    code = "vr_unavailable"


class VRTimeoutError(VRClientError):
    code = "vr_timeout"


class VRSchemaError(VRClientError):
    code = "schema_drift"


class VRHTTPError(VRClientError):
    code = "vr_http_error"


def _expect_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VRSchemaError(f"invalid {label}")
    return value


def _expect_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VRSchemaError(f"missing {label}")
    return value


def _parse_datetime(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_expect_string(value, label))
    except ValueError as error:
        raise VRSchemaError(f"invalid {label}") from error
    if parsed.tzinfo is None:
        raise VRSchemaError(f"invalid {label}")
    return parsed


def _parse_price(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise VRSchemaError("invalid FIX price")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise VRSchemaError("invalid FIX price") from error
    if (
        not decimal_value.is_finite()
        or decimal_value < 0
        or decimal_value != decimal_value.to_integral_value()
    ):
        raise VRSchemaError("invalid FIX price")
    return int(decimal_value)


def _parse_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise VRSchemaError(f"invalid {label}")
    return value


def _optional_datetime(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, label)


def parse_journeys(raw_journeys: Any, travel_date: date) -> list[Journey]:
    if not isinstance(raw_journeys, list):
        raise VRSchemaError("departures response is not an array")
    parsed: list[Journey] = []
    for raw in raw_journeys:
        journey = _expect_mapping(raw, "journey")
        departure_at = _parse_datetime(journey.get("departure_at"), "journey departure_at")
        arrival_at = _parse_datetime(journey.get("arrival_at"), "journey arrival_at")
        duration_minutes = int((arrival_at - departure_at).total_seconds() // 60)
        if duration_minutes <= 0:
            raise VRSchemaError("invalid journey duration")
        prices = _expect_mapping(journey.get("prices"), "journey prices")
        raw_departures = journey.get("departures")
        if not isinstance(raw_departures, list):
            raise VRSchemaError("invalid journey departures")
        legs: list[JourneyLeg] = []
        schedule_references: list[str] = []
        for index, raw_departure in enumerate(raw_departures):
            departure = _expect_mapping(raw_departure, "journey departure")
            raw_reference = departure.get("schedule_reference")
            if raw_reference is not None and not isinstance(raw_reference, (str, int)):
                raise VRSchemaError("invalid schedule_reference")
            reference = f"VR {raw_reference}" if raw_reference is not None else None
            if reference is not None:
                schedule_references.append(reference)
            raw_segments = departure.get("legs", [])
            if not isinstance(raw_segments, list):
                raise VRSchemaError("invalid departure legs")
            vehicle_types: list[int | str] = []
            for segment in raw_segments:
                mapped_segment = _expect_mapping(segment, "departure leg")
                values = mapped_segment.get("vehicle_types", [])
                if not isinstance(values, list) or any(
                    isinstance(item, bool) or not isinstance(item, (int, str)) for item in values
                ):
                    raise VRSchemaError("invalid vehicle_types")
                vehicle_types.extend(values)
            raw_event = departure.get("event")
            if raw_event is not None and not isinstance(raw_event, dict):
                raise VRSchemaError("invalid event")
            raw_messages = departure.get("messages", [])
            if not isinstance(raw_messages, list) or any(
                not isinstance(item, dict) for item in raw_messages
            ):
                raise VRSchemaError("invalid messages")
            legs.append(
                JourneyLeg(
                    schedule_reference=reference,
                    departure_at=_optional_datetime(
                        departure.get("departure_at"), f"leg {index} departure_at"
                    ),
                    arrival_at=_optional_datetime(
                        departure.get("arrival_at"), f"leg {index} arrival_at"
                    ),
                    transport_type=departure.get("transport_type"),
                    traffic_provider=departure.get("traffic_provider"),
                    vehicle_types=sorted(set(vehicle_types), key=str),
                    event=raw_event,
                    messages=raw_messages,
                )
            )
        raw_seats = journey.get("seats_left")
        if raw_seats is not None and (
            isinstance(raw_seats, bool) or not isinstance(raw_seats, int)
        ):
            raise VRSchemaError("invalid seats_left")
        raw_id = journey.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raise VRSchemaError("invalid journey id")
        parsed.append(
            Journey(
                journey_id=raw_id,
                travel_date=travel_date,
                departure_at=departure_at,
                arrival_at=arrival_at,
                duration_minutes=duration_minutes,
                available=_parse_bool(journey.get("available"), "available"),
                bookable=_parse_bool(journey.get("bookable"), "bookable"),
                seats_left=raw_seats,
                fix_price_sek=_parse_price(prices.get("FIX")),
                has_disruption=_parse_bool(journey.get("has_disruption"), "has_disruption"),
                had_rebooked_disruption=_parse_bool(
                    journey.get("had_rebooked_disruption"), "had_rebooked_disruption"
                ),
                schedule_references=schedule_references,
                legs=legs,
            )
        )
    return parsed


class VRClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = SCAN.request_timeout_seconds,
        retry_attempts: int = SCAN.retry_attempts,
        retry_base_seconds: float = SCAN.retry_base_seconds,
        client: httpx.Client | None = None,
        sleep: Any = time.sleep,
        random_value: Any = random.random,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self.sleep = sleep
        self.random_value = random_value

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def search(self, direction: str, travel_date: date) -> list[Journey]:
        if direction == "outbound":
            origin_id, destination_id = GOTEBORG_C, STOCKHOLM_C
        elif direction == "return":
            origin_id, destination_id = STOCKHOLM_C, GOTEBORG_C
        else:
            raise ValueError("direction must be outbound or return")
        payload = {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "date": travel_date.isoformat(),
            "for_outbound": True,
            "passengers": [1],
            "has_stroller": False,
            "has_pet": False,
            "wheelchairs": 0,
            "walkers": 0,
        }
        last_error: VRClientError | None = None
        for attempt in range(self.retry_attempts):
            try:
                response = self.client.post(
                    DEPARTURES_ENDPOINT,
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    timeout=self.timeout_seconds,
                )
                if response.status_code >= 500 or response.status_code == 429:
                    raise VRHTTPError("VR temporarily unavailable")
                if response.status_code >= 400:
                    raise VRHTTPError("VR rejected the fare search")
                return parse_journeys(response.json(), travel_date)
            except httpx.TimeoutException:
                last_error = VRTimeoutError("VR request timed out")
            except httpx.TransportError:
                last_error = VRHTTPError("VR transport failure")
            except VRSchemaError:
                raise
            except VRHTTPError as error:
                last_error = error
                if response.status_code < 500 and response.status_code != 429:
                    break
            if attempt + 1 < self.retry_attempts and last_error is not None:
                self.sleep(self.retry_base_seconds * (2**attempt) + self.random_value() * 0.2)
        raise last_error or VRHTTPError("VR request failed")
