#!/usr/bin/env python3
"""Assemble the target-intake bundle from an upstream evidence graph.

Mechanical only. Graph traversal, edge classification, evidence tiering from
each link's `basis`, and — where the verb is unrecognised — an adjudication
packet carrying every deterministic signal the graph offers. Reading a mechanism
out of a quote is judgment and stays with the agent; see SKILL.md.

Nothing here decides tractability, ranks targets, or picks an accession.

Usage:
    python3 graph_read.py <graph.json>
    python3 graph_read.py <graph.json> --thing t1
    python3 graph_read.py <graph.json> --allow-fixture
    python3 graph_read.py <graph.json> --ask-context
    python3 graph_read.py <graph.json> --check-ask '<ask json>'
"""

import argparse
import json
import re
import sys

# SCHEMA.md v1.1 gives `kind` six values. Both of these name a protein target;
# papers say "IRAK4 knockdown" as readily as "IRAK4 protein", so the extractor
# can legitimately type the same target either way.
TARGET_KINDS = {"protein", "gene"}

# Tiers that must not set chain selection. `hedged_only` is every finding saying
# "may" or "suggests"; `background_only` is every finding restating someone
# else's work. Both produce a confident-looking answer from evidence that has
# not asserted anything.
NON_ACTIONABLE_BASIS = {"background_only", "hedged_only"}

# `how` has NO enum in SCHEMA.md. Every other categorical field there carries an
# explicit a|b|c comment; `how` does not. It is open vocabulary written by the
# upstream extraction model, so these sets can never be complete. An unmatched
# verb is NOT dropped -- it goes to `needs_adjudication` with the signals below.
DIRECT_ACTION = {
    "inhibits", "binds", "blocks", "antagonises", "antagonizes",
    "agonises", "agonizes", "degrades", "stabilises", "stabilizes",
    "activates", "engages", "occupies", "targets", "modulates",
    "inactivates", "disrupts",
}

DOWNSTREAM_EFFECT = {
    "reduces", "increases", "improves", "worsens", "lowers", "raises",
    "suppresses", "restores", "prevents", "attenuates", "ameliorates",
    "induces", "normalises", "normalizes",
}

# Quote-level signals. These read the EVIDENCE, not the verb, so they survive an
# extractor that invents new relation words. Matched as whole words.
DIRECT_TERMS = [
    "ic50", "ec50", " ki ", " kd ", "affinity", "binds", "binding",
    "target engagement", "occupancy", "kinase activity", "enzymatic activity",
    "catalytic", "co-crystal", "cocrystal", "biochemical", "displacement",
    "atp-competitive", "allosteric", "active site",
]
DOWNSTREAM_TERMS = [
    "secretion", "release", "levels", "expression", "production", "output",
    "score", "response rate", "acr20", "acr50", "pasi", "serum", "plasma",
    "symptom", "endpoint", "placebo",
]

# `where` values that place a measurement in a direct-binding context.
DIRECT_CONTEXTS = ["biochemical", "cell-free", "cell free", "purified", "in vitro binding"]

NS_WORD = re.compile(r"[^a-z0-9]+")


def index(graph):
    return {
        "things": {t["id"]: t for t in graph.get("things", [])},
        "papers": {p["id"]: p for p in graph.get("papers", [])},
        "findings": {f["id"]: f for f in graph.get("findings", [])},
        "links": {l["id"]: l for l in graph.get("links", [])},
        "gaps": {g["id"]: g for g in graph.get("gaps", [])},
    }


def classify(link, things):
    """Edge class depends on the SUBJECT's kind, not on the verb alone.

    `activates` from a small molecule is an agonist; `activates` from a receptor
    is pathway biology. Same verb, different class.
    """
    subject = things.get(link["from"], {})
    verb = (link.get("how") or "").lower().strip()

    if subject.get("kind") != "small_molecule":
        return "biological_relation"
    if verb in DIRECT_ACTION:
        return "direct_action"
    if verb in DOWNSTREAM_EFFECT:
        return "downstream_effect"
    return "unclassified"


def paper_ref(paper):
    if not paper:
        return None
    study = (paper.get("study_type") or "").replace("_", " ")
    ref = f"{paper.get('first_author')} et al., {paper.get('journal')} {paper.get('year')}"
    return f"{ref} ({study})" if study else ref


def expand(finding_id, link, idx):
    f = idx["findings"].get(finding_id)
    if not f:
        return None
    things = idx["things"]
    return {
        "finding": finding_id,
        "link": link["id"],
        "relation": (
            f"{things.get(link['from'], {}).get('name')} {link.get('how')} "
            f"{things.get(link['to'], {}).get('name')}"
        ),
        "quote": f.get("quote"),
        "where": f.get("where"),
        "section": f.get("section"),
        "says": f.get("says"),
        "paper": f.get("paper"),
        "paper_ref": paper_ref(idx["papers"].get(f.get("paper"))),
        "retracted": (idx["papers"].get(f.get("paper")) or {}).get("retracted"),
        "is_own_result": f.get("is_own_result"),
        "hedged": f.get("hedged"),
        "finding_confidence": f.get("confidence"),
        "flags": f.get("flags", []),
        "link_basis": link.get("basis"),
        "link_state": link.get("state"),
        "link_confidence": (link.get("confidence") or {}).get("overall"),
    }


def link_findings(link):
    return (
        list(link.get("yes", []))
        + list(link.get("no", []))
        + list(link.get("no_effect", []))
    )


def matched(text, terms):
    if not text:
        return []
    padded = " " + NS_WORD.sub(" ", text.lower()) + " "
    return [t.strip() for t in terms if t.strip() and (" " + t.strip() + " ") in padded
            or (" " not in t.strip() and " " + t.strip() + " " in padded)]


def signals(link, idx):
    """Deterministic evidence for a target-vs-readout call, read from the
    quotes and the graph shape rather than from the verb string.

    Returned as evidence, never as a verdict. The agent adjudicates.
    """
    things = idx["things"]
    obj_id = link.get("to")
    rows = [expand(f, link, idx) for f in link_findings(link)]
    rows = [r for r in rows if r]

    quotes = " ".join(r["quote"] or "" for r in rows)
    wheres = [r["where"] for r in rows if r.get("where")]

    # A readout usually carries the causal chain onward to a disease. A target
    # usually does not. Weak alone, useful alongside the quote terms.
    onward_to_disease = [
        l["id"] for l in idx["links"].values()
        if l.get("from") == obj_id
        and things.get(l.get("to"), {}).get("kind") == "disease"
    ]

    return {
        "object_kind": things.get(obj_id, {}).get("kind"),
        "object_has_edge_to_disease": onward_to_disease,
        "assay_contexts": wheres,
        "direct_context": [
            w for w in wheres if any(c in (w or "").lower() for c in DIRECT_CONTEXTS)
        ],
        "direct_terms_in_quotes": matched(quotes, DIRECT_TERMS),
        "downstream_terms_in_quotes": matched(quotes, DOWNSTREAM_TERMS),
    }


def neighbourhood(thing_id, idx):
    """Every link touching this thing, with its findings expanded and tiered.

    Tier comes from the LINK's `basis`, not from the finding's own confidence.
    A 0.88-confidence quote from a review is still background.
    """
    tiers = {"primary": [], "mixed": [], "background_only": []}
    for link in idx["links"].values():
        if thing_id not in (link.get("from"), link.get("to")):
            continue
        basis = link.get("basis") or "unknown"
        bucket = tiers.setdefault(basis, [])
        # Three arrays, not two. `no_effect` is a measured null result, which is
        # not the same as `no` (evidence against) -- on a direct-action edge it
        # is real tractability evidence that the compound does not engage.
        for fid in link_findings(link):
            row = expand(fid, link, idx)
            if row:
                row["actionable"] = basis not in NON_ACTIONABLE_BASIS
                bucket.append(row)
    return {k: v for k, v in tiers.items() if v}


def nominate(graph, idx):
    """A thing is a target candidate if its kind is protein or gene AND either

      (a) the object of a direct-action edge from a small molecule, or
      (b) named in a gap.

    (b) is what carries the undrugged candidates. Without it the intake can only
    ever return targets somebody already made a molecule against.
    """
    things = idx["things"]
    nominated, rejected, adjudicate = {}, {}, []

    for link in idx["links"].values():
        cls = classify(link, things)
        obj = things.get(link.get("to"), {})
        if not obj:
            continue
        if cls == "direct_action":
            if obj.get("kind") not in TARGET_KINDS:
                rejected.setdefault(obj["id"], []).append(
                    f"direct-action edge {link['id']} ({link.get('how')}) but kind is "
                    f"'{obj.get('kind')}', not one of {sorted(TARGET_KINDS)}"
                )
                continue
            nominated.setdefault(obj["id"], []).append({
                "via": link["id"],
                "why": (
                    f"object of direct-action edge from small_molecule "
                    f"{link['from']} ({link.get('how')})"
                ),
            })
        elif cls == "downstream_effect":
            rejected.setdefault(obj["id"], []).append(
                f"reached only by downstream-effect edge {link['id']} "
                f"({link.get('how')}) -- readout, not target"
            )
        elif cls == "unclassified":
            # NOT dropped. `how` is open vocabulary, so an unmatched verb is a
            # target the intake could not classify -- a decision to make, not a
            # rare edge to ignore.
            adjudicate.append({
                "link": link["id"],
                "how": link.get("how"),
                "subject": {"id": link.get("from"),
                            "name": things.get(link.get("from"), {}).get("name")},
                "object": {"id": link.get("to"), "name": obj.get("name"),
                           "kind": obj.get("kind")},
                "eligible_kind": obj.get("kind") in TARGET_KINDS,
                "signals": signals(link, idx),
                "findings": [r for r in (expand(f, link, idx)
                                         for f in link_findings(link)) if r],
                "decide": (
                    "Is this a direct action on a target, or a downstream effect on a "
                    "readout? See SKILL.md 'Adjudicating an unknown verb'. Refusing is "
                    "allowed; guessing is not."
                ),
            })

    for gap in idx["gaps"].values():
        for tid in gap.get("missing", []):
            thing = things.get(tid, {})
            if not thing:
                continue
            if thing.get("kind") not in TARGET_KINDS:
                rejected.setdefault(tid, []).append(
                    f"named in gap {gap['id']} but kind is '{thing.get('kind')}', "
                    f"not one of {sorted(TARGET_KINDS)}"
                )
                continue
            nominated.setdefault(tid, []).append({
                "via": gap["id"],
                "why": "named in a gap -- undrugged candidate, no direct-action edge yet",
            })

    for tid in nominated:
        rejected.pop(tid, None)

    return nominated, rejected, adjudicate


def build(graph, only=None):
    idx = index(graph)
    things = idx["things"]
    nominated, rejected, adjudicate = nominate(graph, idx)

    if only:
        nominated = {k: v for k, v in nominated.items() if k == only}

    out = []
    for tid, reasons in sorted(nominated.items()):
        t = things[tid]
        out.append({
            "thing": tid,
            "name": t.get("name"),
            "kind": t.get("kind"),
            "aliases": t.get("aliases", []),
            "mentions": t.get("mentions"),
            "nominated_by": reasons,
            # Filled by the agent. Left null on purpose -- see SKILL.md.
            "gene_symbol": None,
            "uniprot_accession": None,
            "ambiguity": None,
            "interaction_to_disrupt": None,
            "mechanism_hypothesis": None,
            "evidence": neighbourhood(tid, idx),
        })

    coverage = graph.get("coverage", {})
    status = graph.get("status")
    # `complete` is the ONLY stop_reason meaning the literature was exhausted.
    # The other four mean the run ran out of budget (SCHEMA.md note 6).
    stop_reason = coverage.get("stop_reason")
    retracted = [p["id"] for p in graph.get("papers", []) if p.get("retracted")]

    return {
        "graph_id": graph.get("graph_id"),
        "round": graph.get("round"),
        "question": graph.get("question"),
        # `status` is never an error blob -- an `empty` or `failed` graph parses
        # fine and yields zero nominations, which reads as "no targets found".
        "status": status,
        "status_warning": (
            None if status == "ok"
            else f"graph status is '{status}' -- lists may be empty for reasons that "
                 f"are not evidence. Do not read zero nominations as a result."
        ),
        "coverage_warning": (
            {
                "truncated": coverage.get("truncated"),
                "stop_reason": stop_reason,
                "depth": coverage.get("depth"),
                "note": (
                    "Only stop_reason 'complete' means the literature was exhausted. "
                    "An absent mechanism statement here is a budget limit, not an "
                    "established absence."
                ),
            }
            if coverage.get("truncated") or (stop_reason and stop_reason != "complete")
            else None
        ),
        "retracted_papers": retracted,
        "nominations": out,
        "rejected": [
            {"thing": tid, "name": things.get(tid, {}).get("name"), "why": why}
            for tid, why in sorted(rejected.items())
        ],
        "needs_adjudication": adjudicate,
    }


# ---------------------------------------------------------------------------
# Ask-back gating. MECHANICAL ONLY.
#
# SCHEMA.md defines FOUR ask verbs and nothing here adds a fifth. What this
# section does is refuse the asks that are mechanically wrong -- malformed,
# unactionable, already issued, or pointed at a graph that has nothing left to
# give. It CANNOT check the three gates that matter most (does the claim affect
# the dossier, is its support secondary-only, did we try to resolve it
# ourselves). Those are judgment and they stay with the agent; see SKILL.md
# "Asking back after intake". A green result here is permission to consider an
# ask, never permission to issue one.
# ---------------------------------------------------------------------------

ASK_TYPES = {"expand_node", "resolve_link", "test_gap", "new_question"}

# Which index an ask's `target` must resolve into. `new_question` points at
# nothing by design -- it is the ask for a claim the graph has no row for.
ASK_TARGET_INDEX = {
    "expand_node": "things",
    "resolve_link": "links",
    "test_gap": "gaps",
    "new_question": None,
}

# An ask has to be answerable by somebody who cannot see our run. "is obefazimod
# a TL1A agent?" is not; naming the sources on both sides is. We cannot judge
# prose, but we can insist the question carries identifiers -- two of them, so
# both sides of the disagreement are reachable.
SOURCE_TOKEN = re.compile(r"(PMC\d{5,}|NCT\d{8}|10\.\d{4,}/\S+|CHEMBL\d+|\b[0-9][A-Z0-9]{3}\b)")

MIN_SOURCE_TOKENS = 2


def is_secondary(finding, papers):
    """A finding that restates someone else's work rather than reporting one.

    Three independent signals, any of which is enough. `flags: [background]` is
    the extractor's own call, `is_own_result: false` is the schema's, and a
    review paper is the journal's. They disagree often enough that reading only
    one of them misses cases -- f1/f2 in the ask-back fixture carry all three,
    but a class table inside a primary trial report carries only the first.
    """
    if "background" in (finding.get("flags") or []):
        return True
    if finding.get("is_own_result") is False:
        return True
    study = (papers.get(finding.get("paper"), {}) or {}).get("study_type") or ""
    return study in {"review", "meta_analysis"}


def already_asked(graph, ask_type, target):
    """Rounds already issued against this graph, matched on (verb, target).

    Re-asking is not harmless. It costs a round, returns the same evidence, and
    -- because `rounds` is the only record of what was tried -- makes the graph
    look like it was interrogated twice as hard as it was.
    """
    hits = []
    for r in graph.get("rounds", []):
        if r.get("ask") == ask_type and r.get("target") == target:
            hits.append(r)
    return hits


def check_ask(graph, ask):
    """Mechanical gates on one proposed ask. Returns (gates, unchecked).

    `gates` is a list of {gate, ok, detail}. `unchecked` names the judgment
    gates this function deliberately does not evaluate, so a caller cannot read
    an all-green result as approval.
    """
    idx = index(graph)
    gates = []

    def gate(name, ok, detail):
        gates.append({"gate": name, "ok": bool(ok), "detail": detail})

    ask_type = ask.get("ask")
    target = ask.get("target")
    question = (ask.get("question") or "").strip()

    gate(
        "ASK_TYPE_IS_ONE_OF_FOUR",
        ask_type in ASK_TYPES,
        f"{ask_type!r}; SCHEMA.md defines exactly {sorted(ASK_TYPES)}. "
        "Inventing a fifth verb makes the ask unconsumable upstream.",
    )

    if ask_type in ASK_TARGET_INDEX:
        want = ASK_TARGET_INDEX[ask_type]
        if want is None:
            gate(
                "TARGET_SHAPE",
                target is None,
                "new_question takes target: null -- it is the ask for a claim "
                f"the graph has no row for. Got {target!r}.",
            )
        else:
            gate(
                "TARGET_RESOLVES_TO_A_ROW",
                target in idx[want],
                f"{ask_type} must point at an id in `{want}`. "
                f"{target!r} {'resolves' if target in idx[want] else 'does NOT resolve'}. "
                "Pointing in prose instead of by id is how an ask becomes unroutable.",
            )
    else:
        gate("TARGET_RESOLVES_TO_A_ROW", False, "unknown ask type; target not checked")

    tokens = sorted(set(SOURCE_TOKEN.findall(question)))
    gate(
        "QUESTION_IS_ACTIONABLE",
        len(tokens) >= MIN_SOURCE_TOKENS,
        f"found {len(tokens)} source identifier(s) {tokens} in `question`; need "
        f"at least {MIN_SOURCE_TOKENS}. An ask must name the sources on BOTH "
        "sides and what would settle it, or the answering team reruns our search.",
    )

    prior = already_asked(graph, ask_type, target)
    gate(
        "NOT_ALREADY_ASKED",
        not prior,
        f"rounds already carries {len(prior)} ask(s) of {ask_type} at {target!r}"
        + (f" (round {prior[0].get('n')}, outcome {prior[0].get('outcome')!r})" if prior else ""),
    )

    coverage = graph.get("coverage", {}) or {}
    stop = coverage.get("stop_reason")
    gate(
        "LITERATURE_NOT_EXHAUSTED",
        stop != "complete",
        f"coverage.stop_reason is {stop!r}. Only 'complete' means the literature "
        "was exhausted; against a complete graph another round returns the same "
        "evidence, so the ask is noise.",
    )

    return gates, [
        "AFFECTS_THE_DOSSIER -- does this claim change a value in the template? "
        "An efficacy or clinical-outcome argument does not touch a tractability "
        "number (dossier rule 7) and fails this gate.",
        "SUPPORT_IS_SECONDARY_ONLY -- is every source a review, class table or "
        "citing paraphrase? A primary or mixed basis is never an ask.",
        "WE_TRIED_AND_FAILED -- were ChEMBL, the registry, the structure and a "
        "corpus grep on the exact identifiers all run and all silent, and is "
        "each null recorded in not_found BEFORE the ask was written?",
    ]


def ask_context(graph):
    """Per-link evidence for the ask-back decision. Evidence, not a verdict.

    Same discipline as `signals()`: every field here is a deterministic fact
    about the graph, and none of them decides. In particular
    `support_is_secondary_only` is necessary and nowhere near sufficient -- most
    secondary-only links are resolvable from ChEMBL or the registry in one
    query, and those must never become asks.
    """
    idx = index(graph)
    coverage = graph.get("coverage", {}) or {}
    stop = coverage.get("stop_reason")

    rows = []
    for link in idx["links"].values():
        fids = link_findings(link)
        findings = [idx["findings"][f] for f in fids if f in idx["findings"]]
        secondary = [f["id"] for f in findings if is_secondary(f, idx["papers"])]
        prior = already_asked(graph, "resolve_link", link["id"])
        rows.append({
            "link": link["id"],
            "relation": (
                f"{idx['things'].get(link.get('from'), {}).get('name')} "
                f"{link.get('how')} "
                f"{idx['things'].get(link.get('to'), {}).get('name')}"
            ),
            "basis": link.get("basis"),
            "n_findings": len(findings),
            "secondary_findings": secondary,
            "support_is_secondary_only": bool(findings) and len(secondary) == len(findings),
            "distinct_papers": sorted({f.get("paper") for f in findings if f.get("paper")}),
            "already_asked_rounds": [r.get("n") for r in prior],
            # The basis test comes FIRST and is the one that decides, exactly as
            # in step 3: the tier comes from the link's `basis`, never from the
            # findings' own properties. The two can disagree -- in the RA graph
            # L6 (IL-6 drives RA) is `basis: primary` while its only finding is
            # a meta-analysis, so `support_is_secondary_only` is true and the
            # basis is not. `basis` wins, L6 is not an ask, and the divergence
            # is worth reading rather than smoothing over.
            "mechanical_gates_clear": (
                link.get("basis") in NON_ACTIONABLE_BASIS
                and bool(findings)
                and len(secondary) == len(findings)
                and not prior
                and stop != "complete"
            ),
        })

    return {
        "graph_id": graph.get("graph_id"),
        "round": graph.get("round"),
        "stop_reason": stop,
        "literature_not_exhausted": stop != "complete",
        "asks_already_issued": [
            {"n": r.get("n"), "ask": r.get("ask"), "target": r.get("target"),
             "outcome": r.get("outcome")}
            for r in graph.get("rounds", [])
        ],
        "links": sorted(rows, key=lambda r: r["link"]),
        "_warning": (
            "mechanical_gates_clear is NOT permission to ask. It says only that "
            "the link is secondary-only, unasked, and against a non-exhausted "
            "graph. The three gates that matter -- does it affect the dossier, "
            "and did WE try ChEMBL / the registry / the structure first, and is "
            "each failed attempt recorded -- are not evaluated here and cannot "
            "be. See SKILL.md 'What must never become an ask'."
        ),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("graph", help="path to the upstream evidence graph JSON")
    ap.add_argument("--thing", help="restrict nominations to one thing id")
    ap.add_argument(
        "--allow-fixture",
        action="store_true",
        help="permit a graph carrying _fixture: true (test runs only)",
    )
    ap.add_argument(
        "--ask-context",
        action="store_true",
        help="per-link mechanical facts bearing on whether to ask back",
    )
    ap.add_argument(
        "--check-ask",
        metavar="JSON",
        help="gate one proposed ask; exits 1 if any mechanical gate fails",
    )
    args = ap.parse_args()

    with open(args.graph) as fh:
        graph = json.load(fh)

    if graph.get("_fixture") and not args.allow_fixture:
        sys.exit(
            "refusing: graph carries _fixture: true, so its papers and quotes are "
            "synthetic. Re-run with --allow-fixture for a test."
        )

    if args.check_ask:
        gates, unchecked = check_ask(graph, json.loads(args.check_ask))
        json.dump({"gates": gates, "not_checked_here": unchecked}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.exit(0 if all(g["ok"] for g in gates) else 1)

    if args.ask_context:
        json.dump(ask_context(graph), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    json.dump(build(graph, args.thing), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
