import copy
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any, Protocol


@dataclass(frozen=True)
class SnapshotRecord:
    mode: str
    payload: dict[str, Any]
    created_at: datetime
    last_successful_refresh: datetime


class FareStore(Protocol):
    def read_snapshot(self, mode: str) -> SnapshotRecord | None: ...

    def write_snapshot(self, snapshot: SnapshotRecord) -> None: ...

    def read_health(self) -> dict[str, Any]: ...

    def write_health(self, health: dict[str, Any]) -> None: ...

    def acquire_lease(self, mode: str, owner: str, now: datetime, expires_at: datetime) -> bool: ...

    def release_lease(self, mode: str, owner: str) -> None: ...


class InMemoryStore:
    """Thread-safe local/test implementation of the production storage contract."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[str, SnapshotRecord] = {}
        self._health: dict[str, Any] = {
            "status": "unknown",
            "last_successful_refresh": None,
            "last_vr_query": None,
            "last_error": None,
        }
        self._leases: dict[str, tuple[str, datetime]] = {}

    def read_snapshot(self, mode: str) -> SnapshotRecord | None:
        with self._lock:
            snapshot = self._snapshots.get(mode)
            return copy.deepcopy(snapshot)

    def write_snapshot(self, snapshot: SnapshotRecord) -> None:
        with self._lock:
            self._snapshots[snapshot.mode] = copy.deepcopy(snapshot)

    def read_health(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._health)

    def write_health(self, health: dict[str, Any]) -> None:
        with self._lock:
            self._health = copy.deepcopy(health)

    def acquire_lease(self, mode: str, owner: str, now: datetime, expires_at: datetime) -> bool:
        with self._lock:
            active = self._leases.get(mode)
            if active is not None and active[1] > now and active[0] != owner:
                return False
            self._leases[mode] = (owner, expires_at)
            return True

    def release_lease(self, mode: str, owner: str) -> None:
        with self._lock:
            active = self._leases.get(mode)
            if active is not None and active[0] == owner:
                del self._leases[mode]
