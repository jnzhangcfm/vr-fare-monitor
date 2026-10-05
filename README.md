# VR Adult Fix fare monitor

This project publishes read-only, official VR Adult Fix fare data for the fixed Göteborg C ↔ Stockholm C monitoring use case.

Production architecture:

```text
GitHub Actions scheduled scanner -> static JSON on gh-pages -> GitHub Pages -> public HTTPS GET
```

There is no production server, cloud database, Docker runtime, generic VR proxy, browser automation, booking flow, or notification integration.

## Public static contract

Once GitHub Pages is enabled, the public files are:

- `/data/7d.json`
- `/data/30d.json`
- `/data/health.json`
- `/data/learning-summary.json`

The base URL is `https://OWNER.github.io/REPOSITORY`. Every fare payload retains the existing source, window, date status, ranking, and Adult/Fix/SEK fields. To keep the public response suitable for ChatGPT, per-date raw journeys and duplicate combination lists are replaced with counts; the complete ranked combinations remain in `ranking`. Static publication adds:

```json
{
  "publication": {
    "schema_version": 1,
    "generated_at": "...",
    "data_path": "7d.json"
  }
}
```

`health.json` records per-mode status, last attempt, last successful refresh, safe error code, data availability, and overall status. If a full VR scan fails, the last successful mode JSON is retained and health becomes `degraded`; a data-source failure is never published as an empty fare result.

## Refresh frequency and 14-day learning period

- The scheduled producer runs at **06:11, 12:17, 18:23, and 23:29 Europe/Stockholm** in `.github/workflows/learning-refresh.yml`. Its `timezone: Europe/Stockholm` schedule follows DST; no UTC conversion is hard-coded.
- The fixed learning period ran from **2026-08-25 through 2026-09-07 inclusive**. During that window, each run made one 30d scan, derived the equivalent 7d current output, appended observations, updated `learning-summary.json`, and updated `health.json`.
- After the learning period, the same four-times-daily schedule continues as the long-term fare monitor. Each run makes **one** 30d VR scan and derives 7d from the same response, so current `7d.json`, `30d.json`, and `health.json` stay fresh without doubling source traffic.
- Post-learning monitoring does **not** append to the fixed learning history or recompute `learning-summary.json`; the completed 14-day learning result remains frozen. The learned recommendation was `four_times_daily`, matching the continuing schedule.

The two legacy mode-specific workflows remain available only through manual dispatch. All workflows share one concurrency group, so competing runs cannot amplify VR traffic or race when writing `gh-pages`.

## Learning history

The append-only history is stored as Stockholm-local daily JSONL partitions on the `gh-pages` branch:

```text
history/YYYY-MM-DD.jsonl
```

Each row represents a returned journey, not only an eligible/ranked one. It records the observation timestamp, travel date/direction, schedule reference, scheduled times, duration, Adult Fix price (or explicit missing state), availability/bookability, seats left, disruption, transport data, source journey id, and schema version. The logical identity is `travel_date | direction | primary schedule reference | scheduled departure`; `journey_id` is retained but not trusted as cross-scan identity.

`data/learning-summary.json` is the compact public analysis: coverage, matched fare transitions, increases/decreases, intraday intervals, lead-time bins, descriptive `seats_left` evidence, and an advisory scan-frequency recommendation. The recommendation never changes workflow schedules automatically. The rule requires at least 8 successful scans and 10 matched price transitions; it recommends four daily only when intraday change rate is at least 10%, twice daily at 2% intraday or 10% overall change rate, and once daily otherwise. These deliberately conservative thresholds are centralized in `LearningConfig` for the later human decision.

The raw JSONL is public fare/timetable information kept for Git inspection and reproducibility, but it is not part of the compact ChatGPT-facing JSON contract.

## Local verification

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

python -m vr_fares.static_export --mode 7d --output-dir /tmp/vr-pages/data
python -m vr_fares.static_export --mode 30d --output-dir /tmp/vr-pages/data
python -m pytest -q
ruff check src tests
```

The legacy Phase 1 direct comparison client remains available:

```bash
vr-fares search --from GOTEBORG --to STOCKHOLM --date YYYY-MM-DD
```

## GitHub setup

The repository must be public for a GitHub Free setup. After pushing the repository and creating the first `gh-pages` commit through a manual workflow run:

1. Go to **Settings → Actions → General** and allow workflow `Read and write permissions`.
2. Go to **Settings → Pages** and set the publishing source to branch `gh-pages`, folder `/(root)`.
3. Run **Refresh public 7d VR fares** and then **Refresh public 30d VR fares** from the Actions tab.
4. Confirm the three JSON URLs above over ordinary public HTTPS.

Only the automatic, repository-scoped `GITHUB_TOKEN` is used by the workflows. Do not add VR credentials: the official read-only endpoint has none. HAR captures, browser state, cookies, tokens, local environments, generated local `site/` data, and caches are excluded by [.gitignore](/Users/jnz/VR 火车票助手/.gitignore).

GitHub Pages on GitHub Free is available for public repositories; private repository Pages requires an eligible paid GitHub plan. See [GitHub Pages availability](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) and [branch publishing guidance](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## Historical note

The previous Cloud Run/Firestore deployment draft is archived in [phase-2-approved-design.md](/Users/jnz/VR 火车票助手/docs/phase-2-approved-design.md). Its runtime files and dependencies have been removed; the accepted fare client and ranking logic remain unchanged.
