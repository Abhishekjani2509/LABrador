#!/usr/bin/env python3
"""Load an upstream graph by `graph_id` from the mapper's store.

SCHEMA.md's contract is that Stage 1 owns storage and Stage 2 never holds or
sends a graph -- it sends a `graph_id` and gets the graph back. The MCP
transport that would carry that does not exist yet, but the store does, laid
out on disk exactly as the schema describes. So this reassembles a graph from
the store rather than reading a single JSON file, which is the same interface
one layer down.

Store layout:
    index.json                  graph_id -> question, round, updated_at
    <graph_id>/meta.json        question, round, rounds[], coverage, status
    <graph_id>/things.json
    <graph_id>/papers.json
    <graph_id>/links.json
    <graph_id>/gaps.json
    <graph_id>/findings/r1.json  one chunk per round, ~80KB cap
    <graph_id>/findings/r2.json

Findings chunk by round because a single memory file caps at 100KB. SCHEMA.md
says rounds append and never rewrite; the shipped store writes a full snapshot
per chunk instead, so reassembly dedupes by id rather than concatenating. See
load_findings.

Usage:
    python3 graph_store.py <store_dir> --list
    python3 graph_store.py <store_dir> --graph-id g_1a4f
    python3 graph_store.py <store_dir> --graph-id g_1a4f | python3 graph_read.py -
"""

import argparse
import json
import os
import re
import sys

R_CHUNK = re.compile(r"^r(\d+)\.json$")

# Fields the real store emits that SCHEMA.md does not document. Recorded rather
# than dropped: a field we do not know about may be one we should be reading,
# and silently discarding it hides that the contract has moved.
DOCUMENTED = {
    "things": {"id", "name", "kind", "aliases", "mentions"},
    "papers": {"id", "title", "year", "journal", "doi", "first_author",
               "study_type", "is_preprint", "retracted", "round"},
    "findings": {"id", "from", "how", "to", "says", "quote", "paper", "where",
                 "section", "is_own_result", "hedged", "confidence", "flags",
                 "round"},
    "links": {"id", "from", "how", "to", "yes", "no", "no_effect", "state",
              "why", "basis", "confidence", "changed_in_round"},
    "gaps": {"id", "missing", "implied_by", "note", "confidence",
             "searched_in_round"},
}


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def load_findings(graph_dir):
    """Merge findings/r<N>.json in round order, deduped by id.

    SCHEMA.md says rounds append and never rewrite, so a plain concatenation
    should be correct. The shipped store does NOT do that -- on g_1a4f, r1 holds
    7 findings and r2 holds 12 including all 7 of r1's. Each chunk is a full
    snapshot, not a delta.

    Concatenating therefore double-counts, and the duplicates would land in
    `yes`/`no` counts that feed `agreement` and `independence`. Dedupe by id
    with the highest round winning, which is correct under either behaviour.

    Sorted numerically, not lexically -- r10 must not land between r1 and r2.
    """
    fdir = os.path.join(graph_dir, "findings")
    if not os.path.isdir(fdir):
        return [], None
    chunks = []
    for name in os.listdir(fdir):
        m = R_CHUNK.match(name)
        if m:
            chunks.append((int(m.group(1)), os.path.join(fdir, name)))

    merged, raw = {}, 0
    for _, path in sorted(chunks):
        rows = read_json(path, []) or []
        raw += len(rows)
        for row in rows:
            merged[row.get("id")] = row

    dupes = raw - len(merged)
    mode = None
    if dupes:
        mode = (
            f"chunks are full snapshots, not deltas: {raw} rows across "
            f"{len(chunks)} files collapsed to {len(merged)} by id. SCHEMA.md "
            f"documents append-only rounds; the store does not behave that way. "
            f"Concatenating would inflate agreement and independence."
        )
    return list(merged.values()), mode


def undocumented_fields(graph):
    drift = {}
    for key, known in DOCUMENTED.items():
        seen = set()
        for row in graph.get(key, []) or []:
            seen |= set(row.keys())
        extra = sorted(seen - known)
        if extra:
            drift[key] = extra
    return drift


def load(store_dir, graph_id):
    graph_dir = os.path.join(store_dir, graph_id)
    if not os.path.isdir(graph_dir):
        raise SystemExit(
            f"unknown graph_id '{graph_id}' in {store_dir}. "
            f"SCHEMA.md: an unknown graph_id is an error and no partial graph "
            f"is returned. Run with --list to see what exists."
        )

    meta = read_json(os.path.join(graph_dir, "meta.json"), {}) or {}
    graph = dict(meta)
    graph["things"] = read_json(os.path.join(graph_dir, "things.json"), []) or []
    graph["papers"] = read_json(os.path.join(graph_dir, "papers.json"), []) or []
    graph["links"] = read_json(os.path.join(graph_dir, "links.json"), []) or []
    graph["gaps"] = read_json(os.path.join(graph_dir, "gaps.json"), []) or []
    graph["findings"], chunk_mode = load_findings(graph_dir)
    if chunk_mode:
        graph["_findings_chunk_mode"] = chunk_mode

    drift = undocumented_fields(graph)
    if drift:
        graph["_undocumented_fields"] = drift

    # Every id must resolve -- SCHEMA.md guarantees it, so a dangling one means
    # the store is torn (a half-written round), not that the graph is sparse.
    ids = {t["id"] for t in graph["things"]}
    fids = {f["id"] for f in graph["findings"]}
    dangling = []
    for l in graph["links"]:
        for end in ("from", "to"):
            if l.get(end) not in ids:
                dangling.append(f"link {l.get('id')}.{end} -> {l.get(end)}")
        for arr in ("yes", "no", "no_effect"):
            for f in l.get(arr, []) or []:
                if f not in fids:
                    dangling.append(f"link {l.get('id')}.{arr} -> {f}")
    # rounds[].target names a row the ask was issued against. On g_1a4f round 2
    # targets g3, which is not in gaps[] -- a gap that was tested and resolved
    # away leaves its id behind in the history. Re-asking it wastes a round.
    gap_ids = {g["id"] for g in graph["gaps"]}
    link_ids = {l["id"] for l in graph["links"]}
    stale = [
        {"round": r.get("n"), "ask": r.get("ask"), "target": r.get("target"),
         "outcome": r.get("outcome"),
         "why": "target no longer present in gaps[] or links[] -- already resolved, do not re-ask"}
        for r in (graph.get("rounds") or [])
        if r.get("target") and r["target"] not in gap_ids | link_ids | ids
    ]
    if stale:
        graph["_resolved_ask_targets"] = stale

    if dangling:
        graph["_dangling_refs"] = dangling

    return graph


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("store", help="path to the mapper's store dir (holds index.json)")
    ap.add_argument("--graph-id", help="graph to load")
    ap.add_argument("--list", action="store_true", help="list graphs in the store")
    args = ap.parse_args()

    if args.list or not args.graph_id:
        idx = read_json(os.path.join(args.store, "index.json"), {}) or {}
        json.dump(idx, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    json.dump(load(args.store, args.graph_id), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
