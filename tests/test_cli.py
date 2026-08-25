import io
import json
import unittest

from vr_fares.cli import main


class CliTests(unittest.TestCase):
    def test_search_command_emits_structured_json(self) -> None:
        stdout = io.StringIO()

        def fake_search(from_code, to_code, date):
            return {
                "query": {"from": from_code, "to": to_code, "date": date},
                "journeys": [{"train_numbers": ["VR 2004"]}],
            }

        exit_code = main(
            ["search", "--from", "GOTEBORG", "--to", "STOCKHOLM", "--date", "2026-08-27"],
            search_fn=fake_search,
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "query": {
                    "from": "GOTEBORG",
                    "to": "STOCKHOLM",
                    "date": "2026-08-27",
                },
                "journeys": [{"train_numbers": ["VR 2004"]}],
            },
        )


if __name__ == "__main__":
    unittest.main()
