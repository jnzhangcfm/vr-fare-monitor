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

The base URL is `https://OWNER.github.io/REPOSITORY`. Every fare payload retains the existing source, journey, eligibility, combination, ranking, and Adult/Fix/SEK fields. Static publication adds only:

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

## Refresh frequency

- `7d`: weekdays at 05:17 UTC in [refresh-7d.yml](/Users/jnz/VR 火车票助手/.github/workflows/refresh-7d.yml).
- `30d`: Monday at 05:43 UTC in [refresh-30d.yml](/Users/jnz/VR 火车票助手/.github/workflows/refresh-30d.yml).

Both workflows can be started manually and share one concurrency group, so two scheduled runs cannot amplify VR traffic. The cron values are isolated in workflow YAML and can be adjusted later without changing scan or ranking logic. This phase does not implement historical price learning.

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
