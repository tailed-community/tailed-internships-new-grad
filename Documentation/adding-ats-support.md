# Adding ATS Support

Add a new ATS only when the platform has a stable public job board or API that can be fetched safely.

## Required Changes

1. Add source detection and config parsing in `scripts/sync_companies.py`.
2. Add a fetcher in `scripts/fetchers/<source>.py`.
3. Register the fetcher in the main fetch flow if needed.
4. Add the source to GitHub Actions update loops.
5. Update documentation and contributor guidance.

## 1. Sync Company Config

Update `scripts/sync_companies.py`:

- Add search terms if the ATS needs keyword searches.
- Teach `detect_source()` to identify the URL.
- Add an `extract_<source>_parts()` function to canonicalize the URL.
- Add `build_<source>_company()`.
- Add the source case to `build_company_config()`.
- Update `sort_company_configs()` only if the default behavior is not enough.

The config should include enough stable identity fields to avoid duplicates. Examples:

- Greenhouse: `slug`
- Workday: `tenant` and `site`
- Oracle HCM: `host`, `language`, and `site`

## 2. Fetcher

Create `scripts/fetchers/<source>.py`.

A fetcher should:

- Read one company config.
- Fetch jobs from the ATS.
- Normalize title, location, URL, source, and job type fields in the same style as existing fetchers.
- Avoid raising for one bad company when the failure can be isolated.

Use existing fetchers as templates before inventing a new structure.

## 3. Workflows

Update `.github/workflows/update-jobs.yml` so the daily job update runs the new source.

If Simplify lead discovery should recognize the source, update:

- `scripts/sync_company_leads.py`
- `scripts/promote_company_leads.py` if identity parsing needs changes

## 4. Documentation

Update:

- `Documentation/adding-companies.md`
- `Documentation/system-overview.md`
- `CONTRIBUTING.md`

## Checklist

- `python -m py_compile scripts/sync_companies.py scripts/fetchers/<source>.py`
- `python scripts/sync_companies.py`
- `python scripts/main.py --source <source>`
- Confirm `data/company_sources.csv` stays normalized.
- Confirm `data/companies.json` contains stable config for the new source.

