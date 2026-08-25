import json
from datetime import UTC, datetime

from vr_fares.service import VRSourceUnavailable
from vr_fares.static_export import StaticExporter


def scan_payload(mode: str) -> dict:
    return {
        "mode": mode,
        "checked_at": "2026-08-25T09:00:00+00:00",
        "window_start": "2026-08-26",
        "window_end": "2026-09-01" if mode == "7d" else "2026-09-24",
        "source": "official_vr_api",
        "currency": "SEK",
        "dates": [],
        "ranking": [],
        "freshness": {
            "state": "fresh",
            "cache_age_seconds": 0,
            "last_successful_refresh": "2026-08-25T09:00:00+00:00",
        },
        "health": {
            "status": "healthy",
            "last_successful_refresh": "2026-08-25T09:00:00+00:00",
            "last_vr_query": "2026-08-25T09:00:00+00:00",
            "last_error": None,
            "partial_failures": [],
        },
    }


def populated_scan_payload(mode: str) -> dict:
    payload = scan_payload(mode)
    payload["dates"] = [
        {
            "date": "2026-08-26",
            "status": "success",
            "journeys": {
                "outbound": [{"journey_id": "outbound-1"}],
                "return": [{"journey_id": "return-1"}, {"journey_id": "return-2"}],
            },
            "valid_combinations": [{"id": "valid-1"}, {"id": "valid-2"}],
            "recommended_combinations": [{"id": "recommended-1"}],
        }
    ]
    payload["ranking"] = [{"global_rank": 1, "prices": {"total_sek": 498}}]
    return payload


class SuccessfulService:
    def get_scan(self, mode: str) -> dict:
        return scan_payload(mode)


class FailingService:
    def get_scan(self, mode: str) -> dict:
        raise VRSourceUnavailable("vr_timeout")


class PopulatedService:
    def get_scan(self, mode: str) -> dict:
        return populated_scan_payload(mode)


def test_export_writes_public_data_and_health_metadata(tmp_path) -> None:
    exporter = StaticExporter(
        service_factory=SuccessfulService,
        now=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )

    result = exporter.export_mode("7d", tmp_path)

    data = json.loads((tmp_path / "7d.json").read_text())
    health = json.loads((tmp_path / "health.json").read_text())
    assert result == {"mode": "7d", "status": "healthy", "data_written": True}
    assert data["publication"] == {
        "schema_version": 1,
        "generated_at": "2026-08-25T10:00:00+00:00",
        "data_path": "7d.json",
    }
    assert health["overall_status"] == "healthy"
    assert health["modes"]["7d"]["status"] == "healthy"
    assert health["modes"]["7d"]["data_available"] is True


def test_failed_export_preserves_previous_data_and_records_safe_health(tmp_path) -> None:
    data_path = tmp_path / "30d.json"
    data_path.write_text('{"previous":"valid"}\n')
    (tmp_path / "health.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "modes": {
                    "30d": {
                        "status": "healthy",
                        "data_available": True,
                        "last_successful_refresh": "2026-08-24T10:00:00+00:00",
                    }
                },
            }
        )
    )
    exporter = StaticExporter(
        service_factory=FailingService,
        now=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )

    result = exporter.export_mode("30d", tmp_path)

    health = json.loads((tmp_path / "health.json").read_text())
    assert result == {"mode": "30d", "status": "source_failure", "data_written": False}
    assert data_path.read_text() == '{"previous":"valid"}\n'
    assert health["overall_status"] == "degraded"
    assert health["modes"]["30d"] == {
        "status": "source_failure",
        "data_available": True,
        "last_attempt_at": "2026-08-25T10:00:00+00:00",
        "last_successful_refresh": "2026-08-24T10:00:00+00:00",
        "last_error": {"code": "vr_timeout"},
        "data_path": "30d.json",
    }


def test_export_publishes_rankings_and_compact_date_summaries(tmp_path) -> None:
    exporter = StaticExporter(
        service_factory=PopulatedService,
        now=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )

    exporter.export_mode("7d", tmp_path)

    data = json.loads((tmp_path / "7d.json").read_text())
    assert data["ranking"] == [{"global_rank": 1, "prices": {"total_sek": 498}}]
    assert data["dates"] == [
        {
            "date": "2026-08-26",
            "status": "success",
            "journey_counts": {"outbound": 1, "return": 2},
            "valid_combination_count": 2,
            "recommended_combination_count": 1,
        }
    ]
