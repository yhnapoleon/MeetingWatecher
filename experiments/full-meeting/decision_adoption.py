"""Compare only the decisions stage using stored transcripts and a fresh output path."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor, FIELDS, model_input, validate
from meeting_eval.inputs import normalize
from meeting_eval.stage_runner import run_stage


def evaluate(source, out, legacy):
    raw = json.loads(source.read_text(encoding="utf8"))
    meeting = normalize(raw, "evaluator")
    payload = {"meeting": model_input(meeting), "decisions": []}
    out.mkdir(parents=True, exist_ok=True)
    extractor = Extractor(ROOT.parent.parent / "meeting-agent/.env", out / "model", "context-v5")
    if legacy:
        def checked(raw):
            fields = {field: [] for field in FIELDS}
            fields["decisions"] = raw["decisions"]
            validate(fields, payload["meeting"], {"decisions": []})
            return {"decisions": fields["decisions"]}
        prompt = (ROOT / "prompts/extract-decisions-v2.txt").read_text(encoding="utf8")
        result = run_stage(extractor.client, prompt, payload, "decisions", checked,
                           out / "model/independent", {"thinking":"disabled", "max_tokens":6000},
                           require_case_id=False)
    else:
        result = extractor.stage("decisions", payload)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    if result.get("_errors"):
        raise ValueError(result["_errors"])
    print(source.parent.name, len(result["decisions"]), "decisions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--legacy", action="store_true")
    args = parser.parse_args()
    evaluate(args.source, args.out, args.legacy)
