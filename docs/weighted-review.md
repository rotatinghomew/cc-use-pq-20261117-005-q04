# 分层加权复核指南

本指南面向课程教师与练习小组，说明如何用 `weighted_demo.json` 复核“直接按现有样本统计”和“按给定分层比例加权”之间的差异。所有示例均为本地合成材料，不是新闻原文，也不来自任何抽样调查。

## 1. 这份练习回答什么

同一批材料可以有两种描述方式：

| 口径 | 分母 | 回答的问题 |
| --- | --- | --- |
| 未加权（原始样本） | 有共识标签的故事修订数 | 这份样本本身里，各标签占多少 |
| 分层加权 | 各层权重之和 | 若按预先写定的层比例重排这份样本，各标签占多少 |

加权不会改变任何一条故事记录、标注、共识或仲裁；它只改变“合计时每篇故事占多少份量”。因此两种口径必须并列展示，不能互相替换，也不能把原始样本数当作加权分母。

## 2. 分层与资格

分层维度固定为三项：

1. `tradition`（传统标签）
2. `source_kind`（来源类型：`book` / `oral_record` / `local_synthetic`）
3. `material_period`（材料时期；旧记录缺省为 `unspecified`）

一个故事修订进入加权统计，需要同时满足：

- 属于本次报告选定的传统（若指定了 `--tradition`）；
- 具有可用共识标签（`unclear` / `unknown` 作为弃权，不进入对应分子，见下）；
- 其所属分层在权重规格中有明确比例。

**共识资格**沿用未加权报告的规则：至少 `--minimum-reviewers` 位独立读者给出可用标签，且没有并列领先。分歧或人数不足的故事仍保留在样本与覆盖表中，但不进入任何一方的比例分子。

## 3. 权重的计算

对每个分层 `s`：

```
有效比例_s = 声明比例_s / 本次报告所选各层声明比例之和
每篇权重  = 有效比例_s / 该层在本次报告样本中的故事修订数
加权分母  = 该轴上所有具标签且权重大于零的故事权重之和
加权比例  = 该标签的权重质量 / 加权分母
```

要点：

- **分母不是样本数。** 加权分母是权重之和（全样本通常在 1 附近）。
- **零权重层不提供比例。** 若某层声明比例为 0，该层故事仍出现在逐篇权重表中，标记 `zero_weight_stratum`，但不进入加权分子或分母；其原始计数仍保留在未加权列。
- **缺失层比例直接报错。** 若样本里出现了规格未覆盖的分层，报告整体失败，而不是悄悄退回原始计数或补 0。
- **声明了但没有样本的层不做插补。** 其有效比例归入 `unrepresented_proportion_mass`，并在 Markdown 与 JSON 中单列。
- **筛选传统时重新归一化。** 若报告只选一个传统，该传统之外的声明比例不参与计算，剩余层按比例放大到 1。JSON 中 `scope.renormalized_to_filter` 为 `true`，Markdown 会说明这一点：这份加权只描述所选子集，不能替代未筛选口径。

## 4. 权重版本与旧报告

权重规格是不可变记录：

- 以 `(weight_spec_id, version)` 为唯一标识；
- 同一标识重复提交相同内容 → `already_registered`（幂等）；
- 同一标识提交不同内容 → 冲突错误；
- 同一 `weight_spec_id` 只能追加更高版本，不能回退或覆盖；
- 报告保存时嵌入完整的权重规格与摘要，并写入 `criteria.weight_spec_id` / `weight_spec_version`。

因此修订权重后：

- 旧报告的内容指纹、口径和数值都不变，`stored_report(old_id)` 仍返回旧版本；
- 新报告必须显式传入新版本；
- 若同一 `weight_spec_id` 已存在多个版本而调用方没有指定版本，工具拒绝生成报告，要求明确版本，避免“悄悄换口径”。

## 5. 教师复核流程

从项目根目录运行：

```sh
PYTHONPATH=src python examples/run_weighted_example.py --output /tmp/weighted-review
```

脚本会创建全新数据库与导出目录，并生成：

| 文件 | 内容 |
| --- | --- |
| `unweighted.json/.md` | 原始样本口径 |
| `weighted-v1.json/.md/.csv` | 第一版权重 |
| `weighted-v2.json/.md/.csv` | 修订后权重 |
| `summary.json` | 三种口径的关键数字对照 |
| `weighted-review.sqlite3` | 可重新打开、可 `audit` 的本地数据库 |

逐篇 CSV 同时包含 `pattern` / `final_pattern` 等原始字段，以及 `stratum`、`weight`、`weight_included`、`weight_exclusion_reason`，便于逐行核对“这一篇是否入选、权重多少”。

手工核对一份加权报告时，建议按以下顺序：

1. 看 `criteria.weight_spec_id` 与 `version`，确认与本组当前采用的比例一致。
2. 看 `weighted_comparison.strata`：每个声明层是否 `represented`；`weight_per_story` 是否等于有效比例除以该层样本数。
3. 看 `weighted_comparison.weights`：零权重或排除项的理由是否正确。
4. 看 `axes.*.by_stratum` 与 `reconciliation`：逐层加权质量之和应等于该轴加权分母。
5. 看 `axes.*.unlabeled_included_weight_mass`：没有共识标签的故事所带的权重是否被明确排除，而不是被重新分配。
6. 对比未加权列与 `weighted_minus_unweighted`，确认结论变化来自权重设定，而非纳入/排除规则发生了变化。

命令行等价流程：

```sh
PYTHONPATH=src python -m story_patterns.cli import \
  --database /tmp/review.sqlite3 --file fixtures/weighted_demo.json
PYTHONPATH=src python -m story_patterns.cli register-weights \
  --database /tmp/review.sqlite3 --file fixtures/weights/exercise-frame-v1.json
PYTHONPATH=src python -m story_patterns.cli report \
  --database /tmp/review.sqlite3 --weight-spec-id exercise-frame-2026a --weight-spec-version 1
PYTHONPATH=src python -m story_patterns.cli export \
  --database /tmp/review.sqlite3 --report-id <REPORT_ID> --format md --output /tmp/report.md
PYTHONPATH=src python -m story_patterns.cli audit --database /tmp/review.sqlite3
```

`fixtures/weighted_demo.json` 自带 `weight_spec`，也可直接用 `demo` 子命令一次跑通；它还会登记 `fixtures/weights/` 中的 v1 与 v2 用于对照。

## 6. 解释边界

- 权重只描述这批练习材料在给定层比例下的构成，不估计新闻文章、已出版故事或任何更大总体。
- 加权无法修复层内选择偏差：若某层样本本身有偏，放大该层只会放大偏差。
- 层比例是练习组预先写定的分析设定，不是从数据估计出来的参数；改变比例就是改变问题。
- 小样本下加权比例可能只有极少数故事支撑，应始终与 `weighted_denominator` 和 `unlabeled_included_weight_mass` 一起阅读。

## 7. 关键文件

- `fixtures/weighted_demo.json`：含 6 篇合成故事、12 条标注、v1 比例。
- `fixtures/weights/exercise-frame-v1.json`、`-v2.json`：可独立登记的两版权重。
- `src/story_patterns/analysis/weighting.py`：校验、权重计算与 `WeightSpecService`。
- `tests/analysis/test_weighting.py`：覆盖缺失比例、零权重、筛选、版本冲突、旧报告保真与审计。
