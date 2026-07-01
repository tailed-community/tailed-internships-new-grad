# System Overview

The repository is built around supported ATS sources, not one-off website scrapers.

## Core Files

- `data/company_sources.csv`: human-maintained source list. Add companies here.
- `data/companies.json`: generated runtime config. Do not edit this by hand for normal company additions.
- `data/jobs.json`: current active jobs.
- `data/archived.json`: previously seen jobs.
- `README.md`: generated internship table.
- `NEW_GRAD.md`: generated new grad table.

## Main Scripts

- `scripts/sync_companies.py`: reads `data/company_sources.csv`, validates URLs, normalizes them, and writes `data/companies.json`.
- `scripts/main.py`: runs fetchers and updates `data/jobs.json`, `data/archived.json`, `README.md`, and `NEW_GRAD.md`.
- `scripts/format_tables.py`: regenerates Markdown tables from existing job data.
- `scripts/sync_company_leads.py`: scans Simplify listings for companies using supported ATS platforms.
- `scripts/promote_company_leads.py`: appends new supported leads to `data/company_sources.csv`.

## Fetcher Flow

Each supported ATS has a fetcher in `scripts/fetchers/`.

The normal update flow is:

```bash
python scripts/sync_companies.py
python scripts/main.py --source greenhouse
```

`sync_companies.py` converts CSV rows into source-specific config. `main.py` uses those configs to fetch jobs through the matching fetcher.

## Source Of Truth

For company sources, `data/company_sources.csv` is the source of truth. `data/companies.json` is regenerated from it.

