#!/usr/bin/env python3
"""教师复核示例：同一批练习材料下的原始计数与分层加权结果。

用法（从项目根目录）：

    PYTHONPATH=src python examples/run_weighted_example.py --output /tmp/weighted-review

脚本会构建一个全新的本地 SQLite 数据库，依次：

1. 导入 ``fixtures/weighted_demo.json`` 中的合成练习材料与标注；
2. 登记 ``fixtures/weights/exercise-frame-v1.json`` 的分层比例；
3. 生成一份未加权报告（criteria.weight_spec_id = null）；
4. 生成一份 v1 加权报告；
5. 登记修订版 v2，并生成一份 v2 加权报告；
6. 导出三份 JSON、三份 Markdown 和一份逐篇权重 CSV，并打印复核摘要。

所有输出都写入 ``--output`` 指定的新目录；目录不存在会被创建，已存在则拒绝覆盖。
数据库文件也放在该目录内，便于整体留档或删除。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from story_patterns.analysis.export import export_csv, export_json  # noqa: E402
from story_patterns.analysis.markdown import render_report  # noqa: E402
from story_patterns.application import StoryPatternApplication  # noqa: E402
from story_patterns.cli import read_json  # noqa: E402
from story_patterns.errors import StoryPatternError  # noqa: E402


def _summary(report: dict) -> dict:
    weighted = report["weighted_comparison"]
    if weighted is None:
        return {
            "report_id": report["report_id"],
            "weight_spec": None,
            "raw_denominator": report["population"]["pattern_consensus"],
            "weighted_denominator": None,
            "rates": {},
            "note": "unweighted: counts are raw selected story revisions",
        }
    axis = weighted["axes"]["reader_pattern"]
    return {
        "report_id": report["report_id"],
        "weight_spec": f"{report['criteria']['weight_spec_id']} v{report['criteria']['weight_spec_version']}",
        "raw_denominator": axis["unweighted_denominator"],
        "weighted_denominator": axis["weighted_denominator"],
        "rates": {
            label: {
                "raw": axis["unweighted_rates"][label],
                "weighted": axis["weighted_rates"][label],
                "difference": axis["weighted_minus_unweighted"][label],
            }
            for label in sorted(axis["unweighted_rates"])
        },
        "zero_weight_excluded": len(weighted["zero_weight_excluded"]),
        "unrepresented_strata": len(weighted["unrepresented_strata"]),
        "renormalized_to_filter": weighted["scope"]["renormalized_to_filter"],
        "reconciled": all(item["reconciliation"]["matches_weighted_denominator"]
                          for item in weighted["axes"].values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True,
                        help="new directory for the database and exported review files")
    arguments = parser.parse_args(argv)
    output = Path(arguments.output)
    if output.exists():
        print(f"refusing to overwrite existing path: {output}", file=sys.stderr)
        return 2
    output.mkdir(parents=True)

    database = output / "weighted-review.sqlite3"
    app = StoryPatternApplication(str(database))

    fixture = read_json(PROJECT / "fixtures" / "weighted_demo.json")
    app.import_batch(fixture["batch"])
    for record in fixture["decisions"]:
        app.record_decision(record)

    v1 = read_json(PROJECT / "fixtures" / "weights" / "exercise-frame-v1.json")
    v2 = read_json(PROJECT / "fixtures" / "weights" / "exercise-frame-v2.json")
    app.register_weight_spec(v1)
    app.register_weight_spec(v2)

    configs = {
        "unweighted": app.create_report(),
        "weighted-v1": app.create_report(weight_spec_id=v1["weight_spec_id"],
                                         weight_spec_version=v1["version"]),
        "weighted-v2": app.create_report(weight_spec_id=v2["weight_spec_id"],
                                         weight_spec_version=v2["version"]),
    }
    summaries = {}
    for name, report in configs.items():
        export_json(report, output / f"{name}.json")
        (output / f"{name}.md").write_text(render_report(report), encoding="utf-8")
        if name != "unweighted":
            export_csv(report, output / f"{name}.csv")
        summaries[name] = _summary(report)
    (output / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    audit = app.audit()
    print(json.dumps({
        "output": str(output),
        "database": str(database),
        "audit_ok": audit["ok"],
        "audit_issue_count": audit["issue_count"],
        "reports": summaries,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StoryPatternError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
