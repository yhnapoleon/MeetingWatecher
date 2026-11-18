"""Run a small evidence-retrieval study on four public QMSum meetings."""

import argparse
from collections import Counter
import hashlib
import json
from math import log
from pathlib import Path
import re
from urllib.request import urlopen


REVISION = "83d7768c1f2b4dfeb091385d3dc7e239b8e5bb7e"
SOURCE = f"https://raw.githubusercontent.com/Yale-LILY/QMSum/{REVISION}/data/ALL/test/"
MEETINGS = ("ES2004a", "ES2004b", "ES2004c", "ES2004d")


def load_meetings(cache):
    cache.mkdir(parents=True, exist_ok=True)
    meetings, hashes = {}, {}
    for name in MEETINGS:
        path = cache / f"{name}.json"
        if not path.exists():
            with urlopen(SOURCE + path.name, timeout=30) as response:
                data = response.read()
            json.loads(data)
            path.write_bytes(data)
        data = path.read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        meetings[name] = json.loads(data)
    return meetings, hashes


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def build_index(meetings):
    windows = []
    document_frequency = Counter()
    for name, meeting in meetings.items():
        turns = meeting["meeting_transcripts"]
        for start in range(0, len(turns), 8):
            stop = min(start + 16, len(turns))
            words = Counter(tokens(" ".join(t["content"] for t in turns[start:stop])))
            windows.append((name, start, stop, words, words.total()))
            document_frequency.update(words.keys())
            if stop == len(turns):
                break
    idf = {
        term: log(1 + (len(windows) - count + 0.5) / (count + 0.5))
        for term, count in document_frequency.items()
    }
    return windows, idf, sum(w[-1] for w in windows) / len(windows)


def bm25(window, query, idf, avg_len):
    counts, length = window[-2:]
    norm = 1.2 * (0.25 + 0.75 * length / avg_len)
    return sum(idf.get(t, 0) * counts[t] * 2.2 / (counts[t] + norm) for t in query)


def evaluate(meetings):
    windows, idf, avg_len = build_index(meetings)
    rows = []
    for name, meeting in meetings.items():
        for i, question in enumerate(meeting["specific_query_list"]):
            query = sorted(set(tokens(question["query"])))
            gold = set()
            for first, last in question["relevant_text_span"]:
                gold.update(range(int(first), int(last) + 1))
            ranked = sorted(windows, key=lambda w: -bm25(w, query, idf, avg_len))
            pools = {
                "known_meeting": [w for w in ranked if w[0] == name],
                "through_current_meeting": [w for w in ranked if w[0] <= name],
                "whole_series": ranked,
            }
            for scope, pool in pools.items():
                best_name, start, stop = pool[0][:3]
                overlap = len(gold.intersection(range(start, stop))) if best_name == name else 0
                rows.append({
                    "query": f"{name}#{i}", "scope": scope, "top_meeting": best_name,
                    "top_window": [start, stop - 1], "correct_meeting": best_name == name,
                    "hit": overlap > 0, "gold_coverage": overlap / len(gold),
                    "window_precision": overlap / (stop - start),
                })
    by_scope = {}
    for scope in ("known_meeting", "through_current_meeting", "whole_series"):
        selected = [r for r in rows if r["scope"] == scope]
        by_scope[scope] = {
            "queries": len(selected), "correct_meeting": sum(r["correct_meeting"] for r in selected),
            "hits": sum(r["hit"] for r in selected),
            **{key: round(sum(r[key] for r in selected) / len(selected), 4)
               for key in ("gold_coverage", "window_precision")},
        }
    return {"windows": len(windows), "results": by_scope, "queries": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path, help="Local cache for four public files")
    args = parser.parse_args()
    meetings, hashes = load_meetings(args.cache / REVISION)
    print(json.dumps({"revision": REVISION, "sha256": hashes, **evaluate(meetings)}, indent=2))
