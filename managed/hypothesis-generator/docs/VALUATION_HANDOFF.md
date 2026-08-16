# Handing a slate to the valuation stage

`managed/program-strategy-valuation/` (LABrador) is the downstream evaluator: a
provenance-aware program brief goes in, and rNPV, protected years, payer access,
patient affordability and a decision grade come out. `src/hyp_gen/valuation.py`
is the adapter between the two.

```bash
hypgen --graph fixtures/example_graph.json --emit-frame-template frame.json
$EDITOR frame.json                       # the four year fields are null on purpose

hypgen --graph fixtures/example_graph.json --profile valuation --dry-run \
       --emit-programs out/ --frame frame.json

labrador analyze out/g_demo1-metformin.program.json \
         --comparables out/comparables.json --simulations 200 --seed 42
labrador portfolio out/*.program.json --comparables out/comparables.json \
         --simulations 200 --seed 42 --sort-by p50_rnpv --descending
```

## What the two halves each know

The join is narrower than it looks, and being honest about where it is narrow is
the entire design.

| LABrador needs | Where it comes from |
|---|---|
| `program_name`, `molecule_identifier` | the graph — subject node |
| `modality` | the graph, but only for `small_molecule`; otherwise the frame |
| `target` | the graph — first protein/gene node the path crosses |
| `initial_indication.name` | the graph — the disease endpoint |
| evidence provenance | the graph — papers, findings, study types, verbatim quotes |
| currency, geography, route, line of therapy, years, stage | **the analyst frame** |
| population, access, income bands | **nobody** — emitted empty |
| prices and comparables | **nobody** — an empty catalogue is emitted |
| development costs, durations, probabilities | **nobody** — emitted empty |

A literature knowledge graph is about mechanism. It contains no epidemiology, no
payer behaviour and no price of any basis, and the adapter's job is to say so in
a shape LABrador can read rather than to fill the holes.

**A `NOT_DECISION_GRADE` result is the success case.** On the demo graph a
pirfenidone program comes back with `decision_grade: NOT_DECISION_GRADE`,
`recommendation: NOT_DECISION_GRADE`, 44 named unsupported critical inputs and
one number that is genuinely supported — `effective_protected_years: 8.0`, from
the frame's filing year. That itemised gap list *is* the output. It is the work
order for the analyst, and it is what you would lose by letting the adapter guess.

## The rules the adapter enforces

**Evidence keys are namespaced, and that is a safety property, not tidiness.**
LABrador decides whether a critical input is supported by looking up a specific
field name in an `evidence` dict — `eligible_patients`, `coverage_fraction`,
`patent_inputs`, `willingness_to_pay_per_qaly`, and so on. Every record this
adapter writes is keyed `hypothesis:`, `mechanism:`, `finding:`, `paper:` or
`frame:`, so a graph-derived citation cannot land under one of them. Without
this, a paper showing that pirfenidone inhibits TGF-β1 could clear the
eligible-patient gate, and a program that should read `NOT_DECISION_GRADE` would
come back `DECISION_GRADE` with a real citation attached — silently, and in a
form that survives review. `LABRADOR_GATE_KEYS` lists the reserved names and
`test_no_emitted_evidence_key_can_clear_a_labrador_gate` enforces it.

**Study type sets the ceiling; the discounts only go down.** `clinical_trial` and
`meta_analysis` map to `HIGH`, `human_cohort` to `MODERATE`, `animal` and
`test_tube` to `LOW`, `computational` to `VERY_LOW`. Hedging, secondhand
reporting and preprint status each cost one rung and they compose. LABrador
clears a gate only on `HIGH`/`MODERATE`, which puts bench work below the line —
correct, since a mouse result should never make a payer-facing input
decision-grade.

**A publication year is not a date.** The graph carries a year; LABrador's
`source_date` is a `date`. Writing `2019-01-01` would manufacture ten months of
precision no source states, so `source_date` is left unset and the year survives
in the citation string where it reads as a year.

**Nothing is ever marked `synthetic`.** That flag means fabricated demo data.
Graph-derived provenance is often weak and sometimes unsupported, but it is not
fabricated, and mislabelling it would make a real citation look like a fixture.

**Two hypotheses about one molecule are two labels, not two programs.** Emitting
them separately would give one molecule two patent clocks and two development
budgets — precisely the double count LABrador's "a label expansion does not
restart the 20-year term" rule exists to prevent. They are grouped into
`initial_indication` + `expansion_indications[0]`, ranked by `rank_score`.
LABrador models exactly one expansion, so a third label is reported as
`labrador_two_label_limit` in `emission.json` rather than dropped.

**The frame is mandatory.** There is no default. `--emit-programs` without
`--frame` is an error, and the template's four year fields are `null` so it fails
validation until a human fills them in. A guessed `filing_year` is
indistinguishable from a sourced one once it is in the JSON, and it moves the
protected window — the one number in the whole result the graph-plus-frame can
actually support.

## Failure modes

The longest section, because the procedure above is the easy half.

**A `protein` node is almost never the drug.** LABrador's `Modality` is
`SMALL_MOLECULE` or `PEPTIDE`, and the graph has no peptide kind. It is tempting
to read a `protein` subject as `PEPTIDE`; that is an inference presented as a
finding, and this repository has already been burned by exactly that habit. Only
`small_molecule` maps automatically. Everything else is skipped as
`modality_not_in_graph` until a human sets `modality` in the frame.

**An `analogical_transfer` path is the donor's edge, not the subject's.** The
whole proposal is that the receiver *lacks* that link, so walking the path to
find a mechanism node attributes the analogue's biology to the molecule being
proposed. `mechanism_nodes()` returns nothing for that motif, the program is
emitted with `target: "UNSPECIFIED"`, and the caveat is written onto
`assumptions.graph_caveat`. This is the same trap that once marked every
analogical hypothesis `broken_path` in `validate.py` — silent both times, which
is why it has a test rather than a comment.

**One frame is applied to every indication, and indications differ.** The frame
carries a single `target_population`, `line_of_therapy` and `therapeutic_area`.
When a molecule gets two labels, the second inherits the first's — on the demo
graph a pirfenidone program ends up describing systemic sclerosis ILD with a
target population written for IPF. LABrador scores the mismatch as a non-match
and tiers comparables down, so it degrades rather than lies, but the field is
wrong and an analyst has to fix it per indication. Do not quote a comparable tier
off an unedited emission.

**`target` falls back to a non-target.** If a path crosses no protein or gene,
the first interior node of any kind is used and an `UNSUPPORTED` evidence record
says so — on the demo graph, pirfenidone's target comes out as "myofibroblast
differentiation", a process. It is the right string for a human to correct and
the wrong string to put in a brief. `frame.target` overrides it.

**The empty comparable catalogue is deliberate, and it is not neutral.** With no
anchor, LABrador raises `MISSING_SELECTED_NET_ANCHOR` and produces no price
corridor, which zeroes the entire cash flow. Every rNPV in an unedited emission
is `0.0`. Reading that as "this program is worthless" instead of "nobody has
supplied a price" is the single easiest mistake to make with this output — check
`decision_grade` before you read `summary`.

**`portfolio` will happily rank three zeroes.** It requires only a shared
currency and valuation year, both of which come from one frame and therefore
always match. The ordering is a numeric sort over `NOT_DECISION_GRADE` rows;
LABrador says so in its own output warning, and it means the same thing here that
`rank_score` means upstream — a way to order a page, not a judgement.

**Absence does not become evidence by changing stage.** The slate's novelty is
already discounted by the graph's `absence_reliability()`. The emitted program
carries that warning forward in `assumptions.absence_warning`, and it must not be
talked back up in a valuation memo: a missing link means this search did not
surface it, never that nobody has shown it.

**Do not let the number choose the hypothesis.** Nothing in the `valuation`
profile scores a candidate by how valuable its program would be. Market size is
not evidence, and a generator that preferred lucrative hypotheses would be
optimising the one axis its own evidence cannot check. Screening order comes out
of LABrador; scientific merit comes out of the slate; they are allowed to
disagree, and when they do, that disagreement is information.

## Reproducing a result

Keep together: the graph file and its `graph_id`/round, the profile and any
`--set` overrides, the frame, `emission.json`, the LABrador `input_digest`,
`seed` and `simulations`, and the full result JSON. The emitted program carries
the graph id, round, question, coverage block and originating hypothesis ids in
`assumptions`, so a result can be walked back to the verbatim sentence a human
wrote — which is the property the whole pipeline exists to preserve.
