# VR fares — Phase 2 approved design

Status: archived Cloud Run/Firestore implementation baseline, superseded by the GitHub Actions + Pages deployment design.

> This document is retained only as historical Phase 2 context. It is not the active runtime architecture.

## Scope

This service exposes only:

- `GET /api/vr/scan?mode=7d`
- `GET /api/vr/scan?mode=30d`
- `GET /api/vr/health`

It retrieves read-only, official VR Adult Fix fares for the fixed Göteborg C ↔ Stockholm C use case. It never accepts caller-supplied stations, travel dates, passenger types, request bodies, bookings, accounts, or payment details.

## Runtime

`FastAPI -> Cloud Run -> Firestore` is the production architecture. Firestore stores scan snapshots, per-mode refresh leases, and health state. A storage protocol keeps application logic independent of Firestore; an in-memory implementation is the default for local development and tests.

Cloud Run is configured with a maximum of two instances. That limit is an extra request-volume safeguard, not a correctness mechanism: the Firestore lease remains the cross-instance single-flight authority.

Cloud Scheduler and historical collection are not part of Phase 2.

## Data source and validation

The only source is the first-party VR endpoint established in Phase 1:

`POST https://api.vrresa.se/api/v1.0/departures/`

The request is a read-only one-adult search between the fixed station identifiers. Response data is schema-validated before it is used. Missing or malformed departures, times, availability, schedule references, or `prices.FIX` values are source/schema failures, never a zero fare or an empty successful scan.

## Calendar and selection policy

For each mode, the window starts tomorrow and includes 7 or 30 calendar days respectively. Only Swedish working days are eligible. The service discovers journeys from the live response; it does not treat example train numbers or times as immutable.

Central typed configuration preserves the approved thresholds:

- outbound: depart at or after 06:24, arrive Stockholm by 12:30;
- return: depart at or after 15:48, prefer 16:30 or later, arrive Göteborg by 21:35;
- duration over 4 hours is rejected; 3:50–4:00 has only a soft penalty;
- mixed/replacement transport is retained when otherwise valid;
- only `prices.FIX`, VR, Adult, and SEK are eligible;
- price is dominant, including the approved price bands;
- early-return and 50 SEK near-tie convenience rules are explicit and deterministic.

Each raw normalized journey is retained in the response alongside valid and recommended return combinations and an explainable ranking key/rationale.

## Freshness and failure behaviour

The 7-day snapshot TTL is 15 minutes; the 30-day TTL is 6 hours. A fresh snapshot is returned without VR traffic. A stale snapshot has one lease holder refresh it; other callers wait briefly and reuse the result. Requests use bounded timeout, conservative retry, exponential backoff, and jitter.

If a refresh fails but a prior valid snapshot exists, the service returns that snapshot explicitly marked stale with cache age, last successful refresh, and a safe error code. If no valid snapshot exists, it returns a safe source failure. A partial date failure remains distinguishable from a successful scan containing zero qualifying journeys.

## Verification boundary

Phase 2 verification includes deterministic tests, local FastAPI requests, cache/single-flight/failure simulations, live VR checks against the Phase 1 direct client, and a local production-container build. Firestore live integration and public Cloud Run deployment require user-provided GCP credentials and are not claimed until actually performed.
