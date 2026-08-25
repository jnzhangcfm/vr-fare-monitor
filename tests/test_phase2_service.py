from datetime import UTC, date, datetime, time, timedelta
from threading import Event, Thread

import pytest

from vr_fares.domain import Journey
from vr_fares.service import ScanService, VRSourceUnavailable
from vr_fares.storage import InMemoryStore


def fixture_journey(travel_date: date, *, outbound: bool) -> Journey:
    departure = time(7, 24) if outbound else time(16, 59)
    arrival = time(10, 50) if outbound else time(20, 45)
    return Journey(
        journey_id=f"{'o' if outbound else 'r'}-{travel_date}",
        travel_date=travel_date,
        departure_at=datetime.combine(travel_date, departure).replace(tzinfo=UTC),
        arrival_at=datetime.combine(travel_date, arrival).replace(tzinfo=UTC),
        duration_minutes=206 if outbound else 226,
        available=True,
        bookable=True,
        seats_left=8,
        fix_price_sek=600 if outbound else 700,
        has_disruption=False,
        had_rebooked_disruption=False,
        schedule_references=["VR 2004" if outbound else "VR 2011"],
        legs=[],
    )


class FakeVRClient:
    def __init__(self, *, blocker: Event | None = None, failure: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.blocker = blocker
        self.failure = failure

    def search(self, direction: str, travel_date: date) -> list[Journey]:
        self.calls.append((direction, travel_date.isoformat()))
        if self.blocker is not None:
            self.blocker.wait(timeout=2)
        if self.failure is not None:
            raise self.failure
        return [fixture_journey(travel_date, outbound=direction == "outbound")]


def make_service(client: FakeVRClient, store: InMemoryStore, now: datetime) -> ScanService:
    return ScanService(store=store, vr_client=client, now=lambda: now, sleep=lambda _: None)


def test_fresh_snapshot_is_reused_without_new_vr_requests() -> None:
    now = datetime(2026, 8, 25, 9, tzinfo=UTC)
    client = FakeVRClient()
    service = make_service(client, InMemoryStore(), now)

    first = service.get_scan("7d")
    second = service.get_scan("7d")

    assert first["freshness"]["state"] == "fresh"
    assert second["freshness"]["state"] == "fresh"
    assert len(client.calls) == 10  # five eligible weekdays, two fixed directions


def test_30d_snapshot_is_reused_without_a_second_full_scan() -> None:
    now = datetime(2026, 8, 25, 9, tzinfo=UTC)
    client = FakeVRClient()
    service = make_service(client, InMemoryStore(), now)

    first = service.get_scan("30d")
    second = service.get_scan("30d")

    assert first["window_start"] == "2026-08-26"
    assert first["window_end"] == "2026-09-24"
    assert second["freshness"]["state"] == "fresh"
    assert len(client.calls) == 44  # 22 weekdays, outbound and return once each


def test_window_uses_stockholm_calendar_day_not_utc_midnight() -> None:
    utc_late = datetime(2026, 8, 25, 23, 30, tzinfo=UTC)
    service = make_service(FakeVRClient(), InMemoryStore(), utc_late)

    result = service.get_scan("7d")

    assert result["window_start"] == "2026-08-27"
    assert result["window_end"] == "2026-09-02"


def test_failed_refresh_returns_explicit_stale_cache_not_empty_success() -> None:
    now = datetime(2026, 8, 25, 9, tzinfo=UTC)
    store = InMemoryStore()
    initial = make_service(FakeVRClient(), store, now).get_scan("7d")
    stale_now = now + timedelta(minutes=16)
    failed = make_service(FakeVRClient(failure=TimeoutError()), store, stale_now)

    result = failed.get_scan("7d")

    assert result["dates"] == initial["dates"]
    assert result["freshness"]["state"] == "stale"
    assert result["health"]["status"] == "degraded"
    assert result["health"]["last_error"]["code"] == "vr_timeout"


def test_first_refresh_failure_without_cache_is_source_failure() -> None:
    now = datetime(2026, 8, 25, 9, tzinfo=UTC)
    service = make_service(FakeVRClient(failure=TimeoutError()), InMemoryStore(), now)

    with pytest.raises(VRSourceUnavailable):
        service.get_scan("7d")


def test_concurrent_stale_requests_share_one_refresh_lease() -> None:
    now = datetime(2026, 8, 25, 9, tzinfo=UTC)
    store = InMemoryStore()
    make_service(FakeVRClient(), store, now).get_scan("7d")
    release = Event()
    slow_client = FakeVRClient(blocker=release)
    service = make_service(slow_client, store, now + timedelta(minutes=16))
    results: list[dict] = []

    first = Thread(target=lambda: results.append(service.get_scan("7d")))
    second = Thread(target=lambda: results.append(service.get_scan("7d")))
    first.start()
    second.start()
    release.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert len(results) == 2
    assert len(slow_client.calls) == 10
    assert all(result["freshness"]["state"] == "fresh" for result in results)
