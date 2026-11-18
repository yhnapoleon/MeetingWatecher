"""Verify the distributed annotations against the source corpus and local media."""

import csv
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

DATA = Path(__file__).resolve().parents[1] / "data" / "mvp-v1"
NITE = "{http://nite.sourceforge.net/}"
ROLES = {"PM": "Project Manager", "ID": "Industrial Designer",
         "ME": "Marketing Expert", "UI": "User Interface Designer"}


def require(condition, context):
    if not condition:
        raise ValueError(context)


def lines(file):
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]


def csv_rows(name):
    with (DATA / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def indexed(rows, key):
    table = {row[key]: row for row in rows}
    require(len(table) == len(rows), f"Duplicate {key}")
    return table


def verify_ami(archive, cases, labels):
    def xml(name):
        return ET.fromstring(archive.read(name))

    @lru_cache(maxsize=None)
    def channel_data(channel):
        words = list(xml(f"words/{channel}.words.xml"))
        position = {w.get(NITE + "id"): i for i, w in enumerate(words)}
        acts = {a.get(NITE + "id"): a for a in xml(f"dialogueActs/{channel}.dialog-act.xml")}
        return words, position, acts

    meetings = {m.get("observation"): m for m in xml("corpusResources/meetings.xml")}
    summaries = {}
    for case in cases:
        mid = case["meeting_id"]
        meeting = meetings[mid]
        roster = {s.get("nxt_agent"): (ROLES[s.get("role")], s.get("global_name"))
                  for s in meeting.findall("speaker")}
        actual = {s["speaker"]: (s["speaker_name"], s["person_ref"]) for s in case["participants"]}
        require(roster == actual and case["meeting_date"] == meeting.get("dateOnly"), mid)
        if mid not in summaries:
            summaries[mid] = {s.get(NITE + "id"): (group.tag, (s.text or "").strip())
                              for group in xml(f"abstractive/{mid}.abssumm.xml")
                              for s in group.findall("sentence")}
        for s in case["segments"]:
            sid = s["id"]
            words, position, acts = channel_data(mid + "." + s["speaker"])
            selected = []
            for ref in acts[sid].findall(NITE + "child"):
                ids = re.findall(r"id\(([^)]+)\)", ref.get("href"))
                selected.extend(words[position[ids[0]]:position[ids[-1]] + 1])
            spoken = [w for w in selected if w.tag == "w" and w.text]
            source_text = " ".join(w.text for w in spoken)
            # Punctuation and contractions can be spaced differently in the word XML.
            tokens = r"\w+|[^\w\s]"
            require(re.findall(tokens, s["text"]) == re.findall(tokens, source_text), sid)
            bounds = [(round(1000 * float(ws[0].get("starttime"))),
                       round(1000 * float(ws[-1].get("endtime")))) for ws in (selected, spoken)]
            require((s["start_ms"], s["end_ms"]) in bounds, sid)
            require((s["speaker_name"], s["person_ref"]) == roster[s["speaker"]], sid)
        for row in labels[case["case_id"]]:
            ref = row["source_annotation"]
            if ref:
                require(summaries[mid][ref["id"]] == (ref["category"], ref["summary"]), row["label_id"])
            if row["owner_ref"]:
                require((ROLES[row["owner_label"]], row["owner_ref"]) in roster.values(), row["label_id"])


def verify_workflow():
    scenario = json.loads((DATA / "workflow/scenario.json").read_text(encoding="utf-8"))
    answers = json.loads((DATA / "workflow/expected.json").read_text(encoding="utf-8"))["recaps"]
    recomputed = []
    for query in scenario["queries"]:
        tasks = {t["guid"]: {**t, "readers": set(t["readers"])} for t in scenario["tasks_at_0900"]}
        for event in sorted(scenario["server_events"], key=lambda e: e["at"]):
            if event["at"] > query["as_of"]:
                break
            task = tasks[event["guid"]]
            if event["kind"] == "revoke_reader":
                task["readers"].remove(event["value"])
            elif event["kind"] == "set_status":
                task["status"] = event["value"]
            else:
                raise ValueError(event["kind"])
        for viewer in query["viewers"]:
            visible = {key for key, t in tasks.items() if viewer in t["readers"]}
            recomputed.append({"meeting": query["meeting"], "viewer": viewer,
                               "expected": sorted(i for i in visible if tasks[i]["status"] == "open"),
                               "forbidden": sorted(tasks.keys() - visible)})
    require(recomputed == answers, "Workflow annotations differ from snapshot and event replay")
    return len(answers)


def main():
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    for asset in manifest["raw"] + manifest["clips"]:
        path = DATA / asset["path"]
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        require(path.stat().st_size == asset["bytes"] and digest == asset["sha256"], path)

    cases = indexed(lines(DATA / "input.jsonl"), "case_id")
    labels = indexed(lines(DATA / "labels.jsonl"), "label_id")
    splits = indexed(csv_rows("splits.csv"), "case_id")
    review = indexed(csv_rows("review.csv"), "label_id")
    media = indexed(csv_rows("media.csv"), "case_id")
    require(cases.keys() == splits.keys() and labels.keys() == review.keys(), "Review/split ID mismatch")
    require(media.keys() == {k for k, c in cases.items() if c["source"] == "AMI_1.6.2"}, "Media coverage")
    require({r["path"] for r in media.values()} == {a["path"] for a in manifest["clips"]}, "Clip paths")
    vc = {str(r["id"]): r for r in lines(DATA / "raw/vcsum_overall_context.txt")}
    per_case = {cid: [] for cid in cases}
    series_split = {}
    segment_split = {}
    for cid, case in cases.items():
        split = splits[cid]
        require(split["meeting_id"] == case["meeting_id"] and split["series"] == case["series"], cid)
        require(series_split.setdefault(case["series"], split["split"]) == split["split"], cid)
        for s in case["segments"]:
            require(segment_split.setdefault(s["id"], split["split"]) == split["split"], s["id"])
        if cid in media:
            entry = media[cid]
            starts = [s["start_ms"] for s in case["segments"]]
            require(starts == sorted(starts) and entry["meeting_id"] == case["meeting_id"], cid)
            require(int(entry["source_start_ms"]) <= min(starts) and
                    int(entry["source_end_ms"]) >= max(s["end_ms"] for s in case["segments"]), cid)
        else:
            for s in case["segments"]:
                prefix, mid, group, sentence = s["id"].split(".")
                source = vc[mid]
                require(prefix == "vc" and case["meeting_id"] == "VC" + mid and
                        case["series"] == "VC" + str(source["av_num"]), s["id"])
                require(s["text"] == source["context"][int(group)][int(sentence)] and
                        s["speaker"] == str(source["speaker"][int(group)]), s["id"])
                require(all(s[k] is None for k in ("start_ms", "end_ms", "person_ref", "speaker_name")), s["id"])

    for lid, row in labels.items():
        case = cases[row["case_id"]]
        per_case[case["case_id"]].append(row)
        evidence = row["evidence_ids"]
        require(evidence and len(set(evidence)) == len(evidence) and
                set(evidence) <= {s["id"] for s in case["segments"]}, lid)
        require(row["operation"] != "create" or row["owner_ref"], lid)
        if row["operation"] in ("create", "candidate"):
            require(row["action_anchor"] in evidence, lid)
        if row["owner_kind"] == "speaker":
            require(row["owner_label"] in {s["speaker"] for s in case["segments"]}, lid)
        require(bool(row["prior_label"]) == bool(row["prior_relation"]), lid)
        if row["prior_label"]:
            prior = cases[labels[row["prior_label"]]["case_id"]]
            require(prior["series"] == case["series"] and
                    (prior["meeting_id"], prior["segments"][0]["start_ms"]) <
                    (case["meeting_id"], case["segments"][0]["start_ms"]), lid)
        sheet = review[lid]
        for field in ("case_id", "operation", "description", "owner_label", "owner_kind",
                      "owner_ref", "due_text", "due_date", "work_window_text", "action_anchor",
                      "prior_label", "prior_relation", "event_type", "reason"):
            require(sheet[field] == (row[field] or ""), f"{lid}: {field}")
        require(sheet["evidence_ids"] == "|".join(evidence), lid)
    require(all(per_case.values()), "Unlabeled excerpt")
    with zipfile.ZipFile(DATA / "raw/ami_public_manual_1.6.2.zip") as archive:
        verify_ami(archive, [cases[k] for k in media], per_case)
    print(json.dumps({"meetings": len({c["meeting_id"] for c in cases.values()}), "cases": len(cases),
                      "segments": sum(len(c["segments"]) for c in cases.values()), "labels": len(labels),
                      "operations": Counter(r["operation"] for r in labels.values()), "clips": len(media),
                      "split": Counter(r["split"] for r in splits.values()), "workflow_checks": verify_workflow()},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError) as exc:
        sys.exit(f"Dataset validation failed: {exc}")
