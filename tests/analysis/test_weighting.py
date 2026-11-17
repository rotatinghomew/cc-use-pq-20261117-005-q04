import json
import tempfile
import unittest
from pathlib import Path

from story_patterns.analysis.weighting import build_weighted_comparison, normalize_weight_spec
from story_patterns.catalog.validate import normalize_story
from story_patterns.errors import AnalysisError, ConflictError, NotFoundError, ValidationError
from tests.support import AppCase, batch, decision, story


def weight_spec(strata, version=1, spec_id="exercise-frame"):
    return {
        "weight_spec_id": spec_id,
        "version": version,
        "basis": "Synthetic teaching frame; not a news or population estimate.",
        "prepared_by": "teaching-group",
        "strata": strata,
    }


def stratum(tradition, source_kind, material_period, proportion):
    return {"tradition": tradition, "source_kind": source_kind,
            "material_period": material_period, "proportion": proportion}


def period_story(story_id, tradition, source_kind, material_period, revision=1):
    record = story(story_id, revision=revision, tradition=tradition)
    record["source"]["kind"] = source_kind
    record["material_period"] = material_period
    return record


class WeightSpecificationValidationTests(unittest.TestCase):
    def test_proportions_must_sum_exactly_to_one(self):
        for values in [(0.5, 0.4), (0.6, 0.6), (0.1, 0.2, 0.3)]:
            rows = [stratum(f"t{index}", "book", "p", value)
                    for index, value in enumerate(values)]
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValidationError, "sum exactly to 1"):
                    normalize_weight_spec(weight_spec(rows))

    def test_zero_proportion_is_kept_explicitly_not_silently_dropped(self):
        spec = normalize_weight_spec(weight_spec([
            stratum("t", "book", "p", 1.0),
            stratum("t", "oral_record", "p", 0.0),
        ]))
        self.assertEqual(len(spec["strata"]), 2)
        self.assertEqual(spec["strata"][1]["proportion"], 0.0)

    def test_duplicate_and_incomplete_stratum_keys_are_rejected(self):
        duplicate = weight_spec([stratum("t", "book", "p", 0.5), stratum("t", "book", "p", 0.5)])
        with self.assertRaisesRegex(ValidationError, "duplicate stratum"):
            normalize_weight_spec(duplicate)
        for bad_kind in ["internet", None, ""]:
            with self.subTest(kind=bad_kind):
                with self.assertRaises(ValidationError):
                    normalize_weight_spec(weight_spec([stratum("t", bad_kind, "p", 1.0)]))

    def test_proportion_must_be_numeric_and_within_range(self):
        for value in [True, "0.5", -0.1, 1.1, None, float("nan"), float("inf")]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    normalize_weight_spec(weight_spec([stratum("t", "book", "p", value)]))

    def test_unsupported_fields_are_rejected_to_keep_weight_basis_traceable(self):
        spec = weight_spec([stratum("t", "book", "p", 1.0)])
        spec["strata"][0]["weight"] = 2.0
        with self.assertRaisesRegex(ValidationError, "unsupported fields"):
            normalize_weight_spec(spec)


class MaterialPeriodTests(unittest.TestCase):
    def test_material_period_defaults_to_unspecified_but_rejects_blank_text(self):
        self.assertEqual(normalize_story(story())["material_period"], "unspecified")
        for value in [" ", ""]:
            record = story()
            record["material_period"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    normalize_story(record)


class WeightedReportTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.import_batch(batch([
            period_story("river-book-1", "river", "book", "early"),
            period_story("river-book-2", "river", "book", "early"),
            period_story("river-oral-1", "river", "oral_record", "early"),
            period_story("mountain-oral-1", "mountain", "oral_record", "late"),
            period_story("mountain-book-1", "mountain", "book", "late"),
        ], "weighted-cohort"))
        for story_id in ["river-book-1", "river-book-2", "river-oral-1"]:
            self.add_votes(story_id, values=[
                decision(story_id, annotator="reader-a", pattern="parallel", outcome="wins"),
                decision(story_id, annotator="reader-b", pattern="parallel", outcome="wins"),
            ])
        for story_id in ["mountain-oral-1", "mountain-book-1"]:
            self.add_votes(story_id, values=[
                decision(story_id, annotator="reader-a", pattern="harm", outcome="loses"),
                decision(story_id, annotator="reader-b", pattern="harm", outcome="loses"),
            ])
        self.spec = weight_spec([
            stratum("river", "book", "early", 0.2),
            stratum("river", "oral_record", "early", 0.2),
            stratum("mountain", "oral_record", "late", 0.5),
            stratum("mountain", "book", "late", 0.1),
        ])

    def test_weighted_denominator_is_not_the_raw_sample_count(self):
        self.app.register_weight_spec(self.spec)
        report = self.app.create_report(weight_spec_id="exercise-frame", weight_spec_version=1)
        weighted = report["weighted_comparison"]
        axis = weighted["axes"]["reader_pattern"]
        self.assertEqual(axis["unweighted_denominator"], 5)
        self.assertEqual(axis["weighted_denominator"], 1.0)
        self.assertAlmostEqual(axis["weighted_rates"]["parallel"], 0.4)
        self.assertAlmostEqual(axis["weighted_rates"]["harm"], 0.6)
        self.assertNotEqual(axis["weighted_denominator"], report["population"]["story_revisions"])
        self.assertAlmostEqual(
            sum(row["weight"] for row in weighted["weights"]), weighted["weighted_total_mass"]
        )

    def test_each_story_weight_is_effective_proportion_over_sample_count(self):
        self.app.register_weight_spec(self.spec)
        report = self.app.create_report(weight_spec_id="exercise-frame", weight_spec_version=1)
        rows = {(row["story_id"], row["revision"]): row for row in report["weighted_comparison"]["weights"]}
        self.assertAlmostEqual(rows[("river-book-1", 1)]["weight"], 0.1)
        self.assertAlmostEqual(rows[("river-book-2", 1)]["weight"], 0.1)
        self.assertAlmostEqual(rows[("river-oral-1", 1)]["weight"], 0.2)
        self.assertAlmostEqual(rows[("mountain-oral-1", 1)]["weight"], 0.5)

    def test_missing_proportion_for_a_sampled_stratum_fails_instead_of_falling_back_to_raw_counts(self):
        incomplete = weight_spec([stratum("river", "book", "early", 1.0)])
        self.app.register_weight_spec(incomplete)
        before = self.app.create_report()
        with self.assertRaisesRegex(AnalysisError, "missing proportions"):
            self.app.create_report(weight_spec_id="exercise-frame")
        self.assertEqual(self.app.stored_report(before["report_id"])["weighted_comparison"], None)
        self.assertEqual(len(self.app.store.list_weight_specs()), 1)
        self.assertEqual(len(self.app.audit()["issues"]), 0)

    def test_zero_weight_stratum_is_excluded_from_weighted_rates_but_retained_in_audit(self):
        zero = weight_spec([
            stratum("river", "book", "early", 0.5),
            stratum("river", "oral_record", "early", 0.0),
            stratum("mountain", "oral_record", "late", 0.5),
            stratum("mountain", "book", "late", 0.0),
        ])
        self.app.register_weight_spec(zero)
        report = self.app.create_report(weight_spec_id="exercise-frame")
        weighted = report["weighted_comparison"]
        axis = weighted["axes"]["reader_pattern"]
        self.assertEqual(axis["unweighted_denominator"], 5)
        self.assertEqual(axis["weighted_denominator"], 1.0)
        self.assertEqual(sorted(item["story_id"] for item in weighted["zero_weight_excluded"]),
                         ["mountain-book-1", "river-oral-1"])
        excluded = {(row["story_id"], row["revision"]): row for row in weighted["weights"]
                    if not row["included"]}
        self.assertEqual(excluded[("river-oral-1", 1)]["exclusion_reason"], "zero_weight_stratum")
        self.assertAlmostEqual(axis["weighted_rates"]["parallel"], 0.5)
        self.assertAlmostEqual(axis["weighted_rates"]["harm"], 0.5)

    def test_tradition_filter_renormalizes_and_marks_the_scope_change(self):
        self.app.register_weight_spec(self.spec)
        report = self.app.create_report("river", weight_spec_id="exercise-frame")
        weighted = report["weighted_comparison"]
        self.assertTrue(weighted["scope"]["renormalized_to_filter"])
        self.assertAlmostEqual(weighted["scope"]["original_selected_proportion_mass"], 0.4)
        self.assertAlmostEqual(weighted["weighted_total_mass"], 1.0)
        river = [row for row in weighted["strata"] if row["tradition"] == "river"]
        self.assertAlmostEqual(sum(row["effective_proportion"] for row in river), 1.0)
        self.assertAlmostEqual(weighted["axes"]["reader_pattern"]["weighted_rates"]["parallel"], 1.0)

    def test_filter_for_tradition_absent_from_spec_is_an_explicit_error(self):
        self.app.register_weight_spec(self.spec)
        with self.assertRaisesRegex(AnalysisError, "does not cover tradition"):
            self.app.create_report("coast", weight_spec_id="exercise-frame")

    def test_unknown_weight_spec_or_version_is_not_silently_unweighted(self):
        with self.assertRaises(NotFoundError):
            self.app.create_report(weight_spec_id="missing-spec")
        self.app.register_weight_spec(self.spec)
        with self.assertRaises(NotFoundError):
            self.app.create_report(weight_spec_id="exercise-frame", weight_spec_version=9)

    def test_revised_weights_require_new_version_and_old_report_keeps_old_caliber(self):
        self.app.register_weight_spec(self.spec)
        first = self.app.create_report(weight_spec_id="exercise-frame", weight_spec_version=1)
        revised = weight_spec([
            stratum("river", "book", "early", 0.1),
            stratum("river", "oral_record", "early", 0.1),
            stratum("mountain", "oral_record", "late", 0.7),
            stratum("mountain", "book", "late", 0.1),
        ], version=2)
        self.app.register_weight_spec(revised)
        with self.assertRaisesRegex(AnalysisError, "multiple registered versions"):
            self.app.create_report(weight_spec_id="exercise-frame")
        second = self.app.create_report(weight_spec_id="exercise-frame", weight_spec_version=2)
        self.assertNotEqual(first["report_id"], second["report_id"])
        self.assertEqual(self.app.stored_report(first["report_id"])["criteria"]["weight_spec_version"], 1)
        self.assertAlmostEqual(
            self.app.stored_report(first["report_id"])["weighted_comparison"]["axes"]["reader_pattern"]
            ["weighted_rates"]["parallel"], 0.4
        )
        self.assertAlmostEqual(
            second["weighted_comparison"]["axes"]["reader_pattern"]["weighted_rates"]["parallel"], 0.2
        )

    def test_reusing_a_version_for_different_proportions_is_a_conflict(self):
        self.app.register_weight_spec(self.spec)
        changed = weight_spec([
            stratum("river", "book", "early", 0.5),
            stratum("river", "oral_record", "early", 0.0),
            stratum("mountain", "oral_record", "late", 0.5),
            stratum("mountain", "book", "late", 0.0),
        ])
        with self.assertRaises(ConflictError):
            self.app.register_weight_spec(changed)

    def test_unregistered_report_is_explicitly_unweighted(self):
        report = self.app.create_report()
        self.assertIsNone(report["weighted_comparison"])
        self.assertIsNone(report["criteria"]["weight_spec_id"])
        self.assertIsNone(report["provenance"]["weight_spec"])

    def test_audit_detects_tampered_weight_specification(self):
        self.app.register_weight_spec(self.spec)
        with self.app.store.transaction() as connection:
            connection.execute("UPDATE weight_specs SET digest='wrong'")
        result = self.app.audit()
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["scope"] == "weight_spec" for item in result["issues"]))

    def test_audit_detects_report_embedding_a_different_weight_specification(self):
        self.app.register_weight_spec(self.spec)
        report = self.app.create_report(weight_spec_id="exercise-frame")
        altered = dict(report)
        altered.pop("report_id", None)
        altered["provenance"] = dict(altered["provenance"])
        altered["provenance"]["weight_spec"] = dict(altered["provenance"]["weight_spec"])
        altered["provenance"]["weight_spec"]["basis"] = "changed after the fact"
        from story_patterns.catalog.validate import canonical_json, digest_json

        report_id = digest_json(altered)[:24]
        document = canonical_json({"report_id": report_id, **altered})
        with self.app.store.transaction() as connection:
            connection.execute(
                "INSERT INTO reports(report_id, request_digest, document) VALUES(?,?,?)",
                (report_id, "tampered", document),
            )
        result = self.app.audit()
        self.assertFalse(result["ok"])
        self.assertTrue(any("weight specification differs" in item["problem"] for item in result["issues"]))

    def test_audit_detects_report_weighting_without_embedded_spec(self):
        report = self.app.create_report()
        altered = dict(report)
        altered.pop("report_id", None)
        altered["weighted_comparison"] = {"fake": True}
        from story_patterns.catalog.validate import canonical_json, digest_json

        report_id = digest_json(altered)[:24]
        with self.app.store.transaction() as connection:
            connection.execute(
                "INSERT INTO reports(report_id, request_digest, document) VALUES(?,?,?)",
                (report_id, "tampered", canonical_json({"report_id": report_id, **altered})),
            )
        result = self.app.audit()
        self.assertFalse(result["ok"])
        self.assertTrue(any("no embedded weight specification" in item["problem"]
                            for item in result["issues"]))

    def test_comparison_includes_weighted_axis_for_each_tradition(self):
        self.app.register_weight_spec(self.spec)
        result = self.app.compare_traditions(weight_spec_id="exercise-frame")
        for row in result["groups"]:
            weighted = row["weighted_comparison"]
            self.assertIsNotNone(weighted)
            self.assertTrue(weighted["scope"]["renormalized_to_filter"])
            self.assertAlmostEqual(weighted["weighted_total_mass"], 1.0)
        self.assertEqual(result["weight_spec_id"], "exercise-frame")
        self.assertEqual(result["weight_spec_version"], 1)
        self.assertIn("renormalize", result["interpretation_limit"])

    def test_comparison_fails_when_a_sampled_tradition_has_no_stratum(self):
        extra = period_story("coast-one", "coast", "book", "late")
        self.app.import_batch(batch([extra], "coast-batch"))
        self.add_votes("coast-one", values=[
            decision("coast-one", annotator="reader-a", pattern="parallel", outcome="wins"),
            decision("coast-one", annotator="reader-b", pattern="parallel", outcome="wins"),
        ])
        self.app.register_weight_spec(self.spec)
        with self.assertRaisesRegex(AnalysisError, "does not cover tradition 'coast'"):
            self.app.compare_traditions(weight_spec_id="exercise-frame")


class WeightedMarkdownAndExportTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.import_batch(batch([
            period_story("river-book-1", "river", "book", "early"),
            period_story("mountain-oral-1", "mountain", "oral_record", "late"),
        ], "markdown"))
        for story_id, pattern in [("river-book-1", "parallel"), ("mountain-oral-1", "harm")]:
            self.add_votes(story_id, values=[
                decision(story_id, annotator="reader-a", pattern=pattern, outcome="wins"),
                decision(story_id, annotator="reader-b", pattern=pattern, outcome="wins"),
            ])
        self.app.register_weight_spec(weight_spec([
            stratum("river", "book", "early", 0.75),
            stratum("mountain", "oral_record", "late", 0.25),
        ]))

    def test_markdown_separates_raw_and_weighted_rates_and_denominators(self):
        from story_patterns.analysis.markdown import render_report

        report = self.app.create_report(weight_spec_id="exercise-frame")
        markdown = render_report(report)
        self.assertIn("Stratified weighting", markdown)
        self.assertIn("Weighted denominators are sums of weights", markdown)
        self.assertIn("Weighted - raw", markdown)
        self.assertIn("do not estimate news reporting", markdown)

    def test_csv_rows_carry_stratum_and_weight_without_replacing_raw_counts(self):
        import csv

        from story_patterns.analysis.export import export_csv

        report = self.app.create_report(weight_spec_id="exercise-frame")
        with tempfile.TemporaryDirectory() as directory:
            path = export_csv(report, Path(directory) / "weighted.csv")
            with path.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual([row["story_id"] for row in rows], ["mountain-oral-1", "river-book-1"])
        weights = {row["story_id"]: float(row["weight"]) for row in rows}
        self.assertAlmostEqual(weights["river-book-1"], 0.75)
        self.assertAlmostEqual(weights["mountain-oral-1"], 0.25)
        self.assertEqual({row["weight_included"] for row in rows}, {"True"})

    def test_cli_registers_weights_and_reports_with_explicit_version(self):
        import contextlib
        import io

        from story_patterns.cli import main

        spec_path = Path(self.temporary.name) / "weights.json"
        spec_path.write_text(json.dumps(weight_spec([
            stratum("river", "book", "early", 0.75),
            stratum("mountain", "oral_record", "late", 0.25),
        ])), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["register-weights", "--database", self.database, "--file", str(spec_path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "already_registered")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["report", "--database", self.database, "--weight-spec-id",
                         "exercise-frame", "--weight-spec-version", "1"])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["criteria"]["weight_spec_version"], 1)
        self.assertEqual(report["weighted_comparison"]["axes"]["reader_pattern"]["weighted_denominator"], 1.0)


class WeightingHelperContractTests(unittest.TestCase):
    def test_unrepresented_declared_stratum_is_flagged_rather_than_imputed(self):
        spec = normalize_weight_spec(weight_spec([
            stratum("river", "book", "early", 0.5),
            stratum("mountain", "oral_record", "late", 0.5),
        ]))
        stories = [period_story("only", "river", "book", "early")]
        results = [{"story_id": "only", "revision": 1, "pattern": "parallel",
                    "youngest_outcome": "wins", "final_pattern": "parallel", "final_outcome": "wins"}]
        weighted = build_weighted_comparison(stories, results, spec)
        self.assertFalse(weighted["fully_represented"])
        self.assertAlmostEqual(weighted["unrepresented_proportion_mass"], 0.5)
        self.assertAlmostEqual(weighted["axes"]["reader_pattern"]["weighted_denominator"], 0.5)
        self.assertEqual(weighted["unrepresented_strata"][0]["tradition"], "mountain")
        self.assertEqual(weighted["unrepresented_strata"][0]["weight_per_story"], None)


if __name__ == "__main__":
    unittest.main()
