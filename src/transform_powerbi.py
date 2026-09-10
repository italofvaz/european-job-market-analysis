from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DAILY_DIR = ROOT_DIR / "data" / "daily"
HISTORY_DIR = ROOT_DIR / "data" / "history"
LOG_DIR = ROOT_DIR / "data" / "logs"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

ANNUAL_SALARY_MIN = 10_000
ANNUAL_SALARY_MAX = 300_000

ROLE_KEYS = {
    "Data Analyst": "DA",
    "BI Analyst": "BI",
    "Business Analyst": "BA",
}

SKILL_RULES = [
    ("sql", "SQL", "Technical", r"\bsql\b"),
    ("python", "Python", "Technical", r"\bpython\b"),
    ("power-bi", "Power BI", "Technical", r"\bpower\s*bi\b|\bpowerbi\b"),
    ("tableau", "Tableau", "Technical", r"\btableau\b"),
    ("excel", "Excel", "Technical", r"\bexcel\b|\bmicrosoft\s+excel\b|\bms\s+excel\b"),
    ("r", "R", "Technical", r"(?<![a-z0-9])r(?![a-z0-9])"),
    ("aws", "AWS", "Cloud", r"\baws\b|\bamazon\s+web\s+services\b"),
    ("azure", "Azure", "Cloud", r"\bazure\b"),
    ("gcp", "Google Cloud", "Cloud", r"\bgcp\b|\bgoogle\s+cloud(?:\s+platform)?\b"),
    ("snowflake", "Snowflake", "Data platform", r"\bsnowflake\b"),
    ("databricks", "Databricks", "Data platform", r"\bdatabricks\b"),
    ("spark", "Spark", "Data platform", r"\bapache\s+spark\b|\bpyspark\b|\bspark\b"),
    ("etl", "ETL", "Data engineering", r"\betl\b|\bextract[, ]+transform[, ]+load\b"),
    ("data-modeling", "Data Modeling", "Data engineering", r"\bdata\s+model(?:ing|ling)\b|\bdimensional\s+model(?:ing|ling)\b"),
    ("dax", "DAX", "Technical", r"\bdax\b"),
    ("machine-learning", "Machine Learning", "Analytics", r"\bmachine\s+learning\b|\bml\b"),
    ("statistics", "Statistics", "Analytics", r"\bstatistics?\b|\bstatistical\b"),
    ("data-visualization", "Data Visualization", "Analytics", r"\bdata\s+visuali[sz]ation\b|\bvisuali[sz]ation\b"),
    ("git", "Git", "Development", r"\bgit\b|\bgithub\b|\bversion\s+control\b"),
    ("agile", "Agile", "Methodology", r"\bagile\b|\bscrum\b"),
    ("stakeholder-management", "Stakeholder Management", "Business", r"\bstakeholder(?:s)?\b|\bstakeholder\s+management\b"),
    ("communication", "Communication", "Business", r"\bcommunication\b|\bkommunikation\b|\bcomunicaci[oó]n\b"),
    ("problem-solving", "Problem Solving", "Business", r"\bproblem[ -]solving\b|\bprobleml[oö]sung\b|\bresoluci[oó]n\s+de\s+problemas\b"),
]

LOGGER = logging.getLogger("powerbi_etl")


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def normalize_key_part(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", text).strip().casefold()


def stable_key(prefix: str, *values: Any) -> str:
    source = "|".join(normalize_key_part(value) for value in values)
    digest = hashlib.sha1(source.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{prefix}-{digest}"


def as_boolean(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype("boolean")
    normalized = series.astype("string").str.strip().str.casefold()
    return normalized.map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}).astype("boolean")


def date_key(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce", utc=True)
    return (dates.dt.year * 10_000 + dates.dt.month * 100 + dates.dt.day).astype("Int64")


def load_sources(root_dir: Path = ROOT_DIR) -> dict[str, pd.DataFrame]:
    daily_paths = sorted((root_dir / "data" / "daily").glob("adzuna_jobs_*.csv"))
    if not daily_paths:
        raise FileNotFoundError("No daily snapshots were found in data/daily.")

    daily_frames = []
    for path in daily_paths:
        frame = read_csv(path)
        frame["source_file"] = path.name
        daily_frames.append(frame)

    sources = {
        "daily": pd.concat(daily_frames, ignore_index=True, sort=False),
        "master": read_csv(root_dir / "data" / "history" / "jobs_master.csv"),
        "matches": read_csv(root_dir / "data" / "history" / "job_search_matches.csv"),
        "runs": read_csv(root_dir / "data" / "logs" / "collection_runs.csv"),
    }
    return sources


def add_dimension_keys(frame: pd.DataFrame) -> pd.DataFrame:
    keyed = frame.copy()
    keyed["country_key"] = keyed["country_code"].astype("string").str.strip().str.lower()
    keyed["role_key"] = keyed["primary_role_family"].map(ROLE_KEYS).fillna("OTHER")
    keyed["company_key"] = keyed.apply(
        lambda row: stable_key("co", row.get("country_code"), row.get("company")), axis=1
    )
    keyed["location_key"] = keyed.apply(
        lambda row: stable_key(
            "loc",
            row.get("country_code"),
            row.get("location"),
            row.get("region"),
            row.get("city"),
        ),
        axis=1,
    )
    return keyed


def add_salary_quality(frame: pd.DataFrame) -> pd.DataFrame:
    checked = frame.copy()
    for column in ["salary_min", "salary_max", "salary_midpoint"]:
        checked[column] = pd.to_numeric(checked.get(column), errors="coerce")

    has_salary = checked["salary_min"].notna() | checked["salary_max"].notna()
    invalid_source = as_boolean(
        checked.get(
            "salary_invalid_nonpositive",
            pd.Series(False, index=checked.index),
        )
    ).fillna(False)
    invalid_range = (
        checked["salary_min"].notna()
        & checked["salary_max"].notna()
        & checked["salary_min"].gt(checked["salary_max"])
    )
    midpoint = checked["salary_midpoint"]

    checked["has_salary"] = has_salary.astype("boolean")
    checked["salary_quality_status"] = "Plausible annual"
    checked.loc[~has_salary, "salary_quality_status"] = "Missing"
    checked.loc[has_salary & midpoint.lt(ANNUAL_SALARY_MIN), "salary_quality_status"] = "Possible rate or parse issue"
    checked.loc[has_salary & midpoint.gt(ANNUAL_SALARY_MAX), "salary_quality_status"] = "High outlier"
    checked.loc[invalid_source | invalid_range, "salary_quality_status"] = "Invalid source value"
    checked.loc[has_salary & midpoint.isna(), "salary_quality_status"] = "Incomplete"
    checked["salary_usable_annual"] = checked["salary_quality_status"].eq("Plausible annual")
    return checked


def choose_most_complete(frame: pd.DataFrame, key: str, detail_columns: list[str]) -> pd.DataFrame:
    candidates = frame.copy()
    available = [column for column in detail_columns if column in candidates.columns]
    candidates["_completeness"] = candidates[available].notna().sum(axis=1)
    return (
        candidates.sort_values([key, "_completeness"], ascending=[True, False])
        .drop_duplicates(key, keep="first")
        .drop(columns="_completeness")
    )


def build_skill_tables(dim_jobs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dim_skill = pd.DataFrame(
        [
            {
                "skill_key": skill_key,
                "skill_name": skill_name,
                "skill_category": category,
            }
            for skill_key, skill_name, category, _ in SKILL_RULES
        ]
    )

    bridge_rows = []
    for row in dim_jobs[["job_key", "job_title", "job_description"]].itertuples(index=False):
        title = normalize_key_part(row.job_title)
        description = normalize_key_part(row.job_description)
        for skill_key, _, _, pattern in SKILL_RULES:
            in_title = bool(re.search(pattern, title, flags=re.IGNORECASE))
            in_description = bool(re.search(pattern, description, flags=re.IGNORECASE))
            if in_title or in_description:
                bridge_rows.append(
                    {
                        "job_key": row.job_key,
                        "skill_key": skill_key,
                        "found_in_title": in_title,
                        "found_in_description": in_description,
                    }
                )

    bridge = pd.DataFrame(
        bridge_rows,
        columns=["job_key", "skill_key", "found_in_title", "found_in_description"],
    )
    return dim_skill, bridge


def build_date_dimension(*series_list: pd.Series) -> pd.DataFrame:
    all_dates = pd.concat(
        [pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None) for series in series_list],
        ignore_index=True,
    ).dropna()
    if all_dates.empty:
        raise ValueError("No valid dates were available to create DimDate.")

    dates = pd.Series(pd.date_range(all_dates.min().normalize(), all_dates.max().normalize(), freq="D"))
    iso = dates.dt.isocalendar()
    dim_date = pd.DataFrame(
        {
            "date_key": (dates.dt.year * 10_000 + dates.dt.month * 100 + dates.dt.day).astype("int64"),
            "date": dates.dt.strftime("%Y-%m-%d"),
            "year": dates.dt.year,
            "quarter": "Q" + dates.dt.quarter.astype(str),
            "month_number": dates.dt.month,
            "month_name": dates.dt.month_name(),
            "year_month": dates.dt.strftime("%Y-%m"),
            "iso_week": iso.week.astype("int64"),
            "week_start": (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d"),
            "day_number": dates.dt.day,
            "day_name": dates.dt.day_name(),
            "is_weekend": dates.dt.weekday.ge(5),
        }
    )
    return dim_date


def build_powerbi_tables(sources: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    daily = add_salary_quality(add_dimension_keys(sources["daily"]))
    master = add_salary_quality(add_dimension_keys(sources["master"]))

    dimension_source = pd.concat([master, daily], ignore_index=True, sort=False)

    dim_country = (
        dimension_source[["country_key", "country_code", "country", "currency"]]
        .drop_duplicates()
        .rename(columns={"country": "country_name"})
        .sort_values("country_name")
        .reset_index(drop=True)
    )

    dim_role = pd.DataFrame(
        [
            {"role_key": key, "role_family": role}
            for role, key in ROLE_KEYS.items()
        ]
    ).sort_values("role_family").reset_index(drop=True)

    company_source = choose_most_complete(
        dimension_source,
        "company_key",
        ["company", "company_disclosed", "country_key"],
    )
    dim_company = company_source[
        ["company_key", "company", "company_disclosed", "country_key"]
    ].rename(columns={"company": "company_name"})
    dim_company["company_disclosed"] = as_boolean(dim_company["company_disclosed"])
    dim_company = dim_company.sort_values(["country_key", "company_name"]).reset_index(drop=True)

    location_source = choose_most_complete(
        dimension_source,
        "location_key",
        ["location", "city", "region", "latitude", "longitude", "country_key"],
    )
    dim_location = location_source[
        ["location_key", "location", "city", "region", "latitude", "longitude", "country_key"]
    ].rename(columns={"location": "location_name"})
    dim_location = dim_location.sort_values(["country_key", "region", "city"], na_position="last").reset_index(drop=True)

    dim_jobs = master.copy()
    dim_jobs["published_date_key"] = date_key(dim_jobs["published_at"])
    dim_jobs["first_seen_date_key"] = date_key(dim_jobs["first_seen_at"])
    dim_jobs["last_seen_date_key"] = date_key(dim_jobs["last_seen_at"])
    job_columns = [
        "job_key", "job_id", "job_title", "category", "country_key", "role_key",
        "company_key", "location_key", "published_at", "published_date_key",
        "first_seen_date_key", "last_seen_date_key", "times_seen", "role_resolution_method",
        "role_review_required", "job_description", "job_url",
    ]
    dim_jobs = dim_jobs[job_columns].sort_values("job_key").reset_index(drop=True)
    dim_jobs["job_id"] = dim_jobs["job_id"].astype("string")
    dim_jobs["role_review_required"] = as_boolean(dim_jobs["role_review_required"])

    daily["snapshot_date_key"] = date_key(daily["snapshot_date"])
    fact_columns = [
        "job_key", "snapshot_date_key", "country_key", "role_key", "company_key",
        "location_key", "salary_min", "salary_max", "salary_midpoint", "has_salary",
        "salary_is_predicted", "salary_quality_status", "salary_usable_annual",
        "workplace_type", "contract_type", "contract_time", "days_since_publication",
        "source_file",
    ]
    fact_job_snapshots = daily[fact_columns].copy()
    fact_job_snapshots.insert(0, "job_snapshot_key", daily["job_key"] + "-" + daily["snapshot_date_key"].astype("string"))
    fact_job_snapshots["job_count"] = 1
    for column in ["has_salary", "salary_is_predicted", "salary_usable_annual"]:
        fact_job_snapshots[column] = as_boolean(fact_job_snapshots[column])
    fact_job_snapshots = fact_job_snapshots.sort_values(["snapshot_date_key", "job_key"]).reset_index(drop=True)

    matches = sources["matches"].copy()
    matches["snapshot_date_key"] = date_key(matches["snapshot_date"])
    matches["country_key"] = matches["country_code"].astype("string").str.lower()
    matches["role_key"] = matches["role_family"].map(ROLE_KEYS).fillna("OTHER")
    fact_search_matches = matches[
        [
            "job_key", "snapshot_date_key", "country_key", "role_key", "search_term",
            "query_page", "query_result_position", "estimated_job_count",
        ]
    ].sort_values(["snapshot_date_key", "job_key", "search_term"]).reset_index(drop=True)

    fact_collection_runs = sources["runs"].copy()
    fact_collection_runs["snapshot_date_key"] = date_key(fact_collection_runs["snapshot_date"])
    run_columns = [
        "snapshot_date_key", "started_at_utc", "finished_at_utc", "api_requests",
        "raw_records", "unique_jobs", "new_jobs", "failed_requests",
        "jobs_requiring_role_review", "daily_file",
    ]
    fact_collection_runs = fact_collection_runs[run_columns].sort_values("snapshot_date_key").reset_index(drop=True)

    dim_date = build_date_dimension(
        daily["snapshot_date"],
        master["published_at"],
        master["first_seen_at"],
        master["last_seen_at"],
    )
    dim_skill, bridge_job_skills = build_skill_tables(dim_jobs)

    return {
        "fact_job_snapshots": fact_job_snapshots,
        "fact_search_matches": fact_search_matches,
        "fact_collection_runs": fact_collection_runs,
        "dim_jobs": dim_jobs,
        "dim_date": dim_date,
        "dim_country": dim_country,
        "dim_role": dim_role,
        "dim_company": dim_company,
        "dim_location": dim_location,
        "dim_skill": dim_skill,
        "bridge_job_skills": bridge_job_skills,
    }


def validate_tables(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    fact = tables["fact_job_snapshots"]
    checks: list[dict[str, Any]] = []

    def add_check(check: str, value: int, status: str) -> None:
        checks.append({"check": check, "value": int(value), "status": status})

    add_check("Duplicate job_snapshot_key", fact.duplicated("job_snapshot_key").sum(), "FAIL" if fact.duplicated("job_snapshot_key").any() else "PASS")
    add_check("Duplicate job_key in DimJobs", tables["dim_jobs"].duplicated("job_key").sum(), "FAIL" if tables["dim_jobs"].duplicated("job_key").any() else "PASS")

    relationships = [
        ("job_key", "dim_jobs", "job_key"),
        ("snapshot_date_key", "dim_date", "date_key"),
        ("country_key", "dim_country", "country_key"),
        ("role_key", "dim_role", "role_key"),
        ("company_key", "dim_company", "company_key"),
        ("location_key", "dim_location", "location_key"),
    ]
    for fact_column, dimension_name, dimension_column in relationships:
        orphan_count = (~fact[fact_column].isin(tables[dimension_name][dimension_column])).sum()
        add_check(
            f"Orphan {fact_column} against {dimension_name}",
            orphan_count,
            "FAIL" if orphan_count else "PASS",
        )

    salary_issue_count = fact["salary_quality_status"].isin(
        ["Possible rate or parse issue", "High outlier", "Invalid source value", "Incomplete"]
    ).sum()
    add_check("Salary records excluded from annual comparison", salary_issue_count, "WARNING" if salary_issue_count else "PASS")
    role_review_count = tables["dim_jobs"]["role_review_required"].fillna(False).sum()
    add_check(
        "Jobs requiring role review",
        role_review_count,
        "WARNING" if role_review_count else "PASS",
    )

    job_locations = tables["dim_jobs"][["job_key", "location_key"]].merge(
        tables["dim_location"][["location_key", "city"]],
        on="location_key",
        how="left",
        validate="many_to_one",
    )
    missing_city_jobs = job_locations["city"].isna().sum()
    add_check(
        "Jobs without city",
        missing_city_jobs,
        "WARNING" if missing_city_jobs else "PASS",
    )

    job_companies = tables["dim_jobs"][["job_key", "company_key"]].merge(
        tables["dim_company"][["company_key", "company_disclosed"]],
        on="company_key",
        how="left",
        validate="many_to_one",
    )
    missing_company_jobs = (~job_companies["company_disclosed"].fillna(False)).sum()
    add_check(
        "Jobs without disclosed company",
        missing_company_jobs,
        "WARNING" if missing_company_jobs else "PASS",
    )

    return pd.DataFrame(checks)


def run_etl(root_dir: Path = ROOT_DIR) -> dict[str, pd.DataFrame]:
    sources = load_sources(root_dir)
    tables = build_powerbi_tables(sources)
    quality_report = validate_tables(tables)
    tables["etl_quality_report"] = quality_report

    output_dir = root_dir / "data" / "processed"
    for name, frame in tables.items():
        write_csv(frame, output_dir / f"{name}.csv")
        LOGGER.info("Created %s with %s rows", name, len(frame))

    failures = quality_report.loc[quality_report["status"].eq("FAIL")]
    if not failures.empty:
        raise RuntimeError(
            "ETL validation failed: "
            + "; ".join(f"{row.check}={row.value}" for row in failures.itertuples())
        )
    return tables


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    tables = run_etl()
    LOGGER.info(
        "Power BI ETL completed: %s job snapshots and %s jobs",
        len(tables["fact_job_snapshots"]),
        len(tables["dim_jobs"]),
    )


if __name__ == "__main__":
    main()
