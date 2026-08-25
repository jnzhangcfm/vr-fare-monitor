import json
from datetime import date

import httpx

from vr_fares.vr_client import DEPARTURES_ENDPOINT, VRClient


def complete_response() -> list[dict]:
    return [
        {
            "id": "journey-2004",
            "departure_at": "2026-08-26T06:24:00+02:00",
            "arrival_at": "2026-08-26T09:50:00+02:00",
            "available": True,
            "bookable": True,
            "seats_left": 10,
            "prices": {"FIX": "579.00"},
            "has_disruption": False,
            "had_rebooked_disruption": False,
            "departures": [
                {
                    "schedule_reference": 2004,
                    "departure_at": "2026-08-26T06:24:00+02:00",
                    "arrival_at": "2026-08-26T09:50:00+02:00",
                    "transport_type": 101,
                    "traffic_provider": 812,
                    "event": None,
                    "messages": [],
                    "legs": [{"vehicle_types": [1]}],
                }
            ],
        }
    ]


def test_new_client_retries_once_then_sends_fixed_adult_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json=complete_response())

    client = VRClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_attempts=2,
        sleep=lambda _: None,
        random_value=lambda: 0,
    )

    journeys = client.search("outbound", date(2026, 8, 26))

    assert len(requests) == 2
    assert str(requests[0].url) == DEPARTURES_ENDPOINT
    assert json.loads(requests[0].content) == {
        "origin_id": "b9501164-fbb4-454a-8918-38a042780795",
        "destination_id": "b9501164-fbb4-454a-8918-38a042780790",
        "date": "2026-08-26",
        "for_outbound": True,
        "passengers": [1],
        "has_stroller": False,
        "has_pet": False,
        "wheelchairs": 0,
        "walkers": 0,
    }
    assert journeys[0].fix_price_sek == 579
