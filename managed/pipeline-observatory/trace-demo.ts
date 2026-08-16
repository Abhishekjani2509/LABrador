/**
 * trace-demo.ts — the glassbox, running for real.
 *
 * WHAT THIS IS, in one sentence: it runs the part of the LABrador pipeline
 * that actually composes today, and around every step it wraps a **trace
 * envelope** — a small, identical JSON record that says what data went in,
 * what number came out, why that number, what was handed to the next node,
 * and which parts are simulated rather than observed.
 *
 * WHO IT IS FOR: a skeptical, non-programmer decision-maker. Every comment in
 * this file is written so that person can read the code as prose and check
 * that the program does what the page (observatory.html) claims it does.
 *
 * THE CHAIN IT TRACES (see DESIGN.md for the full picture):
 *
 *   1. trial-recruitment-forecaster   — real ClinicalTrials.gov records + one
 *      (managed/trial-recruitment-forecaster/recruitability.ts)
 *                                       Claude read of real eligibility prose
 *                                       -> "this trial takes N months to fill"
 *   2. adapter-b / economics-bridge   — turns those months into a launch-delay
 *      (managed/trial-recruitment-forecaster/economics-bridge.ts)
 *                                       overlay the economics engine can price
 *   3. therapeutic-program-economics  — the economics engine itself, run
 *      (managed/therapeutic-program-economics, `labrador analyze`)
 *                                       read-only on its SYNTHETIC demo fixture
 *
 * HONESTY RULE (repo-wide, non-negotiable): the glassbox never upgrades a
 * number's status. If the forecaster says a month count is simulated, the
 * envelope says SIMULATED. If the economics engine stamps its own run
 * NOT_DECISION_GRADE, the envelope says NOT_DECISION_GRADE. This file contains
 * no code path that can remove an honesty label.
 *
 * WHAT IT NEEDS TO RUN, and what happens when it is missing:
 *   - `ANTHROPIC_API_KEY` (in the repo-root `.env`, never committed) and
 *     network access to clinicaltrials.gov — for step 1. Missing either one:
 *     step 1's envelope records `status: "degraded"` with the real error text,
 *     and step 2 is recorded as `skipped`. The trace still gets written.
 *   - `uv` (https://docs.astral.sh/uv/) — for steps 2 and 3, which shell out
 *     to the Python economics engine. Missing: those envelopes degrade the
 *     same way. Nothing is faked in to fill the hole.
 *
 * RUN IT:
 *   bun managed/pipeline-observatory/trace-demo.ts
 *   bun managed/pipeline-observatory/trace-demo.ts --fixture il13-eoe-fibrostenotic
 *
 * WHAT IT WRITES (both under managed/pipeline-observatory/fixtures/):
 *   - trace-demo-output.json          the trace itself — the reviewable artifact
 *   - recruitability-<fixture>.json   the raw step-1 result, so anyone can
 *                                     re-derive the envelope from the source
 * It also re-injects the trace into observatory.html between two marker
 * comments, so the page and the artifact can never drift apart.
 */
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import theses from "../trial-recruitment-forecaster/fixtures/theses.json" with {
  type: "json",
};
import {
  assessRecruitability,
  type RecruitabilityResult,
} from "../trial-recruitment-forecaster/recruitability.ts";
import { IndicationThesis } from "../trial-recruitment-forecaster/thesis.ts";
// The envelope machinery moved to trace.ts when pipeline.ts needed the same
// shapes. Same types, same helpers — a trace from either runner renders on the
// same page.
import {
  buildVerdict,
  capped as cappedTo,
  type DataSource,
  digest,
  envelope,
  firstLine,
  type HonestyLabel,
  injectTrace,
  type KeyNumber,
  REPO_ROOT,
  type StepResult,
  type Trace,
  type TraceEnvelope,
  VERSION,
} from "./trace.ts";

// ---------------------------------------------------------------------------
// Where things live. Resolved from this file's own location so the script runs
// from any working directory.
// ---------------------------------------------------------------------------
const HERE = dirname(fileURLToPath(import.meta.url));
const FORECASTER_DIR = join(
  REPO_ROOT,
  "managed",
  "trial-recruitment-forecaster"
);
const ECONOMICS_DIR = join(
  REPO_ROOT,
  "managed",
  "therapeutic-program-economics"
);
const FIXTURES_DIR = join(HERE, "fixtures");
const OBSERVATORY_HTML = join(HERE, "observatory.html");

/** Default thesis: the forecaster's hero fixture (dupilumab in EoE). */
const DEFAULT_FIXTURE = "dupi-eoe";
/** The sponsor's planned enrolment window, in months — the bridge's default. */
const PLANNED_MONTHS = "18";
/** Monte-Carlo draws and seed. Fixed so any reviewer reproduces our numbers. */
const SIMULATIONS = "200";
const SEED = "42";
/** Subprocess ceiling: neither child should ever take minutes. */
const SUBPROCESS_TIMEOUT_MS = 600_000;
/** How many of the engine's own warnings we carry into `caveats`. */
const MAX_CAVEAT_WARNINGS = 6;
/** How many precedent NCT ids we list per role before saying "and N more". */
const MAX_LISTED_SOURCES = 12;
const MS_PER_SECOND = 1000;
const MONTHS_PER_YEAR = 12;
const PERCENT = 100;

// ---------------------------------------------------------------------------
// STEP 1 — trial-recruitment-forecaster.
// Runs live: it queries ClinicalTrials.gov for real precedent trials and asks
// Claude to read their real eligibility prose. Costs API calls.
// ---------------------------------------------------------------------------

async function runForecaster(
  thesis: IndicationThesis
): Promise<StepResult<RecruitabilityResult>> {
  const started = Date.now();
  try {
    const value = await assessRecruitability(thesis);
    return { ms: Date.now() - started, value };
  } catch (err) {
    return { error: firstLine(err), ms: Date.now() - started };
  }
}

/** The NCT ids this node actually leaned on, each with the role it played. */
function forecasterSources(result: RecruitabilityResult): DataSource[] {
  const precedent = cappedTo(
    result.evidence.precedentTrials,
    MAX_LISTED_SOURCES
  ).map((id) => ({
    id,
    kind: "nct" as const,
    role: "Completed interventional precedent — supplied enrolment velocity, sample-size and site-count anchors",
  }));
  const cited = cappedTo(
    result.eligibility.citedTrials,
    MAX_LISTED_SOURCES
  ).map((id) => ({
    id,
    kind: "nct" as const,
    role: "Eligibility prose Claude actually read to estimate the screen-failure rate",
  }));
  const failed = result.failedPrecedents.map((f) => ({
    id: f.nctId,
    kind: "nct" as const,
    role: `Trial that stopped early — registry reason: "${f.whyStopped}"`,
  }));
  return [...precedent, ...cited, ...failed];
}

/** Every number the forecaster emits, paired with the node's own basis text. */
function forecasterNumbers(result: RecruitabilityResult): KeyNumber[] {
  const [fast, slow] = result.simulatedMonthsRange;
  return [
    {
      basis: result.why,
      label: "Simulated months to enrol",
      unit: "months",
      value: result.simulatedMonthsToEnroll,
    },
    {
      basis:
        "Same model run at the 75th and 25th percentile of observed precedent velocity (interquartile band, not a confidence interval).",
      label: "Simulated range",
      unit: "months",
      value: `${fast}–${slow}`,
    },
    {
      basis: `Score is a straight-line mapping of months: 1.0 at or under 18 months, 0 at or beyond 48 months. Here ${result.simulatedMonthsToEnroll} months.`,
      label: "Recruitability score",
      unit: "0–1",
      value: result.score,
    },
    {
      basis: result.poweringBasis,
      label: "Required patients (N)",
      unit: "patients",
      value: result.requiredN,
    },
    {
      basis: `Site count basis: ${result.sitesBasis}${result.sitesBasis === "precedent" ? " (75th percentile of site counts among precedents that enrolled at least half the required N, clamped to 40–250)" : ""}.`,
      label: "Sites assumed open",
      unit: "sites",
      value: result.sites,
    },
    {
      basis: `${result.eligibility.reasoning} Drivers named from the criteria text: ${result.eligibility.drivers.join("; ")}. Cited: ${result.eligibility.citedTrials.join(", ") || "none"}.`,
      label: "Eligibility pass rate",
      unit: "fraction of marker-positive patients",
      value: result.eligibility.multiplier,
    },
    {
      basis:
        "1 / (biomarker prevalence x eligibility pass rate). This is where low prevalence lands as cost once the model's screening floor stops it landing as time.",
      label: "Patients screened per enrollee",
      unit: "screens",
      value: result.screensPerEnrollee,
    },
    {
      basis:
        "Interventional trials recruiting the same population, scaled from the sampled page to the registry total. Each takes an 8% share of the patient pool in the model.",
      label: "Competing trials",
      unit: "trials",
      value: result.evidence.competingTrials,
    },
  ];
}

function forecasterHonesty(result: RecruitabilityResult): HonestyLabel[] {
  const labels: HonestyLabel[] = [
    {
      detail:
        "The field is literally named `simulatedMonthsToEnroll` in recruitability.ts — a model output, not an observed enrolment.",
      label: "SIMULATED",
      scope:
        "months to enrol, range, score, and every number derived from them",
    },
    {
      detail:
        "The eligibility pass rate is Claude's judgement after reading real I/E prose (median of 3 samples). It is a calibrated estimate, not a measurement.",
      label: "ASSUMED",
      scope: "eligibility pass rate and the drivers list",
    },
  ];
  if (result.eligibility.citedTrials.length === 0) {
    labels.push({
      detail:
        "No precedent trial published eligibility criteria that could be read, so the multiplier fell back to a neutral 0.5.",
      label: "INSUFFICIENT_EVIDENCE",
      scope: "eligibility pass rate",
    });
  }
  return labels;
}

function forecasterEnvelope(
  thesis: IndicationThesis,
  step: StepResult<RecruitabilityResult>
): TraceEnvelope {
  const inputs = {
    digest: digest(thesis),
    humanSummary: `${thesis.asset.name} (${thesis.asset.modality}) ${thesis.target.direction}ing ${thesis.target.symbol} in ${thesis.disease.name}; enrolling only patients with ${thesis.biomarkerPopulation.marker}, present in ${(thesis.biomarkerPopulation.prevalenceInDisease * PERCENT).toFixed(0)}% of patients.`,
    source: `managed/trial-recruitment-forecaster/fixtures/theses.json → id "${thesis.id}"`,
  };
  const version = {
    ...VERSION,
    runner:
      "assessRecruitability() in managed/trial-recruitment-forecaster/recruitability.ts",
  };
  const result = step.value;
  if (!result) {
    // Degraded: say what broke, in the engine's own words. Nothing is invented
    // to fill the gap — an empty panel is more honest than a plausible number.
    return envelope({
      caveats: [
        "This node did not produce a number. Everything downstream of it in this trace is missing, not zero.",
      ],
      dataSources: [],
      decision: {
        honestyLabels: [
          {
            detail: step.error ?? "unknown error",
            label: "DEGRADED",
            scope: "the whole node",
          },
        ],
        keyNumbers: [],
        summary: `The recruitment forecaster could not run: ${step.error ?? "unknown error"}`,
      },
      durationMs: step.ms,
      handoff: null,
      inputs,
      node: "trial-recruitment-forecaster",
      startedAt: new Date(Date.now() - step.ms).toISOString(),
      status: "degraded",
      version,
    });
  }
  return envelope({
    caveats: [
      "Known limitation (NEXT.md): per-site velocity measured on small precedent pools does not transfer cleanly to 100+ site programmes.",
      "The eligibility read is a language model reading text. On historical (`asOf`) runs the registry evidence is date-filtered, but the model's own knowledge boundary cannot be sealed.",
      result.counterfactual
        ? `The forecaster also searched for the cheapest rescue: ${result.counterfactual.change} (reaches "${result.counterfactual.achieves}", ${result.counterfactual.simulatedMonthsAfter} months). That is a modelled what-if, not a plan.`
        : "The design already enrols inside the comfortable window, so no counterfactual rescue was searched.",
    ],
    dataSources: forecasterSources(result),
    decision: {
      honestyLabels: forecasterHonesty(result),
      keyNumbers: forecasterNumbers(result),
      summary: `This trial is modelled to take ${result.simulatedMonthsToEnroll} months to enrol ${result.requiredN} patients across ${result.sites} sites — a recruitability score of ${result.score.toFixed(2)} out of 1.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter: "managed/trial-recruitment-forecaster/economics-bridge.ts",
      payloadSummary: `simulatedMonthsToEnroll=${result.simulatedMonthsToEnroll}, simulatedMonthsRange=[${result.simulatedMonthsRange.join(", ")}], score=${result.score.toFixed(2)}${result.counterfactual ? `, counterfactual reaching "${result.counterfactual.achieves}" at ${result.counterfactual.simulatedMonthsAfter} months` : ""}. Nothing else crosses this boundary — the NCT ids, eligibility drivers and screening burden stay behind.`,
      toNode: "adapter-b (economics-bridge)",
    },
    inputs,
    node: "trial-recruitment-forecaster",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version,
  });
}

// ---------------------------------------------------------------------------
// STEP 2 — adapter B, the seam between recruitment and money.
// We run the REAL bridge as a subprocess rather than reimplementing its
// arithmetic here, because a glassbox that reimplements the thing it is
// observing eventually disagrees with it.
// ---------------------------------------------------------------------------

/** The slice of the bridge's stdout this trace reads. Extra fields ignored. */
type BridgeOutput = {
  basis: Record<string, string>;
  counterfactual: { achieves: string; change: string } | null;
  howToApply: Record<string, string>;
  pricing: Record<string, unknown>;
  simulatedLaunchDelayRangeYears: { high: number; low: number; mode: number };
  simulatedLaunchDelayYears: number;
  simulatedLaunchDelayYearsUnrounded: number;
  simulatedMonthsSavedByCounterfactual: number | null;
};

function runBridge(savedResultPath: string): StepResult<BridgeOutput> {
  const started = Date.now();
  try {
    const stdout = execFileSync(
      "bun",
      [
        join(FORECASTER_DIR, "economics-bridge.ts"),
        "--from-json",
        savedResultPath,
        "--planned-months",
        PLANNED_MONTHS,
      ],
      {
        cwd: REPO_ROOT,
        encoding: "utf8",
        stdio: "pipe",
        timeout: SUBPROCESS_TIMEOUT_MS,
      }
    );
    return {
      ms: Date.now() - started,
      value: JSON.parse(stdout) as BridgeOutput,
    };
  } catch (err) {
    return { error: firstLine(err), ms: Date.now() - started };
  }
}

function bridgeNumbers(out: BridgeOutput): KeyNumber[] {
  const range = out.simulatedLaunchDelayRangeYears;
  const numbers: KeyNumber[] = [
    {
      basis: out.basis.simulatedLaunchDelayYears ?? "",
      label: "Simulated launch delay",
      unit: "whole years",
      value: out.simulatedLaunchDelayYears,
    },
    {
      basis: out.basis.simulatedLaunchDelayRangeYears ?? "",
      label: "Launch-delay range (low / mode / high)",
      unit: "whole years",
      value: `${range.low} / ${range.mode} / ${range.high}`,
    },
    {
      // Surfaced deliberately. Whole-year rounding can turn a real slip into a
      // zero-cost slip, and a reader who only sees the rounded number would
      // never know. The unrounded figure sits right next to it so the reader
      // can see what the convention swallowed.
      basis:
        "The same delay BEFORE the adapter rounds it to whole years. If this number is above zero while the rounded one is zero, the delay was rounded away — that is a modelling convention, not a finding that the delay is free.",
      label: "Launch delay before rounding",
      unit: "years",
      value: out.simulatedLaunchDelayYearsUnrounded,
    },
  ];
  if (out.simulatedMonthsSavedByCounterfactual !== null) {
    numbers.push({
      basis: out.basis.counterfactual ?? "",
      label: "Months the counterfactual would save",
      unit: "months",
      value: out.simulatedMonthsSavedByCounterfactual,
    });
  }
  const { pricing } = out;
  if (pricing.status === "ok") {
    numbers.push({
      basis: String(pricing.note ?? ""),
      label: "Simulated cost of the delay",
      unit: "USD",
      value: Number(pricing.simulatedDelayCostUSD ?? 0),
    });
  }
  return numbers;
}

function bridgeHonesty(out: BridgeOutput): HonestyLabel[] {
  const labels: HonestyLabel[] = [
    {
      detail:
        "Every field the bridge emits is named `simulated…`, because its only input is a simulated month count.",
      label: "SIMULATED",
      scope: "launch delay, its range, and the priced delay cost",
    },
  ];
  const { pricing } = out;
  if (pricing.status === "ok") {
    labels.push(
      {
        detail: String(pricing.pricedAgainst ?? ""),
        label: "SYNTHETIC",
        scope:
          "the dollar figures — they are priced against a fictitious demo programme",
      },
      {
        detail: `The economics engine stamped its own run ${String(pricing.decisionGrade ?? "")}. The bridge passes that through untouched.`,
        label: "NOT_DECISION_GRADE",
        scope: "the priced delay cost",
      }
    );
  } else {
    labels.push({
      detail: String(pricing.note ?? "pricing unavailable"),
      label: "DEGRADED",
      scope: "the dollar figures (none were produced)",
    });
  }
  return labels;
}

function bridgeEnvelope(
  step: StepResult<BridgeOutput>,
  upstream: RecruitabilityResult | undefined,
  savedResultPath: string
): TraceEnvelope {
  const inputs = {
    digest: upstream ? digest(upstream) : "n/a (upstream produced nothing)",
    humanSummary: upstream
      ? `Only the timing fields from step 1: ${upstream.simulatedMonthsToEnroll} months (range ${upstream.simulatedMonthsRange.join("–")}) against a planned ${PLANNED_MONTHS}-month window.`
      : "Nothing — step 1 did not produce a result.",
    source: savedResultPath.replace(`${REPO_ROOT}/`, ""),
  };
  const version = {
    ...VERSION,
    runner: `bun managed/trial-recruitment-forecaster/economics-bridge.ts --from-json <saved> --planned-months ${PLANNED_MONTHS}`,
  };
  const out = step.value;
  if (!out) {
    return envelope({
      caveats: [
        "No launch-delay overlay exists for this run. The economics figures below are the untouched baseline.",
      ],
      dataSources: [],
      decision: {
        honestyLabels: [
          {
            detail: step.error ?? "upstream step produced nothing to convert",
            label: "DEGRADED",
            scope: "the whole adapter",
          },
        ],
        keyNumbers: [],
        summary: `The recruitment-to-economics adapter did not run: ${step.error ?? "no upstream result"}`,
      },
      durationMs: step.ms,
      handoff: null,
      inputs,
      node: "adapter-b (economics-bridge)",
      startedAt: new Date(Date.now() - step.ms).toISOString(),
      status: upstream ? "degraded" : "skipped",
      version,
    });
  }
  const caveats = [
    "Two wirings that look obvious are wrong and are refused on purpose (documented in economics-bridge.ts): recruitability score is NOT a probability of approval, and stage durations do NOT move the launch year.",
    "The delay is rounded to whole years because that is the granularity the economics engine applies to a sampled delay.",
    "This adapter produces an INSTRUCTION, not an applied change: the economics run below is the baseline, and the delay is priced by multiplying the engine's own per-year delay cost. Nobody has re-run the engine with the delay applied.",
  ];
  // The rounding is normally invisible. When it swallows a real slip, say so.
  if (
    out.simulatedLaunchDelayYearsUnrounded > 0 &&
    out.simulatedLaunchDelayYears === 0
  ) {
    caveats.push(
      `ROUNDED AWAY: the forecast slips ${(out.simulatedLaunchDelayYearsUnrounded * MONTHS_PER_YEAR).toFixed(0)} months past the planned window, but whole-year rounding books that as 0 delay years and therefore 0 dollars of delay cost. The slip is real; the price of it is not being charged.`
    );
  }
  return envelope({
    caveats,
    dataSources: [
      {
        id: "SYNTHETIC-LAB-001",
        kind: "synthetic",
        role: "The demo programme the dollar figures are priced against — fictitious by construction",
      },
    ],
    decision: {
      honestyLabels: bridgeHonesty(out),
      keyNumbers: bridgeNumbers(out),
      summary: `A ${out.simulatedLaunchDelayYears}-year launch delay is the only thing this adapter passes to the economics engine — the recruitment score itself is deliberately NOT passed on.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter:
        "the analyst (or a future orchestrator) applies the overlay by hand",
      payloadSummary:
        `${out.howToApply.launch_delay_years ?? ""} ${out.howToApply.launch_year ?? ""}`.trim(),
      toNode: "therapeutic-program-economics",
    },
    inputs,
    node: "adapter-b (economics-bridge)",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version,
  });
}

// ---------------------------------------------------------------------------
// STEP 3 — therapeutic-program-economics, run read-only on its own fixtures.
// ---------------------------------------------------------------------------

/** The slice of the engine's analysis JSON this trace reads. */
type EconomicsOutput = {
  calculation_steps: { formula: string; label: string; step_id: string }[];
  decision_grade: string;
  engine_version: string;
  evidence_references: {
    field_path: string;
    grade: string;
    synthetic: boolean;
  }[];
  input_digest: string;
  input_snapshot: {
    comparables: Record<
      string,
      {
        comparable_id: string;
        name: string;
        price: {
          amount: number;
          basis: string;
          evidence: { grade: string; source_id: string };
        };
      }[]
    >;
  };
  recommendation: string;
  run_id: string;
  summary: Record<string, number | string | null>;
  warnings: { code: string; message: string; severity: string }[];
};

function runEconomics(): StepResult<EconomicsOutput> {
  const started = Date.now();
  try {
    // `uv sync --frozen` installs exactly the locked dependency set — no
    // resolution, no drift between this run and the next reviewer's.
    execFileSync("uv", ["sync", "--frozen"], {
      cwd: ECONOMICS_DIR,
      stdio: "pipe",
      timeout: SUBPROCESS_TIMEOUT_MS,
    });
    const stdout = execFileSync(
      "uv",
      [
        "run",
        "labrador",
        "analyze",
        "fixtures/demo_program.json",
        "--comparables",
        "fixtures/demo_comparables.json",
        "--simulations",
        SIMULATIONS,
        "--seed",
        SEED,
        "--compact",
      ],
      {
        cwd: ECONOMICS_DIR,
        encoding: "utf8",
        stdio: "pipe",
        timeout: SUBPROCESS_TIMEOUT_MS,
      }
    );
    return {
      ms: Date.now() - started,
      value: JSON.parse(stdout) as EconomicsOutput,
    };
  } catch (err) {
    return { error: firstLine(err), ms: Date.now() - started };
  }
}

/** Every price the valuation leaned on, with the price basis kept distinct. */
function economicsSources(out: EconomicsOutput): DataSource[] {
  const rows = Object.values(out.input_snapshot.comparables).flat();
  const prices = rows.map((c) => ({
    id: `${c.comparable_id} (${c.price.evidence.source_id})`,
    kind: "price_observation" as const,
    role: `${c.name}: ${c.price.amount.toLocaleString("en-US")} USD on a ${c.price.basis} basis, evidence grade ${c.price.evidence.grade}`,
  }));
  const syntheticFields = out.evidence_references.filter((e) => e.synthetic);
  return [
    ...prices,
    {
      id: String(out.summary.program_id ?? "unknown"),
      kind: "synthetic",
      role: `The programme being valued. ${syntheticFields.length} of ${out.evidence_references.length} evidence references behind it are stamped SYNTHETIC by the engine itself.`,
    },
  ];
}

function economicsNumbers(out: EconomicsOutput): KeyNumber[] {
  const s = out.summary;
  const provenance = `Engine ${out.engine_version}, run ${out.run_id}, input digest ${out.input_digest}, ${SIMULATIONS} draws at seed ${SEED} — reproducible by re-running the same command.`;
  return [
    {
      basis: `Median of the simulated risk-adjusted net present value across ${SIMULATIONS} draws. ${provenance}`,
      label: "Median rNPV (P50)",
      unit: "USD",
      value: Number(s.p50_rnpv ?? 0),
    },
    {
      basis: `The 10th and 90th percentile of the same draws. These are percentiles of the declared scenario model, NOT confidence intervals or observed frequencies. ${provenance}`,
      label: "rNPV range (P10 / P90)",
      unit: "USD",
      value: `${Number(s.p10_rnpv ?? 0).toLocaleString("en-US")} / ${Number(s.p90_rnpv ?? 0).toLocaleString("en-US")}`,
    },
    {
      basis: `Share of the ${SIMULATIONS} draws in which rNPV came out above zero. ${provenance}`,
      label: "Probability rNPV is positive",
      unit: "fraction of draws",
      value: Number(s.probability_positive_rnpv ?? 0),
    },
    {
      basis: `The engine's own price of a one-year slip in launch — this is the exact rate the recruitment delay above was multiplied by. ${provenance}`,
      label: "Value lost per year of launch delay",
      unit: "USD per year",
      value: Number(s.value_lost_per_launch_delay_year ?? 0),
    },
    {
      basis: `Years of patent protection remaining after launch under the engine's simplified patent clock (term starts at filing, not launch). ${provenance}`,
      label: "Effective protected years",
      unit: "years",
      value: Number(s.effective_protected_years ?? 0),
    },
  ];
}

function economicsHonesty(out: EconomicsOutput): HonestyLabel[] {
  const synthetic = out.evidence_references.filter((e) => e.synthetic).length;
  return [
    {
      detail: `The engine stamped this run ${out.decision_grade} and its recommendation field reads ${out.recommendation}. That verdict is the engine's, not the glassbox's.`,
      label: "NOT_DECISION_GRADE",
      scope: "every dollar figure in this panel",
    },
    {
      detail: `${synthetic} of ${out.evidence_references.length} evidence references are graded SYNTHETIC — fictitious inputs shipped as an interface demonstration.`,
      label: "SYNTHETIC",
      scope: "the programme, its prices, and its population",
    },
    {
      detail:
        "Percentiles come from a declared scenario model with a fixed seed. Same seed, same numbers; different assumptions, different numbers.",
      label: "SIMULATED",
      scope: "P10 / P50 / P90 and the probability-positive figure",
    },
  ];
}

function economicsEnvelope(step: StepResult<EconomicsOutput>): TraceEnvelope {
  const inputs = {
    digest: step.value?.input_digest ?? "n/a (engine did not run)",
    humanSummary:
      "The economics node's own bundled demo programme and comparable-price catalogue. Every value in them is fictitious.",
    source:
      "managed/therapeutic-program-economics/fixtures/demo_program.json + fixtures/demo_comparables.json",
  };
  const version = {
    ...VERSION,
    runner: `uv run labrador analyze fixtures/demo_program.json --comparables fixtures/demo_comparables.json --simulations ${SIMULATIONS} --seed ${SEED} --compact`,
  };
  const out = step.value;
  if (!out) {
    return envelope({
      caveats: [
        "No valuation exists for this run. There is no cached number standing in for it.",
      ],
      dataSources: [],
      decision: {
        honestyLabels: [
          {
            detail: step.error ?? "unknown error",
            label: "DEGRADED",
            scope: "the whole node",
          },
        ],
        keyNumbers: [],
        summary: `The economics engine could not run: ${step.error ?? "unknown error"}`,
      },
      durationMs: step.ms,
      handoff: null,
      inputs,
      node: "therapeutic-program-economics",
      startedAt: new Date(Date.now() - step.ms).toISOString(),
      status: "degraded",
      version,
    });
  }
  // The engine emits its own typed warnings. We carry the loudest ones through
  // verbatim rather than summarising them, because a summarised warning is a
  // softened warning.
  const errors = out.warnings.filter((w) => w.severity === "ERROR");
  const caveats = errors
    .slice(0, MAX_CAVEAT_WARNINGS)
    .map((w) => `${w.code}: ${w.message}`);
  if (errors.length > MAX_CAVEAT_WARNINGS) {
    caveats.push(
      `…and ${errors.length - MAX_CAVEAT_WARNINGS} more ERROR-severity warnings in the engine's own output (${out.warnings.length} warnings in total).`
    );
  }
  caveats.push(
    `The engine published ${out.calculation_steps.length} named calculation steps with their formulas (e.g. "${out.calculation_steps[0]?.label ?? ""}": ${out.calculation_steps[0]?.formula ?? ""}). They are in the full analysis JSON, not summarised here.`
  );
  return envelope({
    caveats,
    dataSources: economicsSources(out),
    decision: {
      honestyLabels: economicsHonesty(out),
      keyNumbers: economicsNumbers(out),
      summary: `On fictitious inputs, the demo programme's median simulated value is ${Number(out.summary.p50_rnpv ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })} USD, and the engine refuses to call the result decision-grade.`,
    },
    durationMs: step.ms,
    handoff: null,
    inputs,
    node: "therapeutic-program-economics",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version,
  });
}

// ---------------------------------------------------------------------------
// The terminal verdict: the end statement plus the full ancestry that produced
// it. Deduplicated honesty labels, so nothing quietly drops off the end.
// ---------------------------------------------------------------------------

/** This runner's own end statement; the rest of the verdict is mechanical. */
function demoHeadline(envelopes: TraceEnvelope[], complete: boolean): string {
  const money = envelopes.at(-1)?.decision.keyNumbers[0];
  return complete
    ? `Chain ran end to end. The recruitment forecast is a simulation, the money it feeds is priced on a fictitious programme, and the economics engine stamps its own output NOT_DECISION_GRADE — so this number sizes a question, it does not answer one. Last number in the chain: ${money?.label ?? "none"} = ${money?.value ?? "n/a"}.`
    : "Chain did NOT run end to end. At least one node degraded or was skipped; the panels below say which, and no number was substituted for the missing step.";
}

// ---------------------------------------------------------------------------
// Main. Reads top to bottom like the pipeline it traces.
// ---------------------------------------------------------------------------

/** Resolve the thesis to trace, or exit with the list of valid fixture ids. */
function pickThesis(): IndicationThesis {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: { fixture: { type: "string" } },
  });
  const wanted = values.fixture ?? DEFAULT_FIXTURE;
  const picked = theses.find((f) => f.thesis.id === wanted);
  if (!picked) {
    process.stderr.write(
      `unknown fixture "${wanted}"; available: ${theses.map((f) => f.thesis.id).join(", ")}\n`
    );
    process.exit(1);
  }
  return IndicationThesis.parse(picked.thesis);
}

/** One line of progress per node, so a watcher sees where a slow run is. */
function report(step: { ms: number }, wrapped: TraceEnvelope): void {
  process.stderr.write(
    `      ${wrapped.status} in ${(step.ms / MS_PER_SECOND).toFixed(1)}s\n`
  );
}

async function main(): Promise<void> {
  const thesis = pickThesis();

  // STEP 1 — the only step that spends money and touches the internet.
  process.stderr.write(
    `[1/3] trial-recruitment-forecaster — live CT.gov + Claude read for "${thesis.id}"…\n`
  );
  const forecastStep = await runForecaster(thesis);
  const savedResultPath = join(
    FIXTURES_DIR,
    `recruitability-${thesis.id}.json`
  );
  if (forecastStep.value) {
    // Saved so the adapter can be re-run for free, and so a reviewer can check
    // the envelope against the node's raw output.
    writeFileSync(
      savedResultPath,
      `${JSON.stringify(forecastStep.value, null, 2)}\n`
    );
  }
  const envelopes: TraceEnvelope[] = [forecasterEnvelope(thesis, forecastStep)];
  report(forecastStep, envelopes[0] as TraceEnvelope);

  // STEP 2 — the seam. Skipped, not faked, when step 1 produced nothing.
  process.stderr.write("[2/3] adapter-b — months → launch-delay overlay…\n");
  const bridgeStep = forecastStep.value
    ? runBridge(savedResultPath)
    : { error: "step 1 produced no result to convert", ms: 0 };
  const bridgeWrapped = bridgeEnvelope(
    bridgeStep,
    forecastStep.value,
    savedResultPath
  );
  envelopes.push(bridgeWrapped);
  report(bridgeStep, bridgeWrapped);

  // STEP 3 — the economics baseline. Runs regardless of steps 1-2, because it
  // is exactly the untouched baseline the delay above would be applied to.
  process.stderr.write(
    "[3/3] therapeutic-program-economics — read-only run on its own fixtures…\n"
  );
  const economicsStep = runEconomics();
  const economicsWrapped = economicsEnvelope(economicsStep);
  envelopes.push(economicsWrapped);
  report(economicsStep, economicsWrapped);

  const trace: Trace = {
    envelopes,
    generatedAt: new Date().toISOString(),
    run: {
      fixtureId: thesis.id,
      plannedMonths: PLANNED_MONTHS,
      seed: SEED,
      simulations: SIMULATIONS,
    },
    traceVersion: "1.0",
    verdict: buildVerdict(envelopes, (complete) =>
      demoHeadline(envelopes, complete)
    ),
  };

  const tracePath = join(FIXTURES_DIR, "trace-demo-output.json");
  writeFileSync(tracePath, `${JSON.stringify(trace, null, 2)}\n`);
  process.stderr.write(`\nwrote ${tracePath.replace(`${REPO_ROOT}/`, "")}\n`);
  process.stderr.write(
    `${injectTrace(OBSERVATORY_HTML, trace, "trace-demo.ts")}\n`
  );
  process.stdout.write(`${trace.verdict.headline}\n`);
}

await main();
