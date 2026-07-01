# Automation Workflows

GitHub Actions keep the repository updated.

## Daily Job Updates

Workflow: `.github/workflows/update-jobs.yml`

Runs daily and by manual dispatch.

Flow:

```bash
python scripts/sync_companies.py
python scripts/main.py --source workday
python scripts/main.py --source lever
python scripts/main.py --source greenhouse
...
```

Each source is committed separately when it changes job data.

## Weekly Simplify Company Source Sync

Workflow: `.github/workflows/sync-simplify-companies.yml`

Runs weekly and by manual dispatch.

Flow:

```bash
python scripts/sync_company_leads.py
python scripts/promote_company_leads.py
python scripts/sync_companies.py
```

This scans Simplify's Summer 2026 listings feed, finds companies using ATS platforms already supported by this repo, appends new sources to `data/company_sources.csv`, and regenerates `data/companies.json`.

## Table Formatting

Workflow: `.github/workflows/format-tables.yml`

Runs when job data or formatting code changes.

Flow:

```bash
python scripts/format_tables.py
```

This only regenerates Markdown tables. It does not fetch jobs.

## Generated Files

These files are commonly changed by automation:

- `data/company_leads.csv`
- `data/company_sources.csv`
- `data/companies.json`
- `data/jobs.json`
- `data/archived.json`
- `README.md`
- `NEW_GRAD.md`

