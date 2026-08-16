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

- The graph contract is Stage 1's `SCHEMA.md`, which lives with Stage 1 and not
  in this repo.
- The knobs and where their defaults come from are in
  [`docs/PARAMETERS.md`](docs/PARAMETERS.md).
- The design and its failure modes are in [`docs/DESIGN.md`](docs/DESIGN.md).
- The handoff to the valuation stage is in
  [`docs/VALUATION_HANDOFF.md`](docs/VALUATION_HANDOFF.md).

## Layout

The Python package sits inside the managed agent that fronts it, the same shape
`managed/program-strategy-valuation/` uses for `labrador_roi`:

```
managed/hypothesis-generator/
  CLAUDE.md        the deployed agent's system prompt, uploaded verbatim
  manifest.json    build output: the Managed Agent definition
  tools.ts         custom tools; they shell out to the CLI below
  acl.ts           who may call the agent
  src/hyp_gen/     this package — the generator itself
  tests/           212 offline tests, no network
  fixtures/        example graphs and the analyst frame
  docs/            design, parameters, valuation handoff
  runs/            output (gitignored)
```

One directory holds the agent and the code it runs, so a checkout of the agent
is a checkout of the thing that does the work. `tools.ts` resolves the package
relative to this directory; nothing outside it needs to know where the
generator lives.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# Structural slate: enumeration, scoring, selection. No model calls, no API key.
PYTHONPATH=src .venv/bin/python -m hyp_gen.cli \
  --graph fixtures/example_graph.json --dry-run

# Full run — articulate, critique, validate citations (needs ANTHROPIC_API_KEY).
PYTHONPATH=src .venv/bin/python -m hyp_gen.cli \
  --graph fixtures/example_graph.json --profile repurposing --out reports/

.venv/bin/python -m pytest        # 212 offline tests, no network
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
hypgen --graph fixtures/example_graph.json --craziness 0.1    # defensible today
hypgen --graph fixtures/example_graph.json --craziness 0.9    # a real leap
hypgen --graph fixtures/example_graph.json --profile repurposing --craziness 0.8
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
hypgen --graph fixtures/example_graph.json --emit-frame-template frame.json
hypgen --graph fixtures/example_graph.json --profile valuation --dry-run \
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
and JSON output, CLI, 212 offline tests.

**Four report modes, one record.** `slate.json` is the record; every report is
a pure function of it, so any view can be produced — or reproduced from a saved
run — without re-running the pipeline.

| Mode | File | Answers |
|---|---|---|
| `prose` (default) | `report.md` | What is this idea, is it any good, what would kill it, what next |
| `table` | `report-table.md` | Which of these should I look at first |
| `trace` | `report-trace.md` | Where did this come from |
| `full` | `report-full.md` | Is the work correct |

`trace` is the observability view: it walks the graph node by node, and each
edge carries its link id, the support recomputed from findings, the conditions
the result was measured under, how far the recomputed support drifted from the
graph's stated confidence, and the verbatim sentence behind every finding —
including the ones that *contradict* the edge.

```bash
hypgen --graph fixtures/example_graph.json --out runs/my-run \
       --report-mode prose --report-mode trace

hypgen --report-from runs/my-run/slate.json --report-mode table --out runs/my-run
```

**A mode changes the form, never the safety.** Failure badges, halted
verifications, error-level validation issues and the absence-of-evidence notice
render in all four — in `table` the flagged rows are restated at full width
under the table, because a flag in a cell is easy to skim past.
`test_every_mode_keeps_the_signals_a_reader_must_not_miss` is what stops a
fifth mode from quietly becoming a softer one.

**The trace diagram** is a static SVG of the walks the deterministic half
found, written by `--emit-diagram FILE.svg`:

```bash
hypgen --report-from runs/my-run/slate.json --emit-diagram runs/my-run/traces.svg
```

Edges are coloured by what the evidence says. There is no "contradicted" flag
on a link — a link carries `yes`, `no` and `no_effect` lists of finding ids, so
**red** means at least one finding argues against the edge (or reports no
effect), **blue** means every finding supports it, and **grey** means no
verbatim finding at all. Dashes are a separate axis: dashed is `single_source`,
solid means more than one research group. The `✓ ✗ ∅` counts on each label say
how many findings sit on each side. Nodes are deduplicated across traces, so
two hypotheses crossing the same node visibly converge, and rows are ordered by
a barycentre pass so the edges do not knot.

The finely dotted grey edge is the hypothesis itself — the edge the graph does
*not* have. It matters most on an `analogical_transfer`, where the solid edge
belongs to the analogue: on the demo graph the drawn `L8` runs
nintedanib → SSc-ILD, and pirfenidone reaches SSc-ILD only by the dotted
proposal. SVG rather than PNG because it needs no plotting dependency, it
diffs, and it embeds in a page unchanged.

**The web UI payload** is the second adapter, next to `valuation.py`:
`webui.emit(slate)` returns one JSON card per hypothesis, written by
`--emit-webui FILE` on a run or recovered from a saved slate:

```bash
hypgen --report-from runs/my-run/slate.json --emit-webui runs/my-run/webui.json
```

Each card carries the walk as one string
(`pirfenidone --inhibits--> myofibroblast differentiation --contributes_to--> …`,
a reversed hop rendered `<--how--`), the support / novelty / testability
metrics plus the rank that orders cards, and `highlights`: one-liners saying
how the graph supports, contradicts, or qualifies the hypothesis. Every
highlight is assembled from structured slate fields and carries the ids it was
built from in `refs`, so the UI can link each line to its evidence — no line
states anything the slate does not. Highlights are ordered weakest-first
(failures, contradictions, cautions, novelty, support), rejection flags render
on the card, and the absence-of-evidence warning sits at payload level where no
card view can drop it.

**`prose` is kept short by two rules.** Argued fields — the falsifier, the
decisive experiment, the strongest objection — are clipped to whole sentences
and the clip is always marked `…`, because an argument that ends mid-case must
not look like one that ended. The statement itself is never clipped: it is the
hypothesis, and a hedged claim cut short reads as a flat one. Second, a caveat
that every hypothesis carries describes the *run*, so it is stated once under
the header instead of once per hypothesis. On the demo slate the two rules take
`report.md` from 8.3k characters to 3.9k, against 31k for the same slate in
`full`.

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
