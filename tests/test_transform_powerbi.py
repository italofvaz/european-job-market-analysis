import unittest

import pandas as pd

from src.transform_powerbi import (
    add_salary_quality,
    build_date_dimension,
    build_skill_tables,
    stable_key,
)


class PowerBiTransformTests(unittest.TestCase):
    def test_stable_key_normalizes_case_and_accents(self):
        first = stable_key("co", "es", "Compañía Ánalitica")
        second = stable_key("co", "ES", "compania analitica")
        self.assertEqual(first, second)

    def test_salary_quality_preserves_but_flags_suspicious_values(self):
        source = pd.DataFrame(
            {
                "salary_min": [50_000, 350, None, 400_000],
                "salary_max": [60_000, 450, None, 420_000],
                "salary_midpoint": [55_000, 400, None, 410_000],
                "salary_invalid_nonpositive": [False, False, False, False],
            }
        )

        checked = add_salary_quality(source)

        self.assertEqual(checked.loc[0, "salary_quality_status"], "Plausible annual")
        self.assertTrue(checked.loc[0, "salary_usable_annual"])
        self.assertEqual(checked.loc[1, "salary_quality_status"], "Possible rate or parse issue")
        self.assertEqual(checked.loc[2, "salary_quality_status"], "Missing")
        self.assertEqual(checked.loc[3, "salary_quality_status"], "High outlier")

    def test_date_dimension_includes_full_range(self):
        dim_date = build_date_dimension(
            pd.Series(["2026-09-01", "2026-09-03"]),
        )
        self.assertEqual(dim_date["date"].tolist(), ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_skill_bridge_tracks_title_and_description_sources(self):
        jobs = pd.DataFrame(
            {
                "job_key": ["gb-1"],
                "job_title": ["Power BI Analyst"],
                "job_description": ["Build SQL reports using Python."],
            }
        )
        _, bridge = build_skill_tables(jobs)
        indexed = bridge.set_index("skill_key")

        self.assertTrue(indexed.loc["power-bi", "found_in_title"])
        self.assertTrue(indexed.loc["sql", "found_in_description"])
        self.assertTrue(indexed.loc["python", "found_in_description"])


if __name__ == "__main__":
    unittest.main()
