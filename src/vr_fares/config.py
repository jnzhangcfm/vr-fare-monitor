from dataclasses import dataclass
from datetime import time, timedelta


@dataclass(frozen=True)
class FarePolicyConfig:
    outbound_earliest: time = time(6, 24)
    outbound_latest_arrival: time = time(12, 30)
    return_earliest: time = time(15, 48)
    return_preferred: time = time(16, 30)
    return_latest_arrival: time = time(21, 35)
    soft_duration_minutes: int = 230
    max_duration_minutes: int = 240
    near_tie_sek: int = 50
    early_return_total_cap_sek: int = 600
    early_return_discount_sek: int = 150


@dataclass(frozen=True)
class ScanConfig:
    window_days: dict[str, int]
    cache_ttls: dict[str, timedelta]
    lease_ttl: timedelta = timedelta(minutes=8)
    wait_for_refresh_seconds: float = 8.0
    wait_poll_seconds: float = 0.1
    request_timeout_seconds: float = 25.0
    retry_attempts: int = 2
    retry_base_seconds: float = 0.6


POLICY = FarePolicyConfig()
SCAN = ScanConfig(
    window_days={"7d": 7, "30d": 30},
    cache_ttls={"7d": timedelta(minutes=15), "30d": timedelta(hours=6)},
)

PRICE_BANDS: tuple[tuple[str, int | None], ...] = (
    ("exceptional", 600),
    ("good", 800),
    ("acceptable", 1000),
    ("expensive", 1400),
    ("unacceptable", None),
)
