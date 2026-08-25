from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class JourneyLeg:
    schedule_reference: str | None
    departure_at: datetime | None
    arrival_at: datetime | None
    transport_type: int | str | None
    traffic_provider: int | str | None
    vehicle_types: list[int | str]
    event: dict[str, Any] | None
    messages: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_reference": self.schedule_reference,
            "departure_at": self.departure_at.isoformat() if self.departure_at else None,
            "arrival_at": self.arrival_at.isoformat() if self.arrival_at else None,
            "transport_type": self.transport_type,
            "traffic_provider": self.traffic_provider,
            "vehicle_types": self.vehicle_types,
            "event": self.event,
            "messages": self.messages,
        }


@dataclass(frozen=True)
class Journey:
    journey_id: str | None
    travel_date: date
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int
    available: bool
    bookable: bool
    seats_left: int | None
    fix_price_sek: int | None
    has_disruption: bool
    had_rebooked_disruption: bool
    schedule_references: list[str]
    legs: list[JourneyLeg]

    def to_dict(self) -> dict[str, Any]:
        return {
            "journey_id": self.journey_id,
            "travel_date": self.travel_date.isoformat(),
            "departure_at": self.departure_at.isoformat(),
            "arrival_at": self.arrival_at.isoformat(),
            "duration_minutes": self.duration_minutes,
            "prices": {"FIX": self.fix_price_sek},
            "currency": "SEK",
            "operator": "VR",
            "passenger": "Adult",
            "ticket_type": "Fix",
            "available": self.available,
            "bookable": self.bookable,
            "seats_left": self.seats_left,
            "has_disruption": self.has_disruption,
            "had_rebooked_disruption": self.had_rebooked_disruption,
            "schedule_references": self.schedule_references,
            "legs": [leg.to_dict() for leg in self.legs],
        }
