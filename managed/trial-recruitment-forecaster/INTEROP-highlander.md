# Highlander ↔ trial-recruitment-forecaster interop — verification

COORDINATION.md §5 flags `hypothesis-highlander` as "module-agnostic but
unverified — its `test_interop.py` runs against stubs". This report closes the
**forecaster side only**: `RecruitabilityResult` (`recruitability.ts`) and the
shared contract `IndicationThesis` (`thesis.ts`). The economics, mapper and
tractability sides stay open for their owners.

Owner: Abhishek, 2026-08-15 late. **Read-only on
`managed/hypothesis-highlander/` — nothing there was modified.** Every verdict
below was produced by running the real code against real payloads (probe
scripts kept out of the repo, in `/tmp`), not by reading alone.

## Method

- Read `highlander/{adapters,thesis,genome,tiers,controller,generator}.py`,
  `tests/test_interop.py`, `README.md`, `COMPOSE.md`.
- Fed highlander's own `IndicationThesis.from_json` a REAL forecaster fixture
  (`fixtures/theses.json[0].thesis` + `target.uniprotAccession`).
- Fed `thesis.ts`'s zod schema a REAL highlander payload (`Genome.to_thesis()`
  shape).
- Ran highlander's `adapter_A_graph_to_evidence` on the REAL mapper graph
  `managed/research-evidence-mapper/runs/g_1a4f.json`.

`test_interop.py` never touches any of these: its graph, its forecaster output
and its thesis are all inline dict literals, and the thesis it validates
against is highlander's own Python mirror, not `thesis.ts`. All 5 of its tests
pass (executed directly; pytest is not installed in this checkout) and prove
nothing about the real contracts — which is exactly the §5 concern, now
confirmed.

## 1. Recruitability module — what highlander expects vs what the node emits

Highlander reads the forecaster in exactly one place,
`adapters.py:76-81 recruitability_from_forecaster(out: dict)`. Two keys. There
is no TypedDict, dataclass or Protocol for it.

| Field highlander expects | What the forecaster emits | Verdict |
|---|---|---|
| `out["score"]`, float 0–1 (`adapters.py:78-79`) | `score: number`, **required**, `recruitability.ts:120`, "0 = unenrollable, 1 = enrols comfortably" | **match** — name and units |
| `out["simulatedMonthsToEnroll"]`, default `36` (`adapters.py:80`) | `simulatedMonthsToEnroll: number`, **required**, `recruitability.ts:127` | **match** on name; the default is dead code (the node always emits `score`, so line 80 is unreachable against the real node) |
| the fallback curve `1-(months-12)/48` (`adapters.py:81`) | the node's own `scoreFromMonths`: 1 if ≤18 mo, 0 if ≥48 mo, else `1-(months-18)/30` (`recruitability.ts:451-459`) | **semantic mismatch (latent)** — at 40 months the node says 0.27, the fallback says 0.42. Harmless while `score` is present; wrong the moment anyone hands it a partial payload |
| — | 16 emitted fields highlander never reads: `counterfactual{achieves,change,simulatedMonthsAfter}`, `simulatedMonthsRange`, `screensPerEnrollee`, `requiredN`, `sites`/`sitesBasis`, `phase3MedianN`, `precedentMedianN`, `poweringBasis`, `eligibility`, `evidence`, `failedPrecedents`, `waterfallDelta`, `why`, `asOf` | **missing (by choice)** — not a defect, but `counterfactual` is the node's most decision-relevant output (the cheapest change that makes an infeasible trial feasible) and a search layer that ignores it cannot act on it |
| a Python `dict` | a TypeScript `Promise<RecruitabilityResult>` | **wiring gap** — there is no process boundary yet; `COMPOSE.md:40` says "replace `_recruitability`'s mock forecast with the forecaster's real output", which means someone must run `assessRecruitability` (async, needs `ANTHROPIC_API_KEY` + CT.gov) and hand over JSON |

Verdict for this table: **the two field names highlander depends on are
correct.** Nothing needs renaming. The gap is that no code path connects them.

## 2. IndicationThesis — both directions

Highlander mirrors the contract by hand in `highlander/thesis.py` ("mirrored
from LABrador's thesis.ts", L2). Mirrors drift; this one has.

| Field highlander expects/emits | What `thesis.ts` actually says | Verdict |
|---|---|---|
| `IndicationThesis.uniprotAccession`, **top level** (`thesis.py:57`; written `genome.py:96`; read `genome.py:108`; asserted `test_interop.py:20`) | `target.uniprotAccession`, **nested** (`thesis.ts:129`; §6 item 2: "Implemented (optional `target.uniprotAccession`)") | **rename/move needed — and it fails SILENTLY in both directions.** Verified: `IndicationThesis.parse()` on a highlander-shaped thesis returns `target.uniprotAccession === undefined` and strips the top-level key with no error (zod strips unknowns); highlander's `from_json` on a real thesis carrying `target.uniprotAccession: "P24394"` yields `t.uniprotAccession is None`. Rafal's join key is lost on every crossing |
| `Evidence.direction ∈ {supports, contradicts}` (`thesis.py:21`, asserted `thesis.py:37`) | `{supports, contradicts, **no_effect**}` (`thesis.ts:72`; §6 item 3, ratified: "a null result and evidence against are different facts") | **semantic mismatch — hard failure.** Verified: a real `no_effect` row (exactly what `evidence-bridge.ts` emits from the real g_1a4f graph) raises `AssertionError: bad evidence direction no_effect` inside `IndicationThesis.validate()` |
| `mechanismHypothesis: str = "unknown"`, top level, always present (`thesis.py:58`) | `mechanismHypothesis: MechanismHypothesis.optional()`, top level (`thesis.ts:119`) | **match on placement**, minor semantic difference: highlander cannot express "absent", only `"unknown"` |
| `from_json(d)` → `IndicationThesis(**d)` with **no key filtering** (`thesis.py:83`) | a schema whose whole ratification strategy (§6) is *additive optional fields* | **fragility.** Verified: one extra top-level key raises `TypeError: unexpected keyword argument`. The next ratified field breaks highlander's ingestion |
| `Genome.from_thesis(t)` uses attribute access (`genome.py:103-111`) | a TS node emits JSON, i.e. a dict | **wiring gap.** Verified: `from_thesis(dict)` raises `AttributeError: 'dict' object has no attribute 'target'`. Callers must go through `IndicationThesis.from_json` first; `COMPOSE.md` does not say so |
| emits `asset{modality,name}`, `target{symbol,direction}`, `disease{name}`, `biomarkerPopulation{marker,prevalenceInDisease,assayAvailable}`, `endpoint{name,type}`, `mechanism`, `evidence`, `tissue`, `uncertainty` (`genome.py:84-98`) | same names, same nesting (`thesis.ts:80-136`) | **match** — a `Genome.to_thesis()` payload parses cleanly under `IndicationThesis.parse` (verified), modulo the accession above |
| never emits `endpoint.expectedEffectSize` (`genome.py:91`) | optional (`thesis.ts:106`) | **match, with a cost** — the forecaster then falls back to precedent-median powering instead of computing N from the effect size. Legal, but every highlander-generated thesis lands on the same powering path |
| never emits `asset.sponsor`, `disease.subtype` | both optional | **match** |
| `biomarkerPopulation.assayAvailable` hardcoded `True` (`genome.py:90`) | required boolean | **semantic mismatch (soft)** — an assumption presented as a fact; for a search layer enumerating speculative biomarkers this is the field most likely to be false |

## 3. The duplicated adapters (both nodes built one)

Highlander ships its own Adapter A and Adapter B (`adapters.py:24`, `:56`),
and so does this node (`evidence-bridge.ts`, `economics-bridge.ts`). They
disagree. This is the item COORDINATION.md §5 should track, because two
adapters producing different numbers from the same upstream is worse than one.

| Point of divergence | highlander `adapters.py` | forecaster bridge | Verdict |
|---|---|---|---|
| mapper `no_effect` | → `contradicts` + `" [no_effect]"` appended to the claim, strength ×0.7 (`:36-37`, `:43-44`) | → `direction: "no_effect"`, the ratified third value | **semantic mismatch, and highlander's side is now out of date** — §6 item 3 settled this after highlander was written |
| `Evidence.strength` | `0.5×study_type + 0.5×findings.confidence`, ×0.5 if not `is_own_result`, ×0.7 if hedged, own study scale (`:19-20`, `:40-44`) | study-type table copied verbatim from the mapper's `assemble.py:199`, ×0.8 preprint, nothing else | **semantic mismatch** — highlander folds in `findings.confidence`, which SCHEMA.md note 3 calls model self-reported; its study scale (clinical_trial 0.8) also differs from the mapper's own (0.9) |
| `background_only` / `hedged_only` findings | kept, discounted (verified: f6 from the real graph is emitted at strength 0.2) | dropped, mirroring Rafal's `graph_read.py:31` | **divergence to settle** — two consumers of one upstream disagree on what is actionable |
| `Evidence.source` | `doi` → paper `id` → `"unknown"` (`:48`) | `doi:` else `PMID:`, otherwise the row is DROPPED | **semantic mismatch** — `"p1"`/`"unknown"` passes highlander's `assert self.source` and passes `thesis.ts` (any non-empty string), but it is not "a real identifier" as `thesis.ts:60-62` requires. Inspectability is lost silently |
| launch delay | scalar `launch_delay_years`, 2dp, target 24 mo, rate hardcoded `5.06e6` (`:56-64`) | whole years (engine rounds: `simulation.py:160`), target = 18 mo (the node's `GOOD_MONTHS`), triangular `{low,mode,high}`, rate read live from `summary.value_lost_per_launch_delay_year` | **semantic mismatch** — the engine's `SimulationAssumptions.launch_delay_years` is a `TriangularRange` (`simulation.py:51`), so a scalar does not drop in; and the hardcoded rate silently goes stale |

Both adapters agree on the important thing: months → launch delay, never
`score` → PoS and never months → `stage_durations`. The disagreements are all
downstream of that.

Real-graph check: highlander's Adapter A on `runs/g_1a4f.json` emits **12 rows,
11 supports / 1 contradicts, strengths 0.2–0.6**, and
`plausibility_from_evidence` scores it **0.996** — a near-certain plausibility
from four in-vitro papers, one of which is a background citation. This node's
bridge emits 11 rows (f6 dropped) at 0.5–0.6.

## 4. Verdict

**The recruitability field names match; the thesis mirror has drifted.**
Highlander will not crash on a real forecaster result — it reads `score` and
`simulatedMonthsToEnroll`, both of which exist with those exact names. It
*will* silently lose `target.uniprotAccession` in both directions, and it
*will* hard-fail `validate()` on any thesis carrying a `no_effect` evidence
row, which is precisely what Adapter A now produces from real mapper graphs.

## 5. Minimal adapter recommendation

Smallest change set, all inside `hypothesis-highlander/` (its owner's call —
this report changes nothing there):

1. **Move the accession.** Emit `target={"symbol": …, "direction": …,
   "uniprotAccession": …}` in `genome.py:87` and read it back from
   `t.target.get("uniprotAccession")` in `genome.py:108`; drop the top-level
   dataclass field, or keep it as a deprecated alias populated from `target`.
   Update `test_interop.py:20`, which currently pins the wrong placement.
2. **Add `no_effect`** to `EVIDENCE_DIRECTION` (`thesis.py:21`) and stop
   collapsing it in `adapters.py:36-37`. Treat it as neutral in
   `plausibility_from_evidence` (`adapters.py:72`) — today every non-`supports`
   row subtracts, so a null result would count as evidence against.
3. **Make `from_json` tolerant**: filter to known dataclass fields
   (`{k: v for k, v in d.items() if k in {f.name for f in fields(...)}}`) so
   additive `thesis.ts` fields stop being breaking changes.
4. **Prefer this node's bridges over the local ones** once a process boundary
   exists: `evidence-bridge.ts` and `economics-bridge.ts` are owned, run
   against real artifacts, and are the ones COORDINATION.md §5 tracks. If
   highlander keeps its own for standalone mode, label them "standalone
   proxy", the way `_simple_rnpv` already is (`COMPOSE.md:31`).
5. **A 6-line contract test** would have caught 1–3: build a thesis from
   `managed/trial-recruitment-forecaster/fixtures/theses.json`, round-trip it
   through `from_json`/`to_thesis`, and assert the accession survives. Stubs
   cannot catch a drifted mirror; only the real fixture can.

Not recommended: renaming anything on the forecaster side. Its field names are
what highlander already expects, and `thesis.ts` is the ratified contract.
