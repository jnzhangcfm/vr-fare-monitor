"""Generate the public static JSON contract used by GitHub Pages."""

import argparse
import copy
import json
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from vr_fares.config import LEARNING
from vr_fares.history import append_observations, load_observations, observations_from_scan
from vr_fares.learning import build_learning_summary, learning_is_active
from vr_fares.policy import rank_globally
from vr_fares.service import ScanService, VRSourceUnavailable
from vr_fares.storage import InMemoryStore
from vr_fares.vr_client import VRClient


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        json.dump(
            value,
            temporary,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def build_scan_service() -> ScanService:
    return ScanService(store=InMemoryStore(), vr_client=VRClient())


class StaticExporter:
    def __init__(
        self,
        *,
        service_factory: Callable[[], Any] = build_scan_service,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.service_factory = service_factory
        self.now = now

    def export_mode(self, mode: str, output_dir: Path) -> dict[str, Any]:
        if mode not in {"7d", "30d"}:
            raise ValueError("mode must be 7d or 30d")
        generated_at = self.now().astimezone(UTC).isoformat()
        output_dir.mkdir(parents=True, exist_ok=True)
        data_path = output_dir / f"{mode}.json"
        health_path = output_dir / "health.json"
        existing_health = _load_json(health_path, {"schema_version": 1, "modes": {}})
        modes = existing_health.get("modes")
        if not isinstance(modes, dict):
            modes = {}
        try:
            service = self.service_factory()
            payload = self._public_payload(service.get_scan(mode))
            payload["publication"] = {
                "schema_version": 1,
                "generated_at": generated_at,
                "data_path": data_path.name,
            }
            _write_json(data_path, payload)
            scan_health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
            modes[mode] = {
                "status": scan_health.get("status", "healthy"),
                "data_available": True,
                "last_attempt_at": generated_at,
                "last_successful_refresh": scan_health.get("last_successful_refresh"),
                "last_error": scan_health.get("last_error"),
                "data_path": data_path.name,
            }
            result = {"mode": mode, "status": modes[mode]["status"], "data_written": True}
        except Exception as error:
            previous = modes.get(mode) if isinstance(modes.get(mode), dict) else {}
            modes[mode] = {
                "status": "source_failure",
                "data_available": data_path.exists(),
                "last_attempt_at": generated_at,
                "last_successful_refresh": previous.get("last_successful_refresh"),
                "last_error": {"code": self._safe_error_code(error)},
                "data_path": data_path.name,
            }
            result = {"mode": mode, "status": "source_failure", "data_written": False}
        health = {
            **existing_health,
            "schema_version": 1,
            "generated_at": generated_at,
            "overall_status": self._overall_status(modes),
            "modes": modes,
        }
        _write_json(health_path, health)
        return result

    def export_learning(
        self, output_dir: Path, *, observation_key: str, force: bool = False
    ) -> dict[str, Any]:
        """Run one 30d observation and publish derived current state plus history."""
        generated_now = self.now().astimezone(UTC)
        generated_at = generated_now.isoformat()
        data_dir = output_dir / "data"
        history_dir = output_dir / "history"
        data_dir.mkdir(parents=True, exist_ok=True)
        health_path = data_dir / "health.json"
        existing_health = _load_json(health_path, {"schema_version": 1, "modes": {}})
        modes = existing_health.get("modes")
        if not isinstance(modes, dict):
            modes = {}
        if not force and not learning_is_active(generated_now):
            learning = self._learning_health(
                existing_health,
                generated_at=generated_at,
                status="inactive",
                last_error=None,
            )
            health = {
                **existing_health,
                "schema_version": 1,
                "generated_at": generated_at,
                "overall_status": self._overall_status(modes),
                "modes": modes,
                "learning": learning,
            }
            _write_json(health_path, health)
            return {
                "mode": "learning",
                "status": "learning_inactive",
                "data_written": False,
                "history_appended": 0,
            }
        try:
            service = self.service_factory()
            raw_30d = service.get_scan("30d")
            scan_health = raw_30d.get("health")
            if not isinstance(scan_health, dict) or scan_health.get("status") != "healthy":
                raise VRSourceUnavailable(
                    str(scan_health.get("status", "source_failure"))
                    if isinstance(scan_health, dict)
                    else "source_failure"
                )
            raw_7d = self._derive_7d(raw_30d)
            for mode, raw_payload in (("30d", raw_30d), ("7d", raw_7d)):
                payload = self._public_payload(raw_payload)
                payload["publication"] = {
                    "schema_version": 1,
                    "generated_at": generated_at,
                    "data_path": f"{mode}.json",
                }
                _write_json(data_dir / f"{mode}.json", payload)
                payload_health = payload.get("health")
                if not isinstance(payload_health, dict):
                    payload_health = {}
                modes[mode] = {
                    "status": payload_health.get("status", "healthy"),
                    "data_available": True,
                    "last_attempt_at": generated_at,
                    "last_successful_refresh": payload_health.get("last_successful_refresh"),
                    "last_error": payload_health.get("last_error"),
                    "data_path": f"{mode}.json",
                }
            records = observations_from_scan(
                raw_30d, observed_at=generated_now, observation_key=observation_key
            )
            appended = append_observations(history_dir, records)
            previous_learning = existing_health.get("learning")
            previous_failed_count = (
                previous_learning.get("failed_scan_count", 0)
                if isinstance(previous_learning, dict)
                else 0
            )
            summary = build_learning_summary(
                load_observations(history_dir),
                now=generated_now,
                failed_scan_count=previous_failed_count,
            )
            _write_json(data_dir / "learning-summary.json", summary)
            learning = self._learning_health(
                existing_health,
                generated_at=generated_at,
                status="healthy",
                last_error=None,
                last_successful_scan=generated_at,
                last_history_append_at=generated_at if appended else None,
                successful_scan_count=summary["coverage"]["successful_scan_count"],
                failed_scan_count=previous_failed_count,
            )
            health = {
                **existing_health,
                "schema_version": 1,
                "generated_at": generated_at,
                "overall_status": self._overall_status(modes),
                "modes": modes,
                "learning": learning,
            }
            _write_json(health_path, health)
            return {
                "mode": "learning",
                "status": "healthy",
                "data_written": True,
                "history_appended": appended,
            }
        except Exception as error:
            learning = self._learning_health(
                existing_health,
                generated_at=generated_at,
                status="source_failure",
                last_error={"code": self._safe_error_code(error)},
                failed_scan_count=self._failed_scan_count(existing_health) + 1,
            )
            health = {
                **existing_health,
                "schema_version": 1,
                "generated_at": generated_at,
                "overall_status": "degraded",
                "modes": modes,
                "learning": learning,
            }
            _write_json(health_path, health)
            return {
                "mode": "learning",
                "status": "source_failure",
                "data_written": False,
                "history_appended": 0,
            }

    @staticmethod
    def _derive_7d(raw_30d: dict[str, Any]) -> dict[str, Any]:
        """Project a raw 30d result onto its first seven calendar days."""
        window_start = date.fromisoformat(raw_30d["window_start"])
        window_end = window_start + timedelta(days=6)
        selected_dates = [
            copy.deepcopy(entry)
            for entry in raw_30d.get("dates", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("date"), str)
            and window_start <= date.fromisoformat(entry["date"]) <= window_end
        ]
        combinations: list[dict[str, Any]] = []
        for entry in selected_dates:
            valid = entry.get("valid_combinations")
            if isinstance(valid, list):
                combinations.extend(copy.deepcopy(valid))
        result = copy.deepcopy(raw_30d)
        result.update(
            {
                "mode": "7d",
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "dates": selected_dates,
                "ranking": rank_globally(combinations),
            }
        )
        return result

    @staticmethod
    def _failed_scan_count(health: dict[str, Any]) -> int:
        learning = health.get("learning")
        if not isinstance(learning, dict):
            return 0
        count = learning.get("failed_scan_count")
        return count if isinstance(count, int) else 0

    @staticmethod
    def _learning_health(
        existing_health: dict[str, Any],
        *,
        generated_at: str,
        status: str,
        last_error: dict[str, str] | None,
        last_successful_scan: str | None = None,
        last_history_append_at: str | None = None,
        successful_scan_count: int | None = None,
        failed_scan_count: int | None = None,
    ) -> dict[str, Any]:
        previous = existing_health.get("learning")
        if not isinstance(previous, dict):
            previous = {}
        return {
            "status": status,
            "active": learning_is_active(datetime.fromisoformat(generated_at)),
            "learning_start_date": LEARNING.start_date.isoformat(),
            "learning_end_date": LEARNING.end_date.isoformat(),
            "last_attempt_at": generated_at,
            "last_successful_scan": last_successful_scan or previous.get("last_successful_scan"),
            "last_history_append_at": last_history_append_at
            or previous.get("last_history_append_at"),
            "successful_scan_count": successful_scan_count
            if successful_scan_count is not None
            else previous.get("successful_scan_count", 0),
            "failed_scan_count": failed_scan_count
            if failed_scan_count is not None
            else previous.get("failed_scan_count", 0),
            "last_error": last_error,
        }

    @staticmethod
    def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
        public_payload = dict(payload)
        compact_dates = []
        for entry in payload.get("dates", []):
            journeys = entry.get("journeys", {})
            compact_dates.append(
                {
                    "date": entry.get("date"),
                    "status": entry.get("status"),
                    "journey_counts": {
                        "outbound": len(journeys.get("outbound", [])),
                        "return": len(journeys.get("return", [])),
                    },
                    "valid_combination_count": len(entry.get("valid_combinations", [])),
                    "recommended_combination_count": len(entry.get("recommended_combinations", [])),
                }
            )
        public_payload["dates"] = compact_dates
        return public_payload

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        if isinstance(error, VRSourceUnavailable):
            return error.code
        return "export_failure"

    @staticmethod
    def _overall_status(modes: dict[str, Any]) -> str:
        states = [entry.get("status") for entry in modes.values() if isinstance(entry, dict)]
        if any(state in {"source_failure", "degraded", "partial_failure"} for state in states):
            return "degraded"
        if any(state == "healthy" for state in states):
            return "healthy"
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export static public VR fare JSON")
    parser.add_argument("--mode", choices=("7d", "30d"))
    parser.add_argument("--learning", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--observation-key", default="manual")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.learning == (args.mode is not None):
        parser.error("provide exactly one of --mode or --learning")
    if args.learning:
        result = StaticExporter().export_learning(
            args.output_dir, observation_key=args.observation_key, force=args.force
        )
    else:
        result = StaticExporter().export_mode(args.mode, args.output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
