from vr_fares.watch import build_watch_payload


def journey(
    departure_at: str,
    price: int,
    *,
    arrival_at: str | None = None,
    available: bool = True,
    bookable: bool = True,
):
    return {
        "journey_id": f"{departure_at}-{price}",
        "departure_at": departure_at,
        "arrival_at": arrival_at or departure_at,
        "duration_minutes": 180,
        "prices": {"FIX": price},
        "available": available,
        "bookable": bookable,
        "seats_left": 3,
        "schedule_references": ["VR 1"],
    }


def test_watch_tracks_only_october_28_with_exclusive_arrival_cutoff() -> None:
    raw_scan = {
        "dates": [
            {
                "date": "2026-10-19",
                "status": "ok",
                "journeys": {
                    "outbound": [
                        journey(
                            "2026-10-19T06:00:00+02:00",
                            450,
                            arrival_at="2026-10-19T09:00:00+02:00",
                        ),
                        journey(
                            "2026-10-19T10:30:00+02:00",
                            499,
                            arrival_at="2026-10-19T16:10:00+02:00",
                        ),
                        journey(
                            "2026-10-19T10:31:00+02:00",
                            399,
                            arrival_at="2026-10-19T16:11:00+02:00",
                        ),
                        journey(
                            "2026-10-19T09:00:00+02:00",
                            520,
                            arrival_at="2026-10-19T12:30:00+02:00",
                        ),
                    ],
                    "return": [],
                },
            },
            {
                "date": "2026-10-28",
                "status": "ok",
                "journeys": {
                    "outbound": [
                        journey(
                            "2026-10-28T14:00:00+01:00",
                            499,
                            arrival_at="2026-10-28T17:59:00+01:00",
                        ),
                        journey(
                            "2026-10-28T14:30:00+01:00",
                            399,
                            arrival_at="2026-10-28T18:00:00+01:00",
                        ),
                    ],
                    "return": [],
                },
            },
        ]
    }

    payload = build_watch_payload(raw_scan, generated_at="2026-10-07T00:00:00+00:00")

    assert payload["schema_version"] == 2
    assert len(payload["targets"]) == 1
    october_28 = payload["targets"][0]
    assert october_28["travel_date"] == "2026-10-28"
    assert october_28["latest_arrival_exclusive"] == "18:00"
    assert october_28["match_count"] == 1
    assert october_28["best_price_sek"] == 499
    assert october_28["matches"][0]["arrival_at"] == "2026-10-28T17:59:00+01:00"
    assert len(payload["alerts"]) == 1
    assert all(item["travel_date"] == "2026-10-28" for item in payload["alerts"])
