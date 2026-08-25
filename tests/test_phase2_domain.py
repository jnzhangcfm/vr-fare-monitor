from datetime import date, datetime, time

import pytest

from vr_fares.calendar import eligible_dates, scan_window
from vr_fares.domain import Journey
from vr_fares.policy import assess_journey, rank_date_combinations, rank_globally
from vr_fares.vr_client import VRSchemaError, parse_journeys


def raw_journey(*, departure: str, arrival: str, price: str | None = "729.00") -> dict:
    return {
        "id": "journey-1",
        "departure_at": departure,
        "arrival_at": arrival,
        "available": True,
        "bookable": True,
        "seats_left": 12,
        "has_disruption": False,
        "had_rebooked_disruption": False,
        "prices": {"FIX": price} if price is not None else {},
        "departures": [
            {
                "schedule_reference": 2004,
                "departure_at": departure,
                "arrival_at": arrival,
                "transport_type": 101,
                "traffic_provider": 812,
                "event": None,
                "messages": [],
                "legs": [{"vehicle_types": [1]}],
            }
        ],
    }


def journey(*, date_value: date, departure: time, arrival: time, price: int) -> Journey:
    return Journey(
        journey_id="fixture",
        travel_date=date_value,
        departure_at=datetime.combine(date_value, departure),
        arrival_at=datetime.combine(date_value, arrival),
        duration_minutes=(
            datetime.combine(date_value, arrival) - datetime.combine(date_value, departure)
        ).seconds
        // 60,
        available=True,
        bookable=True,
        seats_left=10,
        fix_price_sek=price,
        has_disruption=False,
        had_rebooked_disruption=False,
        schedule_references=["VR 2004"],
        legs=[],
    )


def test_scan_window_starts_tomorrow_and_has_inclusive_calendar_length() -> None:
    start, end = scan_window(date(2026, 8, 25), 7)

    assert start == date(2026, 8, 26)
    assert end == date(2026, 9, 1)
    assert (end - start).days + 1 == 7


def test_eligible_dates_skip_weekends_and_swedish_public_holidays() -> None:
    start, end = scan_window(date(2026, 12, 24), 7)

    assert (start, end) == (date(2026, 12, 25), date(2026, 12, 31))
    assert eligible_dates(start, end) == [
        date(2026, 12, 28),
        date(2026, 12, 29),
        date(2026, 12, 30),
        date(2026, 12, 31),
    ]


def test_parser_preserves_fix_metadata_and_replacement_transport() -> None:
    raw = raw_journey(
        departure="2026-08-26T06:24:00+02:00",
        arrival="2026-08-26T09:50:00+02:00",
        price="579.00",
    )
    raw["has_disruption"] = True
    raw["departures"][0]["event"] = {"kind": "replacement"}
    raw["departures"][0]["messages"] = [{"content": "Replacement transport"}]

    result = parse_journeys([raw], date(2026, 8, 26))

    assert result[0].fix_price_sek == 579
    assert result[0].schedule_references == ["VR 2004"]
    assert result[0].has_disruption is True
    assert result[0].legs[0].event == {"kind": "replacement"}


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({}, "missing journey departure_at"),
        (
            raw_journey(
                departure="2026-08-26T06:24:00+02:00",
                arrival="2026-08-26T09:50:00+02:00",
                price="579.50",
            ),
            "invalid FIX price",
        ),
        (
            raw_journey(
                departure="2026-08-26T06:24:00+02:00",
                arrival="2026-08-26T09:50:00+02:00",
                price="free",
            ),
            "invalid FIX price",
        ),
    ],
)
def test_parser_rejects_schema_drift_instead_of_inventing_a_fare(raw: dict, reason: str) -> None:
    with pytest.raises(VRSchemaError, match=reason):
        parse_journeys([raw], date(2026, 8, 26))


def test_assessment_rejects_over_four_hours_but_retains_replacement_transport() -> None:
    target_date = date(2026, 8, 26)
    bus = journey(date_value=target_date, departure=time(6, 24), arrival=time(10, 14), price=579)
    overlong = journey(
        date_value=target_date, departure=time(6, 24), arrival=time(10, 25), price=399
    )

    assert assess_journey(bus, "outbound").eligible is True
    assert assess_journey(bus, "outbound").soft_duration_penalty is True
    assert assess_journey(overlong, "outbound").eligible is False
    assert assess_journey(overlong, "outbound").reasons == ["duration_over_4h"]


def test_missing_fix_price_is_not_treated_as_a_zero_price() -> None:
    target_date = date(2026, 8, 26)
    no_fix = journey(date_value=target_date, departure=time(6, 24), arrival=time(9, 50), price=0)
    no_fix = Journey(**{**no_fix.__dict__, "fix_price_sek": None})

    result = assess_journey(no_fix, "outbound")

    assert result.eligible is False
    assert result.reasons == ["missing_fix_price"]


def test_early_return_is_recommended_only_when_special_price_rule_holds() -> None:
    target_date = date(2026, 8, 26)
    outbound = journey(
        date_value=target_date, departure=time(7, 24), arrival=time(10, 50), price=700
    )
    early_return = journey(
        date_value=target_date, departure=time(15, 48), arrival=time(19, 35), price=650
    )
    later_return = journey(
        date_value=target_date, departure=time(16, 59), arrival=time(20, 45), price=800
    )

    result = rank_date_combinations(target_date, [outbound], [early_return, later_return])

    assert len(result.valid) == 2
    assert result.valid[0]["early_return"] is True
    assert result.valid[0]["recommended"] is True
    assert result.valid[0]["early_return_rule"] == "at_least_150_sek_cheaper_than_later_return"


def test_near_tie_prefers_later_outbound_before_shorter_duration() -> None:
    target_date = date(2026, 8, 26)
    early_outbound = journey(
        date_value=target_date, departure=time(6, 24), arrival=time(9, 40), price=600
    )
    later_outbound = journey(
        date_value=target_date, departure=time(7, 24), arrival=time(11, 0), price=640
    )
    return_trip = journey(
        date_value=target_date, departure=time(16, 59), arrival=time(20, 45), price=700
    )

    result = rank_date_combinations(target_date, [early_outbound, later_outbound], [return_trip])

    assert result.recommended[0]["outbound"]["departure_at"].endswith("07:24:00")
    assert result.recommended[0]["ranking_rationale"][:2] == [
        "within_50_sek_near_tie",
        "later_outbound_preferred",
    ]


def test_global_near_tie_keeps_convenience_order_across_travel_dates() -> None:
    first_date = date(2026, 8, 26)
    second_date = date(2026, 8, 27)
    first = rank_date_combinations(
        first_date,
        [journey(date_value=first_date, departure=time(6, 24), arrival=time(9, 40), price=600)],
        [journey(date_value=first_date, departure=time(16, 59), arrival=time(20, 45), price=700)],
    ).valid
    second = rank_date_combinations(
        second_date,
        [journey(date_value=second_date, departure=time(7, 24), arrival=time(11, 0), price=640)],
        [journey(date_value=second_date, departure=time(16, 59), arrival=time(20, 45), price=700)],
    ).valid

    result = rank_globally(first + second)

    assert result[0]["date"] == "2026-08-27"
    assert result[0]["global_ranking_rationale"][:2] == [
        "within_50_sek_near_tie",
        "later_outbound_preferred",
    ]
