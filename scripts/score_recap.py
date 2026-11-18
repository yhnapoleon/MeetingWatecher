"""Compare predicted pre-meeting task IDs with per-viewer annotations."""

import argparse
import json
from pathlib import Path


def index_rows(rows, fields):
    indexed = {}
    for row in rows:
        key = (row["meeting"], row["viewer"])
        if key in indexed:
            raise ValueError(f"Duplicate recap for {key}")
        for field in fields:
            ids = row[field]
            if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
                raise ValueError(f"{key}: expected a list of task IDs in {field}")
            if len(ids) != len(set(ids)):
                raise ValueError(f"{key}: duplicate task ID in {field}")
        indexed[key] = row
    return indexed


def score(gold_rows, predicted_rows):
    gold = index_rows(gold_rows, ["expected", "forbidden"])
    predictions = index_rows(predicted_rows, ["tasks"])
    extra = predictions.keys() - gold.keys()
    if extra:
        raise ValueError(f"Unannotated meeting/viewer: {sorted(extra)}")
    cases = []
    hits = expected_count = predicted_count = forbidden_count = 0
    for key, row in gold.items():
        expected = set(row["expected"])
        forbidden = set(row["forbidden"])
        if expected & forbidden:
            raise ValueError(f"{key}: gold marks the same task expected and forbidden")
        actual = set(predictions.get(key, {}).get("tasks", []))
        hits += len(expected & actual)
        expected_count += len(expected)
        predicted_count += len(actual)
        forbidden_count += len(actual & forbidden)
        cases.append({
            "meeting": key[0], "viewer": key[1], "missing_prediction": key not in predictions,
            "missed": sorted(expected - actual), "unexpected": sorted(actual - expected),
            "forbidden_returned": sorted(actual & forbidden),
        })
    return {
        "cases_scored": len(gold), "predictions_received": len(predictions),
        "hits": hits, "expected_count": expected_count, "predicted_count": predicted_count,
        "precision": hits / predicted_count if predicted_count else None,
        "recall": hits / expected_count if expected_count else None,
        "forbidden_count": forbidden_count, "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path)
    parser.add_argument("predictions", type=Path)
    args = parser.parse_args()
    try:
        annotations = json.loads(args.gold.read_text(encoding="utf-8"))
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        report = score(annotations["recaps"], predictions)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Invalid input: {error}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
