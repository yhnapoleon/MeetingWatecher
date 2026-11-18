"""Run independent transcript extraction requests and preserve the model responses."""

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("description", "action_anchor", "operation", "owner_kind",
          "owner_label", "owner_ref", "due_text", "due_date")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def credentials(path):
    values = {}
    if path:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    key = values.get("OPENAI_API_KEY")
    model = values.get("MEETING_MODEL")
    base = values.get("MEETING_API_BASE")
    if not all((key, model, base)):
        raise ValueError("Set OPENAI_API_KEY, MEETING_MODEL and MEETING_API_BASE")
    url = urllib.parse.urlsplit(base)
    if url.scheme not in ("http", "https") or url.username or url.password or url.query or url.fragment:
        raise ValueError("MEETING_API_BASE must be an HTTP(S) API URL without credentials or query parameters")
    return key, model, base.rstrip("/") + "/chat/completions"


def validate_prediction(response, case):
    choice = response["choices"][0]
    if choice["finish_reason"] != "stop":
        raise ValueError("INCOMPLETE_MODEL_RESPONSE")
    prediction = json.loads(choice["message"]["content"])
    if prediction["case_id"] != case["case_id"] or not isinstance(prediction["items"], list):
        raise ValueError("INVALID_CASE_OR_ITEMS")
    valid_ids = {s["id"] for s in case["segments"]}
    for item in prediction["items"]:
        if any(k not in item or item[k] is not None and not isinstance(item[k], str) for k in FIELDS):
            raise ValueError("INVALID_ITEM_FIELDS")
        if not item["description"] or item["operation"] not in ("create", "candidate"):
            raise ValueError("INVALID_ACTION")
        if item["owner_kind"] not in (None, "corpus_person", "speaker", "group"):
            raise ValueError("INVALID_OWNER_KIND")
        evidence = item["evidence_ids"]
        if (not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence)
                or len(evidence) != len(set(evidence)) or item["action_anchor"] not in evidence
                or not set(evidence) <= valid_ids):
            raise ValueError("INVALID_EVIDENCE")
    return prediction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    args = parser.parse_args()
    key, model, endpoint = credentials(args.env_file)
    corpus = ROOT / "data/mvp-v1"
    prompt_file = ROOT / "prompts/extract-actions-v1.txt"
    prompt = prompt_file.read_text(encoding="utf-8")
    with (corpus / "splits.csv").open(encoding="utf-8-sig", newline="") as f:
        selected = {r["case_id"] for r in csv.DictReader(f) if r["split"] == args.split}
    cases = [c for c in read_jsonl(corpus / "input.jsonl") if c["case_id"] in selected]
    params = {"model": model, "temperature": 0, "max_tokens": 2500,
              "response_format": {"type": "json_object"}, "stream": False}
    if model.startswith("deepseek"):
        params["thinking"] = {"type": "disabled"}
    config = {"endpoint": endpoint, "parameters": params, "split": args.split,
              "case_ids": [c["case_id"] for c in cases], "prompt_sha256": digest(prompt_file),
              "input_sha256": digest(corpus / "input.jsonl"), "splits_sha256": digest(corpus / "splits.csv")}
    args.out.mkdir(parents=True, exist_ok=True)
    config_file = args.out / "config.json"
    if config_file.exists():
        if json.loads(config_file.read_text(encoding="utf-8")) != config:
            raise ValueError("Existing run uses different inputs, prompt or model. Use a new --out directory")
    else:
        write_json(config_file, config)
        (args.out / "prompt.txt").write_text(prompt, encoding="utf-8")
        (args.out / "input.jsonl").write_text(
            "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
    attempts_file = args.out / "attempts.jsonl"
    attempts = read_jsonl(attempts_file) if attempts_file.exists() else []
    completed = {r["case_id"]: r for r in attempts if r["status"] == "ok"}
    predictions = []
    for index, case in enumerate(cases, 1):
        cid = case["case_id"]
        if cid in completed:
            raw = json.loads((args.out / completed[cid]["response_path"]).read_text(encoding="utf-8"))
            predictions.append(validate_prediction(raw, case))
            continue
        attempt = 1 + sum(a["case_id"] == cid for a in attempts)
        request_body = {**params, "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(case, ensure_ascii=False)}]}
        response_name = f"{cid}.attempt-{attempt}.response.json"
        write_json(args.out / f"{cid}.attempt-{attempt}.request.json", request_body)
        record = {"case_id": cid, "attempt": attempt,
                  "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "response_path": response_name, "status": "failed"}
        request = urllib.request.Request(endpoint, data=json.dumps(request_body).encode("utf-8"),
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=90) as stream:
                response = json.load(stream)
            write_json(args.out / response_name, response)
            record["model_returned"] = response.get("model")
            record["usage"] = response.get("usage")
            prediction = validate_prediction(response, case)
            predictions.append(prediction)
            record["status"] = "ok"
        except urllib.error.HTTPError as error:
            record["http_status"] = error.code
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            record["error_type"] = type(error).__name__
        finally:
            record["duration_seconds"] = round(time.perf_counter() - started, 3)
            with attempts_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            attempts.append(record)
        print(f"{index}/{len(cases)} {cid}: {record['status']} ({record['duration_seconds']}s)", flush=True)
        if record["status"] != "ok":
            raise SystemExit("Run interrupted. Inspect the attempt record; rerun the same command to resume")
    (args.out / "predictions.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions), encoding="utf-8")
    print(f"Saved {len(predictions)} predictions to {args.out / 'predictions.jsonl'}")


if __name__ == "__main__":
    main()
