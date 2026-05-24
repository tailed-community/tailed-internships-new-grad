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
- Greenhouse-hosted board URLs on `boards.greenhouse.io`

Automation flow:

- `data/company_sources.csv` is the human-maintained source of truth.
- `data/companies.json` is generated runtime config.
- The daily source update workflow runs `python scripts/sync_companies.py` automatically before the per-source fetch steps.

Optional local command:

```bash
python scripts/sync_companies.py
```

This regenerates:

- `data/companies.json`

Notes:

- `data/companies.json` is generated runtime config and should not be edited by hand for normal company additions.
- Contributors normally only need to edit `data/company_sources.csv`.
- `python scripts/sync_companies.py` normalizes `data/company_sources.csv` and removes later duplicate rows, keeping the first occurrence.
- Unsupported URLs are skipped by the sync script with a warning.
- For Greenhouse, use the board URL form `https://boards.greenhouse.io/<board-token>`.
- Use `enabled=false` if you want to keep a supported source in the CSV without fetching it yet.

## Add a Glassdoor Discovery Lead

Glassdoor is discovery-only in this repo. It is not a supported runtime job source like Workday, Lever, or Greenhouse.

Contributors should add raw Glassdoor leads to:

- `data/glassdoor_leads.csv`

CSV columns:

- `company`
- `url`
- `title`
- `location`
- `query`
- `native_url`
- `notes`

Discovery flow:

- `data/glassdoor_leads.csv` is the human-maintained discovery input.
- `data/company_leads.json` is the generated discovery output.
- Discovery leads are for review only and do not write directly to `data/jobs.json`.
- If `native_url` points to a supported official ATS page, the discovery sync can canonicalize that URL and add the company source to `data/company_sources.csv` for review.
- Approved companies still flow into the job updater only through `data/company_sources.csv`.

Optional local command:

```bash
python scripts/sync_company_leads.py
```

Default behavior:

- Running the command with no flags performs a public Glassdoor discovery search for `internship` in `Canada`.
- Discovered results are appended to `data/glassdoor_leads.csv` and normalized into `data/company_leads.json`.
- Use `--skip-discovery` if you only want to normalize the existing CSV contents.

To also promote resolvable official ATS URLs into `data/company_sources.csv`:

```bash
python scripts/sync_company_leads.py --promote-ready
python scripts/sync_companies.py
```

Notes:

- Use Glassdoor only for possible company/job leads.
- Do not add Glassdoor URLs to `data/company_sources.csv`.
- `data/company_leads.json` is generated and should not be edited by hand for normal lead additions.
- Use `native_url` for the official ATS/apply URL when available. The sync script extracts the company-level source URL, not the specific job URL.
- The approval boundary remains a PR that reviews promoted official URLs in `data/company_sources.csv`.

## Pull Request Guidelines

- Keep changes small
- Use clear commit messages
- Do not add unrelated changes
- Verify JSON formatting before opening a PR
