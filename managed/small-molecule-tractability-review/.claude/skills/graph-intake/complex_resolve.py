#!/usr/bin/env python3
"""Resolve a protein-complex or pathway NAME to UniProt accessions, or refuse.

Upstream evidence graphs name complexes and pathways -- "MyD88 signalosome",
"TLR/IL-1R signalling axis", "TLR/IL-1R signaling". None of these has a sequence,
so none can be handed to a structural step, and the PPI branch of the intake
needs TWO accessions before it can name an interaction to disrupt. This turns one
side of that pair from a phrase into accessions where a curated entry exists, and
says so plainly where none does.

Lookup, never inference. Membership comes from `complex_components.json`, which
is hand-curated with a citable source per entry. Nothing here derives membership
from a name, from string similarity, or from what a complex is "usually" made of
-- that is the fabrication this file exists to prevent, and it is indetectable
downstream because a guessed component list looks exactly like a retrieved one.

Accessions are re-verified against Paperclip at run time. The table is a claim,
not an authority; a stale or mistyped accession in it must not reach a caller.

Three outcomes, never blurred:

    resolved              exact name/alias hit on a complex; components verified
    pathway_unresolved    exact hit on a PATHWAY -- candidates, not components,
                          and explicitly not resolvable to one complex
    proposal              partial name match; a question for a human, NOT an
                          answer, and never emitted under `components`
    no_match              nothing. Empty with a reason. A correct outcome.

Usage:
    python3 complex_resolve.py "MyD88 signalosome"
    python3 complex_resolve.py "TLR/IL-1R signaling"
    python3 complex_resolve.py "MyD88 complex" --table fixtures/complex_components.json
    python3 complex_resolve.py "Myddosome" --no-verify
"""

import argparse
import json
import os
import re
import subprocess
import sys

# The curated table travels with the fixtures, not with this skill -- it is data
# under review, not code. Resolved relative to the repo root two levels up.
DEFAULT_TABLE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "fixtures", "complex_components.json",
)

# Paperclip needs the repo .env sourced for credentials:
#     set -a; . <repo>/.env; set +a
# Same shell-out pattern as pocket-scan/interface_analysis.py.
PAPERCLIP = os.environ.get("PAPERCLIP_BIN", "/Users/bb/.local/bin/paperclip")

VERIFY_SQL = (
    "SELECT accession, gene_name, protein_name FROM uniprot_v.proteins "
    "WHERE accession IN ({acc_list}) AND organism = 'Homo sapiens'"
)

# UniProt accession shape. Anything else never reaches the SQL string -- the
# accession list is interpolated, so a malformed table entry is a refusal, not a
# query.
ACCESSION_RE = re.compile(r"^[OPQ][0-9][A-Z0-9]{3}[0-9]$|^[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}$")

NS_WORD = re.compile(r"[^a-z0-9]+")

# Normalisation is deliberately minimal: case, punctuation, and the one spelling
# split that is not a naming choice. Everything else -- "NF-kB" vs "NFkB",
# "Myddosome" vs "MyD88 signalosome" -- belongs in the table's `aliases`, where a
# curator wrote it down, not in a rule here that would quietly widen matching.
SPELLING = {"signalling": "signaling", "signalled": "signaled"}

# Tokens that carry no discriminating power. A partial match resting only on
# these is not a match; "some pathway" must not propose every pathway in the
# table.
STOPWORDS = {
    "signaling", "signal", "pathway", "axis", "complex", "the", "of", "and",
    "a", "an", "protein", "proteins", "cascade", "route",
}

# A partial match needs this share of tokens in common. Set where "MyD88
# complex" proposes the Myddosome and "something that does not exist" proposes
# nothing. Tuning it upward loses proposals; downward turns noise into questions.
PARTIAL_THRESHOLD = 0.30


def norm(text):
    if not text:
        return ""
    text = text.lower().replace("κ", "k")
    return " ".join(SPELLING.get(t, t) for t in NS_WORD.sub(" ", text).split())


def tokens(text):
    return set(norm(text).split())


def names_of(entry):
    """Canonical name first, then curated aliases. Exact matching sees only these."""
    return [entry.get("name", "")] + list(entry.get("aliases", []))


def load_table(path):
    with open(path) as fh:
        table = json.load(fh)
    entries = table.get("entries", [])
    for e in entries:
        kind = e.get("kind")
        if kind not in ("complex", "pathway"):
            raise ValueError(f"entry {e.get('id')!r}: kind must be complex|pathway, got {kind!r}")
        # A pathway carrying `components` would resolve as a complex on the next
        # read of this file. Kept as a hard schema error rather than a coercion.
        if kind == "pathway" and e.get("components"):
            raise ValueError(f"entry {e.get('id')!r}: a pathway must carry `candidates`, not `components`")
        if kind == "complex" and e.get("candidates"):
            raise ValueError(f"entry {e.get('id')!r}: a complex must carry `components`, not `candidates`")
    return table, entries


def members(entry):
    """The protein rows of an entry, whichever key they live under."""
    return entry.get("components") if entry.get("kind") == "complex" else entry.get("candidates") or []


def find_exact(query, entries):
    q = norm(query)
    return [e for e in entries if any(norm(n) == q for n in names_of(e))]


def score_partial(query, entry):
    """Shared non-stopword tokens, plus containment either direction.

    Returned as a ranking for a human to read, never as a confidence that the
    match is right. There is no score at which a partial becomes an answer.
    """
    q_all = tokens(query)
    q = q_all - STOPWORDS
    if not q:
        return 0.0, []
    best, shared_best = 0.0, []
    for name in names_of(entry):
        n_all = tokens(name)
        n = n_all - STOPWORDS
        if not n:
            continue
        shared = q & n
        if not shared:
            continue
        s = len(shared) / max(len(q), len(n))
        # Whole-phrase containment ("Myddosome" inside "Myddosome complex")
        # ranks above token overlap alone.
        if norm(query) and (norm(query) in norm(name) or norm(name) in norm(query)):
            s = max(s, 0.75)
        if s > best:
            best, shared_best = s, sorted(shared)
    return best, shared_best


def find_partial(query, entries):
    out = []
    for e in entries:
        s, shared = score_partial(query, e)
        if s >= PARTIAL_THRESHOLD:
            out.append((s, shared, e))
    return sorted(out, key=lambda r: (-r[0], r[2].get("id", "")))


def paperclip_rows(accessions, paperclip=PAPERCLIP, timeout=90):
    """Look up accessions in uniprot_v.proteins. Raises on any failure.

    Accessions are interpolated into the SQL, so every one is shape-checked
    first; a table entry that is not an accession is refused rather than sent.
    """
    bad = [a for a in accessions if not ACCESSION_RE.match(a or "")]
    if bad:
        raise ValueError(f"not UniProt accession shape, refusing to query: {bad}")
    sql = VERIFY_SQL.format(acc_list=", ".join(f"'{a}'" for a in sorted(accessions)))
    proc = subprocess.run(
        [paperclip, "sql", "-s", "proteins", sql],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"paperclip failed: {(proc.stderr or proc.stdout).strip()[:400]}")
    return parse_paperclip_table(proc.stdout)


def parse_paperclip_table(text):
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    header, rows = None, []
    for ln in lines:
        if re.match(r"^-+\+", ln) or re.match(r"^\(\d+ rows?", ln) or ln.startswith("["):
            continue
        parts = [p.strip() for p in ln.split("|")]
        if header is None:
            if len(parts) > 1:
                header = parts
            continue
        if len(parts) != len(header):
            continue
        rows.append(dict(zip(header, parts)))
    return rows


def verify(entry_members, paperclip=PAPERCLIP, timeout=90):
    """Check every accession against UniProt now, rather than trusting the file.

    Returns (status, detail, by_accession). A component is verified only if the
    accession exists AND its gene_name matches what the table claims -- an
    accession that resolves to a different protein is the failure mode that
    matters, and it is invisible if only existence is checked.
    """
    accs = sorted({m.get("accession") for m in entry_members if m.get("accession")})
    if not accs:
        return "not_applicable", "entry carries no accessions", {}
    try:
        rows = paperclip_rows(accs, paperclip=paperclip, timeout=timeout)
    except Exception as exc:  # network, credentials, timeout, malformed table
        return "unavailable", f"{type(exc).__name__}: {exc}", {}

    found = {r.get("accession"): r for r in rows}
    detail = {}
    for m in entry_members:
        acc, sym = m.get("accession"), (m.get("gene_symbol") or "").upper()
        row = found.get(acc)
        if row is None:
            detail[acc] = {"verified": False,
                           "why": "accession not in uniprot_v.proteins for Homo sapiens"}
        elif (row.get("gene_name") or "").upper() != sym:
            detail[acc] = {"verified": False,
                           "why": f"gene_name mismatch: table says {sym}, "
                                  f"UniProt says {row.get('gene_name')}"}
        else:
            detail[acc] = {"verified": True,
                           "uniprot_gene_name": row.get("gene_name"),
                           "uniprot_protein_name": row.get("protein_name")}
    status = "verified" if all(d["verified"] for d in detail.values()) else "partial_failure"
    return status, None, detail


def annotate(rows, detail):
    """Attach verification to each member. Never drops a row silently."""
    out = []
    for m in rows:
        row = dict(m)
        d = detail.get(m.get("accession"))
        row["verified"] = d.get("verified") if d else None
        if d and not d.get("verified"):
            row["verification_error"] = d.get("why")
        elif d and d.get("verified"):
            row["uniprot_protein_name"] = d.get("uniprot_protein_name")
        out.append(row)
    return out


def resolve(query, entries, do_verify=True, paperclip=PAPERCLIP, timeout=90):
    base = {
        "query": query,
        "normalised_query": norm(query),
        "match": None,
        "outcome": None,
        "entry": None,
        "kind": None,
        "components": [],
        "candidates": [],
        "proposals": [],
        "verification": {"status": "not_run", "detail": {}},
        "reason": None,
        "warnings": [],
    }

    exact = find_exact(query, entries)
    if len(exact) > 1:
        # Two curated entries answering to the same name is a table defect, not
        # an ambiguity to resolve at run time by picking one.
        base.update(
            match="exact", outcome="table_conflict",
            reason=("more than one curated entry matches this name exactly: "
                    f"{[e.get('id') for e in exact]}. Fix the table; do not pick."),
        )
        return base

    if exact:
        entry = exact[0]
        rows = members(entry)
        status, err, detail = ("not_run", None, {})
        if do_verify:
            status, err, detail = verify(rows, paperclip=paperclip, timeout=timeout)
        base["verification"] = {"status": status, "error": err, "detail": detail}
        rows = annotate(rows, detail)

        base.update(match="exact", kind=entry.get("kind"), entry={
            "id": entry.get("id"), "name": entry.get("name"),
            "aliases": entry.get("aliases", []), "organism": entry.get("organism"),
            "source": entry.get("source"),
        })

        if entry.get("kind") == "complex":
            base["outcome"] = "resolved"
            base["components"] = rows
            base["reason"] = (f"exact match on curated complex {entry.get('id')!r}; "
                              f"{len(rows)} components, membership sourced per component")
        else:
            # A pathway NEVER populates `components`. A caller reading only that
            # key must see an empty list, not a receptor picked off a list.
            base["outcome"] = "pathway_unresolved"
            base["candidates"] = rows
            base["reason"] = (f"exact match on curated PATHWAY {entry.get('id')!r}. "
                              "A pathway is not a complex and does not resolve to a "
                              "single accession.")
            base["not_a_complex_because"] = entry.get("not_a_complex_because")
            base["what_to_do_instead"] = entry.get("what_to_do_instead")
            base["warnings"].append(
                "These are CANDIDATES on a signalling route, not members of one "
                "assembly. Do not hand any single one to a structural or PPI step "
                "as 'the' resolution of this name."
            )

        if status == "unavailable":
            base["warnings"].append(
                "Accessions could NOT be checked against Paperclip on this run "
                f"({err}). They are reproduced from the curated table unverified. "
                "Do not report them as retrieved."
            )
        elif status == "partial_failure":
            failed = [a for a, d in detail.items() if not d.get("verified")]
            base["warnings"].append(
                f"Verification FAILED for {failed}. The table disagrees with UniProt; "
                "treat those rows as unresolved and correct the table."
            )
        return base

    partial = find_partial(query, entries)
    if partial:
        # Proposals are questions. They carry entry identity and the shared
        # tokens that produced them, and deliberately do NOT carry the member
        # lists -- a caller that wants those must confirm the name first and
        # re-run, which is the confirmation step.
        base.update(
            match="partial", outcome="proposal",
            proposals=[{
                "entry_id": e.get("id"), "name": e.get("name"), "kind": e.get("kind"),
                "aliases": e.get("aliases", []),
                "score": round(s, 3), "shared_terms": shared,
                "n_members": len(members(e)),
                "confirm_with": f'complex_resolve.py "{e.get("name")}"',
            } for s, shared, e in partial[:5]],
            reason=("no exact name or alias matched. These are the nearest curated "
                    "entries, offered as a PROPOSAL requiring confirmation. This is "
                    "not a resolution and the component list is withheld on purpose "
                    "-- confirm the name, then re-run."),
        )
        base["warnings"].append(
            "A partial name match is not an answer. Do not populate "
            "uniprot_accession or interaction_to_disrupt from this output."
        )
        return base

    base.update(
        match="none", outcome="no_match",
        reason=(f"{query!r} is not in the curated table (exact or partial) at "
                "the configured path. Returning empty. The table is curated and "
                "deliberately incomplete; an absent complex is reported as absent "
                "rather than assembled from what the name sounds like. To resolve "
                "it, add a sourced entry."),
    )
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="complex or pathway name from the evidence graph")
    ap.add_argument("--table", default=DEFAULT_TABLE, help="path to complex_components.json")
    ap.add_argument("--paperclip", default=PAPERCLIP, help="path to the paperclip CLI")
    ap.add_argument("--timeout", type=int, default=90, help="seconds for the paperclip call")
    ap.add_argument(
        "--no-verify", action="store_true",
        help="skip the Paperclip check (offline only; output is then unverified)",
    )
    args = ap.parse_args()

    try:
        table, entries = load_table(args.table)
    except FileNotFoundError:
        sys.exit(f"refusing: curated table not found at {args.table}")
    except ValueError as exc:
        sys.exit(f"refusing: {exc}")

    out = resolve(args.name, entries, do_verify=not args.no_verify,
                  paperclip=args.paperclip, timeout=args.timeout)
    out["table"] = {
        "path": os.path.normpath(args.table),
        "schema_version": table.get("schema_version"),
        "retrieved_at": table.get("retrieved_at"),
        "n_entries": len(entries),
        "curated": "hand-curated lookup; absence returns empty, never a guess",
    }
    if args.no_verify:
        out["warnings"].append(
            "--no-verify was passed: accessions were NOT checked against Paperclip."
        )

    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
