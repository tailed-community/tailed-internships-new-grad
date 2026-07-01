# Custom Career Page ATS Discovery

Some companies have branded career pages like `https://example.com/careers`, but the actual jobs are powered by Greenhouse, Lever, Workday, Ashby, or another supported ATS.

The custom career page workflow exists to find those underlying ATS links. It does not try to scrape arbitrary company websites as a final data source.

## Scripts

- `scripts/discover_custom_career_pages.py`: finds likely custom career pages from existing data and archived jobs.
- `scripts/detect_custom_ats_sources.py`: fetches those pages and detects embedded or linked ATS evidence.
- `scripts/promote_custom_ats_candidates.py`: validates route-ready supported candidates and appends them to `data/company_sources.csv`.
- `scripts/custom_career_ats.py`: shared passive detection helpers.

## Typical Flow

```bash
python scripts/discover_custom_career_pages.py
python scripts/detect_custom_ats_sources.py --include-manual
python scripts/promote_custom_ats_candidates.py --apply
python scripts/sync_companies.py
```

Outputs:

- `data/custom_companies_discovered.csv`
- `data/custom_ats_candidates.csv`
- `data/custom_ats_promotion_review.csv`
- `data/custom_company_duplicates.csv`

## Manual Input

Use `data/custom_companies.csv` for known branded career pages that are worth checking:

```csv
company,url,source,enabled,notes
Example,https://example.com/careers,custom,true,Manual candidate
```

## What Gets Promoted

Only supported, route-ready ATS sources are promoted to `data/company_sources.csv`.

Examples:

- A custom page with a Greenhouse embed becomes `https://boards.greenhouse.io/<board-token>`.
- A custom page linking to Lever becomes `https://jobs.lever.co/<company-slug>`.
- A custom page with only bespoke HTML jobs is skipped.

## Why We Skip Bespoke Websites

Company-specific websites often require custom parsing, client-side rendering, anti-bot handling, or one-off rules. That is fragile and expensive to maintain. The reliable path is to detect an ATS and use the existing ATS fetcher.

