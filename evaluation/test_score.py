"""Checks scoring failure modes, including missing answers and invented facts."""
import copy
import unittest
from evaluation.score import score

FACT = dict(id="f1", company="Example Bank", metric="revenue",
            period="FY2025", currency="USD", unit="money", scale="million",
            source_id="doc-1", locator="page:3;row:revenue", value="1250.00",
            abs_tolerance="0.005")


class ScoringTests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(score([FACT], [FACT])["accuracy"], 1)

    def test_missing_is_error(self):
        self.assertEqual(score([FACT], [])["accuracy"], 0)

    def test_abstention_is_not_success(self):
        pred = dict(FACT, value=None)
        self.assertEqual(score([FACT], [pred])["abstention_rate"], 1)
        self.assertEqual(score([FACT], [pred])["accuracy"], 0)

    def test_scale_and_source_must_match(self):
        for field, value in [("scale", "billion"), ("source_id", "wrong"), ("period", "Q42025")]:
            self.assertEqual(score([FACT], [dict(FACT, **{field: value})])["accuracy"], 0)

    def test_tolerance_boundary(self):
        self.assertEqual(score([FACT], [dict(FACT, value="1250.005")])["accuracy"], 1)
        self.assertEqual(score([FACT], [dict(FACT, value="1250.006")])["accuracy"], 0)

    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            score([FACT], [FACT, FACT])

    def test_empty_gold_rejected(self):
        with self.assertRaises(ValueError):
            score([], [])

    def test_nonfinite_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", True):
            with self.assertRaises(ValueError):
                score([FACT], [dict(FACT, value=value)])

    def test_extra_fact_penalises_precision(self):
        result = score([FACT], [FACT, dict(FACT, id="invented")])
        self.assertEqual(result["precision"], .5)
        self.assertEqual(result["extra_predictions"], 1)

    def test_negative_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            score([dict(FACT, abs_tolerance="-1")], [FACT])

    def test_schema_required(self):
        pred = copy.deepcopy(FACT)
        del pred["currency"]
        with self.assertRaises(ValueError):
            score([FACT], [pred])

    def test_threshold_and_uncertainty(self):
        gold = [dict(FACT, id=str(i)) for i in range(20)]
        result = score(gold, gold[:19])
        self.assertEqual(result["accuracy"], .95)
        self.assertTrue(result["threshold_met_on_this_set"])
        self.assertLess(result["accuracy_wilson_95"][0], .95)
        self.assertFalse(result["production_qualified"])


if __name__ == "__main__":
    unittest.main()
