import unittest
from datetime import date

from archive_evidence.freshness import evaluate_freshness


class FreshnessTests(unittest.TestCase):
    def test_unenrolled_material_produces_no_missing_field_findings(self):
        rows = [{"opaque_ref": "ref-1", "enrolled": False}]

        result = evaluate_freshness(rows, today=date(2026, 7, 30), known_paths=set())

        self.assertEqual(result["findings"], [])
        self.assertFalse(result["blocking"])

    def test_enrolled_material_reports_missing_required_temporal_fields(self):
        rows = [{"opaque_ref": "ref-1", "enrolled": True}]

        result = evaluate_freshness(rows, today=date(2026, 7, 30), known_paths=set())

        self.assertEqual(
            result["counts"],
            {"missing_as_of": 1, "missing_freshness_class": 1, "missing_verified_at": 1},
        )
        self.assertFalse(result["blocking"])

    def test_impossible_temporal_values_are_blocking(self):
        rows = [
            {
                "opaque_ref": "ref-1",
                "enrolled": True,
                "as_of": "2026-08-01",
                "verified_at": "2026-07-20",
                "freshness_class": "operational",
            }
        ]

        result = evaluate_freshness(rows, today=date(2026, 7, 30), known_paths=set())

        self.assertTrue(result["blocking"])
        self.assertEqual(result["counts"]["future_as_of"], 1)
        self.assertEqual(result["counts"]["as_of_after_verified_at"], 1)

    def test_overdue_window_is_report_only(self):
        rows = [
            {
                "opaque_ref": "ref-1",
                "enrolled": True,
                "as_of": "2026-04-01",
                "verified_at": "2026-05-01",
                "freshness_class": "active-project",
                "status": "current",
            }
        ]

        result = evaluate_freshness(rows, today=date(2026, 7, 30), known_paths=set())

        self.assertEqual(result["counts"], {"overdue_verification": 1})
        self.assertFalse(result["blocking"])

    def test_null_status_does_not_suppress_report_only_overdue_finding(self):
        rows = [
            {
                "opaque_ref": "ref-1",
                "enrolled": True,
                "as_of": None,
                "verified_at": "2026-06-01",
                "freshness_class": "operational",
                "status": None,
            }
        ]

        result = evaluate_freshness(rows, today=date(2026, 7, 30), known_paths=set())

        self.assertEqual(result["counts"], {"missing_as_of": 1, "overdue_verification": 1})
        self.assertFalse(result["blocking"])

    def test_invalid_class_status_and_missing_supersession_target_block(self):
        rows = [
            {
                "opaque_ref": "ref-1",
                "enrolled": True,
                "as_of": "2026-07-01",
                "verified_at": "2026-07-20",
                "freshness_class": "durable",
                "status": "retired",
                "supersedes": ["knowledge/concepts/missing.md"],
            }
        ]

        result = evaluate_freshness(rows, today=date(2026, 7, 30), known_paths=set())

        self.assertTrue(result["blocking"])
        self.assertEqual(
            result["counts"],
            {
                "invalid_freshness_class": 1,
                "invalid_status": 1,
                "missing_supersession_target": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
