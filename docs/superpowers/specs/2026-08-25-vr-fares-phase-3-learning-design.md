# VR Fare Learning Design

## Goal

Collect a bounded, 14-calendar-day history of the already accepted official VR
Adult Fix fare universe, then publish a deterministic descriptive summary that
supports a later human decision about long-term scan frequency.

## Non-goals

This design does not alter fare retrieval, journey eligibility, ranking,
thresholds, notifications, ticket purchase, browser automation, databases, or
the deployment architecture.

## Data flow

One scheduled learning workflow scans the existing 30d universe four times per
Stockholm local day. The raw 30d scan result is used to (1) publish the compact
current 30d JSON, (2) derive the equivalent compact 7d JSON without a second VR
query, and (3) append one observation line per returned journey to a
date-partitioned JSONL file. The workflow then writes a compact
`learning-summary.json` and extends `health.json` with learning status.

## Scheduling and stopping

The workflow has four `schedule` entries at 06:11, 12:17, 18:23, and 23:29 in
`Europe/Stockholm`. GitHub Actions evaluates DST using the IANA timezone. A
central `LearningConfig` contains inclusive Stockholm-local start and end
dates. Scheduled runs outside that range exit before contacting VR; manual runs
remain available for controlled verification.

The initial learning period is 2026-08-25 through 2026-09-07 inclusive. It is
not extended or replaced automatically by the recommendation.

## History contract

Raw history lives only on the `gh-pages` branch under `history/YYYY-MM-DD.jsonl`
and is not linked as a public Pages API. Every line is one journey observation.
It contains the observation timestamp, travel date, direction, schedule
references, scheduled departure/arrival, duration, Fix price or null,
availability/bookability, seats left, disruption fields, transport fields,
journey id, schema version, and a stable logical identity.

The logical identity is:

`travel_date | direction | primary schedule reference | scheduled departure`

It intentionally does not treat `journey_id` as authoritative across scans.
Repeated execution for the same `observation_id` (timestamp slot plus logical
identity) is ignored, so a rerun cannot duplicate rows. A journey absent from a
later response is not converted into a sold-out observation.

## Failure and health

Only a successful scan may append history or replace current 7d/30d JSON. A
failed scan leaves existing public data untouched and writes a safe
learning-failure health state. Health records the most recent successful
learning scan, history append, health state, and learning period boundaries.

## Summary and recommendation

The summary is deterministic and contains coverage, matched-price transitions,
intraday transitions in Stockholm time, configurable lead-time bins, and a
descriptive seats-left section. Null/missing Fix prices, unavailable journeys,
unbookable journeys, disappearance, and source failure remain distinct.

Recommendation thresholds live in `LearningConfig`. The recommendation is
`once_daily`, `twice_daily`, or `four_times_daily`; it is `insufficient_data`
until minimum coverage is met. It is advisory only and never edits a workflow.

## Verification

Tests cover identity, JSONL append/deduplication, price transition categories,
missing/unavailable/disappearing data, failed scans, intraday and lead-time
summary logic, seats-left insufficiency, recommendation rules, period guard,
and learning health. Existing scanner/ranking tests remain unchanged.
