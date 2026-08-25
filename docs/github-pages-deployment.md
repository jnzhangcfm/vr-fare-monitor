# GitHub Actions and Pages deployment

The active deployment target is a public GitHub repository called `vr-fare-monitor` and a `gh-pages` data branch. The source repository carries code and workflows; `gh-pages` contains only `.nojekyll` and the published `data/*.json` files.

## Repository requirements

- Public repository for GitHub Free.
- Actions enabled with workflow `GITHUB_TOKEN` read/write permission.
- Pages source set to `gh-pages` and `/(root)` after the first workflow creates that branch.
- No repository secrets are required.

## First publication

1. Push the source repository to GitHub.
2. In the Actions tab, run **Refresh public 7d VR fares**.
3. Run **Refresh public 30d VR fares** after the first workflow finishes.
4. Enable Pages branch publishing as above.
5. Verify `https://OWNER.github.io/REPOSITORY/data/health.json` and the two mode files.

The workflows serialize publication with one shared concurrency group. They clone the existing `gh-pages` branch to retain the other mode's last successful JSON, generate only their assigned mode, then commit public data back to that branch.

## Failure behaviour

`vr_fares.static_export` catches source failures, leaves the existing mode file untouched, and writes only a safe `source_failure` health update. A workflow can therefore publish degraded health rather than suppressing evidence or replacing fares with an empty response.

No history store is created in this phase. Future Phase 3 can add date-partitioned public history files or a separate non-public artifact without changing the published current-scan contract.
