import copy
from dataclasses import dataclass
from datetime import date, time
from typing import Any

from vr_fares.config import POLICY, PRICE_BANDS
from vr_fares.domain import Journey


@dataclass(frozen=True)
class JourneyAssessment:
    eligible: bool
    reasons: list[str]
    soft_duration_penalty: bool


@dataclass(frozen=True)
class RankedDate:
    valid: list[dict[str, Any]]
    recommended: list[dict[str, Any]]


def _local_time(value: Journey, field: str) -> time:
    return getattr(value, field).timetz().replace(tzinfo=None)


def assess_journey(journey: Journey, direction: str) -> JourneyAssessment:
    reasons: list[str] = []
    if journey.fix_price_sek is None:
        reasons.append("missing_fix_price")
    if not journey.available:
        reasons.append("unavailable")
    if not journey.bookable:
        reasons.append("unbookable")
    if journey.duration_minutes > POLICY.max_duration_minutes:
        reasons.append("duration_over_4h")
    departure = _local_time(journey, "departure_at")
    arrival = _local_time(journey, "arrival_at")
    if direction == "outbound":
        if departure < POLICY.outbound_earliest:
            reasons.append("outbound_before_0624")
        if arrival > POLICY.outbound_latest_arrival:
            reasons.append("stockholm_arrival_after_1230")
    elif direction == "return":
        if departure < POLICY.return_earliest:
            reasons.append("return_before_1548")
        if arrival > POLICY.return_latest_arrival:
            reasons.append("goteborg_arrival_after_2135")
    else:
        raise ValueError("direction must be outbound or return")
    return JourneyAssessment(
        eligible=not reasons,
        reasons=reasons,
        soft_duration_penalty=POLICY.soft_duration_minutes
        <= journey.duration_minutes
        <= POLICY.max_duration_minutes,
    )


def price_band(total_sek: int) -> str:
    for name, limit in PRICE_BANDS:
        if limit is None or total_sek <= limit:
            return name
    raise AssertionError("unreachable")


def _seconds(value: time) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def _journey_dict(journey: Journey) -> dict[str, Any]:
    return journey.to_dict()


def _combination_convenience_key(item: dict[str, Any]) -> tuple[int, int, int, int, str]:
    outbound = item["outbound"]
    inbound = item["return"]
    outbound_time = time.fromisoformat(outbound["departure_at"][11:19])
    return_time = time.fromisoformat(inbound["departure_at"][11:19])
    duration = outbound["duration_minutes"] + inbound["duration_minutes"]
    return (
        -_seconds(outbound_time),
        -_seconds(return_time),
        duration,
        item["prices"]["total_sek"],
        item["date"],
    )


def rank_globally(combinations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank every qualifying date pair with the approved cross-date near-tie rule."""
    ranked = copy.deepcopy(combinations)
    if not ranked:
        return []
    lowest_total = min(item["prices"]["total_sek"] for item in ranked)
    near_tie = [
        item for item in ranked if item["prices"]["total_sek"] <= lowest_total + POLICY.near_tie_sek
    ]
    remaining = [item for item in ranked if item not in near_tie]
    near_tie.sort(key=_combination_convenience_key)
    remaining.sort(
        key=lambda item: (item["prices"]["total_sek"], *_combination_convenience_key(item))
    )
    ordered = near_tie + remaining
    for global_rank, item in enumerate(ordered, start=1):
        is_near_tie = item in near_tie and len(near_tie) > 1
        item["global_rank"] = global_rank
        item["global_ranking_rationale"] = (
            [
                "within_50_sek_near_tie",
                "later_outbound_preferred",
                "later_return_preferred",
                "shorter_duration_tiebreak",
            ]
            if is_near_tie
            else [
                "lowest_total_price",
                "later_outbound_then_return_tiebreak",
                "shorter_duration_tiebreak",
            ]
        )
    return ordered


def rank_date_combinations(
    travel_date: date, outbound_journeys: list[Journey], return_journeys: list[Journey]
) -> RankedDate:
    valid_outbound = [
        journey for journey in outbound_journeys if assess_journey(journey, "outbound").eligible
    ]
    valid_return = [
        journey for journey in return_journeys if assess_journey(journey, "return").eligible
    ]
    later_return_prices = [
        journey.fix_price_sek
        for journey in valid_return
        if _local_time(journey, "departure_at") >= POLICY.return_preferred
        and journey.fix_price_sek is not None
    ]
    best_later_return = min(later_return_prices) if later_return_prices else None
    combinations: list[dict[str, Any]] = []
    for outbound in valid_outbound:
        for inbound in valid_return:
            assert outbound.fix_price_sek is not None
            assert inbound.fix_price_sek is not None
            early_return = _local_time(inbound, "departure_at") < POLICY.return_preferred
            total = outbound.fix_price_sek + inbound.fix_price_sek
            if not early_return:
                recommended = True
                early_rule = "not_early_return"
            elif total <= POLICY.early_return_total_cap_sek:
                recommended = True
                early_rule = "total_at_or_below_600_sek"
            elif (
                best_later_return is not None
                and inbound.fix_price_sek <= best_later_return - POLICY.early_return_discount_sek
            ):
                recommended = True
                early_rule = "at_least_150_sek_cheaper_than_later_return"
            else:
                recommended = False
                early_rule = "early_return_not_price_justified"
            outbound_assessment = assess_journey(outbound, "outbound")
            return_assessment = assess_journey(inbound, "return")
            combinations.append(
                {
                    "date": travel_date.isoformat(),
                    "outbound": _journey_dict(outbound),
                    "return": _journey_dict(inbound),
                    "prices": {
                        "outbound_fix_sek": outbound.fix_price_sek,
                        "return_fix_sek": inbound.fix_price_sek,
                        "total_sek": total,
                    },
                    "price_band": price_band(total),
                    "stockholm_stay_minutes": int(
                        (inbound.departure_at - outbound.arrival_at).total_seconds() // 60
                    ),
                    "early_return": early_return,
                    "early_return_rule": early_rule,
                    "recommended": recommended,
                    "soft_duration_penalty": {
                        "outbound": outbound_assessment.soft_duration_penalty,
                        "return": return_assessment.soft_duration_penalty,
                    },
                }
            )
    if not combinations:
        return RankedDate(valid=[], recommended=[])
    lowest_total = min(item["prices"]["total_sek"] for item in combinations)
    near_tie = [
        item
        for item in combinations
        if item["prices"]["total_sek"] <= lowest_total + POLICY.near_tie_sek
    ]
    remaining = [item for item in combinations if item not in near_tie]

    def convenience_key(item: dict[str, Any]) -> tuple[int, int, int, int]:
        outbound = item["outbound"]
        inbound = item["return"]
        outbound_time = time.fromisoformat(outbound["departure_at"][11:19])
        return_time = time.fromisoformat(inbound["departure_at"][11:19])
        duration = outbound["duration_minutes"] + inbound["duration_minutes"]
        return (
            -_seconds(outbound_time),
            -_seconds(return_time),
            duration,
            item["prices"]["total_sek"],
        )

    near_tie.sort(key=convenience_key)
    remaining.sort(
        key=lambda item: (
            item["prices"]["total_sek"],
            -_seconds(time.fromisoformat(item["outbound"]["departure_at"][11:19])),
            -_seconds(time.fromisoformat(item["return"]["departure_at"][11:19])),
            item["outbound"]["duration_minutes"] + item["return"]["duration_minutes"],
        )
    )
    ordered = near_tie + remaining
    for rank, item in enumerate(ordered, start=1):
        if len(near_tie) > 1 and item in near_tie:
            rationale = [
                "within_50_sek_near_tie",
                "later_outbound_preferred",
                "later_return_preferred",
                "shorter_duration_tiebreak",
            ]
        else:
            rationale = [
                "lowest_total_price",
                "later_outbound_then_return_tiebreak",
                "shorter_duration_tiebreak",
            ]
        item["rank"] = rank
        item["ranking_key"] = {
            "price_sek": item["prices"]["total_sek"],
            "near_tie_to_lowest": item["prices"]["total_sek"] - lowest_total <= POLICY.near_tie_sek,
            "outbound_departure": item["outbound"]["departure_at"],
            "return_departure": item["return"]["departure_at"],
        }
        item["ranking_rationale"] = rationale
    return RankedDate(valid=ordered, recommended=[item for item in ordered if item["recommended"]])
