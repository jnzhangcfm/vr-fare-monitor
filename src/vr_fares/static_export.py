"""Generate the public static JSON contract used by GitHub Pages."""

import argparse
import json
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        json.dump(value, temporary, ensure_ascii=False, indent=2, sort_keys=True)
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
            payload = service.get_scan(mode)
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
            "schema_version": 1,
            "generated_at": generated_at,
            "overall_status": self._overall_status(modes),
            "modes": modes,
        }
        _write_json(health_path, health)
        return result

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
    parser.add_argument("--mode", choices=("7d", "30d"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = StaticExporter().export_mode(args.mode, args.output_dir)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
