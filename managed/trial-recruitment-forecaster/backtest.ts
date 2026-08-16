/**
 * Backtest harness: how well does the empirical-velocity model predict
 * enrolment duration for trials that actually ran?
 *
 * For each completed trial: roll the evidence horizon back to its start date,
 * compute precedent velocity from same-condition trials that had COMPLETED
 * before that date (self excluded — the API's asOf only filters on first-post
 * date, so completion is checked client-side to keep the run leak-free),
 * predict months to enrol the trial's actual N at its actual site count, and
 * compare to what actually happened.
 *
 * What this validates: the velocity + competition core — the number every
 * other term multiplies into. What it does NOT validate: biomarker narrowing
 * and the Claude eligibility multiplier (a backtested trial's own criteria
 * define its population, so relative narrowing ≈ 1 and no Claude call is
 * made), and the powering formula (N is taken as actual, not derived).
 * Every predicted number is SIMULATED; only the "actual" column is real.
 *
 *   bun managed/trial-recruitment-forecaster/backtest.ts
 *   bun managed/trial-recruitment-forecaster/backtest.ts NCT03633617 NCT...
 *   bun managed/trial-recruitment-forecaster/backtest.ts --condition "eosinophilic esophagitis" 8
 */
import {
  enrollmentMonths,
  getTrial,
  median,
  monthsBetween,
  searchTrials,
  type TrialRecord,
} from "./ctgov.ts";
import {
  competitionPenalty,
  effectiveVelocity,
  percentile,
  velocities,
} from "./recruitability.ts";

/** The validation-criterion seed from NEXT.md: dupilumab EoE phase 3. */
const DEFAULT_SEED = "NCT03633617";
const DEFAULT_CONDITION = "eosinophilic esophagitis";
const DEFAULT_PANEL_SIZE = 6;

type BacktestRow = {
  /** Registry window: start → primary completion, endpoint follow-up included. */
  actualWindowMonths: number;
  /** The comparator: window minus the trial's own primary-endpoint window. */
  actualEnrollMonths: number;
  actualN: number;
  competitorsAtStart: number;
  nctId: string;
  /**
   * √-dilution anchor variant B: median sites among AT-SCALE precedents
   * (enrollment ≥ half the target's N — the population sitesFromPrecedent
   * already trusts for site counts).
   */
  precedentAtScaleMedianSites?: number;
  precedentCount: number;
  /** √-dilution anchor variant A: median site count of the whole pool. */
  precedentMedianSites?: number;
  primaryCompletionDate: string;
  siteCount: number;
  simulatedPredictedMonths: number;
  simulatedPredictedRange: [number, number];
  /**
   * EXPERIMENT (NEXT.md "velocity scale-transfer"), anchor variant B:
   * velocity × √(precedentAtScaleMedianSites / siteCount). Reported for
   * evidence-gathering only; the engine does NOT use either variant.
   */
  simulatedSqrtDilutedAtScaleMonths?: number;
  /**
   * EXPERIMENT anchor variant A: velocity × √(precedentMedianSites /
   * siteCount) — the raw formula as written in NEXT.md. First live run
   * (2026-08-15) showed the pool-median anchor DEGENERATES TO 1 on EoE
   * panels (single-site academic studies dominate), blowing predictions to
   * 3–17× actual — the run-verified reason this is not in the engine.
   */
  simulatedSqrtDilutedMonths?: number;
  startDate: string;
  title: string;
};

type Skip = { nctId: string; skipped: string };

function isRow(r: BacktestRow | Skip): r is BacktestRow {
  return !("skipped" in r);
}

async function backtestTrial(
  trial: TrialRecord,
  condition: string
): Promise<BacktestRow | Skip> {
  const { enrollment, primaryCompletionDate, siteCount, startDate } = trial;
  const actualWindowMonths = monthsBetween(startDate, primaryCompletionDate);
  if (
    !(enrollment && actualWindowMonths && startDate && primaryCompletionDate) ||
    siteCount === 0
  ) {
    return {
      nctId: trial.nctId,
      skipped: "missing enrolment, usable dates, or site list",
    };
  }
  if (!condition) {
    return { nctId: trial.nctId, skipped: "no condition on record" };
  }

  const [completed, anyStatus] = await Promise.all([
    searchTrials({
      asOf: startDate,
      condition,
      pageSize: 100,
      statuses: ["COMPLETED"],
    }),
    searchTrials({ asOf: startDate, condition, pageSize: 500 }),
  ]);

  // Leak-free precedents: INTERVENTIONAL, completed BEFORE this trial
  // started, self excluded. The API asOf filter is on StudyFirstPostDate and
  // status is current, so a trial that completed after `startDate` would
  // otherwise leak its final enrolment and duration into the "prediction";
  // observational registries chart patients they already have, so their
  // "velocity" says nothing about trial consent rates.
  const precedents = completed.trials.filter(
    (t) =>
      t.nctId !== trial.nctId &&
      t.studyType === "INTERVENTIONAL" &&
      t.primaryCompletionDate &&
      t.primaryCompletionDate <= startDate
  );
  const vs = velocities(precedents);
  const baseVelocity = median(vs);
  if (baseVelocity === undefined) {
    return {
      nctId: trial.nctId,
      skipped: "no usable precedent velocities before its start date",
    };
  }

  // Historical competition: status-as-of-date is not queryable, so
  // approximate "active at start" as started ≤ start < primary completion.
  // Trials missing either date are not counted — an undercount, applied
  // uniformly across the panel.
  const competitorsAtStart = anyStatus.trials.filter(
    (t) =>
      t.nctId !== trial.nctId &&
      t.studyType === "INTERVENTIONAL" &&
      t.startDate &&
      t.startDate <= startDate &&
      t.primaryCompletionDate &&
      t.primaryCompletionDate > startDate
  ).length;

  const penalty = competitionPenalty(competitorsAtStart);
  const predict = (v: number) =>
    Math.ceil(
      enrollment /
        (siteCount *
          effectiveVelocity({
            baseVelocity: v,
            competitionPenalty: penalty,
            eligibilityMultiplier: 1,
            prevalence: 1,
          }))
    );
  const lowVelocity = percentile(vs, 0.25) ?? baseVelocity * 0.5;
  const highVelocity = percentile(vs, 0.75) ?? baseVelocity * 2;

  // Same pool velocities() accepted, so the anchor describes the trials
  // that actually contributed velocity samples.
  const usableSitePool = precedents.filter(
    (t) =>
      t.siteCount > 0 &&
      t.enrollment &&
      monthsBetween(t.startDate, t.primaryCompletionDate) !== undefined
  );
  const precedentMedianSites = median(usableSitePool.map((t) => t.siteCount));
  const precedentAtScaleMedianSites = median(
    usableSitePool
      .filter((t) => (t.enrollment ?? 0) >= enrollment / 2)
      .map((t) => t.siteCount)
  );
  const dilute = (anchor: number | undefined) =>
    anchor === undefined
      ? undefined
      : predict(baseVelocity * Math.sqrt(anchor / siteCount));

  return {
    actualEnrollMonths: Math.round(
      enrollmentMonths(actualWindowMonths, trial.primaryTimeFrames)
    ),
    actualN: enrollment,
    actualWindowMonths,
    competitorsAtStart,
    nctId: trial.nctId,
    precedentAtScaleMedianSites,
    precedentCount: vs.length,
    precedentMedianSites,
    primaryCompletionDate,
    simulatedPredictedMonths: predict(baseVelocity),
    simulatedPredictedRange: [predict(highVelocity), predict(lowVelocity)],
    simulatedSqrtDilutedAtScaleMonths: dilute(precedentAtScaleMedianSites),
    simulatedSqrtDilutedMonths: dilute(precedentMedianSites),
    siteCount,
    startDate,
    title: trial.title,
  };
}

async function panelFromIds(
  ids: string[]
): Promise<{ condition: string; trial: TrialRecord }[]> {
  // One bad id (404, typo) must not discard the valid rest of the panel.
  const settled = await Promise.allSettled(
    ids.map(async (id) => {
      const trial = await getTrial(id);
      return { condition: trial.conditions[0] ?? "", trial };
    })
  );
  for (const [i, s] of settled.entries()) {
    if (s.status === "rejected") {
      process.stderr.write(
        `${ids[i]}  SKIPPED — ${s.reason instanceof Error ? s.reason.message : String(s.reason)}\n`
      );
    }
  }
  return settled.flatMap((s) => (s.status === "fulfilled" ? [s.value] : []));
}

async function panelFromCondition(
  condition: string,
  n: number
): Promise<{ condition: string; trial: TrialRecord }[]> {
  const { trials } = await searchTrials({
    condition,
    pageSize: 100,
    statuses: ["COMPLETED"],
  });
  const usable = trials.filter(
    (t) =>
      t.studyType === "INTERVENTIONAL" &&
      (t.enrollment ?? 0) >= 30 &&
      t.siteCount >= 3 &&
      monthsBetween(t.startDate, t.primaryCompletionDate) !== undefined
  );
  // Largest first: big multi-site trials are the ones whose duration the
  // model is actually for, and their dates/counts are the best curated.
  usable.sort((a, b) => (b.enrollment ?? 0) - (a.enrollment ?? 0));
  return usable.slice(0, n).map((trial) => ({ condition, trial }));
}

async function buildPanel(
  argv: string[]
): Promise<{ condition: string; trial: TrialRecord }[]> {
  const [flag, conditionArg, sizeArg] = argv;
  const usage =
    'usage: backtest.ts [NCT ids...] | --condition "<condition>" [n]';
  if (flag !== "--condition" && argv.some((a) => a.startsWith("--"))) {
    throw new Error(usage);
  }
  if (flag === "--condition") {
    if (!conditionArg) {
      throw new Error(usage);
    }
    const n = Number(sizeArg ?? DEFAULT_PANEL_SIZE);
    // A NaN size slices to an empty panel and the run looks like a clean
    // "no usable trials" success (unquoted multi-word conditions land here).
    if (!Number.isInteger(n) || n < 1) {
      throw new Error(
        `panel size "${sizeArg}" is not a positive integer — ${usage} (quote multi-word conditions)`
      );
    }
    return await panelFromCondition(conditionArg, n);
  }
  if (argv.length > 0) {
    return await panelFromIds(argv);
  }
  // Default: the NEXT.md seed trial plus a small same-condition panel.
  const [seeded, discovered] = await Promise.all([
    panelFromIds([DEFAULT_SEED]),
    panelFromCondition(DEFAULT_CONDITION, DEFAULT_PANEL_SIZE),
  ]);
  const seen = new Set(seeded.map((s) => s.trial.nctId));
  return [
    ...seeded,
    ...discovered.filter((d) => !seen.has(d.trial.nctId)),
  ].slice(0, DEFAULT_PANEL_SIZE + 1);
}

const panel = await buildPanel(process.argv.slice(2));
// allSettled: one CT.gov failure on one trial's searches must not discard
// the whole panel's completed rows.
const results = (
  await Promise.allSettled(
    panel.map(({ condition, trial }) => backtestTrial(trial, condition))
  )
).map((s, i) =>
  s.status === "fulfilled"
    ? s.value
    : {
        nctId: panel[i]?.trial.nctId ?? "?",
        skipped: `search failed: ${s.reason instanceof Error ? s.reason.message : String(s.reason)}`,
      }
);
const rows = results.filter(isRow);
const skips = results.filter((r): r is Skip => !isRow(r));

const lines: string[] = [
  "",
  "=".repeat(78),
  "BACKTEST — simulated velocity model vs. what actually happened",
  "predicted numbers are SIMULATED; the actual column is the real record",
  "=".repeat(78),
];

for (const r of rows) {
  const ratio = r.simulatedPredictedMonths / r.actualEnrollMonths;
  lines.push(
    "",
    `${r.nctId}  ${r.title.slice(0, 60)}`,
    `  actual               ${r.actualN} pts, ${r.siteCount} sites, ${r.actualWindowMonths} mo window (${r.startDate} -> ${r.primaryCompletionDate}), est. ~${r.actualEnrollMonths} mo enrolling`,
    `  SIMULATED predicted  ${r.simulatedPredictedMonths} mo to enrol  (range ${r.simulatedPredictedRange[0]}-${r.simulatedPredictedRange[1]})  [${r.precedentCount} precedent velocities, ${r.competitorsAtStart} active competitors at start]`,
    `  predicted/actual     ${ratio.toFixed(2)}x  (vs est. enrolling months)`
  );
  pushExperimentLine(
    lines,
    r,
    "pool-median anchor  ",
    r.simulatedSqrtDilutedMonths,
    r.precedentMedianSites
  );
  pushExperimentLine(
    lines,
    r,
    "at-scale anchor     ",
    r.simulatedSqrtDilutedAtScaleMonths,
    r.precedentAtScaleMedianSites
  );
}

for (const s of skips) {
  lines.push("", `${s.nctId}  SKIPPED — ${s.skipped}`);
}

function pushExperimentLine(
  out: string[],
  r: BacktestRow,
  label: string,
  months: number | undefined,
  anchor: number | undefined
): void {
  if (months === undefined || anchor === undefined) {
    return;
  }
  const ratio = months / r.actualEnrollMonths;
  out.push(
    `  EXPERIMENT sqrt-dilution, ${label}${months} mo  (velocity x sqrt(${anchor} anchor sites / ${r.siteCount} target sites))  ${ratio.toFixed(2)}x — reported only, NOT in the engine`
  );
}

function pushExperimentAggregate(
  out: string[],
  label: string,
  pairs: { actual: number; predicted: number }[]
): void {
  if (pairs.length === 0) {
    return;
  }
  const agg = aggregate(pairs);
  out.push(
    `  EXPERIMENT sqrt-dilution aggregate, ${label} (${pairs.length} trials with an anchor; reported only):`,
    `    median |error|     ${agg.medianErrorPct}%`,
    `    within 1.5x        ${agg.within15}/${pairs.length}`,
    `    within 2x          ${agg.within2}/${pairs.length}`
  );
}

function aggregate(pairs: { actual: number; predicted: number }[]) {
  const errors = pairs.map((p) => Math.abs(p.predicted - p.actual) / p.actual);
  const within = (k: number) =>
    pairs.filter((p) => {
      const ratio = p.predicted / p.actual;
      return ratio <= k && ratio >= 1 / k;
    }).length;
  return {
    medianErrorPct: ((median(errors) ?? 0) * 100).toFixed(0),
    within2: within(2),
    within15: within(1.5),
  };
}

if (rows.length > 0) {
  const base = aggregate(
    rows.map((r) => ({
      actual: r.actualEnrollMonths,
      predicted: r.simulatedPredictedMonths,
    }))
  );
  lines.push(
    "",
    "-".repeat(78),
    `aggregate over ${rows.length} trials (${skips.length} skipped)`,
    `  median |error|       ${base.medianErrorPct}%`,
    `  within 1.5x          ${base.within15}/${rows.length}`,
    `  within 2x            ${base.within2}/${rows.length}`
  );
  pushExperimentAggregate(
    lines,
    "pool-median anchor",
    rows.flatMap((r) =>
      r.simulatedSqrtDilutedMonths === undefined
        ? []
        : [
            {
              actual: r.actualEnrollMonths,
              predicted: r.simulatedSqrtDilutedMonths,
            },
          ]
    )
  );
  pushExperimentAggregate(
    lines,
    "at-scale anchor",
    rows.flatMap((r) =>
      r.simulatedSqrtDilutedAtScaleMonths === undefined
        ? []
        : [
            {
              actual: r.actualEnrollMonths,
              predicted: r.simulatedSqrtDilutedAtScaleMonths,
            },
          ]
    )
  );
}

lines.push("");
process.stdout.write(lines.join("\n"));
