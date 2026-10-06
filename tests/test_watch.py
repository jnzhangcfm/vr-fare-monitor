from vr_fares.watch import build_watch_payload


def journey(departure_at: str, price: int, *, available: bool = True, bookable: bool = True):
    return {
        "journey_id": f"{departure_at}-{price}",
        "departure_at": departure_at,
        "arrival_at": departure_at,
        "duration_minutes": 180,
        "prices": {"FIX": price},
        "available": available,
        "bookable": bookable,
        "seats_left": 3,
        "schedule_references": ["VR 1"],
    }


def test_watch_uses_exact_dates_times_and_strict_sub_500_threshold() -> None:
    raw_scan = {
        "dates": [
            {
                "date": "2026-10-19",
                "status": "ok",
                "journeys": {
                    "outbound": [
                        journey("2026-10-19T05:30:00+02:00", 499),
                        journey("2026-10-19T15:30:00+02:00", 500),
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
        ]
    }

    payload = build_watch_payload(raw_scan, generated_at="2026-10-07T00:00:00+00:00")

    assert payload["price_threshold_sek"] == 500
    assert payload["has_alerts"] is True
    assert payload["alert_count"] == 3

    outbound, inbound = payload["targets"]
    assert outbound["match_count"] == 1
    assert outbound["matches"][0]["fix_price_sek"] == 499
    assert outbound["matches"][0]["departure_at"] == "2026-10-19T05:30:00+02:00"

    assert inbound["earliest_departure"] == "11:00"
    assert [item["fix_price_sek"] for item in inbound["matches"]] == [450, 499]
    assert all(item["departure_at"][11:16] >= "11:00" for item in inbound["matches"])
