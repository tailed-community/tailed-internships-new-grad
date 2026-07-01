# Adding Companies

Add companies to `data/company_sources.csv`.

## CSV Format

```csv
company,url,enabled
Example Company,https://boards.greenhouse.io/example,true
```

Columns:

- `company`: display name.
- `url`: canonical supported ATS board URL.
- `enabled`: `true` or `false`.

Use `enabled=false` when you want to keep a source documented but not fetch it yet.

## Supported URL Shapes

- Workday: `https://<tenant>.wd*.myworkdayjobs.com/<site>`
- Lever: `https://jobs.lever.co/<company-slug>`
- Greenhouse: `https://boards.greenhouse.io/<board-token>` or `https://job-boards.greenhouse.io/<board-token>`
- Ashby: `https://jobs.ashbyhq.com/<job-board-name>`
- iCIMS: `https://<tenant>.icims.com/jobs/search` or `https://<tenant>.jibeapply.com?icims=1`
- Oracle HCM: `https://<host>/hcmUI/CandidateExperience/<language>/sites/<site>`
- SmartRecruiters: `https://jobs.smartrecruiters.com/<company-slug>`
- Rippling: `https://ats.rippling.com/<job-board-slug>/jobs`
- Workable: `https://apply.workable.com/<account-slug>`

## Local Validation

After editing the CSV, run:

```bash
python scripts/sync_companies.py
```

This normalizes `data/company_sources.csv`, removes later duplicate rows, and regenerates `data/companies.json`.

To fetch one source locally:

```bash
python scripts/main.py --source greenhouse
```

Replace `greenhouse` with the ATS you changed.

## Duplicate Handling

The sync script keeps the first matching company/source or URL and skips later duplicates. If you need to replace an old URL, edit the existing row instead of adding a new duplicate row.

