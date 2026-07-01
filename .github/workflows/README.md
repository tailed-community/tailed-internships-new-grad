# Workflows

## Update Job Listings

- Production workflow: `.github/workflows/update-jobs.yml`
- Runs source-scoped updates sequentially
- Currently executes `workday`, then `lever`, then `greenhouse`, then `ashby`, then `icims`, then `oracle_hcm`, then `smartrecruiters`, then `rippling`, then `workable`
- Each source run updates only companies from that source; Workday fetches 6 companies in parallel and searches up to 2 terms in parallel per company
- Updates `data/jobs.json`
- Updates `data/archived.json`
- Regenerates internship and new grad tables in `README.md` and `NEW_GRAD.md`
- Runs daily and also supports manual `workflow_dispatch`

## Format Job Tables

- Formatting-only workflow: `.github/workflows/format-tables.yml`
- Uses existing `data/jobs.json` only
- Regenerates `README.md` and `NEW_GRAD.md` tables without fetching jobs
- Runs automatically when job data or table-formatting code changes on `main`
- Also supports manual `workflow_dispatch`
- Useful after table-formatting changes or manual edits to `data/jobs.json`

## Sync Simplify Company Sources

- Company-source workflow: `.github/workflows/sync-simplify-companies.yml`
- Fetches Simplify's Summer 2026 listings feed weekly
- Promotes companies that use supported ATS platforms into `data/company_sources.csv`
- Regenerates `data/companies.json` from the updated CSV
- Writes skipped/new lead audit data to `data/company_leads.csv`
- Also supports manual `workflow_dispatch`
