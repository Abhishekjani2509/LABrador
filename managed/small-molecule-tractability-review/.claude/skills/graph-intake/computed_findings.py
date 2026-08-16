#!/usr/bin/env python3
"""The `computed_finding` record type — a result our methods produced, in a shape
that cannot be mistaken for a literature finding.

Our methods generate knowledge the literature does not have: measured pocket
volumes, interface residues, cryptic-mechanism classifications, cofold results.
That knowledge should be able to flow back to a graph, so the graph is enriched
by computation and not only by reading. This file is the record type that makes
the flow safe, and SKILL.md failure mode 9 is the rule it implements.

Three constraints, all structural rather than advisory:

1. NO `quote` FIELD EXISTS. SCHEMA.md's one mechanical guarantee is that every
   `findings[].quote` was string-matched against the fetched abstract before the
   finding was written, with failures dropped into `coverage.no_quote_discarded`.
   A computed result has provenance and no sentence. The field is absent, not
   empty, so a consumer reaching for `record["quote"]` raises KeyError instead of
   reading a method string as something a paper said.
2. `computed_confidence`, NOT `confidence`. Upstream `confidence` is how strongly
   a paper states a claim. Ours is measurement uncertainty. The names are kept
   apart because the numbers are not comparable and averaging them yields a
   figure that means nothing. Capped at 0.6, the same cap SCHEMA.md puts on gaps
   -- "a proposal, not a finding".
3. `leakage_risk` IS REQUIRED, with a `leakage_basis`. Laundering is the real
   hazard: a cofold contaminated by PDB training data re-entering as an ordinary
   finding on a later round is literature-grade evidence with the flag gone. For
   a cofold the question is whether the complex is already deposited; if it is,
   the result is a method check and never evidence.

Nothing here writes to a graph, and nothing here is a literature finding. See
`feedback_guard()` -- the answer for a `findings` slot is always no, with reasons.

Usage:
    python3 computed_findings.py <records.json>
    python3 computed_findings.py <records.json> --strict
    python3 computed_findings.py <records.json> --json
"""

import argparse
import json
import sys

# The discriminator. A consumer branches on this before touching anything else.
KIND = "computed"

# Same cap SCHEMA.md applies to `gaps[].confidence` ("capped at 0.6 -- a proposal,
# not a finding"), for the same reason: a computed result is a measurement about
# a structure, never a statement about the literature.
CONFIDENCE_CAP = 0.6

# Closed on purpose, unlike the upstream `how`. `how` is open vocabulary written
# by an extraction model, so graph_read.py must route unknown verbs to
# adjudication. This vocabulary is OURS -- it names methods we run -- so an
# unrecognised value is a typo or an undeclared method, and both should fail.
RESULT_TYPES = {
    "pocket_volume",
    "pocket_druggability",
    "pocket_vs_interface",
    "interface_residues",
    "cryptic_mechanism",
    "backbone_displacement",
    "cofold_transfer",
    "cofold_control",
    "affinity_prediction",
    "ensemble_consensus",
}

# Upstream literature-finding field names. Their presence on a computed record is
# the laundering attempt itself, so each is rejected by name with the reason,
# rather than being silently ignored as an unknown key.
FORBIDDEN_FIELDS = {
    "quote": (
        "a computed result has no verbatim sentence. SCHEMA.md string-matches "
        "every quote against the fetched abstract; a method string would pass "
        "into a `findings` slot as something a paper said"
    ),
    "confidence": (
        "means 'how strongly a paper states this' upstream and 'measurement "
        "uncertainty' here. Use `computed_confidence`; the two must never be "
        "averaged or compared"
    ),
    "says": "yes|no|no_effect describes a claim in a paper, not a measurement",
    "paper": "no paper produced this; provenance.method and run_id did",
    "section": "abstract|results|methods refers to a document this record has none of",
    "hedged": "hedging is a property of prose, not of a number",
    "is_own_result": "this is always our own result; the flag would be vacuous and misleading",
    "flags": "upstream label vocabulary; use `notes`",
    "round": "computed results are not produced by a search round",
}

ALLOWED_FIELDS = {
    "kind",
    "id",
    "result_type",
    "about",
    "statement",
    "value",
    "units",
    "computed_confidence",
    "computed_confidence_capped_from",
    "leakage_risk",
    "leakage_basis",
    "provenance",
    "sources",
    "notes",
    "supersedes",
}

REQUIRED_FIELDS = [
    "kind", "id", "result_type", "about", "statement", "value", "units",
    "computed_confidence", "leakage_risk", "leakage_basis", "provenance",
    "sources",
]

# Rule 10 of the node: every numeric claim carries a source. A number with no
# method, no version, no inputs or no run id is unreproducible, so it is rejected
# at construction rather than carried with a caveat.
PROVENANCE_REQUIRED = ["method", "version", "inputs", "run_id"]
PROVENANCE_OPTIONAL = ["run_date", "parameters_note"]


class ComputedFindingError(ValueError):
    """Raised by to_record(). Carries every problem, not just the first."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def cap_confidence(value):
    """Returns (capped, original_if_capped).

    The cap is applied here rather than trusted to callers, and the original is
    kept on the record so a clamped 0.9 is visible as a clamped 0.9 instead of
    reading as a deliberate 0.6.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value, None
    if value > CONFIDENCE_CAP:
        return CONFIDENCE_CAP, float(value)
    return float(value), None


def is_number(value):
    """bool is an int in Python. A True `value` is a category, not a measurement."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(record):
    """Every problem with this record, as a list of strings. Empty list = valid.

    Returns rather than raises, so a whole file can be checked in one pass and
    every failure reported at once.
    """
    problems = []

    if not isinstance(record, dict):
        return ["record is not a JSON object"]

    # --- discriminator ------------------------------------------------------
    if "kind" not in record:
        problems.append("missing `kind` -- without the discriminator this is indistinguishable from a literature finding")
    elif record.get("kind") != KIND:
        problems.append(f"`kind` is {record.get('kind')!r}, must be exactly {KIND!r}")

    # --- laundering: upstream field names ------------------------------------
    for field in FORBIDDEN_FIELDS:
        if field in record:
            problems.append(f"forbidden field `{field}`: {FORBIDDEN_FIELDS[field]}")

    # Underscore keys are fixture annotation (`_expect`, `_source`, `_why`) and
    # are ignored, matching the convention the other fixtures in this repo use.
    for key in record:
        if key.startswith("_") or key in FORBIDDEN_FIELDS:
            continue
        if key not in ALLOWED_FIELDS:
            problems.append(f"unknown field `{key}` -- the record type is closed, so an unrecognised key is an undeclared claim")

    for field in REQUIRED_FIELDS:
        if field not in record:
            problems.append(f"missing required field `{field}`")

    # --- identity and type ---------------------------------------------------
    if "id" in record and not (isinstance(record["id"], str) and record["id"].strip()):
        problems.append("`id` must be a non-empty string")

    if "result_type" in record and record["result_type"] not in RESULT_TYPES:
        problems.append(
            f"`result_type` {record['result_type']!r} is not one of "
            f"{sorted(RESULT_TYPES)} -- this vocabulary is ours and is closed"
        )

    # --- what it is about ----------------------------------------------------
    about = record.get("about")
    if "about" in record:
        if not isinstance(about, dict):
            problems.append("`about` must be an object")
        else:
            accession = about.get("uniprot_accession")
            if not (isinstance(accession, str) and accession.strip()):
                problems.append("`about.uniprot_accession` is required -- a result about nothing identifiable cannot be attached to anything")
            pdb_ids = about.get("pdb_ids")
            if pdb_ids is not None and not isinstance(pdb_ids, list):
                problems.append("`about.pdb_ids` must be a list when present")
            for key in about:
                if key not in ("uniprot_accession", "pdb_ids", "chains", "site"):
                    problems.append(f"unknown field `about.{key}`")

    # --- the statement is prose, and says so ---------------------------------
    statement = record.get("statement")
    if "statement" in record and not (isinstance(statement, str) and statement.strip()):
        problems.append("`statement` must be a non-empty string -- it is our summary of the result, NOT a quotation from anywhere")

    # --- value and units -----------------------------------------------------
    if "value" in record:
        value = record["value"]
        if value is None:
            problems.append("`value` is null -- a record with no result is not a result. Use 0.0 if the measurement returned zero")
        elif is_number(value):
            # 0.00 A^3 is a RESULT, not a missing value: mdpocket returned exactly
            # that at the true SPD304 site in four of five apo TNF-alpha trimers,
            # and reporting it is the point. So this branch never tests falsiness.
            units = record.get("units")
            if not (isinstance(units, str) and units.strip()):
                problems.append("`units` is required and must be a non-empty string when `value` is numeric -- a bare number is not a measurement")
        elif isinstance(value, str):
            if record.get("units") is not None:
                problems.append("`units` must be null when `value` is a category rather than a number")
        else:
            problems.append("`value` must be a number or a category string")

    # --- confidence, ours, capped -------------------------------------------
    cc = record.get("computed_confidence")
    if "computed_confidence" in record:
        if not is_number(cc):
            problems.append("`computed_confidence` must be a number")
        elif not 0.0 <= cc <= CONFIDENCE_CAP:
            problems.append(
                f"`computed_confidence` is {cc}, outside 0.0-{CONFIDENCE_CAP}. The cap "
                f"mirrors SCHEMA.md's cap on gaps: a computed result is a proposal, not a finding"
            )
    capped_from = record.get("computed_confidence_capped_from")
    if capped_from is not None and not is_number(capped_from):
        problems.append("`computed_confidence_capped_from` must be a number or absent")

    # --- leakage: required, with a reason ------------------------------------
    if "leakage_risk" in record and not isinstance(record["leakage_risk"], bool):
        problems.append("`leakage_risk` must be a boolean -- null or absent would let a contaminated result travel unlabelled")
    basis = record.get("leakage_basis")
    if "leakage_basis" in record and not (isinstance(basis, str) and basis.strip()):
        problems.append("`leakage_basis` must be a non-empty string -- the flag alone does not say what was checked")
    elif isinstance(basis, str) and len(basis.strip()) < 20:
        problems.append("`leakage_basis` is too short to be a basis -- name what was checked (for a cofold: is the complex already deposited?)")

    # --- provenance ----------------------------------------------------------
    prov = record.get("provenance")
    if "provenance" in record:
        if not isinstance(prov, dict):
            problems.append("`provenance` must be an object")
        else:
            for field in PROVENANCE_REQUIRED:
                if field not in prov:
                    problems.append(f"missing `provenance.{field}` -- rule 10: every numeric claim carries a source")
            for field in ("method", "version", "run_id"):
                got = prov.get(field)
                if field in prov and not (isinstance(got, str) and got.strip()):
                    problems.append(f"`provenance.{field}` must be a non-empty string")
            inputs = prov.get("inputs")
            if "inputs" in prov and (not isinstance(inputs, dict) or not inputs):
                problems.append("`provenance.inputs` must be a non-empty object naming what the method was run on -- PDB ids, accessions, parameters")
            for key in prov:
                if key not in PROVENANCE_REQUIRED + PROVENANCE_OPTIONAL:
                    problems.append(f"unknown field `provenance.{key}`")

    # --- sources -------------------------------------------------------------
    sources = record.get("sources")
    if "sources" in record:
        if not isinstance(sources, list) or not sources:
            problems.append("`sources` must be a non-empty list -- rule 10: a figure without provenance must not appear")
        elif not all(isinstance(s, str) and s.strip() for s in sources):
            problems.append("every entry in `sources` must be a non-empty string")

    for field in ("notes", "supersedes"):
        if field in record and record[field] is not None and not isinstance(record[field], str):
            problems.append(f"`{field}` must be a string or null")

    return problems


def to_record(record_id, result_type, about, statement, value, units,
              computed_confidence, leakage_risk, leakage_basis,
              method, version, inputs, run_id, sources,
              run_date=None, parameters_note=None, notes=None, supersedes=None):
    """Build a computed_finding, or raise.

    The provenance quartet is positional and unavoidable: a caller cannot
    construct a number without naming the method, its version, what it ran on and
    which run produced it. The confidence cap is applied here rather than trusted
    to the caller. Raises ComputedFindingError carrying every problem found.
    """
    confidence, capped_from = cap_confidence(computed_confidence)

    record = {
        "kind": KIND,
        "id": record_id,
        "result_type": result_type,
        "about": about,
        "statement": statement,
        "value": value,
        "units": units,
        "computed_confidence": confidence,
        "leakage_risk": leakage_risk,
        "leakage_basis": leakage_basis,
        "provenance": {
            "method": method,
            "version": version,
            "inputs": inputs,
            "run_id": run_id,
        },
        "sources": sources,
    }
    if capped_from is not None:
        record["computed_confidence_capped_from"] = capped_from
    if run_date is not None:
        record["provenance"]["run_date"] = run_date
    if parameters_note is not None:
        record["provenance"]["parameters_note"] = parameters_note
    if notes is not None:
        record["notes"] = notes
    if supersedes is not None:
        record["supersedes"] = supersedes

    problems = validate(record)
    if problems:
        raise ComputedFindingError(problems)
    return record


def evidence_role(record):
    """What this record is allowed to be, once valid.

    A flagged cofold is a method check and nothing else: if the complex is
    already in the PDB, recovering it measures recall of the training set, not
    the biology. CLAUDE.md carries the same sentence on
    `pocket_neighbour_precedent.cofold_transfer.leakage_note`.
    """
    if record.get("leakage_risk") is True:
        return "method_check_only"
    return "computed_annotation"


def feedback_guard(record):
    """Is it safe to feed this back into graph-intake?

    For a literature-finding slot the answer is always no, and the reasons are
    returned rather than assumed known. The record may still travel -- as a
    computed annotation carried alongside a nomination, where its provenance and
    its leakage flag stay attached.
    """
    problems = validate(record)

    why_not = [
        "an upstream `findings` row requires a verbatim `quote`, string-matched "
        "against the fetched abstract before it is written (SCHEMA.md, "
        "guarantees). This record has no quote and cannot acquire one; a "
        "`statement` is our prose, not a sentence from a paper",
        "`computed_confidence` is measurement uncertainty; upstream `confidence` "
        "is how strongly a paper states a claim. Feeding one in as the other "
        "produces a number that means nothing, and it would then flow into "
        "`links.confidence` arithmetic",
        "`leakage_risk` and `leakage_basis` have no home in the upstream schema, "
        "so they would be dropped on the way in. That drop is the laundering: "
        "the flag disappears and the result reads as literature-grade evidence "
        "on the next round",
    ]
    if record.get("leakage_risk") is True:
        why_not.append(
            "this record is flagged for leakage -- "
            + str(record.get("leakage_basis"))
            + " -- so it is a method check and is not evidence in ANY slot, "
            "computed or literature"
        )

    role = evidence_role(record) if not problems else None
    return {
        "safe_as_literature_finding": False,
        "why_not": why_not,
        "safe_as_computed_annotation": not problems and record.get("leakage_risk") is False,
        "role": role,
        "problems": problems,
        "refusal": (
            "Never write a computed_finding into `findings`, `yes`, `no` or "
            "`no_effect`. If the graph should learn from it, that is a new record "
            "type in the upstream schema, negotiated -- not a finding with the "
            "quote left blank."
        ),
    }


def load(path):
    """Accepts a bare list, or an object carrying `computed_findings`."""
    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("computed_findings"), list):
        return data["computed_findings"]
    raise SystemExit(
        f"{path}: expected a JSON list, or an object with a `computed_findings` list"
    )


def check_all(records):
    rows = []
    for n, record in enumerate(records):
        problems = validate(record)
        rid = record.get("id") if isinstance(record, dict) else None
        expect = record.get("_expect") if isinstance(record, dict) else None
        rows.append({
            "index": n,
            "id": rid or f"<no id, record {n}>",
            "result_type": record.get("result_type") if isinstance(record, dict) else None,
            "valid": not problems,
            "problems": problems,
            "expect": expect,
            "expectation_met": None if expect not in ("accept", "reject")
            else (expect == "accept") == (not problems),
            "role": evidence_role(record) if isinstance(record, dict) and not problems else None,
            "leakage_risk": record.get("leakage_risk") if isinstance(record, dict) else None,
            "computed_confidence": record.get("computed_confidence") if isinstance(record, dict) else None,
            "note": record.get("_note") if isinstance(record, dict) else None,
        })
    return rows


def report(rows, path):
    out = []
    out.append(f"computed_findings: {len(rows)} record(s) from {path}")
    out.append("")
    for row in rows:
        verdict = "PASS" if row["valid"] else "FAIL"
        expect = f"  expected: {row['expect']}" if row["expect"] else ""
        out.append(f"[{verdict}] {row['id']}  ({row['result_type']}){expect}")
        if row["valid"]:
            out.append(
                f"        role={row['role']}  leakage_risk={json.dumps(row['leakage_risk'])}  "
                f"computed_confidence={row['computed_confidence']}"
            )
            if row["leakage_risk"] is True:
                out.append("        NOT EVIDENCE -- method check only, in any slot")
        else:
            for problem in row["problems"]:
                out.append(f"        - {problem}")
        if row["note"]:
            out.append(f"        note: {row['note']}")
        if row["expectation_met"] is False:
            out.append("        !! EXPECTATION NOT MET")
        out.append("")

    accepted = sum(1 for r in rows if r["valid"])
    checked = [r for r in rows if r["expectation_met"] is not None]
    matched = sum(1 for r in checked if r["expectation_met"])
    out.append(f"{accepted} accepted, {len(rows) - accepted} rejected.")
    if checked:
        out.append(f"expectations: {matched}/{len(checked)} matched.")
    out.append(
        "feedback guard: 0 of %d may enter an upstream `findings` slot -- no quote "
        "exists, and `computed_confidence` is not the upstream `confidence`."
        % len(rows)
    )
    flagged = [r["id"] for r in rows if r["valid"] and r["leakage_risk"] is True]
    if flagged:
        out.append(
            "leakage-flagged (method check only, never evidence): " + ", ".join(flagged)
        )
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("records", help="path to a computed_findings JSON file")
    ap.add_argument("--json", action="store_true",
                    help="emit the per-record result as JSON instead of text")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any record fails, even one marked _expect: reject")
    args = ap.parse_args()

    rows = check_all(load(args.records))

    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(report(rows, args.records) + "\n")

    # A file whose invalid record was rejected has behaved correctly, so the
    # default exit code follows the EXPECTATIONS, not the pass count. --strict is
    # for pipelines that carry no deliberately-invalid records.
    if any(row["expectation_met"] is False for row in rows):
        sys.exit(1)
    if args.strict and any(not row["valid"] for row in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
