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


def learning_scan_payload() -> dict:
    payload = scan_payload("30d")
    payload["dates"] = [
        {
            "date": "2026-08-26",
            "status": "ok",
            "journeys": {
                "outbound": [
                    {
                        "journey_id": "source-journey-1",
                        "travel_date": "2026-08-26",
                        "departure_at": "2026-08-26T06:24:00+02:00",
                        "arrival_at": "2026-08-26T10:02:00+02:00",
                        "duration_minutes": 218,
                        "prices": {"FIX": 359},
                        "available": True,
                        "bookable": True,
                        "seats_left": 5,
                        "has_disruption": False,
                        "had_rebooked_disruption": False,
                        "schedule_references": ["VR 2004"],
                        "legs": [{"transport_type": 101, "vehicle_types": [1]}],
                    }
                ],
                "return": [],
            },
            "valid_combinations": [],
            "recommended_combinations": [],
        }
    ]
    return payload


class LearningService:
    def get_scan(self, mode: str) -> dict:
        assert mode == "30d"
        return learning_scan_payload()


class UnexpectedLearningService:
    def get_scan(self, mode: str) -> dict:
        raise AssertionError("inactive learning period must not query VR")


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


def test_learning_export_derives_7d_appends_history_and_updates_health(tmp_path) -> None:
    exporter = StaticExporter(
        service_factory=LearningService,
        now=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )

    result = exporter.export_learning(tmp_path, observation_key="scheduled-06", force=True)

    data_7d = json.loads((tmp_path / "data" / "7d.json").read_text())
    data_30d = json.loads((tmp_path / "data" / "30d.json").read_text())
    health = json.loads((tmp_path / "data" / "health.json").read_text())
    summary = json.loads((tmp_path / "data" / "learning-summary.json").read_text())
    history_rows = (tmp_path / "history" / "2026-08-25.jsonl").read_text().splitlines()

    assert result == {
        "mode": "learning",
        "status": "healthy",
        "data_written": True,
        "history_appended": 1,
    }
    assert data_7d["mode"] == "7d"
    assert data_7d["window_end"] == "2026-09-01"
    assert data_30d["mode"] == "30d"
    assert data_30d["dates"][0]["journey_counts"] == {"outbound": 1, "return": 0}
    assert len(history_rows) == 1
    assert summary["coverage"]["observation_count"] == 1
    assert health["learning"]["status"] == "healthy"
    assert health["learning"]["last_history_append_at"] == "2026-08-25T10:00:00+00:00"


def test_learning_export_rerun_does_not_duplicate_history(tmp_path) -> None:
    exporter = StaticExporter(
        service_factory=LearningService,
        now=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )

    first = exporter.export_learning(tmp_path, observation_key="scheduled-06", force=True)
    second = exporter.export_learning(tmp_path, observation_key="scheduled-06", force=True)

    assert first["history_appended"] == 1
    assert second["history_appended"] == 0
    assert len((tmp_path / "history" / "2026-08-25.jsonl").read_text().splitlines()) == 1


def test_failed_learning_export_preserves_current_data_and_writes_no_history(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "30d.json").write_text('{"previous":"30d"}\n')
    (data_dir / "7d.json").write_text('{"previous":"7d"}\n')
    exporter = StaticExporter(
        service_factory=FailingService,
        now=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )

    result = exporter.export_learning(tmp_path, observation_key="scheduled-06", force=True)

    health = json.loads((data_dir / "health.json").read_text())
    assert result == {
        "mode": "learning",
        "status": "source_failure",
        "data_written": False,
        "history_appended": 0,
    }
    assert (data_dir / "30d.json").read_text() == '{"previous":"30d"}\n'
    assert (data_dir / "7d.json").read_text() == '{"previous":"7d"}\n'
    assert not (tmp_path / "history").exists()
    assert health["overall_status"] == "degraded"
    assert health["learning"]["status"] == "source_failure"


def test_inactive_learning_period_does_not_query_or_append_history(tmp_path) -> None:
    exporter = StaticExporter(
        service_factory=UnexpectedLearningService,
        now=lambda: datetime(2026, 9, 9, 10, tzinfo=UTC),
    )

    result = exporter.export_learning(tmp_path, observation_key="scheduled-06")

    assert result == {
        "mode": "learning",
        "status": "learning_inactive",
        "data_written": False,
        "history_appended": 0,
    }
    assert not (tmp_path / "history").exists()
