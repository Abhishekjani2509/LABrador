/**
 * Runnable demo for the Trial Recruitment Forecaster.
 *
 *   bun managed/trial-recruitment-forecaster/demo.ts
 *   bun managed/trial-recruitment-forecaster/demo.ts dupi-eoe
 *   bun managed/trial-recruitment-forecaster/demo.ts dupi-eoe 2018-01-01
 *
 * The third form is the stage moment: same thesis, evidence horizon rolled
 * back to before dupilumab had any EoE approval.
 */
import fixtures from "./fixtures/theses.json" with { type: "json" };
import {
  assessRecruitability,
  type RecruitabilityResult,
} from "./recruitability.ts";
import { IndicationThesis } from "./thesis.ts";

const [wanted, asOf] = process.argv.slice(2);

const selected = wanted
  ? fixtures.filter((f) => f.thesis.id === wanted)
  : fixtures;

if (selected.length === 0) {
  process.stderr.write(
    `No fixture "${wanted}". Available: ${fixtures.map((f) => f.thesis.id).join(", ")}\n`
  );
  process.exit(1);
}

function render(
  thesis: IndicationThesis,
  whyInSet: string,
  result: RecruitabilityResult
): string {
  const lines = [
    "",
    "=".repeat(72),
    `${thesis.id}  —  ${thesis.asset.name} in ${thesis.disease.name}`,
    asOf ? `evidence horizon: on or before ${asOf}` : "evidence horizon: today",
    "=".repeat(72),
    `fixture rationale: ${whyInSet}`,
    "",
    `  SIMULATED time to enroll   ${result.simulatedMonthsToEnroll} months  (range ${result.simulatedMonthsRange[0]}–${result.simulatedMonthsRange[1]})`,
    `  recruitability score       ${(result.score * 100).toFixed(0)} / 100`,
    `  waterfall contribution     ${result.waterfallDelta >= 0 ? "+" : ""}${result.waterfallDelta}`,
    `  required N                 ${result.requiredN}   (basis: ${result.poweringBasis}; precedent median ${result.precedentMedianN ?? "n/a"}, phase-3 median ${result.phase3MedianN ?? "n/a"})`,
    `  sites                      ${result.sites}   (${result.sitesBasis})`,
    "",
    `  why: ${result.why}`,
    "",
    `  eligibility pass rate      ${(result.eligibility.multiplier * 100).toFixed(0)}%`,
    `  screening burden           ~${result.screensPerEnrollee} patients screened per enrollee`,
    `  screen-fail drivers        ${result.eligibility.drivers.join("; ") || "none identified"}`,
    `  cited trials               ${result.eligibility.citedTrials.join(", ") || "none"}`,
    "",
    `  competing recruiting       ${result.evidence.competingTrials} trials`,
    `  precedent trials           ${result.evidence.precedentTrials.slice(0, 6).join(", ") || "none"}`,
  ];

  if (result.failedPrecedents.length > 0) {
    lines.push("", "  failed precedents (kill-mode fuel):");
    for (const f of result.failedPrecedents) {
      lines.push(`    ${f.nctId}  ${f.whyStopped}`);
    }
  }

  if (result.counterfactual) {
    const heading = {
      feasible:
        "CLOSE THE LOOP — cheapest change that gets under the 48-month bar:",
      good: "CLOSE THE LOOP — cheapest change that makes this comfortably enrollable (<=18 mo):",
      none: "CLOSE THE LOOP — no biomarker relaxation rescues this design:",
    }[result.counterfactual.achieves];
    const suffix =
      result.counterfactual.achieves === "none" ? "  (all-comers ceiling)" : "";
    lines.push(
      "",
      `  ${heading}`,
      `    ${result.counterfactual.change}`,
      `    ${result.simulatedMonthsToEnroll} months  ->  ${result.counterfactual.simulatedMonthsAfter} months${suffix}`
    );
  }

  lines.push("");
  return `${lines.join("\n")}\n`;
}

// allSettled: a single transient CT.gov failure on one fixture must not
// discard the other fixtures' completed work.
const runs = await Promise.allSettled(
  selected.map(async ({ thesis: raw, whyInSet }) => {
    const thesis = IndicationThesis.parse(raw);
    const result = await assessRecruitability(thesis, { asOf });
    return render(thesis, whyInSet, result);
  })
);

for (const [i, run] of runs.entries()) {
  if (run.status === "fulfilled") {
    process.stdout.write(run.value);
  } else {
    process.exitCode = 1;
    process.stderr.write(
      `\n${selected[i]?.thesis.id ?? "?"}  FAILED — ${run.reason instanceof Error ? run.reason.message : String(run.reason)}\n`
    );
  }
}
