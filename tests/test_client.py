import unittest

from vr_fares.client import normalize_journey, search


class NormalizeJourneyTests(unittest.TestCase):
    def test_normalizes_adult_fix_fare_and_operational_fields(self) -> None:
        raw = {
            "id": "journey-1",
            "departure_at": "2026-08-26T15:48:00+02:00",
            "arrival_at": "2026-08-26T19:35:00+02:00",
            "available": True,
            "bookable": True,
            "has_disruption": True,
            "had_rebooked_disruption": False,
            "prices": {"FIX": "729.00", "FLEX": "879.00"},
            "departures": [
                {
                    "schedule_reference": 2009,
                    "transport_type": 101,
                    "traffic_provider": 812,
                    "departure_at": "2026-08-26T15:48:00+02:00",
                    "arrival_at": "2026-08-26T19:35:00+02:00",
                    "event": {"kind": "replacement"},
                    "messages": [{"content": "Replacement bus", "type": 1, "subtype": 0}],
                    "legs": [
                        {
                            "origin_id": "stockholm-id",
                            "destination_id": "goteborg-id",
                            "vehicle_types": [1, 2],
                            "travel_direction": 1,
                        }
                    ],
                }
            ],
        }

        result = normalize_journey(raw)

        self.assertEqual(result.get("journey_id"), "journey-1")
        self.assertEqual(result["train_numbers"], ["VR 2009"])
        self.assertEqual(result["duration_minutes"], 227)
        self.assertEqual(
            result["adult_fix"],
            {
                "amount": "729.00",
                "currency": "SEK",
                "passenger": "ADULT",
                "ticket_type": "FIX",
            },
        )
        self.assertTrue(result["has_disruption"])
        self.assertEqual(result["legs"][0]["event"], {"kind": "replacement"})
        self.assertEqual(result["legs"][0]["vehicle_types"], [1, 2])
        self.assertEqual(result["legs"][0]["messages"][0]["content"], "Replacement bus")


class SearchTests(unittest.TestCase):
    def test_search_sends_the_adult_payload_and_returns_normalized_json(self) -> None:
        calls = []

        def transport(endpoint, payload):
            calls.append((endpoint, payload))
            return [
                {
                    "id": "journey-2009",
                    "departures": [
                        {
                            "id": "journey-2009",
                            "legs": [],
                            "schedule_reference": 2009,
                            "transport_type": 101,
                            "traffic_provider": 812,
                            "departure_at": "2026-08-26T15:48:00+02:00",
                            "arrival_at": "2026-08-26T19:35:00+02:00",
                            "origin": {},
                            "destination": {},
                            "prices": {"FIX": "729.00"},
                            "reduced_from": {},
                            "campaign_types": [],
                            "messages": [],
                            "event": None,
                            "available_meal": False,
                        }
                    ],
                    "origin": {},
                    "destination": {},
                    "departure_at": "2026-08-26T15:48:00+02:00",
                    "arrival_at": "2026-08-26T19:35:00+02:00",
                    "available": True,
                    "bookable": True,
                    "passed": False,
                    "move": False,
                    "commuter": False,
                    "has_disruption": False,
                    "had_rebooked_disruption": False,
                    "seats_left": None,
                    "prices": {"FIX": "729.00"},
                    "reduced_from": {"FIX": "729.00"},
                    "campaign_types": [],
                }
            ]

        result = search("STOCKHOLM", "GOTEBORG", "2026-08-26", transport=transport)

        self.assertEqual(
            calls,
            [
                (
                    "https://api.vrresa.se/api/v1.0/departures/",
                    {
                        "origin_id": "b9501164-fbb4-454a-8918-38a042780790",
                        "destination_id": "b9501164-fbb4-454a-8918-38a042780795",
                        "date": "2026-08-26",
                        "for_outbound": True,
                        "passengers": [1],
                        "has_stroller": False,
                        "has_pet": False,
                        "wheelchairs": 0,
                        "walkers": 0,
                    },
                )
            ],
        )
        self.assertEqual(result["query"]["passenger"], "ADULT")
        self.assertEqual(result["query"]["ticket_type"], "FIX")
        self.assertEqual(result["journeys"][0]["train_numbers"], ["VR 2009"])
        self.assertEqual(result["journeys"][0]["adult_fix"]["amount"], "729.00")


if __name__ == "__main__":
    unittest.main()
