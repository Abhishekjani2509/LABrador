#!/usr/bin/env python3
"""Deterministic graph assembly for literature-graph.

Stdlib only. No classes. Pure functions, so each piece is testable alone.

DETERMINISM IS THE POINT. Every score in the output must be recomputable from
findings + papers, and two runs on the same input must be byte-identical. That
means: sort before emitting, never iterate a set into output, no time, no
randomness, and stable sort keys everywhere. Non-determinism here silently
corrupts every score in the graph.
"""

import json
import os
import re
import unicodedata

# --------------------------------------------------------------------------
# identity + dedup
# --------------------------------------------------------------------------

_DOI_PREFIX = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.I)
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

# Greek letters get spelled out: "TNFα" and "TNF-alpha" are the same node.
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "κ": "kappa", "λ": "lambda", "μ": "mu", "σ": "sigma",
    "ω": "omega",
}


def normalize_doi(s):
    """Strip resolver prefix and lowercase. '' for anything falsy."""
    if not s:
        return ""
    return _DOI_PREFIX.sub("", str(s).strip()).strip("/").lower()


def paper_key(paper):
    """Identity for dedup: doi > pmid > normalized title+year.

    A preprint and its published version are one paper when they share a DOI or
    PMID; otherwise title+year catches the common case.
    """
    doi = normalize_doi(paper.get("doi"))
    if doi:
        return "doi:" + doi
    pmid = str(paper.get("pmid") or "").strip()
    if pmid:
        return "pmid:" + pmid
    title = normalize_name(paper.get("title") or "")
    year = str(paper.get("year") or "")
    return "ty:" + title + "|" + year


def dedupe_papers(new, existing):
    """Merge new papers into existing. Returns (merged, id_map).

    id_map maps the incoming paper's id -> the surviving id, so findings can be
    repointed. Existing rows keep their ids forever.
    """
    merged = [dict(p) for p in existing]
    by_key = {}
    for p in merged:
        by_key.setdefault(paper_key(p), p)
    used = {p.get("id") for p in merged}
    id_map = {}
    counter = len(merged)
    for p in new:
        k = paper_key(p)
        hit = by_key.get(k)
        if hit is not None:
            id_map[p.get("id")] = hit.get("id")
            # Fill blanks from the newcomer; never overwrite what we already had.
            for field, value in sorted(p.items()):
                if field in ("id",):
                    continue
                if not hit.get(field) and value:
                    hit[field] = value
            continue
        counter += 1
        new_id = "p%d" % counter
        while new_id in used:
            counter += 1
            new_id = "p%d" % counter
        used.add(new_id)
        row = dict(p)
        row["id"] = new_id
        id_map[p.get("id")] = new_id
        merged.append(row)
        by_key[k] = row
    return merged, id_map


def normalize_name(s):
    """lowercase, strip punctuation, greek->latin, collapse space, de-pluralize."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = "".join(_GREEK.get(ch, ch) for ch in s)
    s = s.lower()
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    if len(s) > 3 and s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


def resolve_entities(new, existing):
    """Merge things by normalized name OR any alias, against the WHOLE graph.

    The model proposes merges upstream; this only applies them, so assembly
    stays deterministic.
    """
    merged = [dict(t) for t in existing]
    index = {}
    for t in merged:
        for label in [t.get("name", "")] + list(t.get("aliases") or []):
            key = normalize_name(label)
            if key:
                index.setdefault(key, t)
    used = {t.get("id") for t in merged}
    id_map = {}
    counter = len(merged)
    for t in new:
        labels = [t.get("name", "")] + list(t.get("aliases") or [])
        hit = None
        for label in labels:
            key = normalize_name(label)
            if key and key in index:
                hit = index[key]
                break
        if hit is not None:
            id_map[t.get("id")] = hit.get("id")
            known = {normalize_name(a) for a in [hit.get("name", "")] + list(hit.get("aliases") or [])}
            extra = sorted({a for a in labels if a and normalize_name(a) not in known})
            if extra:
                hit["aliases"] = sorted(set(list(hit.get("aliases") or []) + extra))
            hit["mentions"] = int(hit.get("mentions") or 0) + int(t.get("mentions") or 1)
            for label in extra:
                index.setdefault(normalize_name(label), hit)
            continue
        counter += 1
        new_id = "t%d" % counter
        while new_id in used:
            counter += 1
            new_id = "t%d" % counter
        used.add(new_id)
        row = dict(t)
        row["id"] = new_id
        row["mentions"] = int(t.get("mentions") or 1)
        row["aliases"] = sorted(set(row.get("aliases") or []))
        merged.append(row)
        id_map[t.get("id")] = new_id
        for label in labels:
            key = normalize_name(label)
            if key:
                index.setdefault(key, row)
    return merged, id_map


# --------------------------------------------------------------------------
# integrity — the guarantee everything else rests on
# --------------------------------------------------------------------------

def verify_quote(quote, source_text):
    """Normalized-whitespace substring check. Mechanical, never a judgement.

    Unicode is NFKC-folded and the typographic characters that tools silently
    swap -- curly quotes, en/em dashes, non-breaking spaces -- are mapped to
    their ASCII forms first. Without that, a quote copied faithfully out of
    fetched text gets dropped over a character the reader never sees,
    which would mass-discard good findings for a cosmetic reason.
    """
    if not quote or not source_text:
        return False
    return _fold(quote) in _fold(source_text)


def _fold(s):
    s = unicodedata.normalize("NFKC", str(s))
    for a, b in (
        ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
        ("–", "-"), ("—", "-"), ("−", "-"),
        (" ", " "), (" ", " "), (" ", " "), (" ", " "),
    ):
        s = s.replace(a, b)
    return _WS.sub(" ", s).strip().lower()


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

# Keys are exactly the papers.study_type vocabulary. No synonyms: an unknown
# value scores as "unknown" rather than silently matching something close.
_STUDY_QUALITY = {
    "meta_analysis": 1.0,
    "clinical_trial": 0.9,
    "human_cohort": 0.8,
    "animal": 0.6,
    "test_tube": 0.5,
    "computational": 0.4,
    "review": 0.3,
    "unknown": 0.4,
}


def evidence_quality(findings, papers):
    """Mean of the study-type table, x0.8 for preprints."""
    by_id = {p.get("id"): p for p in papers}
    scores = []
    for f in findings:
        p = by_id.get(f.get("paper")) or {}
        base = _STUDY_QUALITY.get(str(p.get("study_type") or "unknown"), 0.4)
        if p.get("is_preprint"):
            base *= 0.8
        scores.append(base)
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def agreement(yes, no):
    """0.5 + (yes-no)/(2*(yes+no)). A single source is 0.5, never 1.0."""
    total = yes + no
    if total <= 0:
        return 0.0
    if total == 1:
        return 0.5
    return round(0.5 + (yes - no) / (2.0 * total), 4)


def independence(findings, papers):
    """(distinct first authors - 1) / (papers - 1). One group is not a consensus."""
    by_id = {p.get("id"): p for p in papers}
    ids, authors = set(), set()
    for f in findings:
        p = by_id.get(f.get("paper"))
        if not p:
            continue
        ids.add(p.get("id"))
        authors.add(normalize_name(p.get("first_author") or p.get("id") or ""))
    n = len(ids)
    if n <= 1:
        return 0.0
    return round((len(authors) - 1) / float(n - 1), 4)


def _own(findings):
    """Findings that are this paper's own result. A review restating forty
    studies is one paper, and not independent evidence for any of them."""
    return [f for f in findings if f.get("is_own_result")]


def score_link(findings, papers):
    """0.4*agreement + 0.4*evidence_quality + 0.2*independence."""
    own = _own(findings)
    yes = len([f for f in own if f.get("says") == "yes"])
    no = len([f for f in own if f.get("says") == "no"])
    agr = agreement(yes, no)
    qual = evidence_quality(findings, papers)
    ind = independence(own, papers)
    overall = 0.4 * agr + 0.4 * qual + 0.2 * ind
    return {
        "overall": round(overall, 4),
        "label": confidence_label(overall),
        "agreement": agr,
        "evidence_quality": qual,
        "independence": ind,
    }


def confidence_label(overall):
    """Bucket for humans. The number stays authoritative."""
    if overall >= 0.7:
        return "high"
    if overall >= 0.4:
        return "medium"
    return "low"


def link_state(yes, no, no_effect):
    if no_effect and not yes and not no:
        return "no_effect"
    if yes and no:
        return "disagreed"
    if (yes + no) == 1:
        return "single_source"
    if yes and not no:
        return "agreed"
    if no and not yes:
        return "agreed"
    return "single_source"


def link_basis(findings):
    if not findings:
        return "background_only"
    own = [f for f in findings if f.get("is_own_result")]
    hedged = [f for f in own if f.get("hedged")]
    if not own:
        return "background_only"
    if len(hedged) == len(own):
        return "hedged_only"
    if hedged:
        return "mixed"
    return "primary"


# --------------------------------------------------------------------------
# the boundary-condition detector -- the demo moment
# --------------------------------------------------------------------------

def explain_disagreement(yes_f, no_f):
    """Partition the camps and compare conditions.

    Disjoint, non-empty condition sets mean the two camps measured different
    things -- which is the common case and far more interesting than "they
    disagree". Overlapping sets mean a real contradiction, and we say nothing
    rather than invent a reason.
    """
    a = sorted({str(f.get("where")) for f in yes_f if f.get("where")})
    b = sorted({str(f.get("where")) for f in no_f if f.get("where")})
    if not a or not b:
        return None
    if set(a) & set(b):
        return None
    return "conditions differ: {%s} vs {%s}" % (", ".join(a), ", ".join(b))


# --------------------------------------------------------------------------
# gaps
# --------------------------------------------------------------------------

def find_gaps(links, things, cap=50, prior_gaps=None, searched_pair=None, round_n=None):
    """Open triangles: A-B and B-C exist, A-C does not.

    Ranked by the weaker of the two supporting links -- a gap between two shaky
    links is not interesting. Degree-capped to keep this near-linear; growth is
    quadratic otherwise.
    """
    present = set()
    for l in links:
        present.add((l.get("from"), l.get("to")))
        present.add((l.get("to"), l.get("from")))
    neighbours = {}
    conf = {}
    via_link = {}
    for l in links:
        a, b = l.get("from"), l.get("to")
        c = (l.get("confidence") or {}).get("overall", 0.0)
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
        if c >= conf.get((a, b), -1.0):
            via_link[(a, b)] = l.get("id")
            via_link[(b, a)] = l.get("id")
        conf[(a, b)] = max(conf.get((a, b), 0.0), c)
        conf[(b, a)] = conf[(a, b)]
    out = []
    for b in sorted(neighbours):
        nbrs = sorted(neighbours[b])
        if len(nbrs) > 24:          # degree cap
            nbrs = nbrs[:24]
        for i in range(len(nbrs)):
            for j in range(i + 1, len(nbrs)):
                a, c = nbrs[i], nbrs[j]
                if (a, c) in present:
                    continue
                pair = tuple(sorted((a, c)))
                strength = min(conf.get((a, b), 0.0), conf.get((b, c), 0.0))
                out.append({
                    "pair": pair,
                    "via": b,
                    "implied_by": sorted({via_link.get((a, b)), via_link.get((b, c))} - {None}),
                    "strength": round(strength, 4),
                })
    best = {}
    for g in out:
        k = g["pair"]
        if k not in best or g["strength"] > best[k]["strength"]:
            best[k] = g
    ranked = sorted(best.values(), key=lambda g: (-g["strength"], g["pair"][0], g["pair"][1]))
    ranked = ranked[:cap]

    # Gap ids must be stable across rounds, because test_gap targets one BY ID.
    # Regenerating them positionally would silently retarget g3 at a different
    # pair the moment ranking shifts. Key on the missing pair instead, carry the
    # prior id forward, and carry searched_in_round with it -- "we looked and
    # found nothing" is the whole value of the ask and must not be lost.
    prior_by_pair, used = {}, set()
    for g in (prior_gaps or []):
        pair = tuple(sorted(g.get("missing") or []))
        prior_by_pair[pair] = g
        used.add(g.get("id"))

    gaps, counter = [], 0
    for g in ranked:
        pair = tuple(sorted(g["pair"]))
        old = prior_by_pair.get(pair)
        if old is not None:
            gid = old.get("id")
            searched = old.get("searched_in_round")
        else:
            counter += 1
            gid = "g%d" % counter
            while gid in used:
                counter += 1
                gid = "g%d" % counter
            searched = None
        used.add(gid)
        if searched_pair and pair == tuple(sorted(searched_pair)):
            searched = round_n
        gaps.append({
            "id": gid,
            "missing": [pair[0], pair[1]],
            "implied_by": g["implied_by"],
            "note": "both connect to %s; no direct link reported" % g["via"],
            "confidence": round(min(g["strength"], 0.6), 4),   # a gap is a proposal
            "searched_in_round": searched,
        })
    gaps.sort(key=lambda x: (int(x["id"][1:]) if x["id"][1:].isdigit() else 0, x["id"]))
    return gaps


# --------------------------------------------------------------------------
# rounds
# --------------------------------------------------------------------------

def round_outcome(prior_links, new_links):
    if not prior_links and new_links:
        return "new_evidence"
    prior = {l.get("id"): l for l in prior_links}
    changed = promoted = contradicted = False
    for l in new_links:
        p = prior.get(l.get("id"))
        if p is None:
            changed = True
            continue
        if l.get("state") != p.get("state"):
            changed = True
            if p.get("state") == "single_source" and l.get("state") == "agreed":
                promoted = True
            if l.get("state") == "disagreed":
                contradicted = True
        elif (l.get("confidence") or {}).get("overall") != (p.get("confidence") or {}).get("overall"):
            changed = True
    if contradicted:
        return "contradicted"
    if promoted:
        return "promoted"
    return "new_evidence" if changed else "nothing_new"


def mark_changed(prior_links, new_links, round_n):
    prior = {l.get("id"): l for l in prior_links}
    for l in new_links:
        p = prior.get(l.get("id"))
        if p is None or l.get("state") != p.get("state") or \
           (l.get("confidence") or {}).get("overall") != (p.get("confidence") or {}).get("overall"):
            l["changed_in_round"] = round_n
        else:
            l["changed_in_round"] = p.get("changed_in_round")
    return new_links


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

_CHUNK = 80 * 1024


def _dump(obj):
    """One serializer everywhere: sorted keys, stable separators, trailing NL."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def save_state(graph, dir_path):
    os.makedirs(os.path.join(dir_path, "findings"), exist_ok=True)
    for name in ("things", "papers", "links", "gaps"):
        with open(os.path.join(dir_path, name + ".json"), "w", encoding="utf8") as fh:
            fh.write(_dump(graph.get(name, [])))
    meta = {k: graph.get(k) for k in
            ("schema_version", "graph_id", "question", "round", "status",
             "generated_at", "error", "coverage", "rounds")}
    with open(os.path.join(dir_path, "meta.json"), "w", encoding="utf8") as fh:
        fh.write(_dump(meta))
    rnd = graph.get("round", 1)
    findings = graph.get("findings", [])
    blob = _dump(findings)
    if len(blob.encode("utf8")) <= _CHUNK:
        parts = [findings]
    else:                       # chunk, never rewrite an earlier round
        parts, cur, size = [], [], 0
        for f in findings:
            s = len(_dump(f).encode("utf8"))
            if cur and size + s > _CHUNK:
                parts.append(cur)
                cur, size = [], 0
            cur.append(f)
            size += s
        if cur:
            parts.append(cur)
    for i, part in enumerate(parts):
        suffix = "" if i == 0 else "_%d" % (i + 1)
        path = os.path.join(dir_path, "findings", "r%s%s.json" % (rnd, suffix))
        with open(path, "w", encoding="utf8") as fh:
            fh.write(_dump(part))
    return dir_path


def load_state(dir_path):
    """A missing directory is an empty graph, never an exception."""
    empty = {"things": [], "papers": [], "links": [], "gaps": [], "findings": [],
             "round": 0, "rounds": [], "status": "empty"}
    if not dir_path or not os.path.isdir(dir_path):
        return empty
    out = dict(empty)
    meta_path = os.path.join(dir_path, "meta.json")
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf8") as fh:
            out.update(json.load(fh))
    for name in ("things", "papers", "links", "gaps"):
        p = os.path.join(dir_path, name + ".json")
        if os.path.isfile(p):
            with open(p, encoding="utf8") as fh:
                out[name] = json.load(fh)
    fdir = os.path.join(dir_path, "findings")
    findings = []
    if os.path.isdir(fdir):
        for fn in sorted(os.listdir(fdir)):        # sorted: determinism
            if fn.endswith(".json"):
                with open(os.path.join(fdir, fn), encoding="utf8") as fh:
                    findings.extend(json.load(fh))
    out["findings"] = findings
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(prior_dir, new_findings, new_papers, round_n, ask, question=None,
         graph_id=None, generated_at=None, coverage=None, new_things=None,
         target=None, depth=None, papers_added=None):
    """target: for test_gap, the gap id being tested -- resolved to its pair so
    the answer survives the gap being re-ranked."""
    prior = load_state(prior_dir)

    papers, pmap = dedupe_papers(new_papers or [], prior.get("papers") or [])
    things, tmap = resolve_entities(new_things or [], prior.get("things") or [])

    kept, discarded = [], 0
    src = {p.get("id"): p for p in papers}
    for f in list(prior.get("findings") or []) + list(new_findings or []):
        f = dict(f)
        f["paper"] = pmap.get(f.get("paper"), f.get("paper"))
        text = (src.get(f.get("paper")) or {}).get("source_text", "")
        if text and not verify_quote(f.get("quote"), text):
            discarded += 1
            continue
        for side in ("from", "to"):
            if f.get(side) in tmap:
                f[side] = tmap[f[side]]
        kept.append(f)
    kept.sort(key=lambda f: (str(f.get("from")), str(f.get("to")), str(f.get("paper")), str(f.get("quote"))[:80]))

    grouped = {}
    for f in kept:
        grouped.setdefault((f.get("from"), f.get("how"), f.get("to")), []).append(f)

    links = []
    for n, key in enumerate(sorted(grouped, key=lambda k: tuple(str(x) for x in k)), 1):
        fs = grouped[key]
        own = _own(fs)
        yes = [f for f in own if f.get("says") == "yes"]
        no = [f for f in own if f.get("says") == "no"]
        ne = [f for f in own if f.get("says") == "no_effect"]
        state = link_state(len(yes), len(no), len(ne))
        links.append({
            "id": "L%d" % n,
            "from": key[0], "how": key[1], "to": key[2],
            "state": state,
            "basis": link_basis(fs),
            "confidence": score_link(fs, papers),
            "yes": sorted(f.get("id") for f in yes if f.get("id")),
            "no": sorted(f.get("id") for f in no if f.get("id")),
            "no_effect": sorted(f.get("id") for f in ne if f.get("id")),
            "why": explain_disagreement(yes, no) if state == "disagreed" else None,
            "changed_in_round": None,
        })

    links = mark_changed(prior.get("links") or [], links, round_n)

    searched_pair = None
    if ask == "test_gap" and target:
        for g in (prior.get("gaps") or []):
            if g.get("id") == target:
                searched_pair = tuple(sorted(g.get("missing") or []))
                break
    gaps = find_gaps(links, things, prior_gaps=prior.get("gaps") or [],
                     searched_pair=searched_pair, round_n=round_n)
    outcome = round_outcome(prior.get("links") or [], links)

    cov = dict(coverage or {})
    cov["no_quote_discarded"] = cov.get("no_quote_discarded", 0) + discarded

    rounds = list(prior.get("rounds") or [])
    rounds.append({
        "n": round_n, "ask": ask, "target": target, "depth": depth,
        "papers_added": papers_added if papers_added is not None else len(new_papers or []),
        "outcome": outcome,
    })

    return {
        "schema_version": "1.1",
        "graph_id": graph_id or prior.get("graph_id"),
        "question": question or prior.get("question"),
        "round": round_n,
        "status": prior.get("status", "ok"),
        "generated_at": generated_at,
        "error": None,
        "things": things,
        "papers": papers,
        "findings": kept,
        "links": links,
        "gaps": gaps,
        "coverage": cov,
        "rounds": rounds,
    }
