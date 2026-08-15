# LABrador — Pipeline Spec

LABrador stress-tests a therapeutic program hypothesis by routing it through four
specialist agents, each answering one question the others cannot:

1. **Does the literature support the mechanism?** — `research-evidence-mapper`
2. **Can this target be drugged with this modality?** — `small-molecule-tractability-review`
3. **Can the resulting trial actually be enrolled?** — `trial-recruitment-forecaster`
4. **Do the program economics hold together?** — `therapeutic-program-economics`

A fifth deployed agent, `sandbox-capability-probe`, is infrastructure. It reports
what the remote sandbox can do and never appears in a hypothesis run.

An **orchestrator** holds the thesis, calls the stations, routes their findings back
at each other, and assembles the dossier. It is the only component that sees all
four answers.

## The composition model

**Everything is a deployed Managed Agent, and every hop is text.** Stations receive
a prose brief and return prose. There is no shared serialization format, no schema
registry, no parser at any seam.

This is deliberate. Each station already has a rich internal structure — a knowledge
graph, a two-axis dossier, a simulation result, a seeded cash-flow model. Forcing a
common envelope would mean designing the intersection of five contracts, and that
intersection is smaller than any one of them. Worse, the most decision-relevant
thing a station produces is usually a _qualification_: "0.442 on chain A, 0.257 on
chains A+B, and which one matters depends on what you're trying to break." A schema
field drops the qualification. A sentence keeps it.

Stations that are engines internally (3 and 4) expose them as tool handlers behind
the agent. The orchestrator does not shell out, does not parse stdout, and does not
know which stations are models and which are arithmetic. It sends a message and
reads one.

### Calling a station

```bash
bun run console <station> -- --once "<brief>"
```

Headless, one call, one answer. `bun run console <station>` opens the visual console
for the same agent when a human wants to drive it directly. Once wrappers are live
under `agent/tools/`, `bun run dev` exposes every station through the eve router and
the orchestrator addresses them there instead.

Note: `bun run console <name>` does **not** attach the agent's memory store — only
`--once` and the router wrapper do. Station 1 is stateful, so it must always be
reached through `--once` or the router, never an interactive console session.

### What a brief must carry

**A header block.** Loose `key: value` lines at the top. Not parsed — read. Enough
for the station to know what was asked and under what constraints:

```
thesis:   dupi-eoe
station:  trial-recruitment-forecaster
as_of:    2018-01-01
upstream: research-evidence-mapper (graph g_7f2a, round 2)
          small-molecule-tractability-review (skipped — modality is antibody)
```

`as_of` is the one header every station must honor. When present it is **binding**:
every piece of evidence reported must have existed before that date, and a station
that cannot date-filter a source must say so rather than silently substituting
current data. A retrospective run contaminated by future data is worthless, and
silent contamination is worse than a gap.

**The ask, stated once, in the station's own vocabulary.** One question per call.
Point at prior findings by identifier — a `graph_id` and a link id, a UniProt
accession, an NCT id — never by paraphrase.

**Only the upstream findings that bear on this station's question.** The
orchestrator does not forward the whole dossier. It forwards what changes the answer.

### What an answer must carry

**The finding in the first paragraph.** Not the method, not the caveats. What the
station actually concluded, in a form a reader can act on. Downstream stations may
read only this paragraph.

**Then the qualifications, and every number's provenance.** A figure without a
source does not appear. Sources are identifiers — NCT id, PMID, DOI, ChEMBL id, PDB
id, a named CMS dataset — never a description of where one might look. Anything the
station could not retrieve is reported as not retrieved, with the reason.

### Three rules that hold at every seam

**1. Qualifiers survive the hop or the number doesn't.** Every station has a word
for the gap between what it measured and what it modeled, and it uses that word:
`simulated` on enrollment months, `NOT_DECISION_GRADE` on economics,
`insufficient_evidence` on tractability, a verbatim quote versus an inferred gap in
the evidence graph. A station or orchestrator relaying one of these numbers carries
the qualifier forward or drops the number. There is no third option.

**2. No averaging, ever — across axes or across stations.** Stations answer
different questions and are allowed to disagree. A target can be small-molecule
tractable and clinically failed. A trial can be enrollable and the program
uneconomic. The tractability review already refuses to average its own two axes and
emits no overall number; the orchestrator inherits that discipline at the pipeline
level. When two stations point opposite ways, **the disagreement is the finding** —
it goes in the dossier's disagreement list, unresolved.

**3. No station answers another station's question.** The tractability review does
not decide whether to pursue the indication. The forecaster does not judge the
mechanism. The economics engine does not establish clinical efficacy. Each of these
is written into the station's own contract; the orchestrator enforces it at the seam
and rejects an answer that overreaches rather than quietly using it.

## The run

### Input: the thesis

A run starts from one **indication thesis** — asset, target and direction, disease
and subtype, biomarker population, tissue, predicted endpoint, mechanism, evidence,
uncertainty. `managed/trial-recruitment-forecaster/thesis.ts` holds the typed
version (`IndicationThesis`, Zod) that the forecaster consumes; to the other
stations the same content travels as prose.

Two fields do disproportionate work and are never omitted:

- `biomarkerPopulation.prevalenceInDisease` — a marker present in 12% of patients
  means roughly 8 screened per enrollee, which is usually what decides whether a
  trial is runnable at all.
- `asset.modality` — it decides whether station 2 runs (below).

### Order and parallelism

```
                  thesis
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  [1] evidence mapper     [2] tractability review        (parallel; 2 is modality-gated)
        └───────────┬───────────┘
                    ▼
          [3] recruitment forecast
                    ▼
          [4] program economics
                    ▼
                 dossier
```

Stations 1 and 2 depend only on the thesis and run concurrently. Station 3 depends
on the thesis and benefits from 1 and 2 but is not blocked by them. Station 4 wants
station 3's trial duration and size, so it runs last.

**No station is a gate.** The orchestrator runs all four and reports all four unless
a human stops the run. A negative is evidence, not a verdict, and the failure mode
that matters most here is a real program killed by one station's known blind spot.
Three are documented well enough to name, and each is a reason not to auto-gate:

- **Geometric pocket scoring cannot see cryptic pockets.** On an apo KRAS structure
  the switch-II pocket scores 0.000 and ranks 4 of 5; on a holo structure of the same
  protein the identical method ranks it #1 at 0.708. Same pocket. On apo input, a low
  score is an absence of measurement, not evidence of poor tractability.
- **The forecaster's per-site velocity does not transfer across site-count scales.**
  On registrational trials it currently predicts 0.24–0.39× — too fast — because
  precedent pools of 5–40-site trials run at 0.4–0.6 pt/site/mo while real 95–212-site
  machines run 0.07–0.13.
- **Every bundled economics input is synthetic and therefore `NOT_DECISION_GRADE`.**
  Its precision is interface precision, not evidentiary precision.

### Station 2 is modality-gated

`small-molecule-tractability-review` answers exactly one question — can this target
be addressed **with a small molecule** — and its contract is explicit that an
approved antibody "is not evidence that a small molecule is possible; it is often
evidence of the opposite."

So: `modality: small_molecule` → call it. Any other modality → **skip it and record
the skip.** Do not call it and discount the answer; do not let a skipped station read
as a pass. The dossier shows a skip with its reason.

The hero fixture (`dupi-eoe`, dupilumab, an antibody) skips station 2. That is
correct behavior.

## Cross-station follow-ups

This is the orchestrator's real work, and the reason all five stations are deployed
rather than run once in a line. Four loops are worth wiring explicitly; each turns
one station's uncertainty into another station's question.

**Axis conflict → evidence mapper.** When the tractability review reports an
`axis_conflict` — strong retrieved precedent against a dead-looking pocket, or the
reverse — the orchestrator asks station 1 to resolve the specific relationship,
pointing at a link id. That is a `resolve_link` ask, and it is exactly what station
1's persistent graph exists for.

**Contested mechanism → deeper round.** When station 1 returns a relationship marked
disagreed, the orchestrator checks the stated conditions on both sides before
treating it as conflict — different experimental conditions is the common case — and
re-asks at a higher depth tier only if the conditions genuinely overlap.

**Infeasible trial → counterfactual → re-price.** When station 3 reports a design
that cannot enroll, it returns the smallest change that makes it feasible: broaden
the marker from 30% to 40% and the trial goes from 63 months to 47. The orchestrator
sends **the relaxed design** back through station 4 alongside the original, so the
dossier prices the counterfactual rather than only condemning the original. A
broadened biomarker changes the eligible population, which changes the economics —
that link is the point of running these two stations in sequence.

**Gap worth testing → back to station 1.** When a station reports that something is
unknown rather than negative — an untested relationship, an unstudied target, an
undated source — the orchestrator can ask station 1 to look for it directly
(`test_gap`). A pair that has been searched for and not found is a much stronger
claim than one nobody searched.

Every follow-up is logged in the dossier with the finding that triggered it. A number
that changed between rounds is shown with both values and the round that moved it —
never silently overwritten.

## Station contracts

Each station's own files are authoritative. This section covers only what the seam
needs.

### [1] research-evidence-mapper

`managed/research-evidence-mapper/` — `SCHEMA.md` (requests, graph, storage),
`CONTRACT.md` (responsibilities), `BUILD.md` (build order and verification).

The one station that **holds state across calls.** It owns a persistent graph per
question, keyed by `graph_id`, in its own memory store. The orchestrator sends a
`graph_id` and gets the graph back; it never holds or forwards the graph itself.
Follow-up asks extend the graph in place — same `graph_id`, round increments,
existing identifiers stay stable.

- **Ask:** one of four, one per call. `new_question` (free text), `expand_node`,
  `resolve_link`, `test_gap` — the latter three pointing at an identifier from a
  prior round. Plus a depth tier: `quick` 10 papers / `standard` 25 / `deep` 50 /
  `exhaustive` 300. `exhaustive` runs on the order of sixty extraction passes and is
  not a live tier.
- **Answer:** the state of the graph — entities, claims with their exact source
  sentences, relationships and whether the evidence agrees, and relationships the
  graph implies that nobody has stated. Always the full picture, never a delta;
  diff on the round number.
- **The guarantee downstream can rely on:** every quote is string-matched against
  the text actually fetched before it is written. If a claim appears, that exact
  sentence is in that paper. Claims failing the match are dropped and counted, not
  softened. This is a mechanical check, not a prompt instruction.
- **Also enforced:** papers deduped so a preprint and its published version are one
  paper; a review restating forty studies counts as one paper, not forty; names merge
  against the whole graph, so "KRAS" arriving in round 3 joins the existing "K-Ras"
  node rather than forking it.
- **The qualifier that must propagate:** coverage is partial and the station says by
  how much, including what it did _not_ read. At `quick`, absence of evidence means
  unknown — page one lies.
- **Non-goals:** does not filter by score (a hedged claim marks an emerging area, a
  lone claim is a gap candidate — downstream sets its own threshold), does not loop
  on its own (the depth tier is the budget), and returns a graph even on failure
  rather than an error blob.
- **Scores move between rounds.** A relationship at 0.81 can drop to 0.44 when a new
  round brings a contradicting paper. That is correct. Never cache a confidence
  across rounds.
- **Its memory holds data, never instructions.** Fetched papers are semi-trusted
  content written into a read-write store and read back next round.

### [2] small-molecule-tractability-review

`managed/small-molecule-tractability-review/CLAUDE.md` plus four procedural skills:
`precedent-lookup`, `structure-select`, `pocket-scan` (fpocket, Modal), and
`falsification-sweep`. Calibration fixtures in `fixtures/` carry expected outputs as
a grading key — ten targets ordered as a ladder of increasing hardness, so a failure
tells you how far the system got before it broke.

- **Ask:** a UniProt accession (required — resolve a gene symbol first and record
  both). Optionally an as-of date, disease context, the interaction to disrupt, and a
  mechanism hypothesis: `orthosteric` / `allosteric` / `oligomer_destabilisation` /
  `unknown`.
- **The mechanism hypothesis is not a preference, it is the question.** It determines
  which chains constitute the site and silently changes the answer: KRAS 4OBE gives
  0.442 at rank 1 on chain A and 0.257 at rank 6 on chains A+B — same structure, same
  method. Prepare TNF-alpha as a single chain and its site does not exist at all,
  because the site _is_ the trimer. When the orchestrator has no hypothesis it sends
  none; the station then reports pockets for the biological assembly and explicitly
  refuses to assert which one is relevant.
- **Answer: two axes, separate, never averaged.** Retrieved precedent — what has
  actually been made against this target, and the stronger axis when it exists — and
  computed tractability, what the structure says, with its blind spots declared. When
  they disagree the station reports the disagreement rather than resolving it. There
  is no overall number by design.
- **What must survive the hop:** the modality split (only small molecules count as
  small-molecule precedent; approved biologics are target validation, reported
  separately and labeled as such); druggability as a range across clustering settings
  and across an ensemble, never a point; pocket volume as the primary geometric
  number since volume is reproducible where druggability is not; and whether a low
  score reflects a measured dead site or an unmeasurable cryptic one.
- **Precedent axes never merge.** Activity on this target, on a pocket neighbour, on
  a structural neighbour, and on a sequence family are four different claims of four
  different strengths. "No actives on this target; 340 across the family, best 2 nM"
  is honest and useful. "Moderate precedent" is not.
- **Non-goals, from its own contract:** does not decide whether to pursue the
  indication, does not rank hypotheses against each other, does not average the axes,
  does not design molecules, does not assess biologics. **Clinical failure is not
  evidence against tractability** — a target with 152 holo structures, 12,900
  compounds, 0.1 nM potency and zero approvals is tractable and clinically failed,
  and both belong in the dossier without either discounting the other. The
  terminations are recorded; station 4 and the human weigh them.
- **"Insufficient evidence" is a correct answer** and passes through as such. A
  confident score on an unstudied target is the worst output in the system.

### [3] trial-recruitment-forecaster

`managed/trial-recruitment-forecaster/` — `thesis.ts` (the team-wide thesis
contract), `recruitability.ts` (the engine), `ctgov.ts` (ClinicalTrials.gov v2),
`backtest.ts`, `fixtures/theses.json`, `demo.ts`. The engine runs behind the agent's
tool handlers; `demo.ts` and `backtest.ts` remain the local development surface.

- **Ask:** the thesis, optionally an evidence horizon and a site count.
- **Answer:** simulated months to enroll with a range; a recruitability score;
  required sample size and how it was derived; site count and where it came from;
  patients screened per enrollee; the eligibility pass rate with its ranked
  screen-fail drivers and the trials whose criteria were read; competing trials;
  cited precedent; precedent trials that died of recruitment; and, when the design is
  too slow, the smallest change that reaches feasibility.
- **The counterfactual is the deliverable.** Not "this trial takes 63 months" but
  "broaden the marker from 30% to 40% and it takes 47." That is a design change
  station 4 can price, and it is what the orchestrator forwards.
- **The word that must survive the hop is `simulated`.** Every number here is
  modeled, the field names say so, and this station produces the most
  authoritative-looking output in the pipeline — the easiest in the system to misread
  as validated. In its backtest, only the "actual" column is real.
- **Sample size respects history over formula.** The textbook two-arm calculation is
  floored by the indication's phase-3 precedent median where enough precedent exists:
  the real EoE phase 3 enrolled 321 where the formula said 65. History wins, and the
  basis is reported either way.
- **Known leak, stated rather than hidden:** every registry-derived number is
  horizon-filtered, but the eligibility judgment is a present-day model reading
  period-appropriate criteria text. The prompt pins the horizon and forbids outside
  knowledge, which constrains but does not prove. Say it that way on stage.

### [4] therapeutic-program-economics

`managed/therapeutic-program-economics/` — validated contracts in `models.py`, the
orchestrating engine in `engine.py`, evidence rules in `docs/source-policy.md`,
agent rules in `docs/agent-quickstart.md`, synthetic fixtures in `fixtures/`. The
`labrador` CLI (`validate`, `analyze`, `compare`, `portfolio`, `example`) is the
handler surface behind the agent and the local development surface for humans.

- **Ask:** a validated program brief, an explicitly typed comparable-price catalog,
  a simulation count and a seed. It rejects unlabeled precision at ingestion rather
  than inventing it downstream.
- **Answer:** a screening recommendation with pricing corridors, access and
  affordability, annual cash flow, protected versus post-loss-of-exclusivity revenue,
  risk-adjusted NPV percentiles, the calculation steps, warnings, provenance, and a
  decision-grade flag. Deterministic for a fixed seed — same inputs, same result, for
  a human analyst and an agent alike.
- **What must survive the hop:** the decision grade, the seed, the simulation count,
  and every warning. A percentile quoted without its seed and its grade is not a
  result. Every bundled input is synthetic and therefore `NOT_DECISION_GRADE`;
  relabeling without replacing the evidence does not change that.
- **Rules that hold at the seam:** list price, public reimbursement, estimated net
  and observed net are four different things and are never pooled — no comparable
  reveals a confidential manufacturer net price. A comparable is evidence, not proof
  that two therapies deserve the same price. The 20-year patent clock starts at
  filing and a label expansion does not restart it. Patient income constrains
  coverage, initiation, cost sharing and access; it cannot mechanically reduce
  clinical benefit. Cost-effectiveness, payer budget impact, patient affordability
  and manufacturer cash flow are separate outputs, and a favorable result in one
  establishes nothing about another.
- **Non-goals:** does not establish clinical efficacy, perform legal patent analysis,
  negotiate coverage, retrieve confidential rebate contracts, predict competitor
  behavior, or replace a jurisdiction-specific HEOR model. Portfolio ordering is a
  declared numeric screening sort, never an investment ranking, and comparison
  requires a shared currency and valuation year — no silent FX or time-basis
  conversion.

## The orchestrator

A Claude agent holding the thesis, the run log, and the dossier. Per station it:

1. Writes the brief — header block with the binding `as_of`, the ask in the
   station's own vocabulary, and only the upstream findings that bear on it.
2. Calls the station and waits.
3. Appends the answer to the dossier **unedited**, then writes its own
   one-paragraph read of what it means for the thesis, explicitly marked as the
   orchestrator's interpretation rather than the station's finding.
4. Decides whether any cross-station follow-up above is triggered, and logs the
   trigger alongside the follow-up.

It never rewrites a station's numbers, never resolves a cross-station disagreement,
and never produces a composite score. Its output is a dossier with one section per
station, a disagreement list, a follow-up log, and the run's `as_of` and seeds
recorded once at the top.

**Failure is a section, not an exception.** A station that cannot answer returns why
— unavailable source, insufficient evidence, missing structure, unsupported input —
and that goes in the dossier as a finding. A run with three answers and one
documented gap is a result. A run that silently drops a station is not.

## What this spec does not claim

The four stations were built to different maturity and verification standards, and
each carries known limitations recorded in its own files. The pipeline produces a
dossier a human reads and argues with. It does not produce a decision, a ranking, or
a score, and presenting its output as a single validated verdict would be the exact
error that every station's own contract was written to prevent.
