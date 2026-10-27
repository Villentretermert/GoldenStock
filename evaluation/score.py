"""Strict fact scoring for versioned datasets; never an investment forecast score."""
import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = ("company", "metric", "period", "currency", "unit", "scale", "source_id", "locator")


def number(value):
    """Reject NaN/Infinity and bool rather than silently inflating a score."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid decimal") from error
    if not result.is_finite():
        raise ValueError("Non-finite decimal")
    return result


def validate(rows, gold=False):
    ids = [row.get("id") for row in rows]
    if any(not isinstance(i, str) or not i for i in ids):
        raise ValueError("Every record needs a nonempty string id")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate ids invalidate the run")
    for row in rows:
        if any(not isinstance(row.get(f), str) or not row[f] for f in FIELDS):
            raise ValueError("Missing or invalid identity/provenance field")
        if row.get("value") is not None:
            number(row["value"])
        elif gold:
            raise ValueError("Gold facts require a numeric value")
        if gold:
            tolerance = number(row.get("abs_tolerance", "0"))
            if tolerance < 0:
                raise ValueError("Negative tolerance")


def score(gold, predictions):
    if not gold:
        raise ValueError("Empty gold set cannot produce accuracy")
    validate(gold, gold=True)
    validate(predictions)
    pred = {row["id"]: row for row in predictions}
    correct = 0
    answered = 0
    reasons = Counter()
    groups = {}
    for expected in gold:
        row = pred.get(expected["id"])
        group = groups.setdefault(expected["company"], {"correct": 0, "total": 0})
        group["total"] += 1
        if row is None:
            reasons["missing"] += 1
            continue
        if row.get("value") is None:
            reasons["abstained"] += 1
            continue
        answered += 1
        if any(row[f] != expected[f] for f in FIELDS):
            reasons["identity_or_evidence"] += 1
            continue
        if abs(number(row["value"]) - number(expected["value"])) > number(expected.get("abs_tolerance", "0")):
            reasons["value"] += 1
            continue
        correct += 1
        group["correct"] += 1
    gold_ids = {row["id"] for row in gold}
    extras = sum(row["id"] not in gold_ids for row in predictions)
    emitted = sum(row.get("value") is not None for row in predictions)
    n = len(gold)
    # Wilson interval reports sampling uncertainty, not a claim of deployment quality.
    p = correct / n
    z = 1.96
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    margin = z*((p*(1-p)/n + z*z/(4*n*n))**0.5)/(1+z*z/n)
    return {
        "total": n, "correct": correct, "accuracy": p,
        "precision": correct / emitted if emitted else 0.0,
        "coverage": answered / n, "abstention_rate": reasons["abstained"] / n,
        "missing_rate": reasons["missing"] / n, "extra_predictions": extras,
        "errors": dict(reasons), "by_company": groups,
        "accuracy_wilson_95": [max(0, center-margin), min(1, center+margin)],
        "threshold_met_on_this_set": p >= .95,
        "production_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path)
    parser.add_argument("predictions", type=Path)
    args = parser.parse_args()
    result = score(json.loads(args.gold.read_text(encoding="utf-8")),
                   json.loads(args.predictions.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
