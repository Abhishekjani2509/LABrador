/**
 * Adapter B (COORDINATION.md §5): forecaster → economics launch-delay overlay.
 *
 * Converts a `RecruitabilityResult` into an "economics overlay" that an
 * analyst (or a future orchestrator) applies to Vince's
 * `managed/therapeutic-program-economics` simulator. This script only READS
 * from Vince's directory — it never writes into it or modifies his node.
 *
 *   bun managed/trial-recruitment-forecaster/economics-bridge.ts --fixture dupi-eoe
 *   bun managed/trial-recruitment-forecaster/economics-bridge.ts --from-json result.json
 *   ... [--planned-months 18] [--save-result <path>]
 *
 * `--fixture <id>` runs `assessRecruitability` live on a fixture from
 * `fixtures/theses.json` (costs Claude calls + CT.gov requests;
 * `--save-result` writes the raw RecruitabilityResult so later runs can use
 * `--from-json` for free). `--planned-months` is the sponsor's planned
 * enrolment window; default 18 = the forecaster's GOOD_MONTHS.
 *
 * THE TWO "OBVIOUS" WIRINGS ARE BOTH WRONG — do not re-add them:
 *
 *  1. forecaster `score` → `stage_success_probabilities` /
 *     `program_probability_of_approval`: a CATEGORY ERROR. Recruitability is
 *     "can this trial fill its arms", not probability of approval; the
 *     economics engine cannot detect the substitution and would price
 *     enrolment friction as clinical failure risk.
 *  2. `simulatedMonthsToEnroll` → `stage_durations_years`: in engine.py,
 *     stage durations only shift when stage COSTS are paid — they do not
 *     move `launch_year`, so the delay's value impact would silently vanish.
 *
 * The value-bearing landing zone is LAUNCH DELAY, which the engine already
 * prices (output `summary.value_lost_per_launch_delay_year`):
 *
 *  - deterministic: the analyst adds `simulatedLaunchDelayYears` to the
 *    program's `launch_year` (application convention to be confirmed with
 *    Vince — see COORDINATION.md §5);
 *  - probabilistic: `simulatedLaunchDelayRangeYears` is a triangular
 *    low/mode/high for `SimulationAssumptions.launch_delay_years` (the
 *    engine rounds each sampled delay to WHOLE years — simulation.py:155 —
 *    hence the rounding here).
 *
 * Pricing is best-effort: if `uv` is available, the bridge runs Vince's demo
 * analysis read-only from his directory and multiplies the delay by his
 * engine's `value_lost_per_launch_delay_year`. That number comes from his
 * SYNTHETIC demo fixture (program_id SYNTHETIC-LAB-001), which the engine
 * itself stamps NOT_DECISION_GRADE — the priced figures are directional
 * illustrations, never decision inputs. If uv or the run fails, the overlay
 * still prints, with `pricing.status: "unavailable"`.
 *
 * Honesty rule (repo-wide, non-negotiable): every simulated number stays
 * NAMED simulated, and every number carries a `basis` string.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { z } from "zod";
import fixtures from "./fixtures/theses.json" with { type: "json" };
import { assessRecruitability } from "./recruitability.ts";
import { IndicationThesis } from "./thesis.ts";

/** The engine's GOOD_MONTHS — a sponsor's comfortable enrolment window. */
const DEFAULT_PLANNED_MONTHS = 18;
const MONTHS_PER_YEAR = 12;
const ECONOMICS_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "therapeutic-program-economics"
);

/**
 * The slice of RecruitabilityResult this bridge consumes (see
 * `recruitability.ts` for the full shape). Extra fields in a saved result
 * are ignored, so a full saved RecruitabilityResult validates as-is.
 */
const BridgeInput = z.object({
  asOf: z.string().optional(),
  counterfactual: z
    .object({
      achieves: z.enum(["good", "feasible", "none"]),
      change: z.string(),
      simulatedMonthsAfter: z.number(),
    })
    .optional(),
  score: z.number().optional(),
  simulatedMonthsRange: z.tuple([z.number(), z.number()]),
  simulatedMonthsToEnroll: z.number(),
});
type BridgeInputT = z.infer<typeof BridgeInput>;

type Pricing =
  | {
      decisionGrade: string;
      note: string;
      pricedAgainst: string;
      simulatedCounterfactualValueUSD?: number;
      simulatedDelayCostUSD: number;
      status: "ok";
      valueLostPerLaunchDelayYearUSD: number;
    }
  | { note: string; status: "unavailable" };

function usage(): never {
  process.stderr.write(
    `usage: bun economics-bridge.ts (--fixture <id> | --from-json <path>) [--planned-months <n>] [--save-result <path>]\nfixtures: ${fixtures.map((f) => f.thesis.id).join(", ")}\n`
  );
  process.exit(1);
}

function parseCli() {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: {
      fixture: { type: "string" },
      "from-json": { type: "string" },
      "planned-months": { type: "string" },
      "save-result": { type: "string" },
    },
  });
  const plannedMonths = Number(
    values["planned-months"] ?? DEFAULT_PLANNED_MONTHS
  );
  if (!Number.isFinite(plannedMonths) || plannedMonths <= 0) {
    usage();
  }
  if (Boolean(values.fixture) === Boolean(values["from-json"])) {
    usage(); // exactly one input source
  }
  return {
    fixtureId: values.fixture,
    fromJson: values["from-json"],
    plannedMonths,
    saveResult: values["save-result"],
  };
}

async function loadInput(cli: ReturnType<typeof parseCli>): Promise<{
  result: BridgeInputT;
  source: string;
}> {
  if (cli.fromJson) {
    const raw: unknown = JSON.parse(readFileSync(cli.fromJson, "utf8"));
    return {
      result: BridgeInput.parse(raw),
      source: `saved RecruitabilityResult at ${cli.fromJson}`,
    };
  }
  const fixture = fixtures.find((f) => f.thesis.id === cli.fixtureId);
  if (!fixture) {
    usage();
  }
  const thesis = IndicationThesis.parse(fixture.thesis);
  const result = await assessRecruitability(thesis);
  if (cli.saveResult) {
    writeFileSync(cli.saveResult, JSON.stringify(result, null, 2));
  }
  return {
    result,
    source: `live assessRecruitability run on fixture ${thesis.id} (evidence horizon: today)`,
  };
}

/**
 * months over the planned window → launch-delay years. Rounded to WHOLE
 * years because that is the granularity the economics engine applies
 * (`round(launch_delay_years.sample(rng))`), floored at 0 because finishing
 * early is not a negative delay the engine can price.
 */
function delayYears(months: number, plannedMonths: number) {
  const unrounded = (months - plannedMonths) / MONTHS_PER_YEAR;
  return { rounded: Math.max(0, Math.round(unrounded)), unrounded };
}

function buildOverlay(input: BridgeInputT, plannedMonths: number) {
  const point = delayYears(input.simulatedMonthsToEnroll, plannedMonths);
  const [fastMonths, slowMonths] = input.simulatedMonthsRange;
  const low = delayYears(fastMonths, plannedMonths).rounded;
  const high = Math.max(delayYears(slowMonths, plannedMonths).rounded, low);
  const mode = Math.min(Math.max(point.rounded, low), high);
  const monthsSaved = input.counterfactual
    ? input.simulatedMonthsToEnroll - input.counterfactual.simulatedMonthsAfter
    : undefined;
  return {
    monthsSaved,
    overlay: {
      basis: {
        counterfactual: input.counterfactual
          ? "Passthrough of the forecaster's cheapest-rescue search; simulatedMonthsSavedByCounterfactual = simulatedMonthsToEnroll - counterfactual.simulatedMonthsAfter."
          : "Forecaster emitted no counterfactual (design already enrols within GOOD_MONTHS).",
        simulatedLaunchDelayRangeYears: `Same transform applied to simulatedMonthsRange [${fastMonths}, ${slowMonths}] (interquartile velocity band) for low/high, point estimate as mode; ordered low<=mode<=high as TriangularRange requires.`,
        simulatedLaunchDelayYears: `max(0, round((simulatedMonthsToEnroll ${input.simulatedMonthsToEnroll} - plannedMonths ${plannedMonths}) / 12)); whole years because engine rounds sampled delays to whole years.`,
      },
      counterfactual: input.counterfactual ?? null,
      howToApply: {
        launch_delay_years: `Probabilistic: set SimulationAssumptions.launch_delay_years = {low: ${low}, mode: ${mode}, high: ${high}}.`,
        launch_year: `Deterministic: add ${point.rounded} to the program's initial_indication.launch_year (convention to confirm with Vince).`,
      },
      input: {
        asOf: input.asOf ?? null,
        plannedMonths,
        score: input.score ?? null,
        simulatedMonthsRange: input.simulatedMonthsRange,
        simulatedMonthsToEnroll: input.simulatedMonthsToEnroll,
      },
      simulatedLaunchDelayRangeYears: { high, low, mode },
      simulatedLaunchDelayYears: point.rounded,
      simulatedLaunchDelayYearsUnrounded: point.unrounded,
      simulatedMonthsSavedByCounterfactual: monthsSaved ?? null,
    },
  };
}

/**
 * Best-effort pricing against Vince's engine, run READ-ONLY from his
 * directory (uv writes only its own .venv there — a gitignored build
 * artifact, not a source change). Any failure degrades to "unavailable".
 */
function priceOverlay(
  delayYearsRounded: number,
  savedMonths?: number
): Pricing {
  let stdout: string;
  try {
    execSync("uv sync --frozen", { cwd: ECONOMICS_DIR, stdio: "pipe" });
    stdout = execSync(
      "uv run labrador analyze fixtures/demo_program.json --comparables fixtures/demo_comparables.json --simulations 200 --seed 42 --compact",
      { cwd: ECONOMICS_DIR, encoding: "utf8", stdio: "pipe" }
    );
  } catch (err) {
    return {
      note: `uv unavailable or economics run failed (${err instanceof Error ? err.message.split("\n")[0] : String(err)}); overlay emitted without pricing.`,
      status: "unavailable",
    };
  }
  const parsed = z
    .object({
      decision_grade: z.string(),
      summary: z.object({
        program_id: z.string(),
        value_lost_per_launch_delay_year: z.number(),
      }),
    })
    .safeParse(JSON.parse(stdout));
  if (!parsed.success) {
    return {
      note: "economics output missing summary.value_lost_per_launch_delay_year; overlay emitted without pricing.",
      status: "unavailable",
    };
  }
  const perYear = parsed.data.summary.value_lost_per_launch_delay_year;
  return {
    decisionGrade: parsed.data.decision_grade,
    note: `SIMULATED, priced against Vince's SYNTHETIC demo fixture (${parsed.data.summary.program_id}, fixtures/demo_program.json) — his engine stamps it ${parsed.data.decision_grade}. Directional illustration only, never a decision input. Delay cost = ${delayYearsRounded} whole delay year(s) x value_lost_per_launch_delay_year; counterfactual value = months saved / 12 x the same rate.`,
    pricedAgainst:
      "managed/therapeutic-program-economics/fixtures/demo_program.json (seed 42, 200 simulations)",
    simulatedCounterfactualValueUSD:
      savedMonths === undefined
        ? undefined
        : Math.round((savedMonths / MONTHS_PER_YEAR) * perYear),
    simulatedDelayCostUSD: Math.round(delayYearsRounded * perYear),
    status: "ok",
    valueLostPerLaunchDelayYearUSD: perYear,
  };
}

const args = parseCli();
const { result, source } = await loadInput(args);
const { monthsSaved, overlay } = buildOverlay(result, args.plannedMonths);
const pricing = priceOverlay(overlay.simulatedLaunchDelayYears, monthsSaved);
process.stdout.write(
  `${JSON.stringify({ ...overlay, pricing, source }, null, 2)}\n`
);
