# Contributing

## Ways to Contribute

- Add a missing internship
- Add a missing new grad role
- Fix a broken application link
- Suggest a company source
- Improve automation scripts

## Add a Job Manually

Contributors can update:

- `data/internships.json`
- `data/new_grad.json`

Please follow the existing JSON schema for every job entry.

## Add a Company Source

Companies will later be added to:

`data/companies.json`

For now, companies can be added with `enabled` set to `false` until the fetcher supports them.

## Pull Request Guidelines

- Keep changes small
- Use clear commit messages
- Do not add unrelated changes
- Verify JSON formatting before opening a PR
