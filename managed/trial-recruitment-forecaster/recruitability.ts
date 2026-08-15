/**
 * Trial recruitment forecasting.
 *
 * Answers one question about an indication thesis: *could this trial actually
 * be enrolled, and how long would it take?* — with every input traceable to a
 * real NCT id.
 *
 * The model, deliberately simple enough to explain on stage in 30 seconds:
 *
 *   1. Empirical velocity — from completed precedent trials in this disease,
 *      median patients enrolled per site per month. Real observed behaviour,
 *      not an assumption.
 *   2. Biomarker narrowing — a marker present in a fraction p of patients
 *      multiplies velocity by p. This is the term that usually decides things.
 *   3. Eligibility burden — Claude reads the actual I/E prose of the precedent
 *      trials and estimates what fraction of marker-positive patients would
 *      still pass, and names the drivers. Messy prose in, cited number out.
 *   4. Competition — trials currently recruiting the same population are
 *      competing for the same patients, so velocity is shared.
 *   5. Powering — required N from the predicted effect size.
 *
 * Every number below is SIMULATED. The output type says so in a field name,
 * not just in the UI, because this node emits the most authoritative-looking
 * numbers in the pipeline and is therefore the easiest to misread as validated.
 */
import { makeClient } from "@/lib/claude-managed-agent.ts";
import {
  enrollmentMonths,
  median,
  monthsBetween,
  searchTrials,
  type TrialRecord,
} from "./ctgov.ts";
import type { IndicationThesis } from "./thesis.ts";

/** Trials enrolling this fast per site per month when precedent is unusable. */
const FALLBACK_VELOCITY = 0.5;
/** Site count when precedent can't supply one (see `sitesFromPrecedent`). */
const DEFAULT_SITES = 40;
/**
 * One page of 50 was measurably unstable: the same condition returned a
 * velocity of 0.27 on page 1 alone and 0.405 with 100 results. Page 1 lies.
 */
const SEARCH_PAGE_SIZE = 100;
/** Months beyond which a sponsor treats enrolment as infeasible. */
const INFEASIBLE_MONTHS = 48;
const GOOD_MONTHS = 18;
/** Each concurrently recruiting competitor takes this share of the pool. */
export const COMPETITION_SHARE = 0.08;
/** Eligibility samples per assessment; the median multiplier is used. */
const ELIGIBILITY_SAMPLES = 3;

/**
 * The narrowing penalty (biomarker prevalence × eligibility pass rate)
 * saturates here. Below it, the pure flow model — velocity scales linearly
 * with prevalence — is wrong: sites stop waiting for marker-positive patients
 * to appear in clinic flow and pre-screen for the marker (records review,
 * registries, cheap assays) before consenting anyone. Biomarker-selected
 * trials in 1–5% populations do run — slowly, not 16× slower than their
 * disease's precedent velocity. The cost that DOES keep scaling with
 * 1/prevalence is screening burden, reported as `screensPerEnrollee` so the
 * floor never hides it.
 */
export const NARROWING_FLOOR = 0.1;

export function competitionPenalty(recruitingCount: number): number {
  return 1 / (1 + COMPETITION_SHARE * recruitingCount);
}

/** Per-site enrolment velocity after narrowing, its floor, and competition. */
export function effectiveVelocity(args: {
  baseVelocity: number;
  competitionPenalty: number;
  eligibilityMultiplier: number;
  prevalence: number;
}): number {
  const narrowing = Math.max(
    args.prevalence * args.eligibilityMultiplier,
    NARROWING_FLOOR
  );
  return args.baseVelocity * narrowing * args.competitionPenalty;
}

export type EligibilityBurden = {
  citedTrials: string[];
  /** Fraction of marker-positive patients who would still pass I/E. */
  multiplier: number;
  /** Named, ranked reasons patients screen-fail. */
  drivers: string[];
  reasoning: string;
};

export type RecruitabilityResult = {
  asOf?: string;
  /** The cheapest change that makes an infeasible trial feasible. */
  counterfactual?: {
    /**
     * What the solved relaxation reaches: "good" ≤ 18 months, "feasible"
     * < 48 months, "none" = no biomarker relaxation reaches either — the
     * change text then says what the binding constraint actually is.
     */
    achieves: "good" | "feasible" | "none";
    change: string;
    simulatedMonthsAfter: number;
  };
  eligibility: EligibilityBurden;
  evidence: { competingTrials: number; precedentTrials: string[] };
  failedPrecedents: { nctId: string; whyStopped: string }[];
  /** Median N of phase-3 precedents — the registrational-reality anchor. */
  phase3MedianN?: number;
  /** How `requiredN` was derived, for traceability. */
  poweringBasis: string;
  /** What comparable completed trials actually enrolled — a reality check. */
  precedentMedianN?: number;
  requiredN: number;
  /** Site count used, and where it came from. */
  sites: number;
  sitesBasis: "input" | "precedent" | "default";
  /** 0 = unenenrollable, 1 = enrols comfortably. */
  score: number;
  /**
   * Disease patients screened per enrolled patient, 1/(prevalence ×
   * eligibility). The screening-floor model keeps time-to-enrol finite at low
   * prevalence; this is where the low-prevalence cost actually lands.
   */
  screensPerEnrollee: number;
  simulatedMonthsToEnroll: number;
  simulatedMonthsRange: [number, number];
  /** Signed contribution to the thesis's evidence waterfall, in points. */
  waterfallDelta: number;
  why: string;
};

export function percentile(xs: number[], q: number): number | undefined {
  if (xs.length < 4) {
    return;
  }
  const sorted = [...xs].sort((a, b) => a - b);
  // Linear interpolation between closest ranks. Nearest-rank indexing made
  // p75 of a 4-sample pool the sample MAXIMUM — precisely the outlier the
  // interquartile bounds exist to exclude.
  const idx = q * (sorted.length - 1);
  const lo = Math.floor(idx);
  const loValue = sorted[lo] ?? 0;
  const hiValue = sorted[Math.ceil(idx)] ?? loValue;
  return loValue + (hiValue - loValue) * (idx - lo);
}

/**
 * Patients per site per ENROLLING month, observed across completed precedent
 * trials. The registry window is corrected for each trial's own primary-
 * endpoint follow-up (see `enrollmentMonths`) — without this, long-endpoint
 * phase 3s read as slower than they enrolled, and predictions calibrated on
 * short academic trials run systematically fast.
 */
export function velocities(trials: TrialRecord[]): number[] {
  const out: number[] = [];
  for (const t of trials) {
    const window = monthsBetween(t.startDate, t.primaryCompletionDate);
    if (!(window && t.enrollment) || t.siteCount === 0) {
      continue;
    }
    out.push(
      t.enrollment / t.siteCount / enrollmentMonths(window, t.primaryTimeFrames)
    );
  }
  return out;
}

/** Real trials over-enrol against dropout and non-evaluable patients. */
const DROPOUT_INFLATION = 1.3;

/**
 * Required N, reconciled against registrational reality.
 *
 * The textbook two-arm formula (80% power, alpha 0.05, two-sided: n per arm
 * ≈ 16 / d², inflated for dropout) assumes ONE primary comparison and two
 * arms. Real registrational programmes run multiple parts and arms, carry
 * regulatory safety-database minimums, and consistently land higher — the
 * real EoE phase 3 enrolled 321 where the formula said 65. So when the
 * indication has enough phase-3 precedent for a median to mean anything
 * (≥3 trials), that median is a floor on N: history says programmes at this
 * indication's registrational stage did not run smaller.
 */
function requiredSampleSize(
  thesis: IndicationThesis,
  precedentMedian: number | undefined,
  phase3: { count: number; medianN: number | undefined }
): { basis: string; n: number } {
  const d = thesis.endpoint.expectedEffectSize;
  const formula = d
    ? Math.ceil((16 / (d * d)) * 2 * DROPOUT_INFLATION)
    : undefined;
  const base = formula ?? Math.ceil(precedentMedian ?? 200);
  const baseBasis = formula
    ? `effect size d=${d}`
    : "precedent median (no effect size in thesis)";

  const floor =
    phase3.count >= 3 && phase3.medianN !== undefined
      ? Math.ceil(phase3.medianN)
      : undefined;
  if (floor !== undefined && floor > base) {
    return {
      basis: `phase-3 precedent median (${phase3.count} trials) floors the ${baseBasis} estimate of ${base}`,
      n: floor,
    };
  }
  return { basis: baseBasis, n: base };
}

/**
 * Sites a sponsor would open, from precedent. The naive median of at-scale
 * precedents is dragged to absurdity by single-site academic studies (EoE
 * trials with N≥40 as of 2018: median ONE site) — a sponsor sizing a
 * registrational programme behaves like the upper quartile of trials that
 * enrolled at the required scale, so take the 75th percentile of site
 * counts among precedents with enrollment ≥ requiredN/2. Falls back to
 * DEFAULT_SITES when fewer than 4 such precedents exist (percentile()
 * needs 4+ samples).
 *
 * Clamped to [DEFAULT_SITES, 250]: when even the at-scale precedent is
 * academic-scale (the 2018 EoE pool's p75 is a handful of sites — the first
 * registrational trial hadn't started yet), a sponsor planning a phase 2/3
 * programme still opens at least DEFAULT_SITES. Precedent can raise the
 * estimate, never talk a sponsor below the programme minimum.
 */
function sitesFromPrecedent(
  precedents: TrialRecord[],
  requiredN: number
): number | undefined {
  const atScale = precedents
    .filter((t) => (t.enrollment ?? 0) >= requiredN / 2 && t.siteCount > 0)
    .map((t) => t.siteCount);
  const p75 = percentile(atScale, 0.75);
  if (p75 === undefined) {
    return;
  }
  return Math.min(Math.max(Math.round(p75), DEFAULT_SITES), 250);
}

/**
 * Claude reads real eligibility prose and returns a calibrated multiplier.
 * This is the step that cannot be done with arithmetic: I/E criteria are
 * unstructured text, and which exclusions actually bite is a judgement call.
 */
async function assessEligibility(
  thesis: IndicationThesis,
  precedents: TrialRecord[],
  asOf?: string
): Promise<EligibilityBurden> {
  const withCriteria = precedents
    .filter((t) => t.eligibilityCriteria)
    .slice(0, 5);

  if (withCriteria.length === 0) {
    return {
      citedTrials: [],
      drivers: ["No precedent eligibility criteria available"],
      multiplier: 0.5,
      reasoning: "No precedent trials published I/E criteria; assumed neutral.",
    };
  }

  const client = makeClient();
  const corpus = withCriteria
    .map((t) => `### ${t.nctId} — ${t.title}\n${t.eligibilityCriteria}`)
    .join("\n\n");

  const prompt = `You are estimating screen-failure burden for a proposed trial.

PROPOSED TRIAL
Disease: ${thesis.disease.name}${thesis.disease.subtype ? ` (${thesis.disease.subtype})` : ""}
Asset: ${thesis.asset.name} (${thesis.asset.modality}), ${thesis.target.direction} ${thesis.target.symbol}
Required population: ${thesis.biomarkerPopulation.marker}, present in ${(thesis.biomarkerPopulation.prevalenceInDisease * 100).toFixed(0)}% of patients
Primary endpoint: ${thesis.endpoint.name}

PRECEDENT ELIGIBILITY CRITERIA (real trials)
${corpus}

Of patients who ALREADY have the required biomarker, estimate the fraction who
would still pass typical inclusion/exclusion criteria for this indication.

Rules:
- Do not double-count the biomarker requirement; it is already applied.
- Every driver you name must come from criteria text above, not from general knowledge.
- Cite the NCT ids your reasoning rests on.
${asOf ? `- The evidence horizon is ${asOf}. Reason ONLY from the criteria text above; do not use anything you know about this asset, this indication, or trial outcomes after that date.\n` : ""}
Reply with ONLY a JSON object:
{"multiplier": <0..1>, "drivers": ["..."], "citedTrials": ["NCT..."], "reasoning": "<2 sentences>"}`;

  // Median-of-3: the multiplier drifted 75%→55% across otherwise-similar
  // runs on single samples. `temperature: 0` would be the cheap fix but the
  // API rejects it ("deprecated for this model" on claude-sonnet-5), so pin
  // by sampling instead — the reported drivers/citations come from the
  // median response so the numbers and the prose stay consistent.
  // A sample can come back truncated or malformed (observed: one empty
  // response among 12 concurrent calls killed a whole demo run) — drop bad
  // samples rather than fail the assessment.
  const settled = await Promise.allSettled(
    Array.from({ length: ELIGIBILITY_SAMPLES }, async () => {
      const res = await client.messages.create({
        max_tokens: 1024,
        messages: [{ content: prompt, role: "user" }],
        model: "claude-sonnet-5",
      });
      const text = res.content
        .map((b) => (b.type === "text" ? b.text : ""))
        .join("")
        .trim();
      const json = text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1);
      const parsed = JSON.parse(json) as Record<string, unknown>;
      // Strict validation: LLM JSON deviates in observed ways — a string
      // multiplier ("0.5-0.7") coerces to NaN and NaN survives min/max
      // "clamping"; a string `drivers` crashes `.join()` at render time.
      // A bad sample must throw here so allSettled drops it.
      const multiplier = Number(parsed.multiplier);
      if (!Number.isFinite(multiplier)) {
        throw new Error(`non-numeric multiplier: ${String(parsed.multiplier)}`);
      }
      return {
        citedTrials: Array.isArray(parsed.citedTrials)
          ? parsed.citedTrials.map(String)
          : [],
        drivers: Array.isArray(parsed.drivers)
          ? parsed.drivers.map(String)
          : [],
        multiplier: Math.min(Math.max(multiplier, 0.01), 1),
        reasoning: typeof parsed.reasoning === "string" ? parsed.reasoning : "",
      };
    })
  );
  const samples = settled.flatMap((s) =>
    s.status === "fulfilled" ? [s.value] : []
  );

  const sorted = [...samples].sort((a, b) => a.multiplier - b.multiplier);
  const medianSample = sorted[Math.floor(sorted.length / 2)];
  return (
    medianSample ?? {
      citedTrials: [],
      drivers: ["Eligibility assessment unavailable (all samples failed)"],
      multiplier: 0.5,
      reasoning: "All eligibility samples failed; assumed neutral.",
    }
  );
}

/**
 * Smallest biomarker prevalence that brings enrolment under `targetMonths`,
 * or undefined if even all-comers (prevalence 1) misses it. `monthsAt` is
 * monotone nonincreasing in prevalence — flat while the screening floor
 * binds, then falling — so bisection converges and keeping `hi` feasible is
 * an invariant. The result rounds UP to a whole percent (the granularity a
 * protocol amendment would use), which can only shorten enrolment further.
 */
function solvePrevalenceFor(
  targetMonths: number,
  currentPrevalence: number,
  monthsAt: (prevalence: number) => number
): number | undefined {
  if (monthsAt(1) > targetMonths) {
    return;
  }
  let lo = currentPrevalence;
  let hi = 1;
  for (let i = 0; i < 40; i += 1) {
    const mid = (lo + hi) / 2;
    if (monthsAt(mid) <= targetMonths) {
      hi = mid;
    } else {
      lo = mid;
    }
  }
  return Math.min(Math.ceil(hi * 100) / 100, 1);
}

/**
 * The close-the-loop move: if the design is not comfortably enrollable,
 * solve for the cheapest biomarker relaxation that fixes it — the only lever
 * the thesis itself controls — or say plainly that no relaxation works and
 * what would actually move the needle.
 */
function solveCounterfactual(args: {
  competingTrials: number;
  marker: string;
  monthsAt: (prevalence: number) => number;
  prevalence: number;
  requiredN: number;
  simulatedMonths: number;
  sites: number;
  /** Sites needed to hit `targetMonths` at a given prevalence. */
  sitesFor: (targetMonths: number, prevalence: number) => number;
}): RecruitabilityResult["counterfactual"] {
  const { marker, monthsAt, prevalence: p, simulatedMonths } = args;
  if (simulatedMonths <= GOOD_MONTHS) {
    return;
  }
  // "Feasible" must clear the score-zero line at INFEASIBLE_MONTHS, so
  // solve for strictly under it.
  const feasibleTarget = INFEASIBLE_MONTHS - 1;
  const canBroaden = p < 0.99;
  const broaden = (to: number) =>
    `Broaden ${marker} cutoff to cover ${(to * 100).toFixed(0)}% of patients (from ${(p * 100).toFixed(0)}%)`;

  const pGood = canBroaden
    ? solvePrevalenceFor(GOOD_MONTHS, p, monthsAt)
    : undefined;
  if (pGood !== undefined) {
    return {
      achieves: "good",
      change: broaden(pGood),
      simulatedMonthsAfter: monthsAt(pGood),
    };
  }

  if (simulatedMonths <= feasibleTarget) {
    // Borderline (feasible but not comfortable) and no relaxation reaches
    // comfortable: solving for the feasible target would return a no-op
    // "broaden to ~current%", so say what would actually move the needle.
    return {
      achieves: "none",
      change: `Feasible but slow at ${simulatedMonths} months; no biomarker relaxation reaches ${GOOD_MONTHS} months (all-comers gives ${monthsAt(1)}). Comfortable enrolment would need ~${args.sitesFor(GOOD_MONTHS, p)} sites at the current marker.`,
      simulatedMonthsAfter: monthsAt(1),
    };
  }

  // Currently infeasible: a relaxation reaching merely-feasible is still a
  // rescue worth naming.
  const pFeasible = canBroaden
    ? solvePrevalenceFor(feasibleTarget, p, monthsAt)
    : undefined;
  if (pFeasible !== undefined) {
    return {
      achieves: "feasible",
      change: broaden(pFeasible),
      simulatedMonthsAfter: monthsAt(pFeasible),
    };
  }

  const sitesForFeasible = args.sitesFor(feasibleTarget, 1);
  return {
    achieves: "none",
    change: canBroaden
      ? `No biomarker relaxation works: even all-comers (100%) predicts ${monthsAt(1)} months at ${args.sites} sites. The binding constraints are elsewhere — N=${args.requiredN} against ${args.competingTrials} competing trials; feasibility would need ~${sitesForFeasible} sites even without the biomarker.`
      : `The biomarker already covers ${(p * 100).toFixed(0)}% of patients, so relaxing it is not the lever. Feasibility would need ~${sitesForFeasible} sites, a smaller N, or fewer than ${args.competingTrials} competing trials.`,
    simulatedMonthsAfter: monthsAt(1),
  };
}

function scoreFromMonths(months: number): number {
  if (months <= GOOD_MONTHS) {
    return 1;
  }
  if (months >= INFEASIBLE_MONTHS) {
    return 0;
  }
  return 1 - (months - GOOD_MONTHS) / (INFEASIBLE_MONTHS - GOOD_MONTHS);
}

export async function assessRecruitability(
  thesis: IndicationThesis,
  opts: { asOf?: string; sites?: number } = {}
): Promise<RecruitabilityResult> {
  const { asOf } = opts;

  const [completed, recruiting, stopped, anyStatus] = await Promise.all([
    // Precedents get the deepest page — velocity/N/sites all derive from it.
    searchTrials({
      asOf,
      condition: thesis.disease.name,
      pageSize: 300,
      statuses: ["COMPLETED"],
    }),
    searchTrials({
      asOf,
      condition: thesis.disease.name,
      pageSize: SEARCH_PAGE_SIZE,
      statuses: ["RECRUITING"],
    }),
    searchTrials({
      asOf,
      condition: thesis.disease.name,
      pageSize: SEARCH_PAGE_SIZE,
      statuses: ["TERMINATED", "WITHDRAWN"],
    }),
    // Only needed for asOf runs (historical competition); a cheap no-op
    // otherwise is avoided by resolving to an empty result.
    asOf
      ? searchTrials({
          asOf,
          condition: thesis.disease.name,
          pageSize: 500,
        })
      : Promise.resolve({ total: 0, trials: [] as TrialRecord[] }),
  ]);

  // Competition = INTERVENTIONAL trials actively consenting the same
  // patients. Registries/observational studies don't compete for enrolment
  // slots. For asOf runs, "recruiting" status is era-leaky (status is
  // CURRENT), so approximate active-at-horizon as started ≤ asOf < primary
  // completion — same approximation the backtest validated; trials missing
  // either date are not counted (uniform undercount).
  //
  // Both counts see only one page while the registry may hold more, so scale
  // the page's count by total/page — a fetched-then-discarded `total`
  // silently undercounted big indications (severe asthma: 685 registered vs
  // a 500 page) and made the competition penalty optimistic.
  const scaleUp = (pageCount: number, page: TrialRecord[], total: number) =>
    Math.round(
      pageCount * (page.length > 0 ? Math.max(total / page.length, 1) : 1)
    );
  const competingTrials = asOf
    ? scaleUp(
        anyStatus.trials.filter(
          (t) =>
            t.studyType === "INTERVENTIONAL" &&
            t.startDate &&
            t.startDate <= asOf &&
            t.primaryCompletionDate &&
            t.primaryCompletionDate > asOf
        ).length,
        anyStatus.trials,
        anyStatus.total
      )
    : scaleUp(
        recruiting.trials.filter((t) => t.studyType === "INTERVENTIONAL")
          .length,
        recruiting.trials,
        recruiting.total
      );

  // Precedents must be INTERVENTIONAL: the backtest caught observational
  // registries (700 patients at 5 sites) inflating the velocity pool by an
  // order of magnitude — a registry "enrols" by charting patients it already
  // has, which says nothing about how fast a trial consents them.
  //
  // And when asOf is set, precedents must have COMPLETED by the horizon: the
  // API's asOf filters on StudyFirstPostDate but status is CURRENT, so a
  // trial that completed after the horizon would leak its final enrolment
  // and duration into a retrospective run. (CT.gov dates can be YYYY-MM; the
  // lexicographic compare treats a month-only date as the 1st — accepted
  // imprecision.)
  const precedents = completed.trials.filter(
    (t) =>
      t.studyType === "INTERVENTIONAL" &&
      (!asOf || (t.primaryCompletionDate && t.primaryCompletionDate <= asOf))
  );

  const vs = velocities(precedents);
  const baseVelocity = median(vs) ?? FALLBACK_VELOCITY;
  // Interquartile, not min/max: a single 6-patient pilot and a single
  // mega-registry otherwise produce a range so wide it says nothing.
  const lowVelocity = percentile(vs, 0.25) ?? baseVelocity * 0.5;
  const highVelocity = percentile(vs, 0.75) ?? baseVelocity * 2;

  const eligibility = await assessEligibility(thesis, precedents, asOf);

  const cPenalty = competitionPenalty(competingTrials);
  const p = thesis.biomarkerPopulation.prevalenceInDisease;

  const precedentMedianN = median(
    precedents.map((t) => t.enrollment).filter((n): n is number => !!n)
  );
  const phase3Ns = precedents
    .filter((t) => t.phases.includes("PHASE3"))
    .map((t) => t.enrollment)
    .filter((n): n is number => !!n);
  const phase3MedianN = median(phase3Ns);
  const powering = requiredSampleSize(thesis, precedentMedianN, {
    count: phase3Ns.length,
    medianN: phase3MedianN,
  });
  const requiredN = powering.n;

  const precedentSites = opts.sites
    ? undefined
    : sitesFromPrecedent(precedents, requiredN);
  const sites = opts.sites ?? precedentSites ?? DEFAULT_SITES;
  let sitesBasis: RecruitabilityResult["sitesBasis"] = "default";
  if (opts.sites) {
    sitesBasis = "input";
  } else if (precedentSites !== undefined) {
    sitesBasis = "precedent";
  }

  const monthsFor = (v: number, prevalence: number) =>
    Math.ceil(
      requiredN /
        (sites *
          effectiveVelocity({
            baseVelocity: v,
            competitionPenalty: cPenalty,
            eligibilityMultiplier: eligibility.multiplier,
            prevalence,
          }))
    );

  const simulatedMonthsToEnroll = monthsFor(baseVelocity, p);
  const score = scoreFromMonths(simulatedMonthsToEnroll);

  const floored = p * eligibility.multiplier < NARROWING_FLOOR;
  const screensPerEnrollee = Math.round(
    1 / Math.max(p * eligibility.multiplier, 1e-4)
  );

  const counterfactual = solveCounterfactual({
    competingTrials,
    marker: thesis.biomarkerPopulation.marker,
    monthsAt: (prevalence) => monthsFor(baseVelocity, prevalence),
    prevalence: p,
    requiredN,
    simulatedMonths: simulatedMonthsToEnroll,
    sites,
    sitesFor: (targetMonths, prevalence) =>
      Math.ceil(
        requiredN /
          (targetMonths *
            effectiveVelocity({
              baseVelocity,
              competitionPenalty: cPenalty,
              eligibilityMultiplier: eligibility.multiplier,
              prevalence,
            }))
      ),
  });

  return {
    asOf: opts.asOf,
    counterfactual,
    eligibility,
    evidence: {
      competingTrials,
      precedentTrials: precedents.slice(0, 10).map((t) => t.nctId),
    },
    // Status and whyStopped are CURRENT-day registry state, so an asOf run
    // must also require the trial to have ENDED by the horizon — otherwise a
    // 2018 retrospective renders 2019–2023 terminations as evidence.
    // Terminated trials post their stop date as primaryCompletionDate; those
    // missing it are conservatively excluded from asOf runs.
    failedPrecedents: stopped.trials
      .filter(
        (t) =>
          t.whyStopped &&
          (!asOf ||
            (t.primaryCompletionDate && t.primaryCompletionDate <= asOf))
      )
      .slice(0, 5)
      .map((t) => ({ nctId: t.nctId, whyStopped: t.whyStopped ?? "" })),
    phase3MedianN,
    poweringBasis: powering.basis,
    precedentMedianN,
    requiredN,
    score,
    screensPerEnrollee,
    simulatedMonthsRange: [
      monthsFor(highVelocity, p),
      monthsFor(lowVelocity, p),
    ],
    simulatedMonthsToEnroll,
    sites,
    sitesBasis,
    waterfallDelta: Math.round((score - 0.5) * 24),
    why: `${requiredN} patients (${powering.basis}) at ${sites} sites (${sitesBasis === "precedent" ? "p75 of at-scale precedents" : sitesBasis}); precedent velocity ${baseVelocity.toFixed(2)} pt/site/mo across ${vs.length} completed trials${completed.total > completed.trials.length ? ` (sampled from ${completed.total} registered)` : ""}, narrowed by ${(p * 100).toFixed(0)}% biomarker prevalence and ${(eligibility.multiplier * 100).toFixed(0)}% eligibility pass rate, with ~${competingTrials} interventional trials competing for the same patients${asOf ? " at the horizon" : ""}.${floored ? ` Flow-model narrowing (${(p * eligibility.multiplier * 100).toFixed(1)}%) sits below the ${(NARROWING_FLOOR * 100).toFixed(0)}% active-screening floor, so the floor applies — the low-prevalence cost lands as ~${screensPerEnrollee} patients screened per enrollee, not as infinite months.` : ""}`,
  };
}
