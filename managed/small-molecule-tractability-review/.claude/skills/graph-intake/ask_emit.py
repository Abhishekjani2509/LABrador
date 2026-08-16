#!/usr/bin/env python3
"""Turn a graph_read.py intake bundle into the follow-up asks it implies.

The other half of the loop. graph_read.py says what is missing; this decides
which of SCHEMA.md's four verbs would fill it, in what order, and writes each
one as a Request object.

THERE IS NO TRANSPORT. The mapper is not deployed and no MCP endpoint exists,
so nothing here can SEND an ask -- it emits the request and stops. Whoever runs
it delivers the `next` request by hand and re-runs against the reply. No network
code belongs in this file.

One ask per request, one round per request (SCHEMA.md). So the output is a
PRIORITY ORDER with exactly one entry marked `next`, never a batch. Emitting the
whole list at once is a protocol violation regardless of how good the asks are.

Refuses to emit at all when asking cannot help: `status: failed` means the
search was unavailable, and `coverage.stop_reason: complete` means the
literature was exhausted. Both get a stated refusal instead of a request.

graph_read.py's stdout does not carry `links`, `gaps` or `rounds`, and three of
the six rules need them. Pass the source graph with --graph (or pipe a raw graph
in) to evaluate those; without it they are reported under `not_evaluated` rather
than silently skipped.

Usage:
    python3 ask_emit.py <intake.json>
    python3 ask_emit.py -                       # graph_read.py stdout on stdin
    python3 ask_emit.py <intake.json> --graph <graph.json>
    python3 ask_emit.py <intake.json> --explain
"""

import argparse
import json
import os
import re
import sys

# SCHEMA.md Request: the four verbs and the four depth tiers. Closed enums --
# unlike `how`, both carry an explicit a|b|c comment in the schema.
ASKS = {"expand_node", "resolve_link", "test_gap", "new_question"}
DEPTHS = ["quick", "standard", "deep", "exhaustive"]

# SCHEMA.md note 2: `quick` reads page 1 and page 1 lies, so absence at `quick`
# means nothing. Every ask here exists to settle something the graph left
# unstated, which is exactly the claim `quick` cannot support.
DEFAULT_DEPTH = "deep"

# Exactly the five keys SCHEMA.md's Request block defines. Anything else makes
# the object invalid, including SKILL.md's `question` field -- SKILL.md's table
# shows new_question carrying `target: null` plus a separate `question`, but
# SCHEMA.md is the contract and it says `target` IS the free text. Follow SCHEMA.
REQUEST_KEYS = {"graph_id", "ask", "target", "depth", "reason"}

# A `kind` that gives a thing its own entity node. A symbol sitting on a thing of
# one of these kinds is that node; a symbol sitting on a small_molecule or
# process node has no node of its own, which is what expand_node is for.
ENTITY_KINDS = {"protein", "gene"}

# SKILL.md step 3: both tiers produce a confident-looking answer from evidence
# that asserted nothing. Record, do not act on, and ask for primary evidence.
NON_ACTIONABLE_BASIS = {"background_only", "hedged_only"}

# Action words that NAME the interaction rather than merely stating intent to
# stop it. "MyD88 dimerization inhibition" says what to disrupt; "IRAK4
# inhibition" does not. A target carrying one already has half a mechanism, so
# its information deficit is smaller and it ranks below one that does not.
INTERACTION_ACTIONS = {
    "dimerization", "dimerisation", "oligomerization", "oligomerisation",
    "engagement", "occupancy", "disruption",
}

# Vocabulary of a measurement made ON the target, as opposed to a readout
# downstream of it. Read from quote text, because SCHEMA.md guarantees the quote
# verbatim and guarantees nothing else in the packet.
MECHANISM_TERMS = [
    "ic50", "ec50", "ki", "kd", "affinity", "binds", "binding",
    "target engagement", "occupancy", "kinase activity", "enzymatic activity",
    "catalytic", "co-crystal", "cocrystal", "biochemical", "cell free",
    "displacement", "atp competitive", "allosteric", "active site",
]

# Compound codes carry a run of four digits; no human gene symbol does. Same
# split graph_read.py uses, reused here to pull PF-06650833 and KIC-0101 out of
# an alias list so a new_question can name the compounds it is asking about.
COMPOUND_CODE = re.compile(r"\d{4,}")

NS_WORD = re.compile(r"[^a-z0-9]+")

# Priority bands. Lower emits first. The order is the graph's own economics: a
# missing entity node blocks every later ask, a weak basis silently drives a
# hard output, a disagreement is at least visible, and a gap is the cheapest
# thing to be wrong about.
BAND_MISSING_NODE = 1
BAND_WEAK_BASIS = 2
BAND_DISAGREED = 3
BAND_ADJUDICATE = 4
BAND_NO_MECHANISM = 5
BAND_UNTESTED_GAP = 6


def load(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path) as fh:
        return json.load(fh)


def split_input(payload, graph):
    """Separate the intake bundle from the graph-level lists.

    Either may arrive on stdin: graph_read.py stdout is an intake bundle, and a
    raw graph piped straight in carries things/links/gaps. --graph supplies the
    graph alongside an intake bundle. Whatever is absent stays absent -- the
    rules that need it report themselves as not evaluated.
    """
    intake = payload if ("nominations" in payload or "symbol_candidates" in payload) else {}
    rows = {}
    for source in (payload, graph or {}):
        for key in ("things", "links", "gaps", "rounds", "coverage", "status",
                    "_resolved_ask_targets"):
            if source.get(key) is not None and key not in rows:
                rows[key] = source[key]
    return intake, rows


def has_term(text, terms):
    """Whole-word match over a non-alphanumeric-normalised string. `ki` and `kd`
    are two letters and would match inside any word without the padding."""
    if not text:
        return []
    padded = " " + NS_WORD.sub(" ", text.lower()) + " "
    return [t for t in terms if (" " + t + " ") in padded]


def stop_reason(intake, rows):
    """The one coverage field that licenses a refusal.

    graph_read.py only emits `coverage_warning` when the run was truncated or
    stopped for a non-`complete` reason, so a missing warning does NOT prove
    `complete` -- it is equally consistent with an absent field. Report unknown
    rather than inferring.
    """
    warning = (intake.get("coverage_warning") or {})
    if warning.get("stop_reason"):
        return warning["stop_reason"]
    return (rows.get("coverage") or {}).get("stop_reason")


def refusal(intake, rows):
    """Why asking would be pointless, or None."""
    status = intake.get("status") or rows.get("status")
    reason = stop_reason(intake, rows)
    if status == "failed" or reason == "search_unavailable":
        return (
            f"status is '{status}' -- SCHEMA.md note 7: `failed` means the search "
            f"was unavailable, not that the literature is silent. A new ask goes to "
            f"the same unavailable search and comes back the same way. Fix the "
            f"search, then re-run the intake."
        )
    if reason == "complete":
        return (
            "coverage.stop_reason is 'complete' -- the only one of the six that "
            "means the literature was exhausted rather than the budget. There is "
            "nothing left to retrieve, so every gap below is an absence in the "
            "literature and not a hole in this run. Report the absence; do not "
            "spend a round re-confirming it."
        )
    return None


def readout_things(intake):
    """Things the intake rejected ONLY as downstream readouts.

    Failure mode 2: a readout looks exactly like a target. Expanding one spends a
    round pulling more evidence about where the effect was measured, which is not
    what the dossier needs an accession for.
    """
    out = set()
    for row in intake.get("rejected", []):
        why = row.get("why") or []
        if why and all("readout, not target" in w for w in why):
            out.add(row["thing"])
    return out


def pursued(intake):
    """Targets this intake is actually chasing, with why each one qualifies.

    Two routes, matching the two nomination routes in graph_read.py: an entity
    node that was nominated, and a symbol recovered from a thing's name. The
    second route admits a candidate only when

      - the thing is not already nominated, and
      - the thing's own kind is not protein/gene, so the symbol has no node, and
      - an action word sits beside the symbol, which is what makes the node a
        manipulation OF the protein rather than a passing mention of it, and
      - the symbol did not share its phrase with another symbol, and
      - the thing was not rejected as a pure readout.

    The ambiguity rule is the load-bearing one. expand_node searches a thing's
    `name` + `aliases`; for "TLR/MyD88/NF-kB signalling axis" that string is the
    pathway, so the ask returns the pathway again at the same granularity. Same
    refusal as SKILL.md failure mode 7, one verb over.
    """
    targets, withheld = {}, []

    for nom in intake.get("nominations", []):
        targets[nom["thing"]] = {
            "thing": nom["thing"],
            "name": nom.get("name"),
            "symbol": nom.get("gene_symbol"),
            "action": None,
            "route": "nominated entity node",
            "needs_node": False,
        }

    readouts = readout_things(intake)
    for cand in (intake.get("symbol_candidates") or {}).get("candidates", []):
        tid, symbol = cand["thing"], cand["symbol"]
        if cand.get("already_nominated"):
            continue
        if cand.get("thing_kind") in ENTITY_KINDS:
            withheld.append({
                "ask": "expand_node", "target": tid,
                "why": f"{symbol} sits on a thing already typed "
                       f"'{cand.get('thing_kind')}' -- it has an entity node of its "
                       f"own, so there is nothing for expand_node to create.",
            })
            continue
        if tid in readouts:
            withheld.append({
                "ask": "expand_node", "target": tid,
                "why": f"{symbol} sits on {tid} ('{cand.get('thing_name')}'), which "
                       f"the intake rejected as a downstream readout. Expanding it "
                       f"returns more evidence about where the effect was measured, "
                       f"not what it acts on -- failure mode 2.",
            })
            continue
        # Ambiguity is checked before the action word because it is the more
        # informative refusal: a phrase carrying three symbols cannot be asked
        # about at all, whether or not one of them has an action beside it.
        if cand.get("ambiguous"):
            withheld.append({
                "ask": "expand_node", "target": tid,
                "why": f"{symbol} shares its phrase with "
                       f"{', '.join(cand.get('co_occurring_symbols') or [])} in "
                       f"'{cand.get('phrase')}'. expand_node searches the thing's "
                       f"name and aliases, which is that same phrase, so the reply "
                       f"comes back at the pathway granularity we are trying to "
                       f"leave. Decompose it before asking.",
            })
            continue
        if not cand.get("action"):
            withheld.append({
                "ask": "expand_node", "target": tid,
                "why": f"{symbol} appears in {tid} ('{cand.get('thing_name')}') with "
                       f"no action word beside it. The node mentions the protein; it "
                       f"does not name a manipulation of it, so the symbol is a "
                       f"passing reference and not a target proposal.",
            })
            continue
        targets.setdefault(tid, {
            "thing": tid,
            "name": cand.get("thing_name"),
            "symbol": symbol,
            "action": cand.get("action"),
            "route": f"symbol '{symbol}' recovered from {cand.get('field')}",
            "needs_node": True,
        })

    return targets, withheld


def visible_links(intake, rows):
    """Every link this run can see, keyed by id.

    Full when the graph is supplied. Without it, only the links a nomination's
    evidence or an adjudication packet happened to name -- which is why the
    disagreed-state rule reports itself unevaluated on a graph that nominated
    nothing.
    """
    links = {}
    for link in rows.get("links") or []:
        links[link["id"]] = dict(link)
    if links:
        return links, True

    for nom in intake.get("nominations", []):
        for tier in (nom.get("evidence") or {}).values():
            for row in tier:
                links.setdefault(row["link"], {
                    "id": row["link"], "basis": row.get("link_basis"),
                    "state": row.get("link_state"),
                })
    for entry in intake.get("needs_adjudication", []):
        links.setdefault(entry["link"], {
            "id": entry["link"], "basis": None, "state": None,
            "from": (entry.get("subject") or {}).get("id"),
            "to": (entry.get("object") or {}).get("id"),
        })
    return links, False


def quotes_for(tid, intake, rows):
    """Quote text attributable to one thing, for the mechanism test."""
    texts = []
    for nom in intake.get("nominations", []):
        if nom["thing"] != tid:
            continue
        for tier in (nom.get("evidence") or {}).values():
            texts += [r.get("quote") or "" for r in tier]

    links = [l for l in (rows.get("links") or [])
             if tid in (l.get("from"), l.get("to"))]
    if links:
        wanted = set()
        for link in links:
            for arr in ("yes", "no", "no_effect"):
                wanted |= set(link.get(arr) or [])
        texts += [f.get("quote") or "" for f in (rows.get("findings") or [])
                  if f.get("id") in wanted]
    return " ".join(texts)


def resolved_targets(intake, rows):
    """Ids it is pointless to ask about again.

    Two sources. graph_store.py computes `_resolved_ask_targets` when it
    reassembles from the store. When the graph came from a flat file instead,
    recompute the same thing: a rounds[] target that no longer appears in
    gaps[], links[] or things[] was consumed by the ask that resolved it. On
    g_1a4f that is g3 -- round 2 tested it, it came back contradicted, and it is
    gone from gaps[]. Re-asking spends a round re-deriving an answer already in
    the graph as L3's disagreement.
    """
    out = {}
    for row in rows.get("_resolved_ask_targets") or []:
        out[row["target"]] = (
            f"round {row.get('round')} already asked {row.get('ask')} on it "
            f"(outcome '{row.get('outcome')}') and it is no longer a live row"
        )

    known = set()
    for key in ("gaps", "links", "things"):
        known |= {r["id"] for r in (rows.get(key) or [])}
    if known:
        for rnd in rows.get("rounds") or []:
            target = rnd.get("target")
            if target and target not in known:
                out.setdefault(target, (
                    f"round {rnd.get('n')} asked {rnd.get('ask')} on it (outcome "
                    f"'{rnd.get('outcome')}') and it is absent from gaps[], links[] "
                    f"and things[] -- already resolved away"
                ))
    return out


def spent_depth(rows):
    """Deepest tier already spent on each (ask, target) pair.

    SCHEMA.md note 8: re-asking the same target at the same depth returns the
    cached result without spending, so a repeat has to escalate or it is a
    no-op dressed as a round.
    """
    spent = {}
    for rnd in rows.get("rounds") or []:
        key = (rnd.get("ask"), rnd.get("target"))
        depth = rnd.get("depth")
        if depth in DEPTHS:
            spent[key] = max(spent.get(key, -1), DEPTHS.index(depth))
    return spent


def escalate(ask, target, spent):
    """Depth for this request, and the note explaining a non-default one."""
    prior = spent.get((ask, target))
    if prior is None:
        return DEFAULT_DEPTH, None
    if prior >= len(DEPTHS) - 1:
        return DEPTHS[-1], (
            f"already asked at '{DEPTHS[-1]}', the deepest tier -- a repeat returns "
            f"the cached result and buys nothing"
        )
    return DEPTHS[prior + 1], (
        f"escalated from '{DEPTHS[prior]}', which a previous round already spent on "
        f"this exact target; SCHEMA.md note 8 says a same-depth repeat is served "
        f"from cache"
    )


def compounds_on(tid, rows):
    """Compound codes folded into a thing's aliases, so a question can name them."""
    for thing in rows.get("things") or []:
        if thing.get("id") == tid:
            return [a for a in (thing.get("aliases") or []) if COMPOUND_CODE.search(a)]
    return []


def question_for(targets, rows):
    """A specific question, built from the targets that have no mechanism.

    Specific means: it names the symbol, the measurement that would settle it,
    and the alternative the answer has to choose between. "What is the mechanism
    of IRAK4?" is a vague question and buys a review.
    """
    symbols = [t["symbol"] or t["name"] for t in targets]
    named = " or ".join(symbols)
    compounds = []
    for t in targets:
        compounds += compounds_on(t["thing"], rows)
    against = f" for {' or '.join(compounds)}" if compounds else ""
    ids = ", ".join(f"{t['thing']} ('{t['name']}')" for t in targets)
    return (
        f"Is a direct target-engagement or biochemical measurement -- IC50, Kd, or "
        f"occupancy in a cell-free or purified system -- against {named} reported"
        f"{against}, and does the observed cellular effect require {named} catalytic "
        f"activity or its scaffolding role? Every finding visible on {ids} is a "
        f"cellular or downstream readout, so nothing states what is engaged."
    )


def collect(intake, rows):
    """Every ask the intake implies, banded but not yet ranked or validated."""
    graph_id = intake.get("graph_id") or rows.get("graph_id")
    targets, withheld = pursued(intake)
    links, links_complete = visible_links(intake, rows)
    notes = []
    proposed = []

    # --- band 1: the protein has no node of its own -------------------------
    for tid, target in sorted(targets.items()):
        if not target["needs_node"]:
            continue
        # A bare-intent action ("inhibition") states only that somebody stopped
        # the protein. An interaction-naming one ("dimerization inhibition")
        # already says what to disrupt, so that target is missing less.
        bare = (target["action"] or "").lower().split()[0] not in INTERACTION_ACTIONS
        proposed.append({
            "band": BAND_MISSING_NODE,
            "within": (0 if bare else 1, tid),
            "rule": "symbol_candidates entry on a thing with no entity node",
            "ask": "expand_node",
            "target": tid,
            "reason": (
                f"{target['symbol']} exists in this graph only inside {tid} "
                f"('{target['name']}', kind not protein/gene) -- there is no node of "
                f"its own to carry an accession, and the action word beside it is "
                f"'{target['action']}'"
                + ("" if bare else ", which names the interaction but not the site")
                + ". Unblocks: whether "
                f"{target['symbol']} can be nominated as a target at all, and what "
                f"the dossier should set interaction_to_disrupt to."
            ),
        })

    # --- band 2: the supporting evidence never asserted anything ------------
    for lid, link in sorted(links.items()):
        if link.get("basis") in NON_ACTIONABLE_BASIS:
            proposed.append({
                "band": BAND_WEAK_BASIS,
                "within": (0, lid),
                "rule": f"nomination supported only by basis '{link['basis']}'",
                "ask": "resolve_link",
                "target": lid,
                "reason": (
                    f"{lid} is basis '{link['basis']}', so every finding under it "
                    f"either restated someone else's work or said 'may'. SKILL.md "
                    f"step 3: record it, do not act on it. Unblocks: whether this "
                    f"relationship can set interaction_to_disrupt -- and therefore "
                    f"which chains get scored -- before a dossier run is spent on it."
                ),
            })

    # --- band 3: primary evidence that disagrees with itself ----------------
    for lid, link in sorted(links.items()):
        if any(p["target"] == lid for p in proposed):
            continue
        if link.get("state") == "disagreed":
            why = link.get("why")
            proposed.append({
                "band": BAND_DISAGREED,
                "within": (0, lid),
                "rule": "link state is 'disagreed'",
                "ask": "resolve_link",
                "target": lid,
                "reason": (
                    f"{lid} is state 'disagreed'"
                    + (f" ({why})" if why else "")
                    + f". Basis is '{link.get('basis')}', so this is a conflict "
                    f"between real results rather than a weak-evidence problem, "
                    f"which makes it a stronger reason to ask, not a weaker one. "
                    f"Unblocks: which side of the conflict the dossier's target "
                    f"nomination rests on."
                ),
            })

    # --- band 4: the verb could not be classified ---------------------------
    for entry in intake.get("needs_adjudication", []):
        lid = entry["link"]
        if any(p["target"] == lid for p in proposed):
            continue
        proposed.append({
            "band": BAND_ADJUDICATE,
            "within": (0, lid),
            "rule": "link in needs_adjudication",
            "ask": "resolve_link",
            "target": lid,
            "reason": (
                f"{lid} uses verb '{entry.get('how')}', which is in neither verb set "
                f"-- `how` has no enum in SCHEMA.md, so the intake could not tell a "
                f"direct action on "
                f"{(entry.get('object') or {}).get('name')} from a downstream effect "
                f"on it. Refusing is allowed; guessing is not, and more evidence is "
                f"the way out. Unblocks: whether "
                f"{(entry.get('object') or {}).get('id')} is a target or a readout."
            ),
        })

    # --- band 5: nothing states what is engaged -----------------------------
    unstated = []
    for tid, target in sorted(targets.items()):
        action = (target["action"] or "").lower().split()
        if action and action[0] in INTERACTION_ACTIONS:
            continue
        if has_term(quotes_for(tid, intake, rows), MECHANISM_TERMS):
            continue
        unstated.append(target)
    if unstated:
        proposed.append({
            "band": BAND_NO_MECHANISM,
            "within": (0, ""),
            "rule": "no visible quote states what is engaged",
            "ask": "new_question",
            "target": question_for(unstated, rows),
            "reason": (
                "Not one quote reachable from this graph measures anything on "
                + ", ".join(t["symbol"] or t["name"] for t in unstated)
                + " itself; every finding is a cellular or downstream readout. "
                "SKILL.md step 3: mechanism absent entirely -> new_question. "
                "Unblocks: interaction_to_disrupt, which is null without it, and "
                "which decides chain selection and therefore the druggability "
                "number. Note this returns a NEW graph_id at round 1 -- it is the "
                "only ask that does not extend the graph in place."
            ),
        })

    # --- band 6: a gap nobody has looked for --------------------------------
    if rows.get("gaps") is not None:
        for gap in rows["gaps"]:
            if gap.get("searched_in_round") is not None:
                continue
            hit = sorted(set(gap.get("missing") or []) & set(targets))
            if not hit:
                continue
            proposed.append({
                "band": BAND_UNTESTED_GAP,
                "within": (0, gap["id"]),
                "rule": "gap names a pursued target and searched_in_round is null",
                "ask": "test_gap",
                "target": gap["id"],
                "reason": (
                    f"{gap['id']} names {' and '.join(hit)} and searched_in_round is "
                    f"null, so nobody has looked -- a pair that was searched for and "
                    f"not found is a far stronger claim than one nobody searched. "
                    f"Ranked last because both endpoints are the intervention-level "
                    f"nodes, so the answer returns at the same granularity; "
                    f"expand_node fixes the granularity first."
                ),
            })
    else:
        notes.append(
            "test_gap not evaluated: gaps[] is not in a graph_read.py bundle. Pass "
            "--graph, or pipe the graph itself, to check for untested gaps."
        )

    if not links_complete:
        notes.append(
            "resolve_link evaluated only over links named in nominations[].evidence "
            "and needs_adjudication -- links[] is not in a graph_read.py bundle, so "
            "a 'disagreed' or background_only link touching nothing nominated is "
            "invisible here. Pass --graph to check all of them."
        )
    if rows.get("rounds") is None:
        notes.append(
            "depth escalation not evaluated: rounds[] is not in a graph_read.py "
            "bundle, so a target already asked at this depth would be re-asked and "
            "served from cache. Pass --graph."
        )
    if stop_reason(intake, rows) is None:
        notes.append(
            "coverage.stop_reason unreadable: graph_read.py emits coverage_warning "
            "only when the run was truncated or stopped for a non-'complete' "
            "reason, so its absence does not prove the literature was exhausted. "
            "The refusal check could not run."
        )

    return graph_id, proposed, withheld, notes


def validate(request):
    """Problems with a Request per SCHEMA.md, empty when it is valid."""
    problems = []
    extra = sorted(set(request) - REQUEST_KEYS)
    if extra:
        problems.append(f"keys not in the Request contract: {extra}")
    if request.get("ask") not in ASKS:
        problems.append(f"ask '{request.get('ask')}' is not one of {sorted(ASKS)}")
    if request.get("depth") not in DEPTHS:
        problems.append(f"depth '{request.get('depth')}' is not one of {DEPTHS}")
    if not isinstance(request.get("reason"), str) or not request["reason"].strip():
        problems.append("reason is empty -- it is logged for a human, not dropped")
    target = request.get("target")
    if not isinstance(target, str) or not target.strip():
        problems.append("target must be a row id, or free text for new_question")
    if request.get("ask") == "new_question":
        if "graph_id" in request:
            problems.append("new_question must omit graph_id -- it returns a new one")
    else:
        if not request.get("graph_id"):
            problems.append("graph_id is required for every ask but new_question")
    return problems


def emit(intake, rows):
    refuse = refusal(intake, rows)
    graph_id, proposed, withheld, notes = collect(intake, rows)
    out = {
        "graph_id": graph_id,
        "round": intake.get("round") or rows.get("round"),
        "status": intake.get("status") or rows.get("status"),
        "refused": bool(refuse),
        "refusal": refuse,
        "next": None,
        "asks": [],
        "withheld": withheld,
        "not_evaluated": notes,
        "protocol": (
            "One ask per request, one round per request (SCHEMA.md). `asks` is a "
            "priority order, NOT a batch -- send `next`, wait for the full graph "
            "back, then re-run the intake and this emitter against it. The ranking "
            "below is only valid for this graph_id and round."
        ),
        "transport": (
            "none. The mapper is not deployed and no MCP endpoint exists, so this "
            "emits the request and does not deliver it. Send `next` by hand."
        ),
    }
    if refuse:
        # Asking is pointless, so nothing is emitted -- including the asks that
        # would otherwise rank. Saying so is the output.
        out["withheld"] = withheld + [
            {"ask": p["ask"], "target": p["target"], "why": refuse} for p in proposed
        ]
        return out

    resolved = resolved_targets(intake, rows)
    spent = spent_depth(rows)
    rank = 0
    for item in sorted(proposed, key=lambda p: (p["band"], p["within"])):
        if item["target"] in resolved:
            out["withheld"].append({
                "ask": item["ask"], "target": item["target"],
                "why": f"already resolved: {resolved[item['target']]}",
            })
            continue
        depth, note = escalate(item["ask"], item["target"], spent)
        request = {
            "ask": item["ask"],
            "target": item["target"],
            "depth": depth,
            "reason": item["reason"] + (f" Depth: {note}." if note else ""),
        }
        if item["ask"] != "new_question":
            request = dict({"graph_id": graph_id}, **request)
        problems = validate(request)
        if problems:
            # Never emit an invalid Request. An unknown graph_id or target is an
            # error upstream with no partial graph returned, so a malformed one
            # costs a round and yields nothing.
            out["withheld"].append({
                "ask": item["ask"], "target": item["target"],
                "why": "not a valid Request: " + "; ".join(problems),
            })
            continue
        rank += 1
        out["asks"].append({
            "rank": rank,
            "next": rank == 1,
            "rule": item["rule"],
            "request": request,
        })

    out["next"] = out["asks"][0]["request"] if out["asks"] else None
    return out


def explain(result):
    lines = []
    lines.append(f"{result['graph_id']} round {result['round']} "
                 f"(status {result['status']})")
    if result["refused"]:
        lines.append("")
        lines.append("REFUSING TO ASK")
        lines.append("  " + result["refusal"])
    else:
        lines.append(f"{len(result['asks'])} ask(s) ranked; "
                     f"{'1 to send now' if result['asks'] else 'nothing to send'}")
    lines.append("")

    for entry in result["asks"]:
        request = entry["request"]
        head = "NEXT ->" if entry["next"] else "       "
        # new_question's target IS the question text, so it goes on its own line
        # rather than into the header.
        row = request["target"] if request["ask"] != "new_question" else ""
        header = f"{head} {entry['rank']}. {request['ask']}"
        if row:
            header += f" {row}"
        lines.append(f"{header}  depth={request['depth']}")
        lines.append(f"        rule: {entry['rule']}")
        if request["ask"] == "new_question":
            lines.append(f"        question: {request['target']}")
        lines.append(f"        why: {request['reason']}")
        lines.append("")

    if result["withheld"]:
        lines.append("WITHHELD")
        for row in result["withheld"]:
            lines.append(f"  - {row['ask']} {row['target']}")
            lines.append(f"    {row['why']}")
        lines.append("")

    if result["not_evaluated"]:
        lines.append("NOT EVALUATED")
        for note in result["not_evaluated"]:
            lines.append(f"  - {note}")
        lines.append("")

    lines.append("PROTOCOL")
    lines.append(f"  {result['protocol']}")
    lines.append("TRANSPORT")
    lines.append(f"  {result['transport']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("intake", help="graph_read.py output, or '-' for stdin")
    ap.add_argument(
        "--graph",
        help="source graph JSON, for the links[]/gaps[]/rounds[] rules a "
             "graph_read.py bundle does not carry",
    )
    ap.add_argument(
        "--explain",
        action="store_true",
        help="ranked rationale in prose instead of Request JSON",
    )
    args = ap.parse_args()

    payload = load(args.intake)
    graph = None
    if args.graph:
        if not os.path.exists(args.graph):
            sys.exit(f"no such graph file: {args.graph}")
        graph = load(args.graph)

    intake, rows = split_input(payload, graph)
    result = emit(intake, rows)

    if args.explain:
        sys.stdout.write(explain(result) + "\n")
        return
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
