# Workflows

## Update Job Listings

- Production workflow: `.github/workflows/update-jobs.yml`
- Runs source-scoped updates sequentially
- Currently executes `workday`, then `lever`, then `greenhouse`
- Each source run updates only companies from that source
- Updates `data/jobs.json`
- Updates `data/archived.json`
- Regenerates internship and new grad tables in `README.md` and `NEW_GRAD.md`
- Runs daily and also supports manual `workflow_dispatch`

## Format Job Tables

- Formatting-only workflow: `.github/workflows/format-tables.yml`
- Uses existing `data/jobs.json` only
- Regenerates `README.md` and `NEW_GRAD.md` tables without fetching jobs
- Manual only (`workflow_dispatch`)
- Useful after table-formatting changes or manual edits to `data/jobs.json`

## Sync Company Leads

- Discovery workflow: `.github/workflows/sync-company-leads.yml`
- Default discovery query is public Glassdoor `internship` results for `Canada`
- Syncs Glassdoor discovery input into `data/company_leads.json`
- Can promote resolvable official ATS URLs into `data/company_sources.csv`
- Regenerates `data/companies.json` after promoted source additions
- Does not update `data/jobs.json`, `README.md`, or `NEW_GRAD.md`
- Manual only (`workflow_dispatch`)
- Uses PR review as the approval boundary for promoted official sources
