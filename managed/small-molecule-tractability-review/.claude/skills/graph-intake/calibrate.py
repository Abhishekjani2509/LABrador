#!/usr/bin/env python3
"""Measure how much of the intake is running on heuristics, across many graphs.

Everything in this skill splits two ways. Some of it is derived from SCHEMA.md
and is as correct on graph 500 as on graph 1: the `kind` and `basis` enums, the
orphan-finding and dangling-reference checks, findings dedup, schema-drift
detection. The rest is word lists -- relation verbs, quote terms, assay
contexts, the symbol stop-list -- hand-written against one real graph and three
fixtures we wrote ourselves. Those cannot be complete and were never going to be.

The design makes that safe rather than correct: an unrecognised verb goes to
`needs_adjudication`, an unverified symbol is not nominated, a multi-symbol
phrase stays ambiguous. So the failure mode of an under-tuned list is
UNDER-RECALL, not a wrong answer -- the intake refuses more and asserts less.

That is only useful if somebody can see it happening. This counts it.

Run it over a batch of graphs before trusting an aggregate result, and read
`unseen_verbs` first: those are relation words the corpus used and our lists do
not know. They are the direct measure of how far the heuristics have drifted
from the data.

Usage:
    python3 calibrate.py <graph.json> [<graph.json> ...]
    python3 calibrate.py --store <store_dir>
    python3 calibrate.py <graphs...> --json
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import graph_read as G  # noqa: E402

try:
    import graph_store as S
except ImportError:  # store loading is optional
    S = None


def load_graphs(args):
    graphs = []
    if args.store:
        if S is None:
            raise SystemExit("graph_store.py not importable; pass graph files instead")
        idx = S.read_json(os.path.join(args.store, "index.json"), {}) or {}
        for gid in sorted(idx):
            graphs.append((gid, S.load(args.store, gid)))
    skipped = []
    for path in args.graphs:
        with open(path) as fh:
            g = json.load(fh)
        # A grading key sits beside its graph and matches *.json globs. It has no
        # `things`, so it would survey as an empty graph and dilute every rate.
        if not isinstance(g, dict) or "things" not in g:
            skipped.append(os.path.basename(path))
            continue
        graphs.append((g.get("graph_id") or os.path.basename(path), g))
    if skipped:
        sys.stderr.write(f"skipped (not graphs): {', '.join(skipped)}\n")
    if not graphs:
        raise SystemExit("no graphs given")
    return graphs


def survey(graph):
    """Per-graph counts, plus every vocabulary item our lists did not know."""
    idx = G.index(graph)
    things = idx["things"]
    out = G.build(graph)

    verbs = collections.Counter()
    unseen = collections.Counter()
    for l in idx["links"].values():
        verb = (l.get("how") or "").lower().strip()
        verbs[verb] += 1
        # Only small-molecule subjects are classified by verb at all; a verb on a
        # biological subject is never matched against either list, so counting it
        # as unseen would overstate the drift.
        if things.get(l.get("from"), {}).get("kind") == "small_molecule":
            if verb not in G.DIRECT_ACTION and verb not in G.DOWNSTREAM_EFFECT:
                unseen[verb] += 1

    noms = out.get("nominations", [])
    by_route = collections.Counter()
    for n in noms:
        for r in n.get("nominated_by", []):
            by_route["gap" if str(r.get("via", "")).startswith("g") else "direct_action"] += 1

    cands = (out.get("symbol_candidates") or {}).get("candidates", [])
    tiers = collections.Counter(
        (n.get("evidence_floor") or {}).get("tier", "unknown") for n in noms)

    return {
        "graph_id": out.get("graph_id"),
        "is_fixture": bool(graph.get("_fixture")),
        "status": out.get("status"),
        "stop_reason": (out.get("coverage_warning") or {}).get("stop_reason"),
        "things": len(things),
        "links": len(idx["links"]),
        "findings": len(idx["findings"]),
        "kinds": dict(collections.Counter(
            t.get("kind") for t in things.values()).most_common()),
        "nominations": len(noms),
        "nomination_routes": dict(by_route),
        "evidence_tiers": dict(tiers),
        "rejected": len(out.get("rejected", [])),
        "needs_adjudication": len(out.get("needs_adjudication", [])),
        "orphan_findings": len(out.get("orphan_findings", [])),
        "symbol_candidates": len(cands),
        "symbols_proposed": sorted({c.get("symbol") for c in cands}),
        "verbs": dict(verbs.most_common()),
        "unseen_verbs": dict(unseen.most_common()),
    }


def aggregate(rows):
    unseen = collections.Counter()
    verbs = collections.Counter()
    kinds = collections.Counter()
    for r in rows:
        unseen.update(r["unseen_verbs"])
        verbs.update(r["verbs"])
        kinds.update(r["kinds"])

    tiers = collections.Counter()
    for r in rows:
        tiers.update(r.get("evidence_tiers") or {})
    total_sm_edges = sum(r["needs_adjudication"] for r in rows)
    graphs_with_no_nominations = [r["graph_id"] for r in rows if r["nominations"] == 0]

    return {
        "graphs": len(rows),
        "nominations_total": sum(r["nominations"] for r in rows),
        "evidence_tiers": dict(tiers),
        "graphs_with_zero_nominations": graphs_with_no_nominations,
        "adjudications_total": total_sm_edges,
        "orphan_findings_total": sum(r["orphan_findings"] for r in rows),
        "kinds_seen": dict(kinds.most_common()),
        "verbs_seen": dict(verbs.most_common()),
        # The headline number. Every entry is a relation word the corpus used
        # that neither verb list knows, so every one became an adjudication the
        # agent had to resolve by reading quotes.
        "unseen_verbs": dict(unseen.most_common()),
        "verb_coverage": (
            None if not verbs else
            round(1 - sum(unseen.values()) / sum(verbs.values()), 3)
        ),
    }


def human(rows, agg):
    w = sys.stdout.write
    w(f"{len(rows)} graph(s)\n\n")
    w(f"{'graph':14} {'status':9} {'things':>6} {'nom':>4} {'rej':>4} "
      f"{'adj':>4} {'orph':>5} {'cand':>5}\n")
    for r in rows:
        w(f"{str(r['graph_id'])[:14]:14} {str(r['status'])[:9]:9} "
          f"{r['things']:6} {r['nominations']:4} {r['rejected']:4} "
          f"{r['needs_adjudication']:4} {r['orphan_findings']:5} "
          f"{r['symbol_candidates']:5}\n")

    fixtures = [r["graph_id"] for r in rows if r.get("is_fixture")]
    if fixtures:
        w(f"\nsynthetic fixtures in this batch: {fixtures}\n"
          "  These were written to exercise the code, so rates over them measure\n"
          "  our own assumptions, not the corpus. Read the real graphs separately.\n")
    t = agg.get("evidence_tiers") or {}
    if t:
        weak = t.get("non_actionable", 0) + t.get("gap_only", 0)
        w(f"\nevidence tiers: {t}\n")
        if weak:
            w(f"  {weak} of {agg['nominations_total']} nominations rest on review,\n"
              "  hedged or gap-only evidence. Each is a dossier run that should be\n"
              "  preceded by a resolve_link or test_gap ask, not spent blind.\n")
    w(f"\nkinds seen: {agg['kinds_seen']}\n")
    if agg["verb_coverage"] is not None:
        w(f"verb coverage: {agg['verb_coverage']:.1%} "
          f"({sum(agg['unseen_verbs'].values())} of "
          f"{sum(agg['verbs_seen'].values())} edges used an unknown verb)\n")

    if agg["unseen_verbs"]:
        w("\nUNSEEN VERBS -- relation words the corpus used and our lists do not\n"
          "know. Each one became an adjudication. If a verb here is clearly\n"
          "direct-action or clearly downstream, add it; if it is genuinely\n"
          "ambiguous, leave it and let the quote decide.\n")
        for v, n in agg["unseen_verbs"].items():
            w(f"  {n:4}x  {v}\n")
    else:
        w("\nno unseen verbs -- but that is weak evidence on a small batch.\n")

    if agg["graphs_with_zero_nominations"]:
        w(f"\nzero nominations: {agg['graphs_with_zero_nominations']}\n"
          "  Check whether the graph genuinely names no target, or whether the\n"
          "  heuristics simply did not reach it. Those look identical here.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("graphs", nargs="*", help="graph JSON files")
    ap.add_argument("--store", help="a mapper store dir holding index.json")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    rows = [survey(g) for _, g in load_graphs(args)]
    agg = aggregate(rows)

    if args.json:
        json.dump({"per_graph": rows, "aggregate": agg}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        human(rows, agg)


if __name__ == "__main__":
    main()
