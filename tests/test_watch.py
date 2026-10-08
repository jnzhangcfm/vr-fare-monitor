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


def test_watch_uses_october_19_1610_arrival_cutoff_and_other_exact_cutoffs() -> None:
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
                "date": "2026-10-23",
                "status": "ok",
                "journeys": {
                    "outbound": [],
                    "return": [
                        journey("2026-10-23T10:59:00+02:00", 399),
                        journey("2026-10-23T11:00:00+02:00", 450),
                        journey("2026-10-23T14:00:00+02:00", 499),
                        journey("2026-10-23T16:00:00+02:00", 350, available=False),
                    ],
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

    october_19, october_23, october_28 = payload["targets"]

    assert payload["schema_version"] == 2
    assert october_19["latest_arrival_inclusive"] == "16:10"
    assert october_19["match_count"] == 2
    assert [item["fix_price_sek"] for item in october_19["matches"]] == [450, 499]
    assert all(item["arrival_at"][11:16] <= "16:10" for item in october_19["matches"])
    assert october_19["best_stop_loss_candidate"]["fix_price_sek"] == 450
    assert october_19["stop_loss_date"] == "2026-10-17"

    assert october_23["match_count"] == 2
    assert all(item["departure_at"][11:16] >= "11:00" for item in october_23["matches"])

    assert october_28["match_count"] == 1
    assert october_28["matches"][0]["arrival_at"] == "2026-10-28T17:59:00+01:00"
