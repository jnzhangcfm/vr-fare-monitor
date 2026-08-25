import json
from datetime import UTC, datetime

from vr_fares.history import append_observations, observations_from_scan


def journey(*, fix_price: int | None = 359, available: bool = True, bookable: bool = True) -> dict:
    return {
        "journey_id": "temporary-id",
        "travel_date": "2026-08-26",
        "departure_at": "2026-08-26T06:24:00+02:00",
        "arrival_at": "2026-08-26T10:02:00+02:00",
        "duration_minutes": 218,
        "prices": {"FIX": fix_price},
        "available": available,
        "bookable": bookable,
        "seats_left": 7,
        "has_disruption": False,
        "had_rebooked_disruption": False,
        "schedule_references": ["VR 2004"],
        "legs": [
            {
                "transport_type": 101,
                "vehicle_types": [1],
            }
        ],
    }


def scan_with(*, outbound: dict | None = None, inbound: dict | None = None) -> dict:
    return {
        "dates": [
            {
                "date": "2026-08-26",
                "journeys": {
                    "outbound": [outbound or journey()],
                    "return": [inbound] if inbound else [],
                },
            }
        ]
    }


def test_logical_identity_ignores_unstable_journey_id() -> None:
    first = journey()
    second = journey()
    second["journey_id"] = "changed-by-source"

    first_observation = observations_from_scan(
        scan_with(outbound=first),
        observed_at=datetime(2026, 8, 25, 10, tzinfo=UTC),
        observation_key="scheduled-06",
    )[0]
    second_observation = observations_from_scan(
        scan_with(outbound=second),
        observed_at=datetime(2026, 8, 25, 16, tzinfo=UTC),
        observation_key="scheduled-12",
    )[0]

    assert first_observation["logical_journey_identity"] == (
        "2026-08-26|outbound|VR 2004|2026-08-26T06:24:00+02:00"
    )
    assert (
        second_observation["logical_journey_identity"]
        == first_observation["logical_journey_identity"]
    )
    assert first_observation["journey_id"] == "temporary-id"


def test_observation_preserves_missing_fix_and_unavailable_states() -> None:
    item = observations_from_scan(
        scan_with(outbound=journey(fix_price=None, available=False, bookable=False)),
        observed_at=datetime(2026, 8, 25, 10, tzinfo=UTC),
        observation_key="scheduled-06",
    )[0]

    assert item["fix_price_sek"] is None
    assert item["fix_price_state"] == "missing"
    assert item["available"] is False
    assert item["bookable"] is False
    assert item["seats_left"] == 7


def test_append_writes_one_date_partitioned_jsonl_row_per_observation(tmp_path) -> None:
    records = observations_from_scan(
        scan_with(),
        observed_at=datetime(2026, 8, 25, 10, tzinfo=UTC),
        observation_key="scheduled-06",
    )

    appended = append_observations(tmp_path, records)

    history_path = tmp_path / "2026-08-25.jsonl"
    assert appended == 1
    assert history_path.exists()
    assert [json.loads(line) for line in history_path.read_text().splitlines()] == records


def test_append_suppresses_duplicate_observation_id_on_workflow_rerun(tmp_path) -> None:
    records = observations_from_scan(
        scan_with(),
        observed_at=datetime(2026, 8, 25, 10, tzinfo=UTC),
        observation_key="scheduled-06",
    )

    first = append_observations(tmp_path, records)
    second = append_observations(tmp_path, records)

    assert first == 1
    assert second == 0
    assert len((tmp_path / "2026-08-25.jsonl").read_text().splitlines()) == 1
