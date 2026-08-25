from datetime import UTC, datetime

from vr_fares.learning import build_learning_summary, learning_is_active, recommend_frequency


def observation(
    *,
    identity: str = "2026-09-01|outbound|VR 2004|2026-09-01T06:24:00+02:00",
    observed_at: str = "2026-08-26T04:11:00+00:00",
    travel_date: str = "2026-09-01",
    price: int | None = 359,
    seats_left: int | None = 10,
    available: bool = True,
    bookable: bool = True,
) -> dict:
    return {
        "observation_id": f"slot|{identity}",
        "observed_at": observed_at,
        "logical_journey_identity": identity,
        "travel_date": travel_date,
        "direction": "outbound",
        "fix_price_sek": price,
        "fix_price_state": "available" if price is not None else "missing",
        "available": available,
        "bookable": bookable,
        "seats_left": seats_left,
    }


def test_summary_counts_increases_decreases_and_unchanged_transitions() -> None:
    changed_identity = "2026-09-01|outbound|VR 2004|2026-09-01T06:24:00+02:00"
    unchanged_identity = "2026-09-01|return|VR 2003|2026-09-01T17:51:00+02:00"
    records = [
        observation(identity=changed_identity, price=359, observed_at="2026-08-26T04:11:00+00:00"),
        observation(identity=changed_identity, price=399, observed_at="2026-08-26T10:17:00+00:00"),
        observation(identity=changed_identity, price=379, observed_at="2026-08-27T04:11:00+00:00"),
        observation(
            identity=unchanged_identity, price=289, observed_at="2026-08-26T04:11:00+00:00"
        ),
        observation(
            identity=unchanged_identity, price=289, observed_at="2026-08-27T04:11:00+00:00"
        ),
    ]

    summary = build_learning_summary(records, now=datetime(2026, 8, 27, 12, tzinfo=UTC))

    behavior = summary["price_change_behavior"]
    assert behavior["matched_journey_count"] == 2
    assert behavior["changed_at_least_once_count"] == 1
    assert behavior["never_changed_count"] == 1
    assert behavior["total_price_change_events"] == 2
    assert behavior["increases"] == 1
    assert behavior["decreases"] == 1
    assert behavior["unchanged_transitions"] == 1
    assert behavior["median_absolute_change_sek"] == 30
    assert behavior["maximum_increase_sek"] == 40
    assert behavior["maximum_decrease_sek"] == -20


def test_missing_price_and_disappearance_do_not_become_price_changes() -> None:
    priced_identity = "2026-09-01|outbound|VR 2004|2026-09-01T06:24:00+02:00"
    disappeared_identity = "2026-09-01|return|VR 2003|2026-09-01T17:51:00+02:00"
    records = [
        observation(identity=priced_identity, price=359, observed_at="2026-08-26T04:11:00+00:00"),
        observation(identity=priced_identity, price=None, observed_at="2026-08-26T10:17:00+00:00"),
        observation(
            identity=disappeared_identity, price=289, observed_at="2026-08-26T04:11:00+00:00"
        ),
    ]

    summary = build_learning_summary(records, now=datetime(2026, 8, 26, 12, tzinfo=UTC))

    assert summary["coverage"]["unique_journey_count"] == 2
    assert summary["price_change_behavior"]["total_price_change_events"] == 0
    assert summary["price_change_behavior"]["matched_journey_count"] == 0
    assert summary["price_change_behavior"]["journeys_with_missing_fix_price"] == 1


def test_intraday_change_and_lead_time_bin_are_reported() -> None:
    records = [
        observation(
            price=359,
            travel_date="2026-09-20",
            observed_at="2026-08-26T04:11:00+00:00",
        ),
        observation(
            price=399,
            travel_date="2026-09-20",
            observed_at="2026-08-26T10:17:00+00:00",
        ),
    ]

    summary = build_learning_summary(records, now=datetime(2026, 8, 26, 12, tzinfo=UTC))

    assert summary["intraday_behavior"]["price_change_events"] == 1
    assert summary["intraday_behavior"]["intervals"]["06:11-12:17"]["change_events"] == 1
    assert summary["lead_time_behavior"]["15_30_days"]["change_events"] == 1


def test_insufficient_seats_data_and_short_coverage_produce_safe_recommendation() -> None:
    records = [
        observation(price=359, seats_left=None),
        observation(price=399, seats_left=None, observed_at="2026-08-26T10:17:00+00:00"),
    ]

    summary = build_learning_summary(records, now=datetime(2026, 8, 26, 12, tzinfo=UTC))

    assert summary["seats_left_relationship"]["status"] == "insufficient_data"
    assert summary["recommendation"]["recommended_long_term_frequency"] == "insufficient_data"
    assert summary["recommendation"]["confidence"] == "low"


def test_learning_period_guard_is_inclusive_in_stockholm_time() -> None:
    assert learning_is_active(datetime(2026, 8, 24, 21, 30, tzinfo=UTC)) is False
    assert learning_is_active(datetime(2026, 8, 25, 22, 30, tzinfo=UTC)) is True
    assert learning_is_active(datetime(2026, 9, 7, 21, 30, tzinfo=UTC)) is True
    assert learning_is_active(datetime(2026, 9, 7, 22, 30, tzinfo=UTC)) is False


def test_recommendation_escalates_only_when_observed_change_rates_justify_it() -> None:
    assert (
        recommend_frequency(
            successful_scan_count=8,
            price_transition_count=10,
            intraday_change_rate=0.0,
            any_change_rate=0.05,
        )["recommended_long_term_frequency"]
        == "once_daily"
    )
    assert (
        recommend_frequency(
            successful_scan_count=8,
            price_transition_count=10,
            intraday_change_rate=0.03,
            any_change_rate=0.05,
        )["recommended_long_term_frequency"]
        == "twice_daily"
    )
    assert (
        recommend_frequency(
            successful_scan_count=8,
            price_transition_count=10,
            intraday_change_rate=0.11,
            any_change_rate=0.05,
        )["recommended_long_term_frequency"]
        == "four_times_daily"
    )
