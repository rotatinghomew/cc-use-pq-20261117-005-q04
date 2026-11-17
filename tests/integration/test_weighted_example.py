import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


class WeightedExampleWorkflowTests(unittest.TestCase):
    def test_example_reproduces_raw_v1_and_v2_reports_and_reconciles(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review"
            result = subprocess.run(
                [sys.executable, "-I", str(PROJECT / "examples" / "run_weighted_example.py"),
                 "--output", str(output)],
                capture_output=True, text=True, cwd=PROJECT,
                env={"PYTHONPATH": str(PROJECT / "src")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertIsNone(summary["unweighted"]["weight_spec"])
            self.assertEqual(summary["weighted-v1"]["raw_denominator"], 6)
            self.assertAlmostEqual(summary["weighted-v1"]["weighted_denominator"], 1.0)
            self.assertAlmostEqual(summary["weighted-v1"]["rates"]["harm"]["weighted"], 0.6)
            self.assertAlmostEqual(summary["weighted-v2"]["rates"]["harm"]["weighted"], 0.75)
            self.assertNotEqual(summary["weighted-v1"]["report_id"], summary["weighted-v2"]["report_id"])
            self.assertTrue(all(item["reconciled"] for item in summary.values() if "reconciled" in item))
            for name in ["unweighted.json", "unweighted.md", "weighted-v1.json",
                         "weighted-v1.md", "weighted-v1.csv", "weighted-v2.json", "weighted-v2.md"]:
                self.assertTrue((output / name).is_file(), name)

    def test_example_refuses_to_overwrite_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", str(PROJECT / "examples" / "run_weighted_example.py"),
                 "--output", directory],
                capture_output=True, text=True, cwd=PROJECT,
                env={"PYTHONPATH": str(PROJECT / "src")},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to overwrite", result.stderr)


if __name__ == "__main__":
    unittest.main()
