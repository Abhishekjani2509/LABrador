# simulated-clinical — state of play

Node (4) of the GO Hackathon pipeline, Track A. Owner: Abhishek.
Answers: *given an indication thesis, could this trial actually be enrolled?*

## What exists and is verified working

| File | What it is |
|---|---|
| `thesis.ts` | **The team-wide contract.** Zod schema for an indication thesis. Upstream (hypothesis node) emits it, ROI consumes the result. Not yet agreed with the team — see waiting-on-team. |
| `ctgov.ts` | ClinicalTrials.gov API v2 client. Free, no key. `asOf` horizons, `getTrial(nctId)`, endpoint-window parsing (`enrollmentMonths`). |
| `recruitability.ts` | The engine. Empirical velocity → biomarker narrowing (floored) → eligibility burden (median of 3 Claude reads of real I/E prose) → competition → powering (phase-3 floored) → sites from precedent → counterfactual search. |
| `backtest.ts` | Validation harness: predicted vs actual enrolment for completed trials, horizon rolled back to each trial's start. |
| `fixtures/theses.json` | 4 fixtures, one per mode, each with a `whyInSet` rationale. |
| `demo.ts` | Runnable. `bun managed/simulated-clinical/demo.ts [id] [asOf]` |

Verified end to end on 2026-08-15 (evening): typecheck + ultracite clean, all
four fixtures coherent, hero retrospective solid, backtest runs. `managed/simulated-clinical`
is un-gitignored (narrow negation; full `/managed-agent-setup` Phase 2 with
auth wiring remains a team decision).

## The model, current form

```
months = requiredN / (sites × velocity × max(prevalence × eligibility, 0.10) × 1/(1 + 0.08 × competitors))
```

- **velocity**: median pts/site/ENROLLING-month over interventional completed
  precedents (100-result pages — one page of 50 was measurably unstable).
  Each precedent's registry window is corrected for its own primary-endpoint
  follow-up ("At week 24" → −5.5 mo), floored at window/3.
- **requiredN**: textbook two-arm formula floored by the indication's phase-3
  precedent median when ≥3 phase-3 precedents exist. The real EoE phase 3
  enrolled 321 where the formula said 65; history wins. Basis is reported.
- **sites**: p75 of site counts among precedents with enrollment ≥ N/2
  (registrational sponsors behave like the upper quartile, not the single-site
  academic median), clamped to [40, 250]; explicit `opts.sites` wins;
  basis reported.
- **competition**: interventional-only. asOf runs use the window
  approximation (started ≤ horizon < primary completion) — current-status
  RECRUITING is era-leaky.
- **eligibility**: Claude reads precedent I/E prose; median multiplier of 3
  samples (`temperature: 0` is rejected by claude-sonnet-5 — "deprecated for
  this model"; sampling is the variance pin). Bad samples are dropped, not
  fatal.
- **counterfactual**: bisection for the smallest biomarker relaxation
  reaching ≤18 mo ("good") or <48 ("feasible"); a borderline design
  (19–47 mo, good unreachable) gets a sites-needed answer instead of a no-op
  relaxation; "none" states all-comers months + sites needed.

## Fixture results (2026-08-15, final model)

| Fixture | Result | Counterfactual |
|---|---|---|
| dupi-eoe @2018-01-01 (hero) | **16 mo, 100/100** — leak-free on all axes: N=88 (2018's own phase-3 median), 40 sites, 20 interventional competitors *at the horizon* | none needed |
| dupi-eoe today | 23 mo, 83/100 | borderline: no relaxation reaches 18; ~95 sites would |
| dupi-eg today | 27 mo, 70/100 | borderline (~109 sites) |
| il13-eoe-fibrostenotic | 65 mo, 0/100 | **rescue: broaden 30%→41% → 47 mo** (the solvable-relaxation stage moment) |
| narrow-marker-asthma | 234 mo, 0/100, ~37 screens/enrollee | none: all-comers 52 mo at 122 sites; N=511 vs 39 competitors is the real constraint |

Gift finding intact: NCT01458418 ("inability to complete enrollment"),
NCT02881372 ("lack of recruitment") — real EoE trials dead of what this node
predicts.

## Backtest results and what they mean

`bun managed/simulated-clinical/backtest.ts` — 6 completed EoE-family trials.
The comparator is now honest: predicted ENROLLING months vs the registry
window minus each trial's own endpoint window.

- Bullseyes when structure matches: lirentelimab 2.0x edge, CC-93538 safety
  0.92x, reslizumab 0.69x.
- **Known, isolated limitation: per-site velocity does not transfer across
  site-count scales.** The three registrational efficacy trials predict
  0.24–0.39x (too fast): precedent pools are 5–40-site trials at
  0.4–0.6 pt/site/mo; real 95–212-site machines ran 0.07–0.13. A √-dilution
  experiment (velocity × √(medianPrecedentSites/targetSites)) lands all three
  at 1.09–1.13x on paper but needs a scale-consistent anchor before engine
  adoption (naively applied it wrecks the hero fixture) — candidate next
  model change, decide with more than 6 backtest trials.
- Panel hygiene: NCT04991935 is a rollover study (enrolls pre-consented
  parent-trial patients) — an unfair backtest target; consider excluding
  extension/rollover designs from discovery.

## Fixed today (all previously-listed engine items)

1. Counterfactual bisection search with good/feasible/none tiers (old
   "double prevalence once" output void).
2. Low-prevalence blowup → 10% narrowing floor + `screensPerEnrollee`
   (2314-months output void).
3. Powering reconciled: phase-3 precedent median floors the formula.
4. Sites from precedent (p75 at scale, [40, 250]) instead of hardcoded 40.
5. asOf era-leaks closed: precedent completion filter + historical
   competition window; interventional-only everywhere.
6. Eligibility variance pinned (median-of-3; temperature rejected by API).
7. Endpoint-window correction: velocities and backtest compare enrolling
   months, not registry windows.
8. Fixture set: added il13-eoe-fibrostenotic (solvable relaxation); dupi-eg
   rationale rewritten — CT.gov concept-expands EG to the eosinophilic-GI
   family, so its old "thin precedent" premise was void; it now tests
   adjacent-indication borrowing.

## Known limitations (ranked)

1. Velocity scale-transfer (above) — the big one, isolated by the backtest.
2. GOOD_MONTHS=18 may be miscalibrated for registrational N: with the
   phase-3 floor, almost nothing reaches "good" — real phase 3s enrol in
   ~30 months. Consider phase-scaled thresholds.
3. Eligibility multiplier still drifts with corpus changes (search-result
   order), just not with sampling dice.
4. Historical-competition window counts trials missing dates as absent —
   uniform undercount.

## Waiting on team input (not blocked on code)

- **Ratify `thesis.ts`** with Sean / Abraham / Weichi and Vince before the
  integration hour, or nothing composes.
- **Team fixture asset** — dupilumab/EoE was a unilateral pick to unblock.
- **`/managed-agent-setup` Phase 2** (full un-ignore + auth wiring) — team
  decision; this node is already narrowly un-ignored.
- **Managed Agent wrap** — needs a fresh session by design: `/clear`, then
  `/managed-agent-prototype`; the engine becomes `tools.ts` handlers. Do it
  after thesis ratification so the contract doesn't shift under the deploy.

## Honesty requirement

Every number this node emits is simulated. Field names say so
(`simulatedMonthsToEnroll`, `simulatedPredictedMonths`), and provenance
fields (`poweringBasis`, `sitesBasis`, `why`) say where each factor came
from. Keep it that way in any UI — this node produces the most
authoritative-looking output in the pipeline and is the easiest to misread
as validated. In the backtest, only the "actual" column is real.
