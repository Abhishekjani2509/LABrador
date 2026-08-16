#!/usr/bin/env python3
"""Run the whole graph-intake procedure end to end, in one process.

Four scripts already exist and nothing runs them as a pipeline, so the accession
step -- the one that decides whether a target reaches the dossier at all -- has
been done by hand. This is the entry point:

    1. load the graph          (--graph <file>, or --store <dir> --graph-id <id>)
    2. traverse it             (imports graph_read; does NOT shell out to it)
    3. verify every proposed gene symbol against UniProt via paperclip
    4. promote what verified into dossier inputs, with provenance
    5. emit one report: inputs, unresolved, refused, and why

Stdlib only. Nothing here decides tractability, ranks targets, picks between two
plausible accessions, or assigns a mechanism the evidence has not stated.

WHAT THIS TOOL REFUSES TO DO
----------------------------
It never substitutes a related symbol for one that did not resolve. `NF-kB`
returns no row; `NFKB1` returns P19838 and `RELA` returns Q04206. A resolver
that falls back from the first to either of the others gets a clean row, no
error, and a wrong answer wearing a right answer's clothes -- SKILL.md failure
mode 3, arriving through a fallback instead of a string match. There is no
fallback path in this file, by construction.

It also keeps two things apart that look identical in a result table:

    absent            the query ran and UniProt has no such human gene symbol.
                      That is an answer.
    retrieval_failed  the query did not complete after its retries. That is NOT
                      evidence the symbol is absent, and it must never be read
                      as one. It survives into the output under its own name.

Usage:
    python3 run_intake.py --graph fixtures/upstream_graph_real.json
    python3 run_intake.py --graph fixtures/upstream_graph_real.json --dry-run
    python3 run_intake.py --store ../research-evidence-mapper/runs --graph-id g_1a4f
    python3 run_intake.py --graph fixtures/upstream_graph.json --allow-fixture --json

Exit codes (so this can be used as a check):
    0  ran, graph status ok, at least one dossier input -- or --dry-run, where
       "nothing resolved" is a skipped step rather than a result
    1  graph status is not 'ok' (SKILL.md step 0: a failed graph parses cleanly
       and returns zero nominations, which reads exactly like "no targets here")
    2  verification ran and nothing resolved
    3  could not load the graph, or refused it (fixture guard)
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Imported, not shelled out to -- the traversal's structured output is the input
# to every step below it, and re-parsing our own stdout would be the hand-chaining
# this file exists to remove.
import graph_read  # noqa: E402
import graph_store  # noqa: E402

PAPERCLIP = os.environ.get("PAPERCLIP_BIN", "/Users/bb/.local/bin/paperclip")

# Paperclip needs the repo .env sourced for PAPERCLIP_API_KEY. First existing
# candidate wins; --env-file overrides both.
ENV_CANDIDATES = [
    os.path.normpath(os.path.join(HERE, "..", "..", "..", ".env")),
    os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", ".env")),
    "/Users/bb/repos/claude-agent-starter/.env",
]

# SKILL.md step 4's query, one symbol at a time. See ONE_AT_A_TIME below.
SYMBOL_SQL = (
    "SELECT accession, gene_name, protein_name, organism, sequence_length "
    "FROM uniprot_v.proteins "
    "WHERE gene_name = '{sym}' AND organism = 'Homo sapiens'"
)

# ---------------------------------------------------------------------------
# ONE SYMBOL PER QUERY -- deliberately against precedent-lookup's batching advice
# ---------------------------------------------------------------------------
# precedent-lookup/SKILL.md tells you to aggregate server-side and to avoid extra
# round trips, and SKILL.md step 4 shows the lookup as a single `gene_name IN
# (...)` list. That is the right shape for a database that answers reliably. This
# one currently does not: multi-symbol `IN (...)` predicates against
# uniprot_v.proteins have been timing out intermittently and repeatedly today,
# while single-symbol equality lookups return in ~6-40ms. Measured on this box:
# `gene_name = 'IRAK4'` 7ms, `= 'MYD88'` 6ms, `= 'NFKB1'` 6ms, `= 'RELA'` 8ms;
# `= 'TLR'` timed out twice and then returned "(0 rows, 6ms)" on the third try.
#
# So batching here trades a cheap, retryable, per-symbol failure for a single
# expensive one that takes every symbol down with it -- and, worse, an `IN` list
# that times out cannot tell you which member was going to return a row. Per
# symbol, a timeout is isolated, retryable, and attributable. That last property
# is the one that matters: it is what lets `retrieval_failed` stay distinct from
# `absent` instead of collapsing into "no rows came back".
#
# If the timeouts stop, batch. Until then, do not.
ONE_AT_A_TIME = (
    "one symbol per query, with retries. Multi-symbol gene_name IN (...) "
    "predicates have been timing out intermittently; single-symbol lookups "
    "return in ~6-40ms. A batched timeout cannot be attributed to a symbol, "
    "which would collapse 'retrieval failed' into 'not in UniProt'."
)

# A symbol shape check before interpolation. The symbol is built into the SQL
# string, so anything not of this shape is refused rather than sent.
SAFE_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*$")

# `disease_context` is a LOOKUP, not an inference. A graph node typed `disease`
# is authoritative; failing that, this deliberately short literal table is
# matched against the graph's own `question` string. It is incomplete on purpose
# and returns null rather than guessing at a disease from surrounding words.
DISEASE_PHRASES = (
    "rheumatoid arthritis",
    "psoriatic arthritis",
    "ankylosing spondylitis",
    "systemic lupus erythematosus",
    "inflammatory bowel disease",
    "ulcerative colitis",
    "crohn's disease",
    "crohn disease",
    "atopic dermatitis",
    "multiple sclerosis",
    "psoriasis",
    "asthma",
    "osteoarthritis",
    "gout",
)

# --- interaction_to_disrupt, read from quotes only ---------------------------
#
# SKILL.md step 2: the mechanism is in the quote text, and `how` (or a node name,
# or an action word) is too coarse. So an action word may only PROPOSE a shape;
# a verbatim quote naming both the symbol and the same stem is what licenses it.
# "IRAK4 inhibition" proposes nothing -- `inhibition` states intent, not an
# interaction -- and that is why IRAK4 comes out with an accession and a null
# interaction while MYD88 does not.
ACTION_SHAPES = [
    (
        {"dimerization", "dimerisation", "oligomerization", "oligomerisation",
         "multimerization", "multimerisation"},
        "dimerization interface (oligomeric state)",
        ("dimeriz", "dimeris", "oligomeriz", "oligomeris",
         "multimeriz", "multimeris"),
    ),
]

# Catalytic function is claimed only when a quote says so in these words. "IRAK4
# kinase dependent" is NOT one of them: it says the response needed the kinase,
# not that the compound inhibited kinase activity.
CATALYTIC_PHRASES = (
    "kinase activity", "enzymatic activity", "catalytic activity",
    "protease activity", "atpase activity", "gtpase activity",
    "phosphatase activity", "polymerase activity",
)

# mechanism_hypothesis says WHERE to bind. Failure mode 5: catalytic function
# does not imply orthosteric, and deucravacitinib/TYK2 is why that is not
# pedantry. Only these words in a quote may set it.
MECHANISM_PHRASES = (
    "atp-competitive", "atp competitive", "allosteric", "orthosteric",
    "active site", "covalent", "pseudokinase domain",
)
RESIDUE_RANGE = re.compile(r"\b(?:residues?|amino acids?|aa)\s*\d+\s*[-‐-―]\s*\d+")

NON_WORD = re.compile(r"[^a-z0-9]+")


class PaperclipError(RuntimeError):
    """Paperclip did not return a result. Never an answer about UniProt."""


def describe_exc(exc, timeout):
    """Short, readable failure text. subprocess.TimeoutExpired stringifies the
    entire command including the SQL, which buries the one fact that matters."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"TimeoutExpired: no response within {timeout}s"
    return f"{type(exc).__name__}: {str(exc)[:200]}"


# ---------------------------------------------------------------------------
# environment + graph loading
# ---------------------------------------------------------------------------

def parse_env_file(path):
    """Minimal `set -a; . .env; set +a` equivalent, stdlib only."""
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            env[key.strip()] = val
    return env


def resolve_env_file(explicit):
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit(f"refusing: --env-file not found at {explicit}")
        return explicit
    for cand in ENV_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None


def load_graph(args):
    """--graph <file> or --store <dir> --graph-id <id>. Returns (graph, source)."""
    if args.graph_id:
        if not args.store:
            raise SystemExit("refusing: --graph-id needs --store <dir> (the mapper's store)")
        graph = graph_store.load(args.store, args.graph_id)
        source = {
            "mode": "store",
            "store": os.path.normpath(args.store),
            "graph_id": args.graph_id,
            "note": ("reassembled from the mapper's on-disk store via graph_store; "
                     "findings deduped by id because the shipped store writes a full "
                     "snapshot per round chunk rather than a delta"),
        }
        return graph, source

    if not args.graph:
        raise SystemExit("refusing: pass --graph <file> or --store <dir> --graph-id <id>")
    with open(args.graph) as fh:
        graph = json.load(fh)
    return graph, {"mode": "file", "path": os.path.normpath(args.graph)}


def store_integrity(graph):
    """The store's own self-reported drift. Worth reading before trusting it."""
    keys = ("_findings_chunk_mode", "_undocumented_fields", "_dangling_refs",
            "_resolved_ask_targets")
    out = {k: graph[k] for k in keys if graph.get(k)}
    return out or None


# ---------------------------------------------------------------------------
# UniProt verification
# ---------------------------------------------------------------------------

def parse_paperclip_table(text):
    """Same pipe-delimited table shape complex_resolve.py parses."""
    header, rows = None, []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if re.match(r"^-+\+", line) or re.match(r"^\(\d+ rows?", line) or line.startswith("["):
            continue
        parts = [p.strip() for p in line.split("|")]
        if header is None:
            if len(parts) > 1:
                header = parts
            continue
        if len(parts) != len(header):
            continue
        rows.append(dict(zip(header, parts)))
    return rows


class UniProtVerifier:
    """One symbol per paperclip call, with a timeout and a bounded retry.

    Caches by query form, because the same symbol appears under several things
    (MyD88 arrives from both t4 and t5) and a repeat lookup is a repeat chance
    to time out for no new information.
    """

    def __init__(self, paperclip=PAPERCLIP, timeout=45, retries=2, backoff=1.5,
                 env=None, dry_run=False):
        self.paperclip = paperclip
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.env = env
        self.dry_run = dry_run
        self.cache = {}
        self.log = []

    def _run_once(self, sql):
        proc = subprocess.run(
            [self.paperclip, "sql", "-s", "proteins", sql],
            capture_output=True, text=True, timeout=self.timeout, env=self.env,
        )
        out = proc.stdout or ""
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            raise PaperclipError(f"exit {proc.returncode}: {(err or out).strip()[:300]}")
        # Paperclip reports its own server-side timeout on stdout and still exits
        # 0. Reading that as an empty result set is precisely the bug this file
        # is built to avoid, so it is raised, not parsed.
        for line in out.splitlines():
            if line.startswith("[error]"):
                raise PaperclipError(line.strip()[:300])
        return parse_paperclip_table(out)

    def lookup_form(self, form):
        """One gene_name form. Returns (status, rows, attempts).

        status: 'rows' | 'no_rows' | 'retrieval_failed'
        """
        if form in self.cache:
            return self.cache[form]

        if not SAFE_SYMBOL.match(form or ""):
            result = ("retrieval_failed", [], [{
                "attempt": 0, "ok": False,
                "error": "not gene-symbol shaped; refused before interpolation into SQL",
            }])
            self.cache[form] = result
            return result

        sql = SYMBOL_SQL.format(sym=form)
        attempts = []
        for n in range(1, self.retries + 2):
            t0 = time.time()
            try:
                rows = self._run_once(sql)
            except (PaperclipError, subprocess.TimeoutExpired, OSError) as exc:
                attempts.append({
                    "attempt": n, "ok": False, "ms": int((time.time() - t0) * 1000),
                    "error": describe_exc(exc, self.timeout),
                })
                if n <= self.retries:
                    time.sleep(self.backoff * n)
                continue
            attempts.append({"attempt": n, "ok": True,
                             "ms": int((time.time() - t0) * 1000),
                             "rows": len(rows)})
            result = ("rows" if rows else "no_rows", rows, attempts)
            self.cache[form] = result
            self.log.append({"query_form": form, "sql": sql, "attempts": attempts,
                             "status": result[0], "rows": rows})
            return result

        result = ("retrieval_failed", [], attempts)
        self.cache[form] = result
        self.log.append({"query_form": form, "sql": sql, "attempts": attempts,
                         "status": "retrieval_failed", "rows": []})
        return result

    def verify(self, symbol, query_forms):
        """Every spelling of one symbol. Returns a verification record.

        status:
          verified          exactly one human row came back
          multiple_rows     more than one row -- an ambiguity, not a resolution
          absent            every form completed and returned zero rows
          retrieval_failed  at least one form never completed and none verified
          skipped           --dry-run
        """
        record = {
            "symbol": symbol,
            "query_forms": list(query_forms),
            "status": None,
            "uniprot_accession": None,
            "rows": [],
            "forms_tried": [],
            "why": None,
        }

        if self.dry_run:
            record.update(status="skipped",
                          why="--dry-run: no network call was made. This is NOT a "
                              "statement about whether the symbol is in UniProt.")
            return record

        any_failure = False
        for form in query_forms:
            status, rows, attempts = self.lookup_form(form)
            record["forms_tried"].append({
                "form": form, "status": status, "n_rows": len(rows),
                "attempts": len(attempts),
                "errors": [a.get("error") for a in attempts if not a.get("ok")],
            })
            if status == "rows":
                record["rows"] = rows
                if len(rows) == 1:
                    record.update(
                        status="verified",
                        uniprot_accession=rows[0].get("accession"),
                        why=f"gene_name = '{form}' returned "
                            f"{rows[0].get('accession')} | {rows[0].get('gene_name')} | "
                            f"{rows[0].get('protein_name')}",
                    )
                else:
                    # Two accessions both fitting is an ambiguity to report, not
                    # one to resolve by picking the first row.
                    record.update(
                        status="multiple_rows",
                        why=f"gene_name = '{form}' returned {len(rows)} rows; "
                            f"two accessions both fit and the graph gives no basis "
                            f"to choose. Left unresolved on purpose.",
                    )
                return record
            if status == "retrieval_failed":
                any_failure = True

        if any_failure:
            record.update(
                status="retrieval_failed",
                why="the lookup did not complete after its retries. This is a FAILED "
                    "RETRIEVAL and is NOT evidence that the symbol is absent from "
                    "UniProt. Re-run before drawing any conclusion from it.",
            )
        else:
            record.update(
                status="absent",
                why=f"every form {query_forms} completed and returned zero rows for "
                    f"organism = 'Homo sapiens'. UniProt has no human gene by this "
                    f"symbol. This is an answer, not a failure -- a name for a "
                    f"complex or a family is expected to land here.",
            )
        return record


# ---------------------------------------------------------------------------
# promotion to dossier inputs
# ---------------------------------------------------------------------------

def symbol_in(text, symbol):
    """Symbol present in a quote, hyphen- and case-insensitively."""
    flat = NON_WORD.sub("", (text or "").lower())
    return NON_WORD.sub("", (symbol or "").lower()) in flat


def evidence_rows(thing_id, idx):
    tiers = graph_read.neighbourhood(thing_id, idx)
    return [row for bucket in tiers.values() for row in bucket]


def split_findings(rows):
    """Supporting vs recorded-not-acted-on.

    `no` and `no_effect` are kept out of `supporting` and are NOT folded together
    (failure mode 10), and a finding on a `background_only` / `hedged_only` link
    is recorded rather than acted on (step 3), whichever way it says.
    """
    support, recorded = set(), set()
    for row in rows:
        if row.get("says") == "yes" and row.get("actionable"):
            support.add(row["finding"])
        else:
            recorded.add(row["finding"])
    return sorted(support), sorted(recorded - support)


def derive_interaction(symbol, action, rows):
    """interaction_to_disrupt, or null with the reason it is null.

    An action word proposes a shape; a verbatim quote naming the same symbol and
    the same stem confirms it. No confirmation, no interaction.
    """
    action_l = (action or "").lower()
    action_tokens = set(NON_WORD.sub(" ", action_l).split())

    for words, shape, stems in ACTION_SHAPES:
        if not (action_tokens & words):
            continue
        cited = [r["finding"] for r in rows
                 if symbol_in(r.get("quote"), symbol)
                 and any(s in (r.get("quote") or "").lower() for s in stems)]
        if cited:
            return shape, {
                "from": "quote",
                "action_word": action,
                "confirmed_by": sorted(set(cited)),
                "why": (f"the action word beside the symbol proposes the oligomeric-state "
                        f"shape, and {sorted(set(cited))} state it verbatim naming both "
                        f"{symbol} and the same stem. SKILL.md step 2."),
            }
        return None, {
            "from": None,
            "action_word": action,
            "confirmed_by": [],
            "why": (f"the action word '{action}' proposes '{shape}', but no quote in this "
                    f"graph names both {symbol} and that interaction. An action word "
                    f"never substitutes for the quote (SKILL.md step 2, failure mode 1)."),
        }

    cited = [r["finding"] for r in rows
             if symbol_in(r.get("quote"), symbol)
             and any(p in (r.get("quote") or "").lower() for p in CATALYTIC_PHRASES)]
    if cited:
        return "catalytic function", {
            "from": "quote",
            "action_word": action,
            "confirmed_by": sorted(set(cited)),
            "why": (f"{sorted(set(cited))} name {symbol} together with an explicit "
                    f"catalytic-activity phrase."),
        }

    return None, {
        "from": None,
        "action_word": action,
        "confirmed_by": [],
        "why": ("left null: no quote in this graph states what is inhibited. The action "
                "word states intent, not an interaction, and reading the name or the "
                "verb instead of the quote is failure mode 1. Issue a `new_question` "
                "ask to fill it."),
    }


def derive_mechanism(symbol, rows):
    """mechanism_hypothesis, or null. Says WHERE to bind, and almost never known."""
    cited, terms = [], set()
    for row in rows:
        quote = (row.get("quote") or "").lower()
        if not symbol_in(quote, symbol):
            continue
        hit = [p for p in MECHANISM_PHRASES if p in quote]
        if RESIDUE_RANGE.search(quote):
            hit.append("residue range")
        if hit:
            cited.append(row["finding"])
            terms |= set(hit)
    if cited:
        return sorted(terms)[0], {
            "from": "quote", "confirmed_by": sorted(set(cited)), "terms": sorted(terms),
            "why": "a quote states the binding site or mode.",
        }
    return None, {
        "from": None, "confirmed_by": [], "terms": [],
        "why": ("left null (the dossier's `unknown`): no quote states ATP-competitive, "
                "allosteric, orthosteric, a domain or a residue range. Catalytic "
                "function does not imply orthosteric -- failure mode 5, TYK2/"
                "deucravacitinib. The dossier handles `unknown` by scoring the "
                "biological assembly and recording it in tractability.caveat."),
    }


def derive_disease_context(graph, idx):
    """A disease node if the graph has one; else a literal phrase from `question`."""
    for thing in idx["things"].values():
        if thing.get("kind") == "disease" and thing.get("name"):
            return thing["name"], {
                "from": "graph node", "thing": thing["id"],
                "why": f"thing {thing['id']} is typed `disease`.",
            }
    question = (graph.get("question") or "").lower()
    hits = [p for p in DISEASE_PHRASES if p in question]
    if hits:
        best = max(hits, key=len)
        return best, {
            "from": "question", "thing": None,
            "why": f"literal match on the graph's own question string: '{best}'.",
        }
    return None, {
        "from": None, "thing": None,
        "why": ("left null: no node is typed `disease` and no phrase in the curated "
                "list matched the question. Not guessed from surrounding words."),
    }


def thing_roles(bundle, idx):
    """Why each thing could -- or could not -- carry a target.

    Order matters: a readout rejection outranks everything. IL-6 is the object of
    a downstream-effect edge and its symbol verifies cleanly to P05231; promoting
    it would assess the cytokine the paper measured instead of the protein the
    drug acts on (failure mode 2, and failure mode 3 one step later).
    """
    things = idx["things"]
    nominated = {n["thing"] for n in bundle["nominations"]}
    readout = {r["thing"] for r in bundle["rejected"]
               if any("readout, not target" in w for w in r["why"])}
    subjects = {l["from"] for l in idx["links"].values()
                if graph_read.classify(l, things) == "direct_action"}

    roles = {}
    for tid in things:
        if tid in nominated:
            roles[tid] = ("nominated_entity_node",
                          "kind is protein/gene and the nomination rule holds")
        elif tid in readout:
            roles[tid] = ("downstream_readout",
                          "reached only by downstream-effect edges -- this is where the "
                          "effect was measured, not what the molecule acts on")
        elif tid in subjects:
            roles[tid] = ("intervention_subject",
                          "subject of a direct-action edge; an intervention node whose "
                          "name carries the target (SKILL.md failure mode 11)")
        else:
            roles[tid] = ("not_a_target_route",
                          "neither a nominated entity node nor the subject of a "
                          "direct-action edge; its symbols are proposals with no "
                          "nomination route behind them")
    return roles


PROMOTABLE_ROLES = {"nominated_entity_node", "intervention_subject"}

NO_FALLBACK = (
    "This tool does not substitute a component, paralog or family member for a "
    "symbol that did not resolve. NF-kB returns no row while NFKB1 returns P19838 "
    "and RELA returns Q04206; a fallback would return a clean row and no error, "
    "and be indistinguishable from a correct answer."
)


def run_pipeline(graph, source, args, verifier):
    idx = graph_read.index(graph)
    bundle = graph_read.build(graph)
    roles = thing_roles(bundle, idx)
    disease, disease_basis = derive_disease_context(graph, idx)

    candidates = bundle["symbol_candidates"]["candidates"]

    # One verification per distinct symbol, reused across the things that
    # mention it. MyD88 arrives from both t4 and t5.
    verified_by_key = {}
    for cand in candidates:
        key = graph_read.symbol_key(cand["symbol"])
        if key not in verified_by_key:
            verified_by_key[key] = verifier.verify(cand["symbol"], cand["query_forms"])

    # Group by thing, because ambiguity is a property of the PHRASE, not of a
    # symbol on its own.
    by_thing = {}
    for cand in candidates:
        by_thing.setdefault(cand["thing"], []).append(cand)

    dossier_inputs, unresolved, refused = [], [], []

    for tid in sorted(by_thing):
        group = by_thing[tid]
        thing = idx["things"].get(tid, {})
        role, role_why = roles.get(tid, ("unknown", ""))
        rows = evidence_rows(tid, idx)
        support, recorded = split_findings(rows)

        resolved = []
        for cand in group:
            rec = verified_by_key[graph_read.symbol_key(cand["symbol"])]
            resolved.append((cand, rec))

        unresolved_members = [f"{c['symbol']} ({r['status']})"
                              for c, r in resolved if r["status"] != "verified"]
        # SKILL.md: a phrase carrying several candidates stays ambiguous unless
        # exactly one verifies AND the rest were false regex hits. One unresolved
        # candidate keeps the whole phrase ambiguous -- MYD88 resolving cleanly
        # does not collapse "TLR/MyD88/NF-kB signalling axis" onto MYD88.
        phrase_ambiguous = len(group) > 1 and bool(unresolved_members)

        listed = [{
            "symbol": c["symbol"],
            "query_forms": c["query_forms"],
            "status": r["status"],
            "uniprot_accession": r["uniprot_accession"],
            "why": r["why"],
            "field": c["field"],
            "phrase": c["phrase"],
            "action": c["action"],
        } for c, r in resolved]

        if phrase_ambiguous:
            unresolved.append({
                "thing": tid,
                "name": thing.get("name"),
                "kind": thing.get("kind"),
                "role": role,
                "outcome": "ambiguous",
                "uniprot_accession": None,
                "candidates": listed,
                "why": (f"the phrase {thing.get('name')!r} proposes {len(group)} symbols "
                        f"and {len(unresolved_members)} of them are not verified: "
                        f"{', '.join(unresolved_members)}. An unverified candidate keeps "
                        f"the whole phrase ambiguous; one clean resolution among several "
                        f"does not collapse the phrase onto it."),
                "no_fallback": NO_FALLBACK,
                "ask": {"ask": "expand_node", "target": tid, "depth": "deep"},
            })
            continue

        for cand, rec in resolved:
            if rec["status"] != "verified":
                unresolved.append({
                    "thing": tid,
                    "name": thing.get("name"),
                    "kind": thing.get("kind"),
                    "role": role,
                    "outcome": rec["status"],
                    "uniprot_accession": None,
                    "candidates": [l for l in listed if l["symbol"] == cand["symbol"]],
                    "why": rec["why"],
                    "no_fallback": NO_FALLBACK,
                    "retrieval_failed": rec["status"] == "retrieval_failed",
                })
                continue

            if role not in PROMOTABLE_ROLES:
                refused.append({
                    "thing": tid,
                    "name": thing.get("name"),
                    "kind": thing.get("kind"),
                    "symbol": cand["symbol"],
                    "uniprot_accession_found": rec["uniprot_accession"],
                    "role": role,
                    "why": (f"the symbol verifies ({rec['uniprot_accession']}) but the "
                            f"thing carrying it is {role}: {role_why}. A verified "
                            f"accession is not a nomination."),
                })
                continue

            row = rec["rows"][0] if rec["rows"] else {}
            interaction, interaction_basis = derive_interaction(
                cand["symbol"], cand["action"], rows)
            mechanism, mechanism_basis = derive_mechanism(cand["symbol"], rows)

            caveats = []
            if bundle.get("coverage_warning"):
                caveats.append(
                    "coverage.truncated is %s with stop_reason %r -- only 'complete' "
                    "means the literature was exhausted, so nothing missing from this "
                    "graph is established as absent." % (
                        bundle["coverage_warning"].get("truncated"),
                        bundle["coverage_warning"].get("stop_reason")))
            if role == "intervention_subject":
                caveats.append(
                    "the accession was recovered from a node NAME, not from a "
                    "protein/gene node -- this graph has none. The regex proposed it "
                    "and UniProt confirmed it; the node itself was never typed as a "
                    "target.")
            if not support:
                caveats.append("no supporting finding on any link touching this thing.")

            dossier_inputs.append({
                "uniprot_accession": rec["uniprot_accession"],
                "gene_symbol": row.get("gene_name") or cand["symbol"],
                "protein_name": row.get("protein_name"),
                "organism": row.get("organism"),
                "sequence_length": row.get("sequence_length"),
                "disease_context": disease,
                "disease_context_basis": disease_basis,
                "interaction_to_disrupt": interaction,
                "interaction_to_disrupt_basis": interaction_basis,
                "mechanism_hypothesis": mechanism,
                "mechanism_hypothesis_basis": mechanism_basis,
                # CLAUDE.md rule 0: a target that came from literature is a
                # nomination, not a fact, and the dossier must be able to show
                # which quotes put this protein on the page.
                "nomination_provenance": {
                    "graph_id": graph.get("graph_id"),
                    "round": graph.get("round"),
                    "thing": tid,
                    "thing_name": thing.get("name"),
                    "thing_kind": thing.get("kind"),
                    "route": role,
                    "symbol_as_written": cand["symbol"],
                    "symbol_field": cand["field"],
                    "symbol_phrase": cand["phrase"],
                    "supporting_findings": support,
                    "recorded_not_acted_on": recorded,
                    "verified_by": (
                        f"paperclip sql -s proteins, uniprot_v.proteins, "
                        f"organism = 'Homo sapiens': {rec['why']}"),
                },
                "caveats": caveats,
            })

    # Rejections the traversal already made, carried through rather than dropped.
    for rej in bundle["rejected"]:
        if rej["thing"] in by_thing:
            continue
        refused.append({
            "thing": rej["thing"],
            "name": rej["name"],
            "kind": idx["things"].get(rej["thing"], {}).get("kind"),
            "symbol": None,
            "uniprot_accession_found": None,
            "role": roles.get(rej["thing"], ("unknown", ""))[0],
            "why": "; ".join(rej["why"]) + ". No gene-symbol-shaped token in its name "
                                           "or aliases either, so there is nothing to verify.",
        })

    return {
        "tool": "run_intake.py",
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                                 .replace(microsecond=0).isoformat(),
        "source": source,
        "graph": {
            "graph_id": graph.get("graph_id"),
            "round": graph.get("round"),
            "schema_version": graph.get("schema_version"),
            "question": graph.get("question"),
            "status": bundle["status"],
            "status_warning": bundle["status_warning"],
            "coverage_warning": bundle["coverage_warning"],
            "is_fixture": bool(graph.get("_fixture")),
        },
        "store_integrity": store_integrity(graph),
        "traversal": {
            "nominations_from_entity_nodes": [
                {"thing": n["thing"], "name": n["name"], "kind": n["kind"]}
                for n in bundle["nominations"]
            ],
            "needs_adjudication": bundle["needs_adjudication"],
            "orphan_findings": bundle["orphan_findings"],
            "retracted_papers": bundle["retracted_papers"],
            "symbol_candidates_proposed": len(candidates),
        },
        "verification": {
            "mode": "dry_run" if args.dry_run else "live",
            "paperclip": verifier.paperclip,
            "env_file": args.env_file_used,
            "timeout_s": verifier.timeout,
            "retries": verifier.retries,
            "batching": ONE_AT_A_TIME,
            "symbols": [verified_by_key[k] for k in sorted(verified_by_key)],
            "queries": verifier.log,
        },
        "dossier_inputs": dossier_inputs,
        "unresolved": unresolved,
        "refused": refused,
    }


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def rule(char="-", width=78):
    return char * width


def wrap(text, indent=4, width=78):
    words, lines, cur = (text or "").split(), [], ""
    pad = " " * indent
    for w in words:
        if cur and len(cur) + 1 + len(w) > width - indent:
            lines.append(pad + cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(pad + cur)
    return lines


def render(report):
    g, out = report["graph"], []
    out.append(rule("="))
    out.append("graph-intake  ->  dossier inputs")
    out.append(rule("="))

    src = report["source"]
    where = (f"store {src['store']} / {src['graph_id']}" if src["mode"] == "store"
             else f"file {src['path']}")
    out.append(f"source     : {where}")
    if src["mode"] == "store":
        out += wrap(src["note"], indent=13)
    out.append(f"graph_id   : {g['graph_id']}   round {g['round']}   schema {g['schema_version']}")
    out.append(f"status     : {g['status']}")
    if g["status_warning"]:
        out += wrap(g["status_warning"], indent=13)
    if g["is_fixture"]:
        out += wrap("_fixture: true -- papers, DOIs and quotes here were never "
                    "retrieved from any corpus. Never cite them.", indent=13)
    out.append("question   :")
    out += wrap(g["question"] or "(none)", indent=13)

    cw = g["coverage_warning"]
    if cw:
        out.append("")
        out.append(f"coverage   : truncated={cw.get('truncated')}  "
                   f"stop_reason={cw.get('stop_reason')!r}  depth={cw.get('depth')!r}")
        out += wrap(cw.get("note"), indent=13)

    if report["store_integrity"]:
        out.append("")
        out.append("STORE INTEGRITY")
        for key, val in report["store_integrity"].items():
            out.append(f"  {key}:")
            out += wrap(json.dumps(val) if not isinstance(val, str) else val, indent=6)

    tr = report["traversal"]
    out.append("")
    out.append(rule())
    out.append("STEP 2 - TRAVERSAL (graph_read)")
    out.append(rule())
    noms = tr["nominations_from_entity_nodes"]
    out.append(f"  nominations from protein/gene nodes : {len(noms)}")
    for n in noms:
        out.append(f"      {n['thing']}  {n['name']}  (kind {n['kind']})")
    if not noms:
        out += wrap("zero -- reported alongside status %r above, never on its own. "
                    "The second route (symbols inside entity names) runs next."
                    % g["status"], indent=6)
    out.append(f"  symbol candidates proposed          : {tr['symbol_candidates_proposed']}")
    out.append(f"  needs_adjudication                  : {len(tr['needs_adjudication'])}")
    for a in tr["needs_adjudication"]:
        out.append(f"      {a['link']}  how={a['how']!r}  {a['subject']['name']} -> "
                   f"{a['object']['name']} (kind {a['object']['kind']})")
        out += wrap("unrecognised verb: decide direct action vs downstream readout "
                    "from the quotes. Refusing is allowed; guessing is not.", indent=10)
    out.append(f"  orphan findings (no link)           : "
               f"{[o['finding'] for o in tr['orphan_findings']] or 'none'}")
    for o in tr["orphan_findings"]:
        out += wrap(f"{o['finding']}: {o['why']}", indent=6)
    out.append(f"  retracted papers                    : {tr['retracted_papers'] or 'none'}")

    v = report["verification"]
    out.append("")
    out.append(rule())
    out.append(f"STEP 3 - UNIPROT VERIFICATION  [{v['mode']}]")
    out.append(rule())
    if v["mode"] == "dry_run":
        out += wrap("--dry-run: no paperclip call was made. Nothing below is a "
                    "statement about what UniProt contains. Every symbol is "
                    "'skipped', which is neither 'verified' nor 'absent'.", indent=2)
    else:
        out.append(f"  paperclip : {v['paperclip']}")
        out.append(f"  env       : {v['env_file']}")
        out.append(f"  timeout   : {v['timeout_s']}s   retries: {v['retries']}")
        out += wrap(v["batching"], indent=2)
    out.append("")
    for s in v["symbols"]:
        acc = s["uniprot_accession"] or "-"
        out.append(f"  {s['symbol']:<12} {s['status']:<17} {acc}")
        out += wrap(s["why"], indent=6)
    if v["mode"] != "dry_run":
        failed = [q for q in v["queries"] if q["status"] == "retrieval_failed"]
        retried = [q for q in v["queries"] if len(q["attempts"]) > 1]
        if retried:
            out.append("")
            out.append("  retries were needed:")
            for q in retried:
                errs = [a.get("error") for a in q["attempts"] if not a.get("ok")]
                out.append(f"      {q['query_form']:<12} {len(q['attempts'])} attempts "
                           f"-> {q['status']}")
                for e in errs:
                    out += wrap(e, indent=10)
        if failed:
            out.append("")
            out += wrap("FAILED RETRIEVALS remain: %s. These are NOT absences."
                        % ", ".join(q["query_form"] for q in failed), indent=2)

    out.append("")
    out.append(rule())
    out.append(f"STEP 4 - DOSSIER INPUTS ({len(report['dossier_inputs'])})")
    out.append(rule())
    if not report["dossier_inputs"]:
        out += wrap("none. See UNRESOLVED and REFUSED below for why -- an empty list "
                    "here is only meaningful next to the graph status above.", indent=2)
    for d in report["dossier_inputs"]:
        out.append("")
        out.append(f"  {d['gene_symbol']}  ->  {d['uniprot_accession']}")
        out.append(f"      protein_name           : {d['protein_name']}")
        out.append(f"      organism               : {d['organism']}  "
                   f"({d['sequence_length']} aa)")
        out.append(f"      disease_context        : {d['disease_context']!r}")
        out += wrap(d["disease_context_basis"]["why"], indent=10)
        out.append(f"      interaction_to_disrupt : {d['interaction_to_disrupt']!r}")
        out += wrap(d["interaction_to_disrupt_basis"]["why"], indent=10)
        out.append(f"      mechanism_hypothesis   : {d['mechanism_hypothesis']!r}")
        out += wrap(d["mechanism_hypothesis_basis"]["why"], indent=10)
        p = d["nomination_provenance"]
        out.append(f"      nomination_provenance  : graph {p['graph_id']} round "
                   f"{p['round']} thing {p['thing']} via {p['route']}")
        out.append(f"          symbol read from {p['symbol_field']} of "
                   f"{p['symbol_phrase']!r} as {p['symbol_as_written']!r}")
        out.append(f"          supporting findings   : {p['supporting_findings'] or 'none'}")
        out.append(f"          recorded, not acted on: {p['recorded_not_acted_on'] or 'none'}")
        out += wrap(p["verified_by"], indent=10)
        for c in d["caveats"]:
            out.append("      caveat:")
            out += wrap(c, indent=10)

    out.append("")
    out.append(rule())
    out.append(f"UNRESOLVED ({len(report['unresolved'])})")
    out.append(rule())
    if not report["unresolved"]:
        out.append("  none")
    for u in report["unresolved"]:
        out.append("")
        out.append(f"  {u['thing']}  {u['name']}  (kind {u['kind']}, role {u['role']})")
        out.append(f"      outcome            : {u['outcome']}")
        out.append(f"      uniprot_accession  : {u['uniprot_accession']}")
        out += wrap(u["why"], indent=6)
        for c in u["candidates"]:
            out.append(f"        - {c['symbol']:<10} {c['status']:<17} "
                       f"{c['uniprot_accession'] or '-'}   forms {c['query_forms']}")
            out += wrap(c["why"], indent=12)
        out += wrap(u["no_fallback"], indent=6)
        if u.get("ask"):
            out.append(f"      suggested ask      : {json.dumps(u['ask'])}")

    out.append("")
    out.append(rule())
    out.append(f"REFUSED / NOT PROMOTED ({len(report['refused'])})")
    out.append(rule())
    if not report["refused"]:
        out.append("  none")
    for r in report["refused"]:
        sym = f" [{r['symbol']} -> {r['uniprot_accession_found']}]" if r["symbol"] else ""
        out.append(f"  {r['thing']}  {r['name']}  (kind {r['kind']}){sym}")
        out += wrap(r["why"], indent=6)

    out.append("")
    out.append(rule("="))
    out.append(f"EXIT {report['exit_code']} - {report['exit_reason']}")
    out.append(rule("="))
    return "\n".join(out)


def decide_exit(report, dry_run):
    g = report["graph"]
    if g["status"] != "ok":
        return 1, (f"graph status is {g['status']!r}, not 'ok'. Zero or few results "
                   f"here are not evidence about the literature.")
    if dry_run:
        return 0, ("--dry-run: the graph loaded and traversed, and verification was "
                   "skipped. 'Nothing resolved' is a skipped step, not a result, so "
                   "this does not fail. Re-run without --dry-run to use as a check.")
    if not report["dossier_inputs"]:
        failed = [s["symbol"] for s in report["verification"]["symbols"]
                  if s["status"] == "retrieval_failed"]
        if failed:
            return 2, (f"nothing resolved, and {failed} were FAILED RETRIEVALS rather "
                       f"than absences. Re-run before concluding anything.")
        return 2, "nothing resolved to a dossier input."
    return 0, (f"{len(report['dossier_inputs'])} dossier input(s); "
               f"{len(report['unresolved'])} unresolved; "
               f"{len(report['refused'])} refused.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("graph source")
    src.add_argument("--graph", help="path to a single upstream graph JSON")
    src.add_argument("--store", help="the mapper's store dir (holds index.json)")
    src.add_argument("--graph-id", help="graph id to load from --store")
    ap.add_argument("--allow-fixture", action="store_true",
                    help="permit a graph carrying _fixture: true (test runs only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="skip every network call; offline testing only")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--paperclip", default=PAPERCLIP, help="path to the paperclip CLI")
    ap.add_argument("--env-file", help="path to the .env holding PAPERCLIP_API_KEY")
    ap.add_argument("--timeout", type=int, default=45,
                    help="seconds per paperclip call (default 45)")
    ap.add_argument("--retries", type=int, default=2,
                    help="retries per query form after the first attempt (default 2)")
    args = ap.parse_args()

    try:
        graph, source = load_graph(args)
    except SystemExit as exc:
        # graph_store.load raises SystemExit on an unknown graph_id, and so do
        # the source checks above. Exit 3 (could not load) rather than 1, which
        # means something specific: the graph loaded and its status was not ok.
        sys.stderr.write(f"{exc}\n")
        return 3
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"refusing: could not load the graph: {exc}\n")
        return 3

    if graph.get("_fixture") and not args.allow_fixture:
        sys.stderr.write(
            "refusing: graph carries _fixture: true, so its papers and quotes are "
            "synthetic. Re-run with --allow-fixture for a test.\n")
        return 3

    env = None
    args.env_file_used = None
    if not args.dry_run:
        try:
            env_path = resolve_env_file(args.env_file)
        except SystemExit as exc:
            sys.stderr.write(f"{exc}\n")
            return 3
        args.env_file_used = env_path
        env = dict(os.environ)
        if env_path:
            env.update(parse_env_file(env_path))
        if not env.get("PAPERCLIP_API_KEY"):
            sys.stderr.write(
                "warning: PAPERCLIP_API_KEY not found in the environment or in "
                f"{env_path!r}. Lookups will most likely fail, and a failed lookup "
                "is recorded as a FAILED RETRIEVAL, never as an absent symbol.\n")

    verifier = UniProtVerifier(
        paperclip=args.paperclip, timeout=args.timeout, retries=args.retries,
        env=env, dry_run=args.dry_run)

    report = run_pipeline(graph, source, args, verifier)
    code, reason = decide_exit(report, args.dry_run)
    report["exit_code"], report["exit_reason"] = code, reason

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render(report) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
