# Workflows

## Update Job Listings

- Production workflow: `.github/workflows/update-jobs.yml`
- Runs source-scoped updates sequentially
- Currently executes `workday`, then `lever`, then `greenhouse`, then `ashby`, then `icims`, then `oracle_hcm`
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
