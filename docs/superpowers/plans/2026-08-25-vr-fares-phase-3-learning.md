# VR Fare Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, four-times-daily Stockholm-local historical observation layer and learning summary without changing fare selection or ranking.

**Architecture:** A new pure history module serializes returned existing 30d journeys to daily JSONL and summarizes observations. `StaticExporter` orchestrates the existing 30d scan, a derived 7d projection, history append, summary, and safe health publication. One timezone-aware GitHub Actions workflow is the scheduled producer.

**Tech Stack:** Python 3.12, stdlib JSON/JSONL/zoneinfo/statistics, existing pytest/Ruff, GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-08-25-vr-fares-phase-3-learning-design.md`

## Global Constraints

- Preserve existing VR client, filtering, ranking, thresholds, and static current-data contract.
- Use no database, Docker, paid GitHub feature, generic proxy, notifications, or browser automation.
- History is date-partitioned JSONL; failed scans write no fake observations.
- Scheduled learning uses direct `Europe/Stockholm` timezone-aware schedules and stops after the configured inclusive period.

---

### Task 1: Define learning configuration and observation/history contract

**Files:**
- Modify: `src/vr_fares/config.py`
- Create: `src/vr_fares/history.py`
- Create: `tests/test_history.py`

**Interfaces:**
- Produces `LEARNING: LearningConfig`, `JourneyObservation`, `append_observations`, and `logical_journey_identity`.

- [ ] Write failing tests for stable identity, missing Fix price, unavailable journey, date-partitioned JSONL append, and duplicate observation suppression.
- [ ] Run `python -m pytest tests/test_history.py -q` and confirm it fails because the history module does not exist.
- [ ] Implement the minimal immutable config, observation extraction, atomic append, and duplicate filtering.
- [ ] Re-run the focused tests and commit the green unit.

### Task 2: Add deterministic learning analysis

**Files:**
- Modify: `src/vr_fares/history.py`
- Create: `src/vr_fares/learning.py`
- Modify: `tests/test_history.py`
- Create: `tests/test_learning.py`

**Interfaces:**
- Consumes `JourneyObservation` records.
- Produces `build_learning_summary(observations, now)` and `learning_is_active(now)`.

- [ ] Write failing tests for unchanged/increase/decrease transitions, disappearance, intraday changes, lead-time bins, seats-left insufficiency, recommendation outcomes, and learning-period boundaries.
- [ ] Run the focused tests and confirm the missing analysis module fails.
- [ ] Implement chronological matching, descriptive statistics, configurable bins/recommendation, and safe insufficient-data outputs.
- [ ] Re-run the focused tests and commit the green unit.

### Task 3: Orchestrate one scan into current JSON, history, summary, and health

**Files:**
- Modify: `src/vr_fares/static_export.py`
- Modify: `tests/test_static_export.py`

**Interfaces:**
- Produces `StaticExporter.export_learning(output_dir)`.
- Consumes the unchanged `ScanService.get_scan("30d")` response and history/learning interfaces.

- [ ] Write failing exporter tests for derived 7d output, append exactly once, failed scan preserving current data/history, and learning health fields.
- [ ] Run focused exporter tests and confirm the method is missing.
- [ ] Implement minimal 30d-to-7d projection using existing date data and `rank_globally`, safe writes, history append, summary generation, and health extension.
- [ ] Re-run focused tests and commit the green unit.

### Task 4: Add timezone-aware learning workflow and documentation

**Files:**
- Create: `.github/workflows/learning-refresh.yml`
- Modify: `.github/workflows/refresh-7d.yml`
- Modify: `.github/workflows/refresh-30d.yml`
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Scheduled producer invokes `python -m vr_fares.static_export --learning --output-dir site`.

- [ ] Add workflow with four explicit `schedule` entries using `timezone: Europe/Stockholm`, shared concurrency group, manual dispatch, guarded learning period, and one `gh-pages` commit.
- [ ] Disable scheduled triggers in the legacy independent refresh workflows while retaining manual dispatch.
- [ ] Document schedule, history, summary, DST behavior, and public URLs.
- [ ] Validate workflow YAML parsing and commit the configuration/docs unit.

### Task 5: Full verification and one production learning run

**Files:**
- Modify only generated `gh-pages` content through the workflow.

- [ ] Run full pytest, Ruff check/format, compileall, pip check, workflow YAML parse, and secret/path scans.
- [ ] Simulate multiple observations locally and inspect the deterministic summary.
- [ ] Push the source commit, manually dispatch the learning workflow once, and confirm exactly one history append, current public JSON, health, summary, and Pages delivery.
- [ ] Compare representative published fare values with Phase 1 direct client at low request rate.
