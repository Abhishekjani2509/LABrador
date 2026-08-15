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

## Fixture results (2026-08-15, after adversarial review round)

| Fixture | Result | Counterfactual |
|---|---|---|
| dupi-eoe @2018-01-01 (hero) | **12 mo, 100/100** — leak-free on all axes: N=88 (2018's own phase-3 median), 40 sites, ~20 interventional competitors *at the horizon*, failed-precedents horizon-filtered | none needed |
| dupi-eoe today | 22 mo, 87/100 | borderline: no relaxation reaches 18; ~85 sites would |
| dupi-eg today | 25 mo, 77/100 | **"good" tier: broaden 70%→96% → 18 mo** |
| il13-eoe-fibrostenotic | 63 mo, 0/100 | **"feasible" tier: broaden 30%→40% → 47 mo** |
| narrow-marker-asthma | 181 mo, 0/100, ~37 screens/enrollee | "feasible" tier: broaden 6%→86% → 47 mo — i.e. abandon the enrichment strategy, which is dupilumab's real severe-asthma story |

All three counterfactual tiers (good / feasible / borderline-none) are now
demonstrated across the fixture set.

Gift finding intact and now horizon-honest: the 2018 run cites only pre-2018
recruitment deaths (NCT01458418 "inability to complete enrollment",
NCT01404832 "inadequate recruitment"); NCT02881372 ("lack of recruitment",
withdrawn 2023) appears only in today-runs.

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

## Adversarial review round (21-agent workflow, same day)

11 confirmed findings, all fixed: percentile() nearest-rank off-by-one (p75
of a 4-sample pool was the MAX — now linear interpolation); monthsBetween
mixed UTC parsing with local getters (off-by-one months west of UTC, silent
trial drops — now getUTC*); **asOf runs leaked post-horizon terminations
into failedPrecedents** (a 2018 run showed 2019–2023 failures as kill-mode
fuel — now horizon-filtered); one-page truncation with fetched totals
discarded (completed page → 300, competition counts scaled by total/page,
sampling disclosed in `why`); NaN-surviving LLM multiplier and un-validated
drivers/citedTrials (strict validation, bad samples dropped); one fetch or
one bad NCT id killing whole demo/backtest runs (allSettled + one retry on
429/5xx); NaN panel size silently producing an empty "successful" backtest
(validated, throws usage).

## Known limitations (ranked)

1. Velocity scale-transfer (above) — the big one, isolated by the backtest.
2. **The Claude eligibility multiplier is an unclosed post-horizon channel
   in asOf runs**: the model has 2025-era knowledge of the asset, and the
   criteria text is the registry's CURRENT version. The prompt now pins the
   horizon and forbids outside knowledge, but that constrains, not proves.
   The honest phrasing on stage: "every *registry-derived* number is
   horizon-filtered; the eligibility judgment is a present-day model reading
   period criteria text."
3. GOOD_MONTHS=18 may be miscalibrated for registrational N: real phase 3s
   enrol in ~30 months. Consider phase-scaled thresholds.
4. Eligibility multiplier still drifts with corpus changes (search-result
   order), just not with sampling dice.
5. Historical-competition window counts trials missing dates as absent, and
   page-scaled counts assume the page is representative of the total.

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
