# European Job Market Analysis

An end-to-end data analytics project exploring Data Analyst, BI Analyst, and
Business Analyst vacancies across the United Kingdom, Germany, Switzerland,
and Spain using the Adzuna API, Python, and Power BI.

## Automated data collection

The repository includes a GitHub Actions workflow that runs every day at
07:17 UTC. It collects the latest searchable Adzuna listings, removes duplicate
job IDs within the daily snapshot, and updates the project history.

Generated files:

- `data/daily/adzuna_jobs_YYYY-MM-DD.csv`: one cleaned snapshot per day;
- `data/history/jobs_master.csv`: one row per job, with first/last seen dates;
- `data/history/job_snapshots.csv`: daily job-presence observations;
- `data/history/job_search_matches.csv`: search-term lineage;
- `data/logs/collection_runs.csv`: execution and quality metrics.

The collector keeps salaries in their original currencies: GBP, EUR, and CHF.
It does not treat the absence of remote-work keywords as proof that a job is
on-site.

## Initial setup

1. Open **Settings → Secrets and variables → Actions** in this repository.
2. Create a repository secret named `ADZUNA_APP_ID`.
3. Create a repository secret named `ADZUNA_APP_KEY`.
4. Open **Actions → Daily Adzuna job collection**.
5. Select **Run workflow** to test the first collection.

If the workflow cannot push the generated CSV files, open
**Settings → Actions → General → Workflow permissions** and select
**Read and write permissions**.

Never add the real API credentials to `.env`, source files, notebooks, or CSV
files committed to GitHub.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ADZUNA_APP_ID="your_app_id"
export ADZUNA_APP_KEY="your_app_key"
python src/collect_jobs.py
```

## Methodological scope

The daily output is a repeated snapshot of advertisements accessible through
the Adzuna Search API. It should not be described as a census of every vacancy
published in each country. Search coverage, language, selected terms, API page
limits, and listing availability all affect the results.

## Data source and permitted use

Vacancy and salary data is sourced from [The Adzuna API](https://www.adzuna.co.uk/).
This project is intended for personal research and portfolio use. Review the
[Adzuna API Terms of Service](https://developer.adzuna.com/docs/terms_of_service)
and obtain any required written permission before commercial, governmental, or
institutional use.

The original code in this repository is licensed under the MIT License. The
job-advertisement data is not covered by that software license and remains
subject to Adzuna's applicable terms.
