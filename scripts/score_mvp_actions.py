"""Score evidence-anchored action predictions. One JSONL row per excerpt, including empty results."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from verify_mvp_dataset import DATA, csv_rows, indexed, lines, require

ACTIONS = {"create", "candidate"}
FIELDS = ("operation", "owner_kind", "owner_label", "owner_ref", "due_text", "due_date")


def prf(tp, gold, predicted):
    return {"hits": tp, "expected": gold, "predicted": predicted,
            "precision": tp / predicted if predicted else None,
            "recall": tp / gold if gold else None,
            "f1": 2 * tp / (gold + predicted) if gold + predicted else None}


def score(predictions, split, *, labels=None, inputs=None, selected_ids=None):
    cases = indexed(inputs if inputs is not None else lines(DATA / "input.jsonl"), "case_id")
    selected = set(selected_ids) if selected_ids is not None else {r["case_id"] for r in csv_rows("splits.csv") if r["split"] == split}
    supplied = indexed(predictions, "case_id")
    require(supplied.keys() == selected,
            f"Missing cases {sorted(selected - supplied.keys())}, unexpected {sorted(supplied.keys() - selected)}")
    gold = {}
    for row in labels if labels is not None else lines(DATA / "labels.jsonl"):
        if row["case_id"] in selected and row["operation"] in ACTIONS:
            k = row["case_id"], row["action_anchor"]
            require(k not in gold, f"Shared action anchor {k}")
            gold[k] = row
    guesses = defaultdict(list)
    for cid, row in supplied.items():
        allowed = {s["id"] for s in cases[cid]["segments"]}
        require(isinstance(row["items"], list), cid)
        for item in row["items"]:
            ev = item["evidence_ids"]
            require(item["operation"] in ACTIONS and isinstance(ev, list) and len(ev) == len(set(ev))
                    and item["action_anchor"] in ev and set(ev) <= allowed, f"Invalid evidence/operation in {cid}")
            require(all(f in item for f in FIELDS), f"Missing output field in {cid}")
            guesses[cid, item["action_anchor"]].append(item)
    matched = sorted(gold.keys() & guesses.keys())
    errors = [{"case": cid, "anchor": anchor, "error": "missed"} for cid, anchor in sorted(gold.keys() - guesses.keys())]
    for k, group in sorted(guesses.items()):
        extra = len(group) - int(k in gold)
        if extra:
            errors.append({"case": k[0], "anchor": k[1], "extra_predictions": extra})
    correct = Counter()
    positive_dates = positive_date_hits = 0
    ev_hits = ev_gold = ev_pred = 0
    for k in matched:
        # One gold event per anchor in v1. Later repeats are extra predictions.
        expected, actual = gold[k], guesses[k][0]
        wrong = []
        for field in FIELDS:
            if field == "owner_label" and expected["owner_kind"] == "corpus_person":
                # Stable person references already disambiguate the display role.
                continue
            if actual[field] == expected[field]:
                correct[field] += 1
            else:
                wrong.append(field)
        if wrong:
            errors.append({"case": k[0], "anchor": k[1], "wrong": wrong})
        positive_dates += int(expected["due_date"] is not None)
        positive_date_hits += int(expected["due_date"] is not None and actual["due_date"] == expected["due_date"])
        wanted, found = set(expected["evidence_ids"]), set(actual["evidence_ids"])
        ev_hits += len(wanted & found)
        ev_gold += len(wanted)
        ev_pred += len(found)
    sizes = {f: len(matched) for f in FIELDS}
    sizes["owner_label"] = sum(gold[k]["owner_kind"] != "corpus_person" for k in matched)
    total_predictions = sum(map(len, guesses.values()))
    return {"split": split, "excerpts": len(selected),
            "action_anchors": prf(len(matched), len(gold), total_predictions),
            "create_anchors": prf(sum(gold[k]["operation"] == guesses[k][0]["operation"] == "create" for k in matched),
                                  sum(r["operation"] == "create" for r in gold.values()),
                                  sum(r["operation"] == "create" for group in guesses.values() for r in group)),
            "matched_fields": {f: {"correct": correct[f], "total": sizes[f]} for f in FIELDS},
            "positive_calendar_dates_on_matches": {"correct": positive_date_hits, "total": positive_dates},
            "evidence_on_matched_actions": prf(ev_hits, ev_gold, ev_pred), "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    args = parser.parse_args()
    try:
        print(json.dumps(score(lines(args.predictions), args.split), ensure_ascii=False, indent=2))
    except (TypeError, KeyError, ValueError, OSError) as error:
        parser.exit(2, f"Invalid input: {error}\n")
