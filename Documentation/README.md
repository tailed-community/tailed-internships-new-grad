# Documentation

This folder explains how the job-source automation works and how to extend it.

## Start Here

- [System Overview](./system-overview.md): how CSV sources, generated config, fetchers, jobs, archives, and Markdown tables connect.
- [Adding Companies](./adding-companies.md): how to add a supported company source to `data/company_sources.csv`.
- [Adding ATS Support](./adding-ats-support.md): how to add a new ATS integration later.
- [Custom Career Page ATS Discovery](./custom-career-pages.md): how custom company career pages are used only to find underlying ATS platforms.
- [Automation Workflows](./automation-workflows.md): what the GitHub Actions workflows do.
- [Contributor Checklist](./contributor-checklist.md): practical checks before opening a PR.

## Main Rule

The repository does not try to scrape every custom company website directly. The stable path is:

1. Find company career pages.
2. Detect whether those pages point to a supported ATS.
3. Add the canonical ATS source to `data/company_sources.csv`.
4. Generate `data/companies.json`.
5. Fetch jobs through the supported ATS fetchers.

