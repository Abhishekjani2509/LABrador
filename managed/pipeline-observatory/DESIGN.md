# The Glassbox — workflow observability for the LABrador pipeline

**Who this is for:** two readers at once. A teammate wiring their node into the
trace, and a skeptical decision-maker who has been burned by black-box "AI
platforms" and will not accept a number they cannot check. Every design choice
below is justified against the second reader; the first reader gets file+field
precision.

**What it is:** one small, identical JSON record — the **trace envelope** —
wrapped around every node call in a pipeline run, plus one self-contained HTML
page that renders the chain of envelopes in plain language. The envelope says:
what data went in (with checkable ids), what number came out and on what
stated basis, what was handed to the next node, and which parts are
SIMULATED / SYNTHETIC / ASSUMED rather than observed.

**What it is not:** `managed/hypothesis-highlander` is the layer that
*optimizes across many runs* (archives, Pareto fronts, niches). The glassbox
*explains one run*. Highlander answers "which hypothesis should we try next?";
the glassbox answers "why should I believe what this run just told me?". They
meet in exactly one place: a highlander archive entry would be strictly more
trustworthy if it stored the trace of the run that produced it (see §10
assignment for Vince in COORDINATION.md).

**Working demo:** `trace-demo.ts` here runs the chain that composes today
(forecaster → economics bridge → economics engine) and writes
`fixtures/trace-demo-output.json` — a real trace from a real run —
which `observatory.html` renders without a server, a build step, or network.

---

## 1. The skeptic's walkthrough — the questions the glassbox must answer

The persona: a biotech decision-maker. Smart, numerate, not a programmer.
Their operating assumption is that an AI pipeline will hide its weakest link.
Their questions, node by node, and where the answer lives:

**At the trial-recruitment forecaster** *("you claim this trial fills in 22 months")*
- "Which trials did you learn that speed from?" → `dataSources[]`: every NCT
  id, each with a `role` sentence ("completed interventional precedent —
  supplied enrolment velocity"). The ids are checkable on clinicaltrials.gov.
- "Is 22 months a measurement or a guess?" → `honestyLabels`: SIMULATED, with
  `detail` naming the literal field (`simulatedMonthsToEnroll`) so the reader
  can see the code never pretended otherwise.
- "Where did the sample size and site count come from?" → `keyNumbers[].basis`,
  verbatim from the node's own `poweringBasis` / `sitesBasis` strings ("phase-3
  precedent median (23 trials) floors the effect size d=0.8 estimate of 65").
- "What part is a model reading, not arithmetic?" → the ASSUMED label on the
  eligibility pass rate: "Claude's judgement after reading real I/E prose
  (median of 3 samples)".

**At the economics bridge** *("that delay costs $X")*
- "Who decided months become launch-delay years?" → `handoff.adapter` names
  the exact file (`economics-bridge.ts`); the envelope's caveats carry the
  whole-year rounding rule and why fractional months vanish.
- "Are those dollars real?" → SYNTHETIC label, scope "the dollar figures",
  detail naming the fictitious demo programme they were priced against.

**At the economics engine** *("median value −$23.4M, NOT decision grade")*
- "Would you show me this if it were embarrassing?" → the engine's own
  `NOT_DECISION_GRADE` stamp is passed through untouched and styled loudest on
  the page. The glassbox never upgrades a status — that is its one hard rule.
- "Same inputs, same answer?" → `inputs.digest` (sha256 over canonicalised
  JSON) plus the seed in `run` — two runs that saw the same inputs prove it.

**At the end** *("so what's the verdict?")*
- "Give me one sentence, then let me walk backwards." → `verdict.headline` in
  plain language, `verdict.ancestry` listing every node that touched the
  number, and `verdict.honestyLabels` — every label from anywhere in the
  chain, deduplicated, so nothing gets laundered by distance.

Two questions the demo cannot answer yet — they are the two biggest gaps and
they are assigned in COORDINATION.md §10:
1. "What did the literature actually say?" — the evidence mapper emits
   verbatim quotes with DOIs, but no per-run summary of how many quotes passed
   mechanical verification (the number that makes 'verbatim' checkable).
2. "Is the target even druggable?" — the tractability node has the strongest
   provenance rules in the repo but no end-to-end runnable output yet, so
   there is nothing to wrap.

## 2. The trace envelope — commented spec

The normative definition is the `TraceEnvelope` / `Trace` types in
`trace-demo.ts` (they are what the demo actually validates against). This is
the same shape as commented JSON, one comment per field on *why the skeptic
needs it*:

```jsonc
// ---- One envelope per node call --------------------------------------------
{
  "node": "trial-recruitment-forecaster",   // which station is speaking
  "startedAt": "2026-08-15T…Z",             // when — so runs are orderable
  "durationMs": 41250,                      // how long — slow steps are where shortcuts hide
  "status": "ok",                           // ok | degraded | skipped. A missing key or
                                            // unreachable service NEVER fakes a result —
                                            // it degrades, visibly, and the trace still writes.
  "version": {
    "commit": "d95ad42",                    // the exact code that produced this number
    "dirty": false,                         // true = uncommitted edits were present; a
                                            // skeptic should trust a dirty run less
    "runner": "bun managed/pipeline-observatory/trace-demo.ts"
  },
  "inputs": {
    "digest": "sha256:…",                   // canonicalised-JSON hash: proves two runs saw
                                            // identical inputs without shipping the payload
    "humanSummary": "dupilumab in eosinophilic esophagitis, biomarker ≥15 eos/hpf (85%)",
    "source": "fixtures/theses.json#dupi-eoe"  // where the input came from, so it can be opened
  },
  "dataSources": [                          // EVERY external record used, each checkable
    { "kind": "nct",                        // nct | doi | price_observation | structure | synthetic
      "id": "NCT03633617",                  // the id itself — paste it into clinicaltrials.gov
      "role": "completed phase-3 precedent — supplied enrolment velocity" }
  ],                                        // `role` is the trust-carrying field: not just
                                            // WHAT was read but what it was USED FOR here
  "decision": {
    "summary": "This trial is modelled to take 22 months to enrol 159 patients across 69 sites.",
                                            // one sentence a non-specialist can read aloud
    "keyNumbers": [
      { "label": "months to enrol", "value": 22, "unit": "months",
        "basis": "phase-3 precedent median (23 trials) floors the effect size d=0.8 estimate of 65" }
    ],                                      // `basis` is VERBATIM from the node — the glassbox
                                            // never paraphrases a justification it can quote
    "honestyLabels": [                      // the core of the whole design
      { "label": "SIMULATED",               // SIMULATED | SYNTHETIC | ASSUMED |
                                            // NOT_DECISION_GRADE | INSUFFICIENT_EVIDENCE | DEGRADED
        "scope": "months to enrol, range, score, and every number derived from them",
        "detail": "the field is literally named simulatedMonthsToEnroll in recruitability.ts" }
    ]                                       // labels have SCOPE (which numbers) and DETAIL
                                            // (where the label came from). Downstream nodes
                                            // may ADD labels; nothing may remove one.
  },
  "handoff": {                              // null on the terminal node
    "toNode": "therapeutic-program-economics",
    "adapter": "managed/trial-recruitment-forecaster/economics-bridge.ts",
                                            // the seam is a named file — auditable, blameable
    "payloadSummary": "a launch-delay overlay: 0 whole years (range 0–3), months saved by counterfactual: 3"
  },
  "caveats": [                              // limitations the READER must carry forward.
    "per-site velocity is known not to transfer to 100+ site scale (NEXT.md)"
  ]                                         // rule: never empty out of laziness — if a node's
                                            // own docs state a limitation, it appears here
}

// ---- The trace that wraps the envelopes -------------------------------------
{
  "traceVersion": "1",
  "generatedAt": "…",
  "run": { "fixtureId": "dupi-eoe", "plannedMonths": "18", "seed": "42", "simulations": "200" },
  "envelopes": [ /* one per node, in execution order */ ],
  "verdict": {
    "status": "complete",                   // incomplete = at least one degraded/skipped step;
                                            // the headline must then say what is missing
    "headline": "…one plain sentence…",
    "ancestry": [ { "node": "…", "status": "ok", "summary": "…" } ],
                                            // the terminal number's family tree, oldest first
    "honestyLabels": [ /* every label in the chain, deduplicated — nothing laundered */ ]
  }
}
```

## 3. Per-node instrumentation — what exists, what's missing

"Already emits" is precise (file + field). Every "missing" row is a §10
assignment in COORDINATION.md — no gap listed here is unassigned there.

| Node | Already emits (→ envelope field) | Missing |
|---|---|---|
| **trial-recruitment-forecaster** | `RecruitabilityResult.why` (→ decision.summary raw material); `poweringBasis`, `sitesBasis` (→ keyNumbers.basis, verbatim); `evidence.precedentTrials` + `failedPrecedents` NCT ids (→ dataSources); `screensPerEnrollee`, `simulatedMonths*` names (→ SIMULATED labels); `counterfactual` (→ handoff payload); `asOf` (→ caveat) — all in `recruitability.ts` | Node doesn't stamp its own `version.commit`; dataSource `role`s are derived by the demo, not emitted; eligibility ASSUMED label derived from docs, not a field |
| **economics-bridge (Adapter B)** | per-number `basis` strings, `howToApply`, `pricing.status`, engine grade passthrough — `economics-bridge.ts` | nothing blocking — the demo wraps it fully |
| **therapeutic-program-economics** | `AnalysisResult`: `input_digest` (→ inputs.digest), `calculation_steps`, typed `warnings`, `decision_grade` (→ NOT_DECISION_GRADE label), per-evidence `SYNTHETIC` grades (→ SYNTHETIC label + dataSources), redaction — `engine.py`, `provenance.py` | no one-sentence plain-language headline (demo composes one); comparable-price roles assembled by the demo, not the engine |
| **research-evidence-mapper** | verbatim `quote` per finding + DOIs (→ dataSources kind:doi), `coverage` accounting, disagreement records — `SCHEMA.md`, real artifacts `runs/g_1a4f*` | **per-run quote-verification stats** (assemble.py verifies quotes but doesn't summarize pass/fail counts — the number that makes "verbatim" checkable); findings lack `round`/`flags` vs SCHEMA promise; `r2.json` is a snapshot, not the promised append-only chunk (both found by the evidence-bridge build); entity typing gap (§6 item 6) limits dataSources |
| **small-molecule-tractability-review** | the repo's strongest provenance RULES (per-number provenance, falsification ledger, `insufficient_evidence` verdict, four separated precedent axes — `CLAUDE.md`) | **no end-to-end runnable output yet** (assembly never run) — nothing to wrap; when the dossier JSON exists, its `falsification` block maps directly to caveats + honestyLabels |
| **hypothesis-highlander** | failure ledger, archive entries | out of scope for single-run traces (see differentiation); candidate consumer: store the trace of each evaluated run in the archive entry |

## 4. Portability runbook — clone to running, per node

What a NEW person (or machine) needs. Everything degrades honestly: a missing
key or tool produces a `degraded` envelope with the real error, never a fake
number.

```bash
git clone https://github.com/Abhishekjani2509/LABrador.git && cd LABrador
bun install --frozen-lockfile        # TS workspace. Bun only — not npm/node.
bun run typecheck && bun run check   # green with NO key, NO network
```

| What | Command | Needs key? | Needs network? |
|---|---|---|---|
| Forecaster demo | `bun managed/trial-recruitment-forecaster/demo.ts dupi-eoe` | ANTHROPIC_API_KEY (`cp .env.example .env`, add key) | yes (clinicaltrials.gov + api.anthropic.com) |
| Forecaster backtest | `bun managed/trial-recruitment-forecaster/backtest.ts` | **no** | yes (clinicaltrials.gov only) |
| Economics engine | `cd managed/therapeutic-program-economics && uv sync --frozen --extra dev && uv run pytest && uv run labrador analyze fixtures/demo_program.json --comparables fixtures/demo_comparables.json --seed 42` | **no** | first `uv sync` only |
| Evidence bridge (Adapter A) | `bun managed/trial-recruitment-forecaster/evidence-bridge.ts managed/research-evidence-mapper/runs/g_1a4f.json` | **no** | **no** — runs on committed artifacts |
| Highlander tests | `cd managed/hypothesis-highlander && uv sync --frozen --extra dev && uv run pytest` | **no** | first sync only |
| **The glassbox** | `bun managed/pipeline-observatory/trace-demo.ts` then open `observatory.html` in any browser | key optional (degrades) | degrades without |
| Mapper agent | deployed Managed Agent (`bun run console research-evidence-mapper`) | platform key | yes |
| Tractability review | not end-to-end runnable yet — `pipeline.html` records per-stage status | — | — |

`observatory.html` itself needs nothing: no server, no build, no CDN — open the
file. That is deliberate: the least technical reader has the shortest path.

## 5. Why not just read the nodes' own output?

You can — the envelope adds three things raw output doesn't have:
**uniformity** (one shape for a skeptic to learn, not five), **provenance
stitching** (the handoff chain is explicit, so "where did this dollar figure's
months come from?" is answerable by walking `ancestry`), and **label
conservation** (a SIMULATED stamped upstream provably survives to the terminal
verdict — the one guarantee that most distinguishes this from a pitch deck).
