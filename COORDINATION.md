# COORDINATION.md — team state + working process

**Read this file first every time you pull `main`.** It is the single source
of truth for who owns what, what is done, what is pending, what nobody owns
yet, and the process we all follow. If you change any of those facts, you
update this file in the same push. Last full update: **2026-08-15 (late
evening — refreshed after every merge per §7.10)**.

---

## 1. The pipeline (who feeds whom)

```
hypothesis (thesis.ts contract)
      │
      ├──> research-evidence-mapper ──── findings[] ──┐   (adapter A, built: evidence-bridge.ts)
      ├──> small-molecule-tractability-review         ├─> IndicationThesis.evidence[]
      │                                               │
      ▼                                               │
trial-recruitment-forecaster  <───────────────────────┘
      │  score, simulatedMonthsToEnroll, counterfactual
      ▼   (adapter B, built: economics-bridge.ts, months -> launch-delay overlay)
therapeutic-program-economics
      │  rNPV, value_lost_per_launch_delay_year, decision grade
      ▼
   verdict
```

The shared contract is [`IndicationThesis`](./managed/trial-recruitment-forecaster/thesis.ts).
**Status: not yet ratified — see §6.** Nothing composes end-to-end today;
adapters A and B are both built (§5) and await their upstream owners' review.

## 2. Branch map — who owns what

| Person | Branch | Node (dir under `managed/`) | Merged into main? |
|---|---|---|---|
| Abhishek | `abhishek-jani` | `trial-recruitment-forecaster` | ✅ |
| Rafal | `rafwiewiora/druggability-dossier` | `small-molecule-tractability-review` | ✅ (incl. `f84bfff`: 651x figure withdrawn, cryptic/disorder/interface modules added) |
| Soliman | `msoliman6/literature-graph-mcp` | `research-evidence-mapper` | ✅ |
| Moamen | `moamen` | ~~`sandbox-capability-probe`~~ — **deleted from repo** ("delete useless spike", 2026-08-15 late): throwaway that served its purpose; findings preserved in research-evidence-mapper's CONTRACT.md | ✅ (then removed) |
| Vince | `vaalessi/program-strategy-valuation` | `therapeutic-program-economics` | ✅ |
| Vince | `vaalessi/hypothesis-highlander` | `hypothesis-highlander` (meta-search ABOVE the pipeline) | ✅ |
| Abraham (+ Sean, Weichi) | `AbrehamT/Hypothesis_Generator` | hypothesis node — **no code pushed yet**; note Vince's highlander now covers hypothesis *enumeration* — coordinate to avoid building the same thing twice | (nothing to merge) |
| Cyrus | works on `main` | infra, merges, renames, README | — |

Note: Cyrus renamed all node dirs on 2026-08-15 (`d6b8451`). Old names
(`simulated-clinical`, `druggability-dossier`, `literature-graph`, `spike`)
are dead — do not create files under them.

## 3. Done — per person

**Abhishek — trial-recruitment-forecaster** *(runnable)*
- Engine: precedent velocity → biomarker narrowing (floored) → Claude-read
  eligibility (median-of-3) → competition → phase-3-floored powering →
  sites-from-precedent → counterfactual bisection search (good/feasible/none).
- 4 fixtures covering all counterfactual tiers; leak-free 2018 retrospective
  (dupilumab-EoE: 12 mo, 100/100, approved 2022); 6-trial backtest.
- 11 adversarial-review findings fixed same day. `thesis.ts` authored (the
  proposed shared contract). Details: [NEXT.md](./managed/trial-recruitment-forecaster/NEXT.md).
- Adapter B shipped (`economics-bridge.ts`, 2026-08-15 late) — see §5 row.
- Adapter A shipped (`evidence-bridge.ts`, 2026-08-15 late), run on Soliman's
  real `runs/g_1a4f.json` — see §5 row for the schema deviations it found.

**Rafal — small-molecule-tractability-review** *(partial prototype)*
- 4 real skills (precedent-lookup, structure-select, pocket-scan,
  falsification-sweep), deployed CPU Modal pocket scanner (fpocket + P2Rank),
  10-target calibration fixtures, evidence-rules CLAUDE.md, pipeline.html
  status board. Precedent + structure-selection stages VERIFIED.
- graph-intake stage (2026-08-15 late): reads a research-evidence-mapper
  graph on the REAL SCHEMA.md (first live cross-node edge — mapper →
  tractability) and nominates UniProt targets from it; handles `no_effect`,
  `hedged_only`, failed-graph status, and gene-vs-protein kinds.
- Hardened against the FIRST REAL mapper graph (g_1a4f, 2026-08-15 late):
  the real graph carries no protein/gene entities — proteins survive only
  inside intervention names ("IRAK4 inhibition" typed small_molecule) — so
  intake initially nominated nothing despite all self-written fixtures
  passing. Lesson recorded: fixtures you write yourself lie; §6 item 6 is
  the schema-level fix.

**Soliman — research-evidence-mapper** *(DEPLOYED 2026-08-15 late — second live Managed Agent, first product one)*
- SCHEMA.md / CONTRACT.md / BUILD.md design packet, now plus: agent
  CLAUDE.md, three skills (literature-search, claim-extraction,
  graph-assembly with deterministic assemble.py), and first run artifacts
  (`runs/g_1a4f`). Deployed: manifest + acl + eve wrapper landed, plus a
  shared-runtime MCP fail-fast watchdog (surfaces never-reached-tools in
  minutes instead of after the timeout budget).

**Moamen — sandbox-capability-probe** *(done; node since deleted from the repo — findings live on in Soliman's CONTRACT.md)*
- The only deployed Managed Agent. Proved: bundled scripts execute in the
  sandbox, python 3.11 + uv present, memory mounts writable, sqlite3 absent,
  egress open to the 3 tested hosts. Results recorded in Soliman's CONTRACT.md.

**Vince — therapeutic-program-economics** *(runnable, v0.2.0)*
- Deterministic pydantic/numpy economics simulator: pricing corridors, patent
  clock, cash flow, Monte Carlo rNPV, provenance + secret redaction,
  decision-grade gate. CLI + Streamlit.
- v0.2.0 hardening drop (2026-08-15 late): evaluation module with reality
  anchors, run replay, red-team hardening + interpretability-contract docs,
  five new test suites — 87/87 tests pass on merged main.
- PoA + antibody hardening (2026-08-15 late): Modality enum extended with
  ANTIBODY (his §4 item — antibody programs like dupilumab are now
  priceable, so the forecaster fixture set composes with economics), and
  the demo fixture's PoA inconsistency fixed (gate ERROR gone).
- **NEW node: `hypothesis-highlander`** (2026-08-15 late) — quality-diversity
  meta-search that sits ABOVE the four nodes: fixes one indication (RA
  example), enumerates biomarkers × hypotheses, runs each through the
  existing nodes, learns across runs (MAP-Elites archive + Pareto front +
  failure ledger). Module-agnostic by design; stdlib core; 18/18 tests pass
  on merged main. Interop with the real node contracts not yet verified —
  see §5.

**Cyrus — infra**
- Merged all branches into `main`, renamed nodes for clarity, rewrote README
  with honest capability boundaries, Managed-Agents harness + deploy/console
  CLIs. `main` is the default branch.

## 4. Pending — per person

**Abhishek**
- [ ] Drive `thesis.ts` ratification (§6) — blocking all composition.
      **Update 2026-08-15 late: the schema legwork is DONE** — all four §6
      items implemented as additive optional fields on `abhishek-jani`
      (old theses still parse; typecheck + check green). What remains is
      sign-offs: checklist now in §6.
- [ ] Wrap forecaster as a Managed Agent (fresh session: `/clear` →
      `/managed-agent-prototype`; engine becomes `tools.ts` handlers). Do
      after ratification.
- [x] ~~Known model limitation: per-site velocity doesn't transfer to 100+
      site scale.~~ **Decided 2026-08-15 late on 22 fresh backtest rows
      across two conditions**: √-dilution REJECTED as a blanket engine term —
      the pool-median anchor degenerates to 1 site and blows predictions
      3–17x; an at-scale anchor helps EoE but wrecks already-calibrated
      atopic dermatitis. Both variants now print as EXPERIMENT columns in
      `backtest.ts` on every run; the remaining open problem (a mismatch
      gate) is documented in NEXT.md and stays in its Known limitations.

**Rafal**
- [x] `f84bfff` merged (2026-08-15 late, rename-aware).
- [ ] Falsification sweep has never been executed; dossier assembly never run
      end-to-end; GPU escalation stage blocked on a Modal payment method.
- [ ] Pocket scanner runs in Rafal's personal Modal workspace — single point
      of failure for any demo; document or share the credential path.
- [ ] Pin the `proto-tools` git dependency (unpinned ref = unreproducible image).

**Soliman**
- [x] First implementation drop merged (CLAUDE.md, 3 skills, assemble.py,
      run artifacts). Remaining per BUILD.md: fixtures, wrapper, and the
      blocking verification criteria — owner to confirm what's left.
- [ ] Long-lived Paperclip auth (which header the MCP accepts for API keys).
- [ ] Committed session id in CONTRACT.md:199 — scrub if repo goes public.

**Moamen**
- [ ] Nothing owed. Optional high-leverage favor: add `clinicaltrials.gov`
      (and any host another node needs) to probe.py's NET list and re-run, so
      sandbox egress is known before anyone's Managed-Agent wrap assumes it.

**Vince**
- [x] demo fixture PoA inconsistency fixed (2026-08-15 late) — gate ERROR gone.
- [x] Modality enum extended with ANTIBODY (2026-08-15 late) — dupilumab-class
      programs now representable; thesis.ts boundary comment updated to match.
- [ ] Component README says "no license selected"; root repo says MIT — align.

**Abraham / Sean / Weichi**
- [ ] Hypothesis node: nothing is pushed. The pipeline's entry point does not
      exist. If it emits `IndicationThesis` (§6), everything downstream is
      already runnable against it.

**Cyrus**
- [x] Rafal's `f84bfff` rename-aware merge (done by the integrator flow).
- [ ] No orchestrator; router has no registered specialists yet.

## 5. Unowned work + active hazards

| Item | What it is | Suggested owner |
|---|---|---|
| ~~**Adapter A**~~ | **Built 2026-08-15 late (owner Abhishek; Soliman to review)**: `managed/trial-recruitment-forecaster/evidence-bridge.ts` — mapper `findings[]` → thesis `Evidence[]`, run against the REAL `research-evidence-mapper/runs/g_1a4f.json` (12 findings → 11 rows; f6 dropped, `background_only`). `no_effect` convention settled: passthrough to the third `direction` value (§6 item 3), never collapsed. `claim` carries the verbatim quote + triple; `source` is `doi:`/`PMID:` and a paper with neither drops the row; `strength` copies the mapper's own `_STUDY_QUALITY` table (assemble.py:199) ×0.8 preprint; `background_only`/`hedged_only` excluded, mirroring Rafal's `graph_read.py:31`. **REAL-ARTIFACT CAVEAT for Soliman**: g_1a4f deviates from SCHEMA.md — findings lack `round` and `flags`, papers lack `round`, findings carry an undocumented `claim` paraphrase, and `findings/r2.json` is a full snapshot rather than an append-only round chunk (concatenating chunks double-counts). Also untested: no `no_effect` finding exists in any real graph yet. | done (Abhishek; Soliman to review) |
| ~~**Adapter B**~~ | **Built 2026-08-15 late (owner Abhishek)**: `managed/trial-recruitment-forecaster/economics-bridge.ts` — overlay script shipped (delay years + triangular `launch_delay_years` range + counterfactual pricing, best-effort against the demo fixture, read-only on Vince's dir); **Vince to confirm the `launch_year` application convention**. The two "obvious" wirings remain wrong and are documented in the file header: score→PoS is a category error; months→stage_durations only shifts cost timing. The value-bearing slot is launch delay, which the engine already prices (`value_lost_per_launch_delay_year` ≈ $5.06M/yr on the demo fixture). | done (Abhishek; Vince to confirm convention) |
| **Orchestrator** | one command running thesis → evidence → recruitment → economics. NOTE: Vince's `hypothesis-highlander` claims this layer as a meta-search — decide whether it IS the orchestrator or sits above a simpler one | Cyrus + Vince |
| **Highlander↔nodes interop** | highlander says "module-agnostic" but its calls against the real node contracts (thesis.ts, RecruitabilityResult, ProgramInput, mapper graphs) are unverified — its test_interop.py runs against stubs. **Forecaster side VERIFIED 2026-08-15 late (Abhishek, read-only): the two `RecruitabilityResult` fields it reads (`score`, `simulatedMonthsToEnroll`) match exactly, but its hand-mirrored thesis has drifted — `uniprotAccession` is top-level instead of `target.uniprotAccession` (silently lost in BOTH directions, verified) and `Evidence.direction` lacks `no_effect`, so a real bridged thesis hard-fails its `validate()`. Report + mismatch table + minimal fix: [`managed/trial-recruitment-forecaster/INTEROP-highlander.md`](./managed/trial-recruitment-forecaster/INTEROP-highlander.md). Economics / mapper / tractability sides still open.** | Vince + node owners (forecaster side done) |
| ~~HAZARD: rename collision~~ | **Resolved 2026-08-15 late**: git's directory-rename detection mapped both Rafal's and Soliman's old-path commits onto the renamed dirs; new files were accepted at the detected locations. `scripts/integrate.ts` escalates this class and `fixDeadPaths` catches any residue. | done |
| **Decision-grade policy** | economics excludes simulation-sourced inputs from decision grade BY DESIGN — a composed demo will always read NOT_DECISION_GRADE unless the team explicitly decides how simulated upstream numbers are graded. Decide before the stage demo, not on it. | Everyone (5-min call) |

## 6. thesis.ts ratification agenda (the blocking conversation)

`IndicationThesis` is declared the shared contract in the README but no other
node consumes it yet. Concrete items, each discovered by reading the other
nodes' actual contracts. **Status 2026-08-15 late: items 1–4 are IMPLEMENTED
in `thesis.ts` on `abhishek-jani` as additive, optional, backward-compatible
changes — every pre-change fixture still parses, typecheck + check green.
Ratification is now a sign-off, not a design session.**

1. Add optional `mechanismHypothesis: "orthosteric" | "allosteric" |
   "oligomer_destabilisation" | "unknown"` — Rafal's node needs the enum
   (load-bearing for chain selection); free-text `mechanism` can't feed it.
   **Implemented** (optional top-level field).
2. Add optional `uniprotAccession` — Rafal's join key (gene symbol requires a
   resolution step he'd rather record than perform).
   **Implemented** (optional `target.uniprotAccession`).
3. `Evidence.direction` has `supports | contradicts`; Soliman's findings also
   emit `no_effect`. Pick a convention (third value, or map to contradicts
   with a note). **Implemented as a third value** — a null result and
   evidence-against are different facts; collapsing them destroys
   information. Consumers may treat `no_effect` as neutral.
4. Modality vocabulary: thesis has 6 values, economics accepts 2. Align or
   declare the boundary. **Boundary declared** in a comment on `Modality`:
   the wide vocabulary stays (upstream must not misdescribe an antibody to
   get a valuation); non-priceable modalities are the economics node's
   documented gap until its owner extends his enum (his §4 item).
5. Confirm the adapters in §5 and their owners (both are built; Vince to
   confirm the `launch_year` application convention for B; Soliman to review
   A's mapping and the SCHEMA.md deviations it found in `runs/g_1a4f`).
6. **SCHEMA.md: `how` needs an enum** (raised by Rafal's graph-intake,
   2026-08-15 late): every other categorical field is enumerated, but `how`
   is open vocabulary — so "drug inhibits IRAK4" (a target) and "drug
   reduces IL-6" (a downstream effect) are structurally identical. Soliman
   to enumerate at least the target-nominating verbs. **Now backed by real
   evidence**: the first real graph (g_1a4f) types "IRAK4 inhibition" as a
   small_molecule intervention with no protein/gene entity anywhere —
   consumers can't find targets without either typed entities or a `how`
   enum (see Rafal's e6d946c commit message for the full post-mortem).

Sign-off checklist (a "yes" or a concrete objection each; silence ≠ consent):

- [ ] **Rafal** — items 1–2: enum values + accession placement under `target`.
- [ ] **Soliman** — item 3: `no_effect` as a third `direction` value; and
      item 6: the `how` enum in SCHEMA.md.
- [ ] **Vince** — item 4: RESOLVED BY ACTION (he extended his enum with ANTIBODY) — formal yes still welcome;
      plus the Adapter B `launch_year` application convention (§5).
- [ ] **Abraham / Sean / Weichi** — as emitters: can the hypothesis node
      populate the required fields (all new fields are optional)?

## 7. The process (what you actually do)

**On every pull of `main`:**
1. `git pull` → **read this file** → check §5 for hazards touching your area.
2. If your plans changed since your last push, update your §3/§4 rows.

**While working:**
3. Work in **your own `managed/<node>/` directory**. Never edit another
   person's node dir; if you need something changed there, add a line to §5
   or ask the owner. Shared files (README, root configs, `thesis.ts` once
   ratified) change only with a §6-style agenda note or the owner's OK.
4. Keep your node's state honest in its own doc (NEXT.md pattern —
   trial-recruitment-forecaster's is the reference). Simulated numbers stay
   *named* simulated (`simulatedMonthsToEnroll`, `NOT_DECISION_GRADE` —
   both nodes already do this; keep the standard).

**Before every push:**
5. Run your node's verification (§8). Green or say why not in the commit.
6. Update this file: move finished items to §3, new debts to §4, new
   cross-node needs to §5.

**Landing work:**
7. Push to **your own branch**. The **auto-integrator** merges it to `main`:
   `bun scripts/integrate.ts` sweeps every branch, `merge --no-ff`s anything
   new, auto-fixes resurrected pre-rename paths, runs typecheck + check, and
   only pushes if green — a merge-log entry lands in §9 each time. It runs
   continuously from Abhishek's watcher session (30s polling) and anyone can
   run it manually. *(Amends the "Cyrus merges by hand" sprint decision —
   Abhishek's call, 2026-08-15 evening; revert by deleting this step.)*
8. **Conflicts and red checks are never auto-pushed.** The integrator reports
   `CONFLICT` / `COLLISION` / `VERIFY-FAILED` and leaves them for a human (or
   the watching Claude session) to resolve with judgment.
9. Small COORDINATION.md-only updates may go straight to `main`.
10. **After every merge lands, this file gets refreshed in two tiers:** the
    integrator appends the §9 log line (branch, commit subjects, checks)
    automatically, and the watcher session (or whoever merged) updates the
    affected person's §3/§4 rows and any §5 items the merge resolved — so
    §2–§5 never drift from what main actually contains.
11. After a merge lands: everyone pulls, GOTO step 1.

## 8. Verification commands per node

| Node | Command(s) |
|---|---|
| repo-wide TS | `bun run typecheck && bun run check` |
| trial-recruitment-forecaster | `bun managed/trial-recruitment-forecaster/demo.ts` (needs `ANTHROPIC_API_KEY`); `bun managed/trial-recruitment-forecaster/backtest.ts` |
| therapeutic-program-economics | `cd managed/therapeutic-program-economics && uv sync --frozen --extra dev && uv run pytest && uv run ruff check .` |
| small-molecule-tractability-review | no runnable end-to-end yet; pipeline.html records per-stage status |
| research-evidence-mapper | docs only; BUILD.md lists blocking verification criteria |
| sandbox-capability-probe | `bun run console sandbox-capability-probe -- --once "run the probe"` (deployed) |

---

*Facts in this file were verified against the tree at `9003ad3` plus remote
branch state on 2026-08-15. If you find a stale claim, fixing it here IS the
process working.*

## 9. Merge log (automated)

Appended by `scripts/integrate.ts` on every verified auto-merge (manual tier-2 resolutions logged here too).

- **2026-08-15 23:55 UTC** — merged `msoliman6/literature-graph-mcp` (0941254, tier-2 rename-location resolution); earlier today: `f84bfff` + `1b39569` same class — typecheck+check green.
- **2026-08-15 23:58 UTC** — merged `vaalessi/program-strategy-valuation` (253a04f, tier-2: rename locations + pyproject version conflict — kept Vince's 0.2.0 bump with main's naming; new evaluation/replay/red-team modules) — his pytest 87/87 + typecheck+check green.

- **2026-08-16 00:00 UTC** — merged `vaalessi/program-strategy-valuation` (MERGED) — typecheck+check green.

- **2026-08-16 00:07 UTC** — merged `abhishek-jani` (MERGED) — Adapter B: forecaster -> economics launch-delay overlay (economics-bridge.ts) — typecheck+check green.

- **2026-08-16 00:11 UTC** — merged `rafwiewiora/druggability-dossier` (MERGED) — graph-intake: read the upstream evidence graph, on the real schema — typecheck+check green.
- **2026-08-16 00:23 UTC** — merged `abhishek-jani` (6c3c094, tier-2: par6 checklist union) — thesis.ts ratification legwork (items 1-4, all optional/back-compat, 4/4 fixtures parse) · backtest scale-transfer EXPERIMENT columns (sqrt-dilution rejected on 22 fresh rows) — typecheck+check green.

- **2026-08-16 00:25 UTC** — merged `vaalessi/hypothesis-highlander` (MERGED) — Add hypothesis-highlander: quality-diversity meta-search over the pipeline — typecheck+check green.
- **2026-08-16 00:30 UTC** — merged `msoliman6/literature-graph-mcp` (b9a0c71, tier-2: shared-runtime conflict — union of Cyrus's streaming generator + Soliman's MCP fail-fast watchdog, complexity refactor; wrapper paths fixed to renamed dir) — research-evidence-mapper is now DEPLOYED (manifest + acl + eve wrapper) — typecheck+check green.

- **2026-08-16 00:39 UTC** — merged `vaalessi/program-strategy-valuation` (MERGED) — Harden ROI PoA and antibody support — typecheck+check green.

- **2026-08-16 00:41 UTC** — merged `msoliman6/literature-graph-mcp` (MERGED) — mapper: raw-JSON output contract enforced, and gap ranking that discriminates — typecheck+check green.

- **2026-08-16 00:42 UTC** — merged `rafwiewiora/druggability-dossier` (MERGED) — graph-intake: survive the first real graph, and carry computation back — typecheck+check green.

- **2026-08-16 00:47 UTC** — merged `abhishek-jani` (MERGED) — Verify highlander interop against the real forecaster contracts (read-only) · Adapter A: mapper findings -> IndicationThesis.Evidence[], on the real graph; merged `vaalessi/hypothesis-highlander` (MERGED) — Apply adversarially-verified review fixes (7 items, +11 regression tests) — typecheck+check green.

## 10. Observability layer (glassbox) — plan + assignments

**Why:** a skeptical non-programmer will not trust a number they cannot check.
The glassbox wraps every node call in one identical **trace envelope** — data
used (checkable NCT/DOI/price ids + what each was used for), the decision with
its verbatim basis strings, what was handed to the next node, and honesty
labels (SIMULATED / SYNTHETIC / ASSUMED / NOT_DECISION_GRADE) that nothing
downstream may remove. It explains ONE run; `hypothesis-highlander` optimizes
across MANY — different layers, deliberately.

**Spec + working demo:** `managed/pipeline-observatory/` — DESIGN.md (envelope
spec, per-node instrumentation table, portability runbook), trace-demo.ts (a
REAL trace of forecaster → economics-bridge → economics, saved to
fixtures/trace-demo-output.json), observatory.html (open in any browser, no
server — the non-CS view). Every assignment below comes from the DESIGN.md §3
gaps table — nothing invented.

**Abhishek** — TASK: forecaster emits its own envelope pieces natively
(version/commit stamp, dataSource roles, eligibility ASSUMED label as a field)
instead of the demo deriving them. WHY: "which trials did you learn from, and
what's a guess?" answered by the node itself, not a wrapper. ACCEPTANCE:
trace-demo builds the forecaster envelope with zero derivation heuristics.
EFFORT: S.

**Soliman** — TASK: per-run quote-verification summary (assemble.py already
verifies quotes; surface pass/fail counts + coverage in one run-level block),
and fix the SCHEMA drift the bridge found (findings lack round/flags; r2.json
is a snapshot, not the promised append-only chunk). WHY: "verbatim quotes" is
only checkable if the checker's score is visible. ACCEPTANCE: a mapper run
artifact carries {quotesVerified, quotesFailed, coverage} and matches
SCHEMA.md. EFFORT: M.

**Rafal** — TASK: when dossier assembly first runs end-to-end, emit the JSON
with the falsification ledger + insufficient_evidence verdicts mapping into
envelope caveats/honestyLabels (the rules in your CLAUDE.md already define
them). Interim: pipeline.html stage statuses land as caveats. WHY: "is the
target druggable?" is currently the skeptic's biggest unanswerable. ACCEPTANCE:
one real dossier JSON wrapped by trace-demo. EFFORT: M (blocked on assembly).

**Vince** — TASK (economics): emit a one-sentence plain-language headline in
AnalysisResult (everything else already maps). EFFORT: S. TASK (highlander):
store the trace of each evaluated run in the archive entry, and reconcile your
built-in Adapter A/B with the canonical bridges (INTEROP-highlander.md lists
the exact divergences — background_only rows kept, source "unknown" fallback,
fractional delay years, hardcoded $/yr). WHY: an archive entry with a trace is
evidence; without one it's a claim. ACCEPTANCE: highlander interop tests run
against the real contracts, not inline stubs. EFFORT: M.

**Cyrus** — TASK: emit envelopes from the Managed-Agents runtime (runTask
already streams progress events — the natural hook), so DEPLOYED agents get
traced the same as local scripts. WHY: the glassbox must survive the move to
cloud agents or it dies at deployment. ACCEPTANCE: one deployed-agent call
produces a trace envelope with version/commit + duration. EFFORT: M.

**Moamen** — no assignment (probe node retired). Optional S: if any envelope
needs a new egress host from the sandbox, re-run the probe pattern first.

**Abraham / Sean / Weichi** — TASK (when the hypothesis node exists): emit an
envelope alongside each IndicationThesis — dataSources = the papers/graph ids
the hypothesis came from. WHY: the chain's FIRST link is otherwise invisible.
ACCEPTANCE: a thesis arrives with its envelope; trace-demo prepends it.
EFFORT: S (once the node exists).
