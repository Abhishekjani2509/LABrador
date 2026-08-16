# hyp_gen — hypothesis generation from a knowledge graph

Stage 2 of the Track A Co-Scientist. It takes **one JSON knowledge graph** and
returns a slate of hypotheses, each one traceable to a link id, a finding id,
and the verbatim sentence a human wrote.

It is deliberately blind to where the graph came from. No search strategy, no
PubMed, no query log — if a fact is not in the graph, it cannot appear in a
hypothesis. That is what makes the output checkable: every claim resolves to a
row in the input.

A hypothesis here is a function of `(graph, params)` and nothing else. Two runs
with the same inputs produce the same slate, so a disagreement about the output
is a disagreement about parameters rather than about luck.

- The graph contract is [`../SCHEMA.md`](../SCHEMA.md) (Stage 1 owns it).
- The knobs and where their defaults come from are in
  [`docs/PARAMETERS.md`](docs/PARAMETERS.md).
- The design and its failure modes are in [`docs/DESIGN.md`](docs/DESIGN.md).

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# Structural slate: enumeration, scoring, selection. No model calls, no API key.
PYTHONPATH=src .venv/bin/python -m hyp_gen.cli \
  --graph data/example_graph.json --dry-run

# Full run — articulate, critique, validate citations (needs ANTHROPIC_API_KEY).
PYTHONPATH=src .venv/bin/python -m hyp_gen.cli \
  --graph data/example_graph.json --profile repurposing --out reports/

.venv/bin/python -m pytest        # 148 offline tests, no network
```

Start with `--dry-run`. Most early failures are traversal or parameter
failures, and they are far easier to see as a table of candidates than inside a
finished report.

```
id                          motif                    sup   nov  test  risk   str    rank
H-analog-t1-t11-via-t2      analogical_transfer     0.71  0.34  0.70  0.00  1.00   0.461
    pirfenidone → systemic sclerosis ILD
    · g2 was searched in round 2
    ! independence: all primary evidence here is from Distler; nothing replicates it
H-g1                        gap_closure             0.46  0.39  0.55  0.33  0.54   0.454
    metformin → AMPK → collagen I deposition → idiopathic pulmonary fibrosis
```

The `!` and `✗` lines are the deterministic verification gates, which need no
API key. They are worth reading before a real run: `✗` is a candidate that will
be thrown out, and knowing that costs nothing here and a model call later.

## Pipeline

```
graph.json
   │
   ├─ graph.py       parse + index + typed, degree-weighted traversal
   ├─ candidates.py  four motifs → structural candidates (deterministic)
   ├─ scoring.py     recompute support from findings; novelty, risk, testability
   ├─ select.py      thresholds → Pareto front → MMR → quotas
   ├─ evidence.py    per-candidate pack: the model's entire world
   ├─ reason.py      articulate → critique from N lenses → compare → evolve
   ├─ validate.py    structure against the graph, citations against the pack
   ├─ verify.py      six gates in cost order; a halt skips the rest, loudly
   ├─ asks.py        weakest point → one Stage 1 request, by id
   ├─ report.py      short report.md by default, full audit trail on request
   └─ valuation.py   slate → LABrador ProgramInput, for the valuation stage
```

Everything above `reason.py` is deterministic and runs without an API key.
Model calls happen only for candidates that survive selection, so cost scales
with `selection.top_k`, not with graph size.

## Where hypotheses come from

Four motifs, each a distinct reason a statement is worth making:

| Motif | The shape | The claim |
|---|---|---|
| `gap_closure` | Stage 1 flagged a pair its own links imply but nobody states | the implied relation is real |
| `transitive_chain` | A→B→C exists, A→C does not | the chain composes |
| `analogical_transfer` | X and Y share neighbours; X has an edge Y lacks | Y has it too |
| `condition_split` | a link disagrees, under different `where` conditions | both results are right; the condition is the variable |

`condition_split` is the one people are surprised by. Schema note 5 says a
`disagreed` link is usually two experimental conditions rather than a conflict,
so reconciling it is treated as a first-class hypothesis instead of a data
quality problem.

## The parts that carry the design

- **Absence is not evidence of absence.** Novelty that rests on a gap is scaled
  by the graph's own `absence_reliability()`, computed from coverage depth and
  truncation. At `quick` depth that factor is zero: page one lies, so nothing
  may claim to be new merely because this search did not surface it.
- **Support is recomputed, not trusted.** Schema note 3 invites Stage 2 to
  disagree with `links.confidence`, and we do — from `findings` + `papers`,
  with study type, hedging, secondhand citation, preprint status and
  independent-group counts all applied. `drift` reports where we differ.
- **Support and novelty are separate axes.** A fully supported hypothesis is a
  known fact. Averaging the two ranks textbook statements first, so the scores
  stay a vector and the Pareto front is available for whoever consumes it.
- **A chain is as strong as its weakest link.** Weakest-link aggregation is the
  default because `mean` lets one strong link launder two weak ones.
- **Hubs are damped, not banned.** Degree-weighted path counts (Rephetio's
  DWPC) stop "aspirin → inflammation → everything" from topping every slate.
- **The model may only cite what it was shown.** Each candidate gets an
  evidence pack, and any id outside it is rejected by `validate.py` and the
  hypothesis flagged. A model that cites `L7` when `L7` was never in its pack
  has stopped reporting and started remembering.
- **Verification is a process with an order, and a skip is not a pass.** Six
  gates per hypothesis, cheapest first, so the four deterministic ones can
  reject a candidate before the adversarial gate spends a call. When one halts,
  the rest are recorded as skipped *naming the halt* — five green checks because
  the sixth never ran would read as more verified than the truth, not less.
- **Critics get lenses, not copies.** Three identical refuters mostly agree;
  a mechanism critic and an evidence critic fail on different things.
- **The loop closes by id.** Each hypothesis names the exact `resolve_link`,
  `test_gap`, or `expand_node` request that would move it, in Stage 1's request
  shape — no prose for Stage 1 to interpret.

## Profiles

One graph, five stances. `--profile` picks one; `--set group.key=value` patches
any field on top.

| Profile | For |
|---|---|
| `default` | balanced |
| `conservative` | short paths, strong links, two independent groups, no reversals |
| `speculative` | longer paths, weaker links, more critics |
| `repurposing` | compound → gene/protein → process → disease |
| `mechanism` | closed discovery: both ends given, find the B terms |
| `valuation` | shaped for the ROI stage: intervention in, disease out, ≤2 labels per molecule |

```bash
# Why might metformin act on IPF?  (closed discovery)
--profile mechanism --set framing.anchors='["metformin"]' --set framing.targets='["IPF"]'
```

## How crazy do you want it?

`--craziness` is one float from 0 to 1. A profile picks *what question* to ask
the graph; craziness picks *how far out* to reach for an answer.

```bash
hypgen --graph data/example_graph.json --craziness 0.1    # defensible today
hypgen --graph data/example_graph.json --craziness 0.9    # a real leap
hypgen --graph data/example_graph.json --profile repurposing --craziness 0.8
```

At 0.0 you get two-hop chains between strongly-supported links, corroborated by
two independent groups — nearly boring, which is the point when the next step
costs money:

```
H-chain-t12-t4-2   transitive_chain   sup 0.55  nov 0.07  test 0.70
    senescent alveolar epithelium → TGF-beta1 → myofibroblast differentiation
```

At 1.0 the similarity motif leads, cross-kind analogy is allowed, and the top of
the slate is the "I read this one thing in a slightly different field" kind of
idea — with the independence warning attached rather than hidden:

```
H-analog-t8-t5-via-t7   analogical_transfer   sup 0.62  nov 0.16  test 0.70
    metformin → idiopathic pulmonary fibrosis
    ! independence: all primary evidence here is from Jenkins; nothing replicates it
```

The dial widens the aperture. It never lowers the audit standard: the same chain
of links scores the same support at either end, absence still is not evidence of
absence, a hypothesis still may not cite what it was not shown, and the
`structure` and `citations` gates still halt. Scrutiny goes *up* with ambition —
1.0 buys a third critic and a revision round, because that end's failure mode is
fluent nonsense. The full schedule and the things it is forbidden to move are in
[`docs/PARAMETERS.md`](docs/PARAMETERS.md).

## Handing off to valuation

`managed/program-strategy-valuation/` (LABrador) is the ROI stage: a program
brief in, rNPV and a decision grade out. `valuation.py` emits its input.

```bash
hypgen --graph data/example_graph.json --emit-frame-template frame.json
hypgen --graph data/example_graph.json --profile valuation --dry-run \
       --emit-programs out/ --frame frame.json
labrador analyze out/*.program.json --comparables out/comparables.json --seed 42
```

The frame is mandatory and its four year fields start `null`: currency,
geography, route, launch year and above all the patent filing year are analyst
decisions, not graph findings, and a guess is indistinguishable from a sourced
value once it is in the JSON.

Expect `NOT_DECISION_GRADE`. A literature graph has no epidemiology, no payer
behaviour and no price, so the emitted program is honestly full of holes and
LABrador's job is to name them — 44 of them on the demo graph, against one number
that really is supported (`effective_protected_years`). That gap list is the
deliverable. The contract and its failure modes are in
[`docs/VALUATION_HANDOFF.md`](docs/VALUATION_HANDOFF.md); the one to read first is
that every rNPV in an unedited emission is `0.0` because nobody has supplied a
price, which is not the same thing as a worthless program.

## Status

**Working.** Graph parsing, typed/degree-weighted traversal, all four motifs,
evidence recomputation, multi-objective scoring, MMR selection with quotas,
evidence packs, staged six-gate verification with halting, articulation,
multi-lens critique, Elo tournament, evolution rounds, Stage 1 asks, markdown
and JSON output, CLI, 148 offline tests.

**Two report lengths.** `report.md` is the short read — statement, chain,
scores, what would kill it, the decisive experiment, the strongest objection,
and every warning. The claims tables, gate tables and verbatim source sentences
live in `report-full.md`, written by `--full-report`. Rendering is a pure
function of the slate, so either can be recovered later without re-running the
model stages:

```bash
hypgen --report-from runs/my-run/slate.json --full-report --out runs/my-run
```

Brief drops corroboration, never a warning: failure badges, halted
verifications, error-level validation issues and the absence-of-evidence notice
render at both lengths.

Verification carries a gate table and one of four verdicts (`verified` /
`qualified` / `unverified` / `rejected`) in `slate.json` and in the full report:

```
gate 1 structure       PASS   3 hop(s), path intact, not already stated
gate 2 citations       PASS   4 ids, all legal
gate 3 consistency     PASS   5 claims, 3 grounded in evidence
gate 4 independence    FAIL   F2, F7 share first author Distler — 1 group, run requires 2
gate 5 falsifiability  SKIP   halted at independence
gate 6 adversarial     SKIP   halted at independence
──────────────────────────────────────────────────────────────────────────
VERDICT  unverified (halted: independence)
```

Building it surfaced a live bug worth naming: `check_structure` walked every
candidate's path from `subject`, but an `analogical_transfer` candidate's path
is the *donor's* bridge edge by construction. Every analogical hypothesis was
therefore marked `broken_path` — an error — and blocked before articulation, in
every run since the motif was written, including the top-ranked row in the
example output above. Fixed in `validate.py`, with a regression test.

**Untested against the live API.** No key was available in this environment.
The model stages are exercised end-to-end by a scripted fake judge (including
refusal, budget exhaustion, and illegal-citation paths), and the call shape is
checked against `anthropic` 0.122.0, but the first real run should be a
`--profile conservative` one-off with `selection.top_k=2`.

**Not built.** Retrospective validation (hold out a round, check whether the
generator proposes what the later round found — the number worth demoing);
multi-round driving of Stage 1 from `asks`; dataset-support scoring, which is a
sibling stage rather than this one.
