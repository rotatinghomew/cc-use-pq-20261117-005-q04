from __future__ import annotations

import json


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> list[str]:
    headings = [label for _, label in columns]
    lines = ["| " + " | ".join(headings) + " |", "| " + " | ".join("---" for _ in headings) + " |"]
    for row in rows:
        cells = [str(row.get(key, "" )).replace("|", "\\|").replace("\n", " ") for key, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_report(report: dict) -> str:
    population = report["population"]
    criteria = report["criteria"]
    lines = [
        f"# Narrative analysis report {report['report_id']}", "",
        "This report summarizes annotated local records. It does not make literary claims on its own.", "",
        "## Scope", "",
        f"- Tradition filter: {criteria['tradition'] or 'all'}",
        f"- Minimum independent readers: {criteria['minimum_reviewers']}",
        f"- Weight specification: "
        f"{criteria['weight_spec_id'] + ' v' + str(criteria['weight_spec_version']) if criteria.get('weight_spec_id') else 'none (raw descriptive counts)'}",
        f"- Story revisions: {population['story_revisions']}",
        f"- Pattern consensus: {population['pattern_consensus']}",
        f"- Outcome consensus: {population['outcome_consensus']}", "",
        "## Independent-reader consensus counts", "",
    ]
    lines.extend(_table([{"pattern": key, "count": value} for key, value in report["pattern_counts"].items()],
                        [("pattern", "Pattern"), ("count", "Stories")]))
    lines.extend(["", "## Final pattern counts", ""])
    lines.extend(_table([{"pattern": key, "count": value}
                         for key, value in report["final_pattern_counts"].items()],
                        [("pattern", "Pattern"), ("count", "Stories")]))
    lines.extend(["", "## Coverage", "", "Status counts retain unresolved records in the denominator.", ""])
    coverage = report["coverage"]["pattern"]
    lines.extend(_table([{"status": key, "count": value} for key, value in coverage.items()],
                        [("status", "Pattern review status"), ("count", "Stories")]))
    lines.extend(["", "## Provenance", "", "Story revisions and decision IDs used:", "",
                  "```json", json.dumps(report["provenance"], ensure_ascii=False, indent=2), "```", ""])
    weighted = report.get("weighted_comparison")
    if weighted:
        lines.extend(_weighted_lines(report, weighted))
    return "\n".join(lines)


def _number(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _weighted_lines(report: dict, weighted: dict) -> list[str]:
    criteria = report["criteria"]
    spec = weighted["spec"]
    lines = [
        "", "## Stratified weighting (descriptive only)", "",
        f"- Weight specification: {spec['weight_spec_id']} v{spec['version']}",
        f"- Basis: {spec['basis']}",
        f"- Prepared by: {spec['prepared_by']}",
        f"- Eligibility: selected story revisions with a consensus label; "
        f"sample story revisions = {weighted['eligible_story_revisions']}",
        f"- Weight formula: {weighted['weight_formula']}",
        "",
        "The table below separates the raw sample counts from the weighted estimates. "
        "Weighted denominators are sums of weights, not raw story counts.",
        "",
    ]
    if weighted["scope"]["renormalized_to_filter"]:
        lines.extend([
            f"Tradition filter `{criteria['tradition']}` covers only "
            f"{weighted['scope']['original_selected_proportion_mass']:.4f} of the declared "
            "proportion mass; the remaining strata are outside the requested cohort. "
            "Within-cohort weights are renormalized to that selected mass and cannot stand in "
            "for the unfiltered exercise frame.",
            "",
        ])
    stratum_rows = [
        {
            "tradition": row["tradition"], "source_kind": row["source_kind"],
            "material_period": row["material_period"],
            "target": _number(row["target_proportion"]),
            "effective": _number(row["effective_proportion"]),
            "sampled": row["sampled_story_revisions"],
            "per_story": _number(row["weight_per_story"]),
            "status": row["status"],
        }
        for row in weighted["strata"]
    ]
    lines.extend(_table(stratum_rows, [
        ("tradition", "Tradition"), ("source_kind", "Source kind"),
        ("material_period", "Material period"), ("target", "Declared proportion"),
        ("effective", "Effective proportion"), ("sampled", "Sample revisions"),
        ("per_story", "Weight per story"), ("status", "Status"),
    ]))
    lines.extend(["", "### Weighted versus unweighted", "",
                  "Where a story has no consensus label, or an `unknown` outcome, its weight is "
                  "kept out of the weighted denominator and reported below rather than silently "
                  "redistributed.", ""])
    axis_rows = []
    for axis_name, axis in weighted["axes"].items():
        for label in sorted(set(axis["unweighted_counts"]) | set(axis["weighted_counts"])):
            axis_rows.append({
                "axis": axis_name,
                "label": label,
                "unweighted": f"{axis['unweighted_counts'].get(label, 0)}"
                              f" / {axis['unweighted_denominator']}",
                "unweighted_rate": _number(axis["unweighted_rates"].get(label)),
                "weighted_mass": _number(axis["weighted_counts"].get(label, 0.0)),
                "weighted_denominator": _number(axis["weighted_denominator"]),
                "weighted_rate": _number(axis["weighted_rates"].get(label)),
                "difference": _number(axis["weighted_minus_unweighted"].get(label)),
            })
    lines.extend(_table(axis_rows, [
        ("axis", "Axis"), ("label", "Label"),
        ("unweighted", "Raw count / raw denominator"), ("unweighted_rate", "Raw rate"),
        ("weighted_mass", "Weighted mass"), ("weighted_denominator", "Weight denominator"),
        ("weighted_rate", "Weighted rate"), ("difference", "Weighted - raw"),
    ]))
    exclude_rows = []
    for axis_name, axis in weighted["axes"].items():
        exclude_rows.append({
            "axis": axis_name,
            "raw_excluded": json.dumps(axis["excluded_story_revisions"], ensure_ascii=False),
            "zero_weight": axis["excluded_zero_weight_story_revisions"],
            "included_mass": _number(axis["included_weight_mass"]),
            "unlabeled_mass": _number(axis["unlabeled_included_weight_mass"]),
        })
    lines.extend(["", "### Weight mass excluded from each axis", ""])
    lines.extend(_table(exclude_rows, [
        ("axis", "Axis"), ("raw_excluded", "Raw exclusions"), ("zero_weight", "Zero-weight stories"),
        ("included_mass", "Included weight mass"), ("unlabeled_mass", "Unlabeled included mass"),
    ]))
    lines.extend(["", "### Per-stratum contribution", "",
                  "Each weighted rate can be recomputed as the label mass below divided by "
                  "the sum of the weight denominators.", ""])
    contribution_rows = []
    for axis_name, axis in weighted["axes"].items():
        for item in axis["by_stratum"]:
            for label in sorted(item["weighted_masses"]):
                contribution_rows.append({
                    "axis": axis_name,
                    "stratum": " / ".join((item["tradition"], item["source_kind"],
                                           item["material_period"])),
                    "label": label,
                    "raw": item["unweighted_counts"].get(label, 0),
                    "mass": _number(item["weighted_masses"][label]),
                })
    lines.extend(_table(contribution_rows, [
        ("axis", "Axis"), ("stratum", "Stratum"), ("label", "Label"),
        ("raw", "Raw stories"), ("mass", "Weighted mass"),
    ]))
    mismatched = [name for name, axis in weighted["axes"].items()
                  if not axis["reconciliation"]["matches_weighted_denominator"]]
    if mismatched:
        lines.extend(["", "WARNING: weighted denominator did not reconcile for: "
                      + ", ".join(sorted(mismatched))])
    if weighted["zero_weight_excluded"]:
        lines.extend(["", "Zero-weight strata are retained in the audit trail but excluded from rates:", ""])
        lines.extend(_table(weighted["zero_weight_excluded"], [
            ("story_id", "Story"), ("revision", "Revision"), ("reason", "Reason"),
        ]))
    if weighted["unrepresented_strata"]:
        lines.extend(["", "Declared strata with no eligible story revision (not imputed):", ""])
        lines.extend(_table(weighted["unrepresented_strata"], [
            ("tradition", "Tradition"), ("source_kind", "Source kind"),
            ("material_period", "Material period"), ("effective", "Effective proportion"),
        ]))
    lines.extend(["", f"Limit: {weighted['interpretation_limit']}", ""])
    return lines
