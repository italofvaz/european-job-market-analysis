from __future__ import annotations

import ast
import html
import json
import logging
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DAILY_DIR = DATA_DIR / "daily"
HISTORY_DIR = DATA_DIR / "history"
LOG_DIR = DATA_DIR / "logs"

RESULTS_PER_PAGE = 50
MAX_PAGES_PER_TERM = 5
MAX_REQUESTS_PER_RUN = 70
REQUEST_INTERVAL_SECONDS = 3

SEARCH_CONFIG = [
    {"country_code": "gb", "country": "United Kingdom", "currency": "GBP", "role_family": "Data Analyst", "search_term": "data analyst"},
    {"country_code": "gb", "country": "United Kingdom", "currency": "GBP", "role_family": "BI Analyst", "search_term": "BI analyst"},
    {"country_code": "gb", "country": "United Kingdom", "currency": "GBP", "role_family": "BI Analyst", "search_term": "business intelligence analyst"},
    {"country_code": "gb", "country": "United Kingdom", "currency": "GBP", "role_family": "Business Analyst", "search_term": "business analyst"},
    {"country_code": "de", "country": "Germany", "currency": "EUR", "role_family": "Data Analyst", "search_term": "data analyst"},
    {"country_code": "de", "country": "Germany", "currency": "EUR", "role_family": "Data Analyst", "search_term": "datenanalyst"},
    {"country_code": "de", "country": "Germany", "currency": "EUR", "role_family": "BI Analyst", "search_term": "BI analyst"},
    {"country_code": "de", "country": "Germany", "currency": "EUR", "role_family": "BI Analyst", "search_term": "business intelligence analyst"},
    {"country_code": "de", "country": "Germany", "currency": "EUR", "role_family": "Business Analyst", "search_term": "business analyst"},
    {"country_code": "ch", "country": "Switzerland", "currency": "CHF", "role_family": "Data Analyst", "search_term": "data analyst"},
    {"country_code": "ch", "country": "Switzerland", "currency": "CHF", "role_family": "BI Analyst", "search_term": "BI analyst"},
    {"country_code": "ch", "country": "Switzerland", "currency": "CHF", "role_family": "BI Analyst", "search_term": "business intelligence analyst"},
    {"country_code": "ch", "country": "Switzerland", "currency": "CHF", "role_family": "Business Analyst", "search_term": "business analyst"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "Data Analyst", "search_term": "data analyst"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "Data Analyst", "search_term": "analista de datos"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "BI Analyst", "search_term": "BI analyst"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "BI Analyst", "search_term": "business intelligence analyst"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "BI Analyst", "search_term": "analista BI"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "Business Analyst", "search_term": "business analyst"},
    {"country_code": "es", "country": "Spain", "currency": "EUR", "role_family": "Business Analyst", "search_term": "analista de negocio"},
]

LOGGER = logging.getLogger("adzuna_collection")


class RequestBudgetExceeded(RuntimeError):
    """Raised before a request would exceed the configured daily budget."""


class AdzunaClient:
    def __init__(self, app_id: str, app_key: str) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.request_count = 0
        self.session = requests.Session()

    def search(self, country_code: str, search_term: str, page: int) -> dict[str, Any]:
        if self.request_count >= MAX_REQUESTS_PER_RUN:
            raise RequestBudgetExceeded(
                f"The run reached its safety limit of {MAX_REQUESTS_PER_RUN} API requests."
            )

        if self.request_count:
            time.sleep(REQUEST_INTERVAL_SECONDS)

        url = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/{page}"
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": RESULTS_PER_PAGE,
            "what": search_term,
            "title_only": 1,
            "sort_by": "date",
            "content-type": "application/json",
        }

        self.request_count += 1
        response = self.session.get(url, params=params, timeout=45)
        response.raise_for_status()
        return response.json()


def clean_text(value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return pd.NA
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else pd.NA


def normalize_for_matching(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return text.lower().strip()


def parse_location_area(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (SyntaxError, ValueError):
        pass
    return [text]


def classify_title_role(title: Any) -> Any:
    text = normalize_for_matching(title)

    if re.search(r"\bdata\s*(?:&|and)?\s*business analyst\b", text):
        return "Business Analyst"
    if re.search(r"\bdata(?:\s+analytics)?[\s-]+analyst\b", text):
        return "Data Analyst"
    if re.search(r"\banalista[\s-]+(?:de[\s-]+)?datos\b", text):
        return "Data Analyst"
    if re.search(r"\bdaten(?:[\s-]?analyst|analytiker)\b", text):
        return "Data Analyst"
    if re.search(r"\bbusiness intelligence\b|\bbi[\s-]+analyst\b|\banalista[\s-]+bi\b", text):
        return "BI Analyst"
    if re.search(r"\bbusiness[\s-]+analyst\b|\bbusiness[\s-]+analysis\b", text):
        return "Business Analyst"
    if re.search(r"\banalista[\s-]+de[\s-]+negocios?\b", text):
        return "Business Analyst"
    if re.search(r"\bgeschafts(?:analyst|analytiker)\b", text):
        return "Business Analyst"
    return pd.NA


def choose_primary_role(title_role: Any, matched_families: str) -> tuple[str, str, bool]:
    if pd.notna(title_role):
        return str(title_role), "Title rule", False

    families = [family.strip() for family in str(matched_families).split("|") if family.strip()]
    unique_families = list(dict.fromkeys(families))
    if len(unique_families) == 1:
        return unique_families[0], "Single search family", False

    priority = ["Data Analyst", "BI Analyst", "Business Analyst"]
    fallback = next((role for role in priority if role in unique_families), "Business Analyst")
    return fallback, "Multiple-family fallback", True


def classify_workplace(title: Any, description: Any) -> str:
    title_text = "" if title is None or pd.isna(title) else str(title)
    description_text = "" if description is None or pd.isna(description) else str(description)
    text = normalize_for_matching(f"{title_text} {description_text}")
    hybrid = [r"\bhybrid\b", r"\bhybride\b", r"\bhibrid[oa]\b", r"\bhybridarbeit\b"]
    remote = [
        r"\bremote\b", r"\bremot[oa]\b", r"\bteletrabajo\b", r"\bhome[ -]?office\b",
        r"\bwork from home\b", r"\bwfh\b", r"\btravail a distance\b",
    ]
    onsite = [r"\bon[ -]?site\b", r"\bpresencial\b", r"\bvor ort\b", r"\boffice-based\b"]

    if any(re.search(pattern, text) for pattern in hybrid):
        return "Hybrid"
    if any(re.search(pattern, text) for pattern in remote):
        return "Remote"
    if any(re.search(pattern, text) for pattern in onsite):
        return "On-site"
    return "Not specified"


def collect_raw_snapshot(client: AdzunaClient, collected_at: pd.Timestamp) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    failures: list[dict[str, Any]] = []
    budget_exhausted = False

    for search in SEARCH_CONFIG:
        if budget_exhausted:
            break

        LOGGER.info(
            "Collecting %s | %s | %s",
            search["country"],
            search["role_family"],
            search["search_term"],
        )

        try:
            first_page = client.search(search["country_code"], search["search_term"], 1)
        except RequestBudgetExceeded as exc:
            failures.append({**search, "page": 1, "reason": str(exc)})
            budget_exhausted = True
            break
        except requests.RequestException as exc:
            failures.append({**search, "page": 1, "reason": str(exc)})
            LOGGER.error("Page 1 failed: %s", exc)
            continue

        estimated_count = int(first_page.get("count", 0) or 0)
        pages_planned = min(max(math.ceil(estimated_count / RESULTS_PER_PAGE), 1), MAX_PAGES_PER_TERM)

        page_payloads = [(1, first_page)]
        for page in range(2, pages_planned + 1):
            try:
                page_payloads.append(
                    (page, client.search(search["country_code"], search["search_term"], page))
                )
            except RequestBudgetExceeded as exc:
                failures.append({**search, "page": page, "reason": str(exc)})
                budget_exhausted = True
                break
            except requests.RequestException as exc:
                failures.append({**search, "page": page, "reason": str(exc)})
                LOGGER.error("Page %s failed: %s", page, exc)

        for page, payload in page_payloads:
            results = payload.get("results", [])
            if not results:
                continue
            page_df = pd.json_normalize(results)
            page_df["country_code"] = search["country_code"]
            page_df["country"] = search["country"]
            page_df["currency"] = search["currency"]
            page_df["role_family"] = search["role_family"]
            page_df["search_term"] = search["search_term"]
            page_df["query_page"] = page
            page_df["estimated_job_count"] = estimated_count
            page_df["collected_at_utc"] = collected_at.isoformat()
            first_position = ((page - 1) * RESULTS_PER_PAGE) + 1
            page_df["query_result_position"] = range(first_position, first_position + len(page_df))
            frames.append(page_df)

        if budget_exhausted:
            break

    if not frames:
        raise RuntimeError("No job data was collected.")
    return pd.concat(frames, ignore_index=True, sort=False), failures


def clean_snapshot(raw_df: pd.DataFrame, snapshot_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = ["id", "title", "country_code", "country", "currency", "role_family", "search_term"]
    missing = [column for column in required if column not in raw_df.columns]
    if missing:
        raise KeyError(f"Missing required API columns: {missing}")

    working = raw_df.copy()
    working["country_code"] = working["country_code"].astype("string").str.strip().str.lower()
    working["id"] = working["id"].astype("string").str.strip()
    working = working[working["id"].notna() & working["id"].ne("")].copy()
    working["job_key"] = working["country_code"] + "-" + working["id"]

    match_columns = [
        "job_key", "country_code", "id", "role_family", "search_term", "query_page",
        "query_result_position", "estimated_job_count", "collected_at_utc",
    ]
    matches = working[[column for column in match_columns if column in working.columns]].copy()
    matches["snapshot_date"] = snapshot_date
    matches = matches.sort_values(["job_key", "query_result_position"], na_position="last")
    matches = matches.drop_duplicates(["job_key", "role_family", "search_term"], keep="first")

    match_summary = (
        matches.groupby("job_key")
        .agg(
            matched_search_terms=("search_term", lambda values: " | ".join(sorted(set(values.dropna().astype(str))))),
            matched_role_families=("role_family", lambda values: " | ".join(sorted(set(values.dropna().astype(str))))),
            search_term_count=("search_term", "nunique"),
            role_family_count=("role_family", "nunique"),
        )
        .reset_index()
    )

    important = [
        "title", "description", "company.display_name", "location.display_name", "location.area",
        "created", "salary_min", "salary_max", "contract_type", "contract_time", "latitude",
        "longitude", "category.label", "redirect_url",
    ]
    available_important = [column for column in important if column in working.columns]
    working["_completeness"] = working[available_important].notna().sum(axis=1)
    position_values = working.get(
        "query_result_position",
        pd.Series(pd.NA, index=working.index, dtype="Float64"),
    )
    working["_position"] = pd.to_numeric(position_values, errors="coerce").fillna(float("inf"))
    clean = (
        working.sort_values(["job_key", "_completeness", "_position"], ascending=[True, False, True])
        .drop_duplicates("job_key", keep="first")
        .drop(columns=["_completeness", "_position"])
        .merge(match_summary, on="job_key", how="left", validate="one_to_one")
    )

    rename_map = {
        "id": "job_id",
        "title": "job_title",
        "description": "job_description",
        "company.display_name": "company",
        "location.display_name": "location",
        "location.area": "location_area",
        "created": "published_at",
        "category.label": "category",
        "redirect_url": "job_url",
        "role_family": "selected_role_family",
    }
    clean = clean.rename(columns=rename_map)

    text_columns = [
        "job_title", "job_description", "company", "location", "category", "contract_type",
        "contract_time", "job_url",
    ]
    for column in text_columns:
        if column in clean.columns:
            clean[column] = clean[column].apply(clean_text)

    clean["company_disclosed"] = clean.get("company", pd.Series(pd.NA, index=clean.index)).notna()
    clean["company"] = clean.get("company", pd.Series(pd.NA, index=clean.index)).fillna("Not disclosed")

    clean["published_at"] = pd.to_datetime(clean.get("published_at"), errors="coerce", utc=True)
    clean["collected_at_utc"] = pd.to_datetime(clean.get("collected_at_utc"), errors="coerce", utc=True)
    clean["published_date"] = clean["published_at"].dt.date.astype("string")
    clean["snapshot_date"] = snapshot_date
    clean["publication_year"] = clean["published_at"].dt.year.astype("Int64")
    clean["publication_month"] = clean["published_at"].dt.month.astype("Int64")
    clean["publication_year_month"] = clean["published_at"].dt.strftime("%Y-%m")
    clean["days_since_publication"] = (
        clean["collected_at_utc"].dt.floor("D") - clean["published_at"].dt.floor("D")
    ).dt.days.astype("Int64")

    for column in ["salary_min", "salary_max", "latitude", "longitude"]:
        if column not in clean.columns:
            clean[column] = pd.NA
        clean[column] = pd.to_numeric(clean[column], errors="coerce")

    clean["salary_invalid_nonpositive"] = (
        (clean["salary_min"].notna() & clean["salary_min"].le(0))
        | (clean["salary_max"].notna() & clean["salary_max"].le(0))
    )
    clean.loc[clean["salary_min"].le(0), "salary_min"] = pd.NA
    clean.loc[clean["salary_max"].le(0), "salary_max"] = pd.NA
    clean["has_salary"] = clean["salary_min"].notna() | clean["salary_max"].notna()
    clean["salary_midpoint"] = clean[["salary_min", "salary_max"]].mean(axis=1, skipna=True)
    if "salary_is_predicted" in clean.columns:
        clean["salary_is_predicted"] = (
            pd.to_numeric(clean["salary_is_predicted"], errors="coerce").map({1: True, 0: False}).astype("boolean")
        )
    else:
        clean["salary_is_predicted"] = pd.Series(pd.NA, index=clean.index, dtype="boolean")

    contract_time_map = {"full_time": "Full-time", "part_time": "Part-time"}
    contract_type_map = {"permanent": "Permanent", "contract": "Contract"}
    clean["contract_time"] = clean.get("contract_time", pd.Series(pd.NA, index=clean.index)).str.lower().map(contract_time_map).fillna("Not specified")
    clean["contract_type"] = clean.get("contract_type", pd.Series(pd.NA, index=clean.index)).str.lower().map(contract_type_map).fillna("Not specified")

    location_lists = clean.get("location_area", pd.Series(pd.NA, index=clean.index)).apply(parse_location_area)
    clean["location_hierarchy"] = location_lists.apply(lambda values: " | ".join(values) if values else pd.NA)
    clean["region"] = location_lists.apply(lambda values: values[1] if len(values) > 1 else pd.NA)
    clean["city"] = location_lists.apply(lambda values: values[-1] if len(values) > 1 else pd.NA)
    clean["location_area"] = location_lists.apply(json.dumps)

    clean["title_role_family"] = clean["job_title"].apply(classify_title_role)
    role_choices = clean.apply(
        lambda row: choose_primary_role(row["title_role_family"], row["matched_role_families"]), axis=1
    )
    clean["primary_role_family"] = role_choices.apply(lambda value: value[0])
    clean["role_resolution_method"] = role_choices.apply(lambda value: value[1])
    clean["role_review_required"] = role_choices.apply(lambda value: value[2])
    clean["workplace_type"] = clean.apply(
        lambda row: classify_workplace(row.get("job_title"), row.get("job_description")), axis=1
    )

    final_columns = [
        "job_key", "job_id", "job_title", "primary_role_family", "title_role_family",
        "selected_role_family", "matched_role_families", "matched_search_terms", "search_term_count",
        "role_family_count", "role_resolution_method", "role_review_required", "company",
        "company_disclosed", "category", "country_code", "country", "currency", "location",
        "city", "region", "location_hierarchy", "location_area", "latitude", "longitude",
        "workplace_type", "contract_type", "contract_time", "published_at", "published_date",
        "publication_year", "publication_month", "publication_year_month", "snapshot_date",
        "days_since_publication", "salary_min", "salary_max", "salary_midpoint", "has_salary",
        "salary_is_predicted", "salary_invalid_nonpositive", "job_description", "job_url",
        "collected_at_utc",
    ]
    clean = clean[[column for column in final_columns if column in clean.columns]].copy()
    clean = clean.sort_values(["country", "primary_role_family", "published_at"], ascending=[True, True, False])

    matches = matches.rename(columns={"id": "job_id"})
    return clean.reset_index(drop=True), matches.reset_index(drop=True)


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def update_history(daily_jobs: pd.DataFrame, daily_matches: pd.DataFrame, snapshot_date: str) -> int:
    master_path = HISTORY_DIR / "jobs_master.csv"
    snapshots_path = HISTORY_DIR / "job_snapshots.csv"
    matches_path = HISTORY_DIR / "job_search_matches.csv"

    existing_master = read_csv_if_exists(master_path)
    existing_keys = set(existing_master.get("job_key", pd.Series(dtype="string")).dropna().astype(str))
    new_job_count = int((~daily_jobs["job_key"].astype(str).isin(existing_keys)).sum())

    existing_snapshots = read_csv_if_exists(snapshots_path)
    daily_observations = daily_jobs[
        ["job_key", "snapshot_date", "country_code", "country", "primary_role_family", "has_salary", "workplace_type"]
    ].copy()
    snapshots = pd.concat([existing_snapshots, daily_observations], ignore_index=True, sort=False)
    snapshots = snapshots.drop_duplicates(["job_key", "snapshot_date"], keep="last")
    snapshots = snapshots.sort_values(["snapshot_date", "job_key"])

    seen_stats = (
        snapshots.groupby("job_key")
        .agg(
            first_seen_at=("snapshot_date", "min"),
            last_seen_at=("snapshot_date", "max"),
            times_seen=("snapshot_date", "nunique"),
        )
        .reset_index()
    )

    history_columns = ["first_seen_at", "last_seen_at", "times_seen"]
    existing_details = existing_master.drop(columns=history_columns, errors="ignore")
    all_details = pd.concat([existing_details, daily_jobs], ignore_index=True, sort=False)
    all_details["_collected_sort"] = pd.to_datetime(all_details.get("collected_at_utc"), errors="coerce", utc=True)
    master = (
        all_details.sort_values(["job_key", "_collected_sort"])
        .drop_duplicates("job_key", keep="last")
        .drop(columns="_collected_sort")
        .merge(seen_stats, on="job_key", how="left", validate="one_to_one")
        .sort_values(["country", "primary_role_family", "published_at"], ascending=[True, True, False])
    )

    existing_matches = read_csv_if_exists(matches_path)
    matches = pd.concat([existing_matches, daily_matches], ignore_index=True, sort=False)
    matches = matches.drop_duplicates(["job_key", "snapshot_date", "role_family", "search_term"], keep="last")
    matches = matches.sort_values(["snapshot_date", "job_key", "search_term"])

    write_csv(master, master_path)
    write_csv(snapshots, snapshots_path)
    write_csv(matches, matches_path)
    return new_job_count


def append_run_log(run_record: dict[str, Any]) -> None:
    path = LOG_DIR / "collection_runs.csv"
    existing = read_csv_if_exists(path)
    updated = pd.concat([existing, pd.DataFrame([run_record])], ignore_index=True, sort=False)
    write_csv(updated, path)


def validate_environment() -> tuple[str, str]:
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise RuntimeError(
            "ADZUNA_APP_ID and ADZUNA_APP_KEY must be configured as environment variables."
        )
    return app_id, app_key


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    started_at = datetime.now(timezone.utc)
    collected_at = pd.Timestamp(started_at)
    snapshot_date = started_at.date().isoformat()
    app_id, app_key = validate_environment()
    client = AdzunaClient(app_id, app_key)

    raw_df, failures = collect_raw_snapshot(client, collected_at)
    daily_jobs, daily_matches = clean_snapshot(raw_df, snapshot_date)
    new_job_count = update_history(daily_jobs, daily_matches, snapshot_date)

    daily_path = DAILY_DIR / f"adzuna_jobs_{snapshot_date}.csv"
    write_csv(daily_jobs, daily_path)

    finished_at = datetime.now(timezone.utc)
    append_run_log(
        {
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "snapshot_date": snapshot_date,
            "api_requests": client.request_count,
            "raw_records": len(raw_df),
            "unique_jobs": len(daily_jobs),
            "new_jobs": new_job_count,
            "failed_requests": len(failures),
            "jobs_requiring_role_review": int(daily_jobs["role_review_required"].sum()),
            "daily_file": str(daily_path.relative_to(ROOT_DIR)),
        }
    )

    if failures:
        failure_path = LOG_DIR / f"failed_requests_{snapshot_date}.json"
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.write_text(json.dumps(failures, indent=2, ensure_ascii=False), encoding="utf-8")

    LOGGER.info(
        "Finished: %s raw records, %s unique jobs, %s new jobs, %s API requests, %s failures",
        len(raw_df), len(daily_jobs), new_job_count, client.request_count, len(failures),
    )


if __name__ == "__main__":
    main()
