# Contributing

## Ways to Contribute

- Add a missing internship
- Add a missing new grad role
- Fix a broken application link
- Suggest a company source
- Improve automation scripts

## Add a Job Manually

Contributors can update:

- `data/jobs.json`

Please follow the existing JSON schema for every job entry and set the correct `type`:

- `"internship"`
- `"new_grad"`

## Add a Company Source

Contributors should add company career pages to:

- `data/company_sources.csv`

CSV columns:

- `company`
- `url`
- `enabled`

Current support:

- Workday URLs on `myworkdayjobs.com`
- Lever URLs on `jobs.lever.co`
- Greenhouse-hosted board URLs on `boards.greenhouse.io` and `job-boards.greenhouse.io`
- Ashby URLs on `jobs.ashbyhq.com`

Automation flow:

- `data/company_sources.csv` is the human-maintained source of truth.
- `data/companies.json` is generated runtime config.
- The daily source update workflow runs `python scripts/sync_companies.py` automatically before the per-source fetch steps.

Optional local command:

```bash
python scripts/sync_companies.py
```

Discovery command:

```bash
python scripts/sync_company_leads.py
```

This fetches Simplify's public listings feed and writes supported ATS company leads to:

- `data/company_leads.csv`

This regenerates:

- `data/companies.json`

Notes:

- `data/companies.json` is generated runtime config and should not be edited by hand for normal company additions.
- Contributors normally only need to edit `data/company_sources.csv`.
- `python scripts/sync_companies.py` normalizes `data/company_sources.csv` and removes later duplicate rows, keeping the first occurrence.
- Unsupported URLs are skipped by the sync script with a warning.
- For Greenhouse, use the board URL form `https://boards.greenhouse.io/<board-token>`.
- For Ashby, use the board URL form `https://jobs.ashbyhq.com/<job-board-name>`.
- Use `enabled=false` if you want to keep a supported source in the CSV without fetching it yet.

## Pull Request Guidelines

- Keep changes small
- Use clear commit messages
- Do not add unrelated changes
- Verify JSON formatting before opening a PR
