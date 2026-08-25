# VR fares Phase 2 implementation plan

> Execute in the existing workspace: the project has no Git repository and the user explicitly requested direct implementation here.

**Goal:** deliver a narrow, read-only FastAPI service for cached 7-day and 30-day official VR Adult Fix scans, with in-memory and Firestore storage backends.

**Architecture:** typed domain/configuration and a schema-validating VR client feed a deterministic scan/ranking service. The service talks only to a storage protocol. FastAPI is a thin safe public boundary. Firestore implements persistent snapshots, health, and transactional leases; local/test mode uses memory.

**Tech:** Python 3.12, FastAPI, httpx, Pydantic, holidays, google-cloud-firestore, unittest/pytest, Docker.

## Task 1 — Establish package and tests

1. Add project runtime and development dependencies.
2. Write deterministic tests for window/calendar, journey validation, selection/ranking, cache and failures before implementations.
3. Verify existing Phase 1 tests continue to pass.

## Task 2 — Implement domain and VR access

1. Add central typed settings and Swedish weekday calendar.
2. Add strict response parser and bounded-retry first-party client.
3. Keep the Phase 1 CLI unchanged and reuse its output as a live comparison oracle.
4. Run unit tests for parser and calendar.

## Task 3 — Implement selection, storage, and scan service

1. Implement eligibility and ranking with all approved thresholds and explainable fields.
2. Add storage protocol and lock-protected memory store.
3. Add Firestore implementation, including a Firestore transaction for lease acquisition.
4. Implement fresh/stale snapshots, wait-and-reuse single-flight, partial failures, and safe health state.
5. Run deterministic cache, failure, and concurrency tests.

## Task 4 — Add HTTP and deployable packaging

1. Add FastAPI routes and safe exception responses.
2. Add Dockerfile, docker ignore rules, Cloud Run manifest/template, and minimal deployment instructions.
3. Check compilation, linting, local server requests, and production container build.

## Task 5 — End-to-end verification and handoff

1. Run all automated tests.
2. Make low-rate live 7d and 30d scans and compare selected fare records with the Phase 1 client.
3. Record only sanitized, non-secret evidence in documentation.
4. Report Cloud prerequisites separately from completed local work; do not deploy or begin Phase 3.
