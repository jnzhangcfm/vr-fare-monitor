import copy
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from vr_fares.calendar import eligible_dates, scan_window
from vr_fares.config import SCAN
from vr_fares.policy import rank_date_combinations, rank_globally
from vr_fares.storage import FareStore, SnapshotRecord
from vr_fares.vr_client import VRClientError, VRSchemaError

STOCKHOLM_TIMEZONE = ZoneInfo("Europe/Stockholm")


class VRSourceUnavailable(Exception):
    def __init__(self, code: str = "vr_unavailable") -> None:
        self.code = code
        super().__init__(code)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ScanService:
    def __init__(
        self,
        *,
        store: FareStore,
        vr_client: Any,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.vr_client = vr_client
        self.now = now or (lambda: datetime.now(UTC))
        self.sleep = sleep

    def get_scan(self, mode: str) -> dict[str, Any]:
        if mode not in SCAN.window_days:
            raise ValueError("invalid mode")
        now = _as_utc(self.now())
        snapshot = self.store.read_snapshot(mode)
        if snapshot is not None and self._is_fresh(snapshot, mode, now):
            return self._present(snapshot, now, freshness="fresh")
        owner = str(uuid.uuid4())
        if self.store.acquire_lease(mode, owner, now, now + SCAN.lease_ttl):
            try:
                refreshed = self._refresh(mode, now)
                return self._present(refreshed, now, freshness="fresh")
            except VRSourceUnavailable as error:
                self._record_failure(now, error.code)
                if snapshot is not None:
                    return self._present(snapshot, now, freshness="stale")
                raise
            finally:
                self.store.release_lease(mode, owner)
        return self._wait_for_refresh(mode, now, snapshot)

    def get_health(self) -> dict[str, Any]:
        return self._safe_health(self.store.read_health())

    def _is_fresh(self, snapshot: SnapshotRecord, mode: str, now: datetime) -> bool:
        return now - _as_utc(snapshot.created_at) <= SCAN.cache_ttls[mode]

    def _present(
        self, snapshot: SnapshotRecord, now: datetime, *, freshness: str
    ) -> dict[str, Any]:
        result = copy.deepcopy(snapshot.payload)
        age_seconds = max(0, int((now - _as_utc(snapshot.created_at)).total_seconds()))
        health = self._safe_health(self.store.read_health())
        if freshness == "stale" and health["status"] not in {"partial_failure", "degraded"}:
            health["status"] = "degraded"
        result["freshness"] = {
            "state": freshness,
            "cache_age_seconds": age_seconds,
            "last_successful_refresh": snapshot.last_successful_refresh.isoformat(),
        }
        result["health"] = health
        return result

    def _wait_for_refresh(
        self, mode: str, now: datetime, stale_snapshot: SnapshotRecord | None
    ) -> dict[str, Any]:
        deadline = time.monotonic() + SCAN.wait_for_refresh_seconds
        while time.monotonic() < deadline:
            snapshot = self.store.read_snapshot(mode)
            if snapshot is not None and self._is_fresh(snapshot, mode, now):
                return self._present(snapshot, now, freshness="fresh")
            self.sleep(SCAN.wait_poll_seconds)
        if stale_snapshot is not None:
            health = self.store.read_health()
            if health.get("status") == "unknown":
                self._record_failure(now, "refresh_in_progress")
            return self._present(stale_snapshot, now, freshness="stale")
        raise VRSourceUnavailable("refresh_in_progress")

    def _refresh(self, mode: str, now: datetime) -> SnapshotRecord:
        window_start, window_end = scan_window(
            now.astimezone(STOCKHOLM_TIMEZONE).date(), SCAN.window_days[mode]
        )
        dates: list[dict[str, Any]] = []
        all_ranking: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for travel_date in eligible_dates(window_start, window_end):
            try:
                outbound = self.vr_client.search("outbound", travel_date)
                self.sleep(0.3)
                inbound = self.vr_client.search("return", travel_date)
                ranked = rank_date_combinations(travel_date, outbound, inbound)
                status = "ok" if ranked.valid else "no_qualifying_journeys"
                date_result = {
                    "date": travel_date.isoformat(),
                    "status": status,
                    "journeys": {
                        "outbound": [journey.to_dict() for journey in outbound],
                        "return": [journey.to_dict() for journey in inbound],
                    },
                    "valid_combinations": ranked.valid,
                    "recommended_combinations": ranked.recommended,
                }
                dates.append(date_result)
                all_ranking.extend(ranked.valid)
                self.sleep(0.3)
            except Exception as error:  # classified below; individual dates can be partial failures
                code = self._safe_error_code(error)
                failures.append({"date": travel_date.isoformat(), "code": code})
                dates.append(
                    {
                        "date": travel_date.isoformat(),
                        "status": "source_failure",
                        "error": {"code": code},
                        "journeys": {"outbound": [], "return": []},
                        "valid_combinations": [],
                        "recommended_combinations": [],
                    }
                )
        if failures and len(failures) == len(dates):
            raise VRSourceUnavailable(failures[0]["code"])
        all_ranking = rank_globally(all_ranking)
        health = {
            "status": "partial_failure" if failures else "healthy",
            "last_successful_refresh": now.isoformat(),
            "last_vr_query": now.isoformat(),
            "last_error": {"code": failures[0]["code"]} if failures else None,
            "partial_failures": failures,
        }
        payload = {
            "mode": mode,
            "checked_at": now.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "source": "official_vr_api",
            "currency": "SEK",
            "dates": dates,
            "ranking": all_ranking,
        }
        snapshot = SnapshotRecord(
            mode=mode, payload=payload, created_at=now, last_successful_refresh=now
        )
        self.store.write_snapshot(snapshot)
        self.store.write_health(health)
        return snapshot

    def _record_failure(self, now: datetime, code: str) -> None:
        current = self.store.read_health()
        self.store.write_health(
            {
                "status": "degraded",
                "last_successful_refresh": current.get("last_successful_refresh"),
                "last_vr_query": now.isoformat(),
                "last_error": {"code": code},
                "partial_failures": current.get("partial_failures", []),
            }
        )

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        if isinstance(error, VRClientError):
            return error.code
        if isinstance(error, TimeoutError):
            return "vr_timeout"
        if isinstance(error, VRSchemaError):
            return "schema_drift"
        return "vr_unavailable"

    @staticmethod
    def _safe_health(health: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": health.get("status", "unknown"),
            "last_successful_refresh": health.get("last_successful_refresh"),
            "last_vr_query": health.get("last_vr_query"),
            "last_error": health.get("last_error"),
            "partial_failures": health.get("partial_failures", []),
        }
