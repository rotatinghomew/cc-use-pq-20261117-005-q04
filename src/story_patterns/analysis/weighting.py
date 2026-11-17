from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from story_patterns.catalog.validate import canonical_json, digest_json
from story_patterns.errors import AnalysisError, ConflictError, ValidationError

STRATUM_FIELDS = ("tradition", "source_kind", "material_period")
SOURCE_KINDS = {"book", "oral_record", "local_synthetic"}


def _spec_text(value, field: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > limit:
        raise ValidationError(f"{field} exceeds {limit} characters")
    return value


def _proportion(value, field: str) -> tuple[float, Decimal]:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a number from 0 to 1")
    try:
        exact = Decimal(str(value))
        if not exact.is_finite() or exact < 0 or exact > 1:
            raise ValidationError(f"{field} must be between 0 and 1")
    except InvalidOperation as error:
        raise ValidationError(f"{field} must be a number from 0 to 1") from error
    return float(exact), exact


def normalize_weight_spec(raw: object) -> dict:
    """Validate and canonicalize an immutable stratified weight specification.

    Proportions describe the exercise frame named in ``basis``. They are not a
    claim about news reporting or any wider population.
    """
    if not isinstance(raw, dict):
        raise ValidationError("weight specification must be an object")
    allowed = {"weight_spec_id", "version", "basis", "prepared_by", "strata"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValidationError(f"weight specification has unsupported fields: {', '.join(unknown)}")
    spec_id = _spec_text(raw.get("weight_spec_id"), "weight_spec_id", 120)
    version = raw.get("version")
    if type(version) is not int or version < 1:
        raise ValidationError("weight specification version must be a positive integer")
    basis = _spec_text(raw.get("basis"), "basis", 1500)
    prepared_by = _spec_text(raw.get("prepared_by"), "prepared_by", 120)
    rows = raw.get("strata")
    if not isinstance(rows, list) or not rows:
        raise ValidationError("strata must be a non-empty list")
    normalized = []
    seen = set()
    exact_total = Decimal(0)
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"stratum {index} must be an object")
        extra = sorted(set(item) - set(STRATUM_FIELDS) - {"proportion"})
        if extra:
            raise ValidationError(f"stratum {index} has unsupported fields: {', '.join(extra)}")
        tradition = _spec_text(item.get("tradition"), f"strata[{index}].tradition", 120)
        source_kind = item.get("source_kind")
        if source_kind not in SOURCE_KINDS:
            raise ValidationError(f"strata[{index}].source_kind must be book, oral_record, or local_synthetic")
        material_period = _spec_text(item.get("material_period"), f"strata[{index}].material_period", 120)
        key = (tradition, source_kind, material_period)
        if key in seen:
            raise ValidationError(f"duplicate stratum: {tradition} / {source_kind} / {material_period}")
        seen.add(key)
        proportion, exact = _proportion(item.get("proportion"), f"strata[{index}].proportion")
        exact_total += exact
        normalized.append({
            "tradition": tradition,
            "source_kind": source_kind,
            "material_period": material_period,
            "proportion": proportion,
        })
    if exact_total != Decimal(1):
        raise ValidationError(f"stratum proportions must sum exactly to 1 (received {exact_total})")
    normalized.sort(key=lambda item: (item["tradition"], item["source_kind"], item["material_period"]))
    return {
        "weight_spec_id": spec_id,
        "version": version,
        "basis": basis,
        "prepared_by": prepared_by,
        "strata": normalized,
    }


def _stratum_key(item: dict) -> tuple[str, str, str]:
    return (item["tradition"], item["source_kind"], item["material_period"])


def _story_stratum(story: dict) -> tuple[str, str, str]:
    return (
        story["tradition"],
        story["source"]["kind"],
        story.get("material_period", "unspecified"),
    )


def _stratum_contributions(story_results: list[dict], weights: dict, field: str,
                           excluded_labels: set[str]) -> list[dict]:
    """Per-stratum label masses, so a reviewer can recompute each weighted rate."""
    rows = {}
    for result in story_results:
        label = result.get(field)
        if label is None or label in excluded_labels:
            continue
        weight_row = weights[(result["story_id"], result["revision"])]
        if not weight_row["included"]:
            continue
        key = (
            weight_row["stratum"]["tradition"],
            weight_row["stratum"]["source_kind"],
            weight_row["stratum"]["material_period"],
        )
        entry = rows.setdefault(key, {"unweighted": Counter(), "weighted": Counter(), "weight": 0.0})
        entry["unweighted"][label] += 1
        entry["weighted"][label] += weight_row["weight"]
        entry["weight"] += weight_row["weight"]
    output = []
    for key in sorted(rows):
        entry = rows[key]
        output.append({
            "tradition": key[0],
            "source_kind": key[1],
            "material_period": key[2],
            "weighted_mass": entry["weight"],
            "unweighted_counts": dict(sorted(entry["unweighted"].items())),
            "weighted_masses": {label: entry["weighted"][label] for label in sorted(entry["weighted"])},
        })
    return output


def _axis(story_results: list[dict], weights: dict, field: str, excluded_labels: set[str]) -> dict:
    unweighted = Counter()
    weighted = Counter()
    excluded = Counter()
    unweighted_denominator = 0
    weighted_denominator = 0.0
    included_mass = 0.0
    zero_weight_stories = 0
    for row in story_results:
        weight_row = weights[(row["story_id"], row["revision"])]
        if weight_row["included"]:
            included_mass += weight_row["weight"]
        else:
            zero_weight_stories += 1
        label = row.get(field)
        if label is None or label in excluded_labels:
            excluded["missing" if label is None else label] += 1
            continue
        unweighted_denominator += 1
        unweighted[label] += 1
        if not weight_row["included"]:
            continue
        weight = weight_row["weight"]
        if weight > 0:
            weighted_denominator += weight
            weighted[label] += weight
    labels = sorted(set(unweighted) | set(weighted))
    unweighted_rates = {
        label: unweighted[label] / unweighted_denominator for label in labels
    } if unweighted_denominator else {}
    weighted_rates = {
        label: weighted[label] / weighted_denominator for label in labels
    } if weighted_denominator else {}
    differences = {
        label: weighted_rates[label] - unweighted_rates[label]
        for label in labels if label in unweighted_rates and label in weighted_rates
    }
    return {
        "unweighted_counts": {label: unweighted[label] for label in labels},
        "unweighted_denominator": unweighted_denominator,
        "unweighted_rates": unweighted_rates,
        "weighted_counts": {label: weighted[label] for label in labels},
        "weighted_denominator": weighted_denominator,
        "weighted_rates": weighted_rates,
        "weighted_minus_unweighted": differences,
        "excluded_story_revisions": dict(sorted(excluded.items())),
        "excluded_zero_weight_story_revisions": zero_weight_stories,
        "included_weight_mass": included_mass,
        "unlabeled_included_weight_mass": included_mass - weighted_denominator,
        "eligible_story_revisions": unweighted_denominator,
    }


def build_weighted_comparison(stories: list[dict], story_results: list[dict], spec: dict,
                              tradition: str | None = None) -> dict:
    """Compute post-stratified descriptive weights for the selected sample.

    Weight per story is the effective stratum proportion divided by the number
    of selected sample story revisions in that stratum. The weighted denominator
    for every rate is the sum of the weights of the stories that actually carry
    the relevant consensus label. It is never the raw sample count.
    """
    all_strata = {_stratum_key(item): item["proportion"] for item in spec["strata"]}
    in_scope = {
        key: value for key, value in all_strata.items()
        if tradition is None or key[0] == tradition
    }
    if not in_scope:
        raise AnalysisError(
            f"weight specification {spec['weight_spec_id']} v{spec['version']} "
            f"does not cover tradition {tradition!r}"
        )
    scope_mass = sum(Decimal(str(value)) for value in in_scope.values())
    if scope_mass <= 0:
        raise AnalysisError("selected weight strata have zero total proportion")
    effective = {key: float(Decimal(str(value)) / scope_mass) for key, value in in_scope.items()}

    sample_counts = Counter(_story_stratum(story) for story in stories)
    missing = sorted(set(sample_counts) - set(all_strata))
    if missing:
        described = "; ".join(" / ".join(key) for key in missing)
        raise AnalysisError(
            "weight specification is missing proportions for sampled strata: " + described
        )

    zero_weight_keys = {key for key, value in effective.items() if value == 0}
    unrepresented_keys = {
        key for key, value in effective.items() if value > 0 and sample_counts[key] == 0
    }

    weights = {}
    weight_rows = []
    excluded_zero = []
    for story in stories:
        identity = (story["story_id"], story["revision"])
        key = _story_stratum(story)
        count = sample_counts[key]
        weight = 0.0 if key in zero_weight_keys else effective[key] / count
        included = weight > 0
        row = {
            "story_id": story["story_id"],
            "revision": story["revision"],
            "stratum": {
                "tradition": key[0],
                "source_kind": key[1],
                "material_period": key[2],
            },
            "weight": weight,
            "included": included,
            "exclusion_reason": None if included else "zero_weight_stratum",
        }
        weights[identity] = row
        weight_rows.append(row)
        if not included:
            excluded_zero.append({
                "story_id": story["story_id"],
                "revision": story["revision"],
                "stratum": row["stratum"],
                "reason": "zero_weight_stratum",
            })

    weighted_total_mass = sum(row["weight"] for row in weight_rows)
    represented_mass = sum(
        effective[key] for key in effective if sample_counts[key] > 0
    )
    unrepresented_mass = sum(
        effective[key] for key in effective if sample_counts[key] == 0
    )
    stratum_rows = []
    for key in sorted(effective):
        target = all_strata[key]
        count = sample_counts[key]
        status = "zero_weight" if key in zero_weight_keys else (
            "unrepresented" if key in unrepresented_keys else "represented"
        )
        stratum_rows.append({
            "tradition": key[0],
            "source_kind": key[1],
            "material_period": key[2],
            "target_proportion": target,
            "effective_proportion": effective[key],
            "sampled_story_revisions": count,
            "weight_per_story": 0.0 if key in zero_weight_keys else effective[key] / count
            if count else None,
            "status": status,
        })

    axes = {
        "reader_pattern": _axis(story_results, weights, "pattern", set()),
        "reader_outcome": _axis(story_results, weights, "youngest_outcome", set()),
        "final_pattern": _axis(story_results, weights, "final_pattern", set()),
        "final_outcome": _axis(story_results, weights, "final_outcome", {"unknown"}),
    }
    contributions = {
        "reader_pattern": _stratum_contributions(story_results, weights, "pattern", set()),
        "reader_outcome": _stratum_contributions(story_results, weights, "youngest_outcome", set()),
        "final_pattern": _stratum_contributions(story_results, weights, "final_pattern", set()),
        "final_outcome": _stratum_contributions(story_results, weights, "final_outcome", {"unknown"}),
    }
    for name, axis in axes.items():
        axis["weighted_covered_mass_share"] = (
            axis["weighted_denominator"] / weighted_total_mass if weighted_total_mass else None
        )
        axis["by_stratum"] = contributions[name]
        reconciled = sum(item["weighted_mass"] for item in contributions[name])
        axis["reconciliation"] = {
            "sum_of_stratum_weighted_mass": reconciled,
            "matches_weighted_denominator": abs(reconciled - axis["weighted_denominator"]) <= 1e-9,
            "unlabeled_included_weight_mass": axis["included_weight_mass"]
            - axis["weighted_denominator"],
        }

    return {
        "method": "post-stratified descriptive weighting of the selected exercise sample",
        "weight_formula": (
            "weight = effective stratum proportion / selected sample story revisions in that stratum; "
            "weighted denominators are sums of weights, never raw sample counts"
        ),
        "strata_dimensions": list(STRATUM_FIELDS),
        "spec": spec,
        "spec_digest": digest_json(spec),
        "scope": {
            "report_tradition_filter": tradition,
            "spec_strata": len(all_strata),
            "selected_strata": len(in_scope),
            "original_selected_proportion_mass": float(scope_mass),
            "renormalized_to_filter": scope_mass != Decimal(1),
        },
        "eligible_story_revisions": len(stories),
        "weighted_total_mass": weighted_total_mass,
        "represented_proportion_mass": represented_mass,
        "unrepresented_proportion_mass": unrepresented_mass,
        "fully_represented": not unrepresented_keys,
        "strata": stratum_rows,
        "weights": weight_rows,
        "zero_weight_excluded": excluded_zero,
        "unrepresented_strata": [
            row for row in stratum_rows if row["status"] == "unrepresented"
        ],
        "axes": axes,
        "interpretation_limit": (
            "Weights are descriptive post-stratification adjustments for this local exercise "
            "sample only. They do not estimate news reporting, published tales, or any wider "
            "population, and they cannot correct selection bias within a stratum."
        ),
    }


class WeightSpecService:
    def __init__(self, store):
        self.store = store

    def register(self, raw: dict) -> dict:
        spec = normalize_weight_spec(raw)
        digest = digest_json(spec)
        with self.store.transaction() as connection:
            previous = connection.execute(
                "SELECT digest FROM weight_specs WHERE weight_spec_id=? AND version=?",
                (spec["weight_spec_id"], spec["version"]),
            ).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise ConflictError(
                        f"weight specification {spec['weight_spec_id']} v{spec['version']} "
                        "already identifies different content"
                    )
                return {
                    "weight_spec_id": spec["weight_spec_id"],
                    "version": spec["version"],
                    "digest": digest,
                    "status": "already_registered",
                }
            latest = connection.execute(
                "SELECT MAX(version) AS version FROM weight_specs WHERE weight_spec_id=?",
                (spec["weight_spec_id"],),
            ).fetchone()["version"]
            if latest is not None and spec["version"] <= latest:
                raise ConflictError(
                    f"weight specification {spec['weight_spec_id']} v{spec['version']} "
                    f"does not supersede stored v{latest}; use a higher version"
                )
            connection.execute(
                "INSERT INTO weight_specs(weight_spec_id, version, digest, document) VALUES(?,?,?,?)",
                (spec["weight_spec_id"], spec["version"], digest, canonical_json(spec)),
            )
        return {
            "weight_spec_id": spec["weight_spec_id"],
            "version": spec["version"],
            "digest": digest,
            "status": "registered",
        }

    def list(self) -> list[dict]:
        return self.store.list_weight_specs()
