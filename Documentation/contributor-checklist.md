# Contributor Checklist

Use this checklist before opening a PR.

## Company Source Changes

- Add or edit rows in `data/company_sources.csv`.
- Run `python scripts/sync_companies.py`.
- Confirm `data/companies.json` was regenerated.
- Check warnings from the script.

## Fetcher Or ATS Changes

- Keep the change source-scoped.
- Reuse existing helper patterns.
- Make URL canonicalization deterministic.
- Add duplicate identity handling when the ATS has stable tenant, slug, or site fields.
- Run `python -m py_compile` on changed scripts.
- Run a source-specific fetch if possible:

```bash
python scripts/main.py --source <source>
```

## Custom Career Page Discovery Changes

- Do not add bespoke website scraping unless there is a clear long-term maintenance plan.
- Prefer detecting a supported ATS under the branded page.
- Run the discovery, detection, promotion, and sync scripts in order.

## Documentation Changes

- Update the relevant file under `Documentation/`.
- Update `CONTRIBUTING.md` if contributor-facing steps changed.
- Update workflow docs if GitHub Actions changed.

## PR Hygiene

- Keep generated output and code changes easy to review.
- Do not mix unrelated refactors with source additions.
- Check for accidental bytecode or local output files.

