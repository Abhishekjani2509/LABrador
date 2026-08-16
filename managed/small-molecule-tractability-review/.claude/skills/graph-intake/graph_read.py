#!/usr/bin/env python3
"""Assemble the target-intake bundle from an upstream evidence graph.

Mechanical only. Graph traversal, edge classification, evidence tiering from
each link's `basis`, and — where the verb is unrecognised — an adjudication
packet carrying every deterministic signal the graph offers. Reading a mechanism
out of a quote is judgment and stays with the agent; see SKILL.md.

Also proposes gene-symbol candidates found inside thing names, because a real
upstream graph can carry its proteins only there. Those are PROPOSALS for
UniProt verification, never nominations.

Nothing here decides tractability, ranks targets, or picks an accession.

Usage:
    python3 graph_read.py <graph.json>
    python3 graph_read.py <graph.json> --thing t1
    python3 graph_read.py <graph.json> --allow-fixture
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

# --- Second nomination route: symbols buried in entity names -----------------
#
# The kind-based route needs a `protein` or `gene` node. A real upstream graph
# may have none: "IRAK4 inhibition" is typed `small_molecule` because it names an
# intervention, and the protein exists only as a substring of that name.
#
# This route PROPOSES ONLY. A regex cannot know that a token is a gene, so every
# symbol below is emitted for verification against uniprot_v.proteins (SKILL.md
# step 4) and nothing here enters `nominations`. The script stays stdlib-only and
# offline by construction -- it must not call paperclip.

# One token, 2-10 chars, alphanumeric with internal hyphens.
SYMBOL_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*$")

# Compound codes are symbol-shaped (ST2825, PF-06650833, KIC-0101). No human gene
# symbol carries a run of four digits, so that run separates the two.
COMPOUND_CODE = re.compile(r"\d{4,}")

# Separators that join DISTINCT symbols. Hyphen is NOT one of them: NF-kB, IL-6
# and IRAK-4 are single symbols that happen to carry a hyphen.
SYMBOL_SEPARATORS = re.compile(r"[/,+&]")

TRIM = " \t\"'()[]{}.,;:!?"

# The action word sitting next to a symbol seeds `interaction_to_disrupt`:
# "MyD88 dimerization inhibition" implies disrupting a dimerization interface,
# "IRAK4 inhibition" implies catalytic function. Carried verbatim -- turning it
# into a mechanism is the agent's call, not this script's.
ACTION_WORDS = {
    "inhibition", "inhibitor", "inhibitors", "inhibiting", "inhibited",
    "blockade", "blocking", "blocker", "block",
    "knockdown", "knockout", "silencing", "depletion", "ablation", "deletion",
    "degradation", "degrader", "degrading",
    "agonism", "agonist", "antagonism", "antagonist",
    "dimerization", "dimerisation", "oligomerization", "oligomerisation",
    "activation", "activator", "stabilization", "stabilisation",
    "engagement", "occupancy", "disruption", "suppression", "modulation",
    "deficiency", "loss",
}

# Stop-list: symbol-SHAPED tokens that are never gene symbols -- disease and
# tissue abbreviations, cell lines, reagents, assays, clinical endpoints, plus
# the action vocabulary itself. Matched case-insensitively, so an extractor that
# writes AXIS or SIGNALLING in caps still proposes nothing.
#
# Deliberately NOT here: TNF, TLR, IL-6 and friends. They are real symbols; the
# UniProt lookup, not this set, decides whether they resolve.
NOT_SYMBOLS = {
    "ra", "oa", "sle", "ibd", "copd", "gvhd", "as", "ms", "cd",
    "acr20", "acr50", "acr70", "das28", "pasi", "sdai", "cdai", "rct",
    "fls", "sf", "sfs", "pbmc", "pbmcs", "thp1", "thp", "hek", "hek293",
    "hela", "jurkat", "u937", "k562", "cho", "mcf7", "a549", "raw264",
    "bmdm", "huvec", "ipsc",
    "lps", "pma", "cfa", "atp", "adp", "gtp", "dmso", "pbs", "fbs",
    "dna", "rna", "mrna", "sirna", "shrna", "crispr", "cas9",
    "ic50", "ec50", "kd", "ki", "elisa", "facs", "pcr", "qpcr", "nmr",
    "hplc", "lcms", "msd", "spr", "itc", "auc", "cmax",
    "wt", "ko", "usa", "uk", "eu", "fda", "ema", "nih",
    "axis", "pathway", "signalling", "signaling", "inflammation", "disease",
    "protein", "kinase", "receptor", "complex", "cells", "cell",
}
NOT_SYMBOLS |= ACTION_WORDS


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


def symbol_shaped(token):
    """Shape test only. Says nothing about whether the token names a gene."""
    if not (2 <= len(token) <= 10):
        return False
    if not SYMBOL_SHAPE.match(token):
        return False
    if COMPOUND_CODE.search(token):
        return False
    # Two capitals is the floor. One is ordinary prose capitalisation (Rho,
    # Toll-like, Matrigel); symbols carry their case (MyD88, NF-kB, IRAK4).
    if sum(1 for c in token if c.isupper()) < 2:
        return False
    return token.lower() not in NOT_SYMBOLS


def symbol_key(symbol):
    """Dedupe key only. IRAK-4 and IRAK4 are one candidate; the spelling the
    extractor used is kept verbatim on every mention."""
    return symbol.upper().replace("-", "")


def query_forms(symbol):
    """Spellings to put in the SQL `IN` list, in order. Not a rewrite of the
    symbol -- each form is a separate lookup that may return nothing."""
    forms = []
    for form in (symbol, symbol.upper(), symbol.upper().replace("-", "")):
        if form not in forms:
            forms.append(form)
    return forms


def action_near(tokens, i):
    """The action word adjacent to tokens[i], as (text, position).

    Suffix first ("MyD88 dimerization inhibition"), then prefix, optionally
    across "of" ("knockdown of MYD88"). Contiguous runs only, so an action word
    elsewhere in the phrase is not attached to this symbol.
    """
    after = []
    j = i + 1
    while j < len(tokens) and tokens[j].strip(TRIM).lower() in ACTION_WORDS:
        after.append(tokens[j].strip(TRIM))
        j += 1
    if after:
        return " ".join(after), "suffix"

    j = i - 1
    if j >= 0 and tokens[j].strip(TRIM).lower() == "of":
        j -= 1
    before = []
    while j >= 0 and tokens[j].strip(TRIM).lower() in ACTION_WORDS:
        before.insert(0, tokens[j].strip(TRIM))
        j -= 1
    if before:
        return " ".join(before), "prefix"
    return None, None


def scan_phrase(phrase):
    """Every symbol in one verbatim string, with its adjacent action word.

    A multi-symbol phrase returns EVERY symbol. "TLR/MyD88/NF-kB signalling
    axis" is three candidates; collapsing it to one is the failure this route
    exists to avoid.
    """
    tokens = phrase.split()
    hits, seen = [], set()
    for i, token in enumerate(tokens):
        for part in SYMBOL_SEPARATORS.split(token):
            part = part.strip(TRIM)
            if not symbol_shaped(part) or symbol_key(part) in seen:
                continue
            seen.add(symbol_key(part))
            action, position = action_near(tokens, i)
            hits.append({"symbol": part, "action": action,
                         "action_position": position})

    spellings = [h["symbol"] for h in hits]
    for hit in hits:
        hit["co_occurring_symbols"] = [
            s for s in spellings if symbol_key(s) != symbol_key(hit["symbol"])
        ]
    return hits


def thing_symbols(thing):
    """Scan `name` and every alias, whatever the thing's `kind`. Kind is exactly
    what this route cannot trust -- the target may be typed small_molecule."""
    fields = [("name", thing.get("name"))]
    fields += [("aliases[%d]" % n, a)
               for n, a in enumerate(thing.get("aliases") or [])]

    found, order = {}, []
    for field, phrase in fields:
        if not phrase:
            continue
        for hit in scan_phrase(phrase):
            mention = {
                "as_written": hit["symbol"],
                "field": field,
                # Whole-field means the extractor gave the symbol; parsed-out
                # means this regex inferred it from a longer phrase.
                "whole_field": hit["symbol"] == phrase.strip(TRIM),
                "phrase": phrase,
                "action": hit["action"],
                "action_position": hit["action_position"],
                "co_occurring_symbols": hit["co_occurring_symbols"],
            }
            key = symbol_key(hit["symbol"])
            if key not in found:
                found[key] = {"symbol": hit["symbol"], "mentions": []}
                order.append(key)
            found[key]["mentions"].append(mention)
    return [found[k] for k in order]


def symbol_candidates(idx, nominated_ids, only=None):
    """Symbols proposed from entity names, for UniProt verification.

    Never a nomination and never asserted. A candidate that resolves to no row
    is the lookup answering -- "NF-kB" names a complex, not a gene, so it is
    EXPECTED to fail and that failure is the result, not an error.
    """
    candidates = []
    for thing in idx["things"].values():
        if only and thing["id"] != only:
            continue
        for entry in thing_symbols(thing):
            mentions = entry["mentions"]
            # An action word is the point of this route, so a mention carrying
            # one leads even if a bare mention came first.
            lead = next((m for m in mentions if m["action"]), mentions[0])
            co = []
            for m in mentions:
                for s in m["co_occurring_symbols"]:
                    if symbol_key(s) not in {symbol_key(x) for x in co}:
                        co.append(s)
            candidates.append({
                "symbol": entry["symbol"],
                "query_forms": query_forms(entry["symbol"]),
                "action": lead["action"],
                "action_position": lead["action_position"],
                "thing": thing["id"],
                "thing_kind": thing.get("kind"),
                "thing_name": thing.get("name"),
                "already_nominated": thing["id"] in nominated_ids,
                "field": lead["field"],
                "whole_field": lead["whole_field"],
                "phrase": lead["phrase"],
                # True whenever the symbol shared a phrase with another symbol.
                # The agent resolves which one the dossier is about; picking one
                # here would be a guess.
                "ambiguous": bool(co),
                "co_occurring_symbols": co,
                "other_mentions": [m for m in mentions if m is not lead],
                # Filled by the agent from the SQL. Left null on purpose.
                "verified": None,
                "uniprot_accession": None,
            })

    return {
        "note": (
            "PROPOSED, NOT CONFIRMED. Regex over thing `name` and `aliases`, run "
            "because a graph can carry its proteins only inside intervention "
            "names -- 'IRAK4 inhibition' is typed small_molecule. Nothing here is "
            "a nomination. Verify every symbol against uniprot_v.proteins before "
            "using it; a symbol naming a complex rather than a gene (NF-kB) is "
            "expected to return no row, and that is the answer, not a failure."
        ),
        "verify_with": (
            "SELECT accession, gene_name, protein_name, organism, sequence_length "
            "FROM uniprot_v.proteins WHERE gene_name IN (<query_forms>) "
            "AND organism = 'Homo sapiens'"
        ),
        "ambiguous_things": sorted({c["thing"] for c in candidates
                                    if c["ambiguous"]}),
        "candidates": candidates,
    }


def build(graph, only=None):
    idx = index(graph)
    things = idx["things"]
    nominated, rejected, adjudicate = nominate(graph, idx)
    # Captured before the --thing filter: `already_nominated` reports the graph,
    # not the slice being printed.
    nominated_ids = set(nominated)

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

    # `links` summarises `findings`, but nothing guarantees every finding is
    # summarised BY one. On the real g_1a4f, f6 is referenced by no link and is
    # also the graph's only is_own_result: false row -- so a link-walking intake
    # sees 11 of 12 findings and never sees the one background-flavoured item.
    linked = set()
    for l in idx["links"].values():
        for arr in ("yes", "no", "no_effect"):
            linked |= set(l.get(arr) or [])
    orphans = [
        {
            "finding": f["id"],
            "relation": f"{things.get(f.get('from'), {}).get('name')} "
                        f"{f.get('how')} {things.get(f.get('to'), {}).get('name')}",
            "says": f.get("says"),
            "quote": f.get("quote"),
            "is_own_result": f.get("is_own_result"),
            "why": "referenced by no link -- invisible to link traversal, read it directly",
        }
        for fid, f in idx["findings"].items() if fid not in linked
    ]

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
        "orphan_findings": orphans,
        "nominations": out,
        "rejected": [
            {"thing": tid, "name": things.get(tid, {}).get("name"), "why": why}
            for tid, why in sorted(rejected.items())
        ],
        "needs_adjudication": adjudicate,
        # Second route. Independent of `nominations` -- it neither adds to nor
        # subtracts from them, and a graph with entity nodes still nominates on
        # kind exactly as before.
        "symbol_candidates": symbol_candidates(idx, nominated_ids, only),
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
    args = ap.parse_args()

    with open(args.graph) as fh:
        graph = json.load(fh)

    if graph.get("_fixture") and not args.allow_fixture:
        sys.exit(
            "refusing: graph carries _fixture: true, so its papers and quotes are "
            "synthetic. Re-run with --allow-fixture for a test."
        )

    json.dump(build(graph, args.thing), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
