import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.collect_jobs import AdzunaClient, clean_snapshot


class CollectorTests(unittest.TestCase):
    @patch("src.collect_jobs.requests.Session")
    def test_search_limits_matching_to_titles(self, session_class):
        response = MagicMock()
        response.json.return_value = {"count": 0, "results": []}
        session_class.return_value.get.return_value = response

        client = AdzunaClient("test-id", "test-key")
        client.search("gb", "data analyst", 1)

        request_params = session_class.return_value.get.call_args.kwargs["params"]
        self.assertEqual(request_params["what"], "data analyst")
        self.assertEqual(request_params["title_only"],"data analyst")
        self.assertEqual(request_params["sort_by"], "date")

    def test_clean_snapshot_deduplicates_and_resolves_roles(self):
        raw = pd.DataFrame(
            [
                self._job(
                    role_family="Data Analyst",
                    search_term="data analyst",
                    query_result_position=5,
                    description=None,
                    company=None,
                ),
                self._job(
                    role_family="Business Analyst",
                    search_term="business analyst",
                    query_result_position=1,
                    description="Hybrid role with SQL and reporting.",
                    company="Example Ltd",
                ),
            ]
        )

        jobs, matches = clean_snapshot(raw, "2026-09-03")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(matches), 2)
        job = jobs.iloc[0]
        self.assertEqual(job["job_key"], "gb-100")
        self.assertEqual(job["primary_role_family"], "Business Analyst")
        self.assertEqual(job["matched_role_families"], "Business Analyst | Data Analyst")
        self.assertEqual(job["company"], "Example Ltd")
        self.assertEqual(job["workplace_type"], "Hybrid")
        self.assertEqual(job["salary_midpoint"], 55_000)
        self.assertFalse(job["role_review_required"])

    @staticmethod
    def _job(
        role_family,
        search_term,
        query_result_position,
        description,
        company,
    ):
        return {
            "id": "100",
            "title": "Business Analyst - Data Governance",
            "description": description,
            "company.display_name": company,
            "location.display_name": "London",
            "location.area": ["UK", "London"],
            "created": "2026-09-03T08:00:00Z",
            "salary_min": 50_000,
            "salary_max": 60_000,
            "salary_is_predicted": 0,
            "contract_type": "permanent",
            "contract_time": "full_time",
            "latitude": 51.5,
            "longitude": -0.1,
            "category.label": "IT Jobs",
            "redirect_url": "https://example.com/100",
            "country_code": "gb",
            "country": "United Kingdom",
            "currency": "GBP",
            "role_family": role_family,
            "search_term": search_term,
            "query_page": 1,
            "query_result_position": query_result_position,
            "estimated_job_count": 200,
            "collected_at_utc": "2026-09-03T10:00:00Z",
        }


if __name__ == "__main__":
    unittest.main()
