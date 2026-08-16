/**
 * pipeline.ts — the whole LABrador chain, one command, one traced artifact.
 *
 *   bun run pipeline
 *
 * WHAT IT IS. `trace-demo.ts` traces the three stations that composed in
 * mid-August. This runs the FULL chain the team drew in COORDINATION §11 —
 * hypothesis → thesis → evidence → tractability → recruitment → economics —
 * on ONE subject, end to end, with the same trace envelope around every
 * station. It is the "orchestrator" row of §11 in its simplest honest form: a
 * runner, not a meta-search. (`hypothesis-highlander` optimises across MANY
 * runs; this explains ONE. Different layers, deliberately.)
 *
 * THE SUBJECT IS FIXED AND COHERENT: an IRAK4 inhibitor in rheumatoid
 * arthritis. It has to be. The only real evidence graph anyone has committed
 * (`research-evidence-mapper/runs/g_1a4f.json`) asks an IRAK4/RA question, so
 * pairing it with a forecaster fixture from a different disease would produce a
 * chain that looks composed and means nothing.
 *
 * ── THE SEVEN STATIONS ───────────────────────────────────────────────────
 *
 *  1  hypothesis-generator      hyp_gen dry-run over the REAL mapper graph
 *                               (uv subprocess, no model calls, no key needed)
 *  2  adapter-d (thesis-bridge) slate hypothesis + analyst frame → IndicationThesis
 *  3  adapter-a (evidence-bridge) the same graph's findings → Evidence rows,
 *                               so the thesis's own evidence can be compared
 *                               against everything the graph could have given
 *  4  adapter-c (dossier-bridge) two committed tractability dossiers → Evidence
 *                               rows. NEITHER IS IRAK4 — see the honesty note
 *  5  trial-recruitment-forecaster  live: CT.gov + a Claude read of real
 *                               eligibility prose. Degrades honestly with no key
 *  6  adapter-b (economics-bridge)  months → launch-delay overlay
 *  7  therapeutic-program-economics  `labrador analyze` on a SYNTHETIC IRAK4/RA
 *                               programme with a SYNTHETIC RA comparables set
 *
 * ── THE THREE HONESTY FACTS THIS RUN CANNOT HIDE ─────────────────────────
 *
 * The verdict headline names all three every time, and they are the reason
 * this runner exists rather than a slide:
 *
 *  ASSUMED — the thesis's biomarker population and endpoint are an ANALYST's
 *    numbers (fixtures/irak4-ra.frame.json). A literature graph has no
 *    epidemiology and no endpoint; the frame says so field by field.
 *  SUBJECT MISMATCH — station 4 runs on JAK1 and TNF dossiers, because no
 *    IRAK4 dossier exists yet. Their rows are QUARANTINED: they are reported
 *    and never merged into the thesis. (Owner: Rafal — an IRAK4/Q9NWZ3 dossier
 *    is the one input that would make this station real.)
 *  SYNTHETIC — station 7's programme and comparables are fictitious by
 *    construction, and the engine stamps its own run NOT_DECISION_GRADE.
 *
 * ── WHAT IT WRITES ───────────────────────────────────────────────────────
 *
 *   fixtures/pipeline-irak4-ra.trace.json   the trace — the reviewable artifact
 *   fixtures/hypgen-irak4-ra.slate.json     the slate station 1 produced
 *   fixtures/thesis-irak4-ra.json           the thesis station 2 produced
 *   fixtures/recruitability-<id>.json       station 5's raw result
 *   pipeline.html                           the same renderer as observatory.html,
 *                                           with this trace injected
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import {
  assessRecruitability,
  COMPETITION_SHARE,
  type RecruitabilityResult,
} from "../trial-recruitment-forecaster/recruitability.ts";
import {
  type Evidence,
  IndicationThesis,
} from "../trial-recruitment-forecaster/thesis.ts";
import {
  buildVerdict,
  capped,
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

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = join(HERE, "fixtures");
const PIPELINE_HTML = join(HERE, "pipeline.html");
const FORECASTER_DIR = join(
  REPO_ROOT,
  "managed",
  "trial-recruitment-forecaster"
);
const HYPGEN_DIR = join(REPO_ROOT, "managed", "hypothesis-generator");
const ECONOMICS_DIR = join(
  REPO_ROOT,
  "managed",
  "therapeutic-program-economics"
);
const TRACTABILITY_EXAMPLES = join(
  REPO_ROOT,
  "managed",
  "small-molecule-tractability-review",
  ".claude",
  "skills",
  "assemble-dossier",
  "examples"
);
const GRAPH_PATH = join(
  REPO_ROOT,
  "managed",
  "research-evidence-mapper",
  "runs",
  "g_1a4f.json"
);
const FRAME_PATH = join(FORECASTER_DIR, "fixtures", "irak4-ra.frame.json");
const SLATE_PATH = join(FIXTURES_DIR, "hypgen-irak4-ra.slate.json");
const THESIS_PATH = join(FIXTURES_DIR, "thesis-irak4-ra.json");
const PROGRAM_PATH = join(FIXTURES_DIR, "irak4-ra.SYNTHETIC.program.json");
const COMPARABLES_PATH = join(
  FIXTURES_DIR,
  "irak4-ra.SYNTHETIC.comparables.json"
);
const DOSSIERS = [
  { file: "jak1_P23458.json", label: "JAK1" },
  { file: "tnf_P01375.json", label: "TNF" },
];

/**
 * `default`, NOT `valuation`. Verified by running both: `--profile valuation`
 * shortlists ZERO hypotheses on g_1a4f, because it demands two independent
 * research groups and a protein/gene node on the path, and this graph has one
 * group and no protein entity at all. Picking `valuation` here would make the
 * whole pipeline print "nothing survived selection" and look broken.
 */
const HYPGEN_PROFILE = "default";
/** The hypothesis whose subject IS the IRAK4 inhibitor. */
const DEFAULT_HYPOTHESIS = "H-g1";
const THESIS_TARGET_SYMBOL = "IRAK4";
const THESIS_TARGET_ACCESSION = "Q9NWZ3";
const PLANNED_MONTHS = "18";
const SIMULATIONS = "200";
const SEED = "42";
const SUBPROCESS_TIMEOUT_MS = 600_000;
const MAX_LISTED_SOURCES = 12;
const MAX_CAVEAT_WARNINGS = 6;
const MS_PER_SECOND = 1000;
const MONTHS_PER_YEAR = 12;
const PERCENT = 100;
const STATION_COUNT = 7;
/** Below this competition penalty, the share model is off its calibration. */
const CROWDING_PENALTY_ALARM = 0.2;

/** Run a child process, returning stdout or the first line of the failure. */
function run(cmd: string, args: string[], cwd: string): StepResult<string> {
  const started = Date.now();
  try {
    const stdout = execFileSync(cmd, args, {
      cwd,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      stdio: "pipe",
      timeout: SUBPROCESS_TIMEOUT_MS,
    });
    return { ms: Date.now() - started, value: stdout };
  } catch (err) {
    return { error: firstLine(err), ms: Date.now() - started };
  }
}

/** The envelope every failed station gets: says what broke, invents nothing. */
function degraded(args: {
  inputs: TraceEnvelope["inputs"];
  ms: number;
  node: string;
  reason: string;
  runner: string;
  status?: "degraded" | "skipped";
}): TraceEnvelope {
  return envelope({
    caveats: [
      "This station produced no number. Everything downstream of it is missing, not zero — no value was substituted.",
    ],
    dataSources: [],
    decision: {
      honestyLabels: [
        { detail: args.reason, label: "DEGRADED", scope: "the whole station" },
      ],
      keyNumbers: [],
      summary: `${args.node} did not run: ${args.reason}`,
    },
    durationMs: args.ms,
    handoff: null,
    inputs: args.inputs,
    node: args.node,
    startedAt: new Date(Date.now() - args.ms).toISOString(),
    status: args.status ?? "degraded",
    version: { ...VERSION, runner: args.runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 1 — hypothesis-generator (hyp_gen), structural dry run.
// ---------------------------------------------------------------------------

type SlateSummary = {
  counts: { findings: number; hypotheses: number; papers: number };
  coverage: string;
  graphId: string;
  ids: string[];
  question: string;
};

function runHypGen(): StepResult<SlateSummary> {
  const outDir = mkdtempSync(join(tmpdir(), "hypgen-"));
  const step = run(
    "uv",
    [
      "run",
      "python",
      "-m",
      "hyp_gen.cli",
      "--graph",
      GRAPH_PATH,
      "--profile",
      HYPGEN_PROFILE,
      "--dry-run",
      "--out",
      outDir,
    ],
    HYPGEN_DIR
  );
  if (!step.value) {
    return { error: step.error, ms: step.ms };
  }
  const slateText = readFileSync(join(outDir, "slate.json"), "utf8");
  // The slate is committed as the demo artifact: a reader can re-run the same
  // command and diff it, which is the only way the trace's first station is
  // checkable at all.
  writeFileSync(SLATE_PATH, slateText);
  const slate = JSON.parse(slateText) as {
    coverage?: Record<string, unknown>;
    counts?: Record<string, number>;
    graph_id: string;
    hypotheses: { id: string }[];
    question: string;
  };
  const coverage = slate.coverage ?? {};
  return {
    ms: step.ms,
    value: {
      counts: {
        findings: Number(slate.counts?.findings ?? 0),
        hypotheses: slate.hypotheses.length,
        papers: Number(slate.counts?.papers ?? 0),
      },
      coverage: `depth ${String(coverage.depth ?? "unknown")}, read ${String(coverage.read ?? "?")}/${String(coverage.found ?? "?")}${coverage.truncated ? ", TRUNCATED" : ""}`,
      graphId: slate.graph_id,
      ids: slate.hypotheses.map((h) => h.id),
      question: slate.question,
    },
  };
}

function hypGenEnvelope(step: StepResult<SlateSummary>): TraceEnvelope {
  const inputs = {
    digest: digest(GRAPH_PATH.replace(`${REPO_ROOT}/`, "")),
    humanSummary:
      "The only real evidence graph committed to this repo: research-evidence-mapper run g_1a4f, an IRAK4-in-rheumatoid-arthritis question.",
    source: GRAPH_PATH.replace(`${REPO_ROOT}/`, ""),
  };
  const runner = `uv run python -m hyp_gen.cli --graph <graph> --profile ${HYPGEN_PROFILE} --dry-run --out <dir>`;
  const { value } = step;
  if (!value) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "hypothesis-generator (hyp_gen)",
      reason: step.error ?? "unknown error",
      runner,
    });
  }
  return envelope({
    caveats: [
      `The generator's own coverage line: ${value.coverage}. A truncated search means "this search did not surface it", never "nobody has shown it".`,
      "--dry-run means NO model calls: this is the deterministic structural slate, so nothing here was written by a language model.",
      "PROFILE NOTE, verified by running both: --profile valuation shortlists ZERO on this graph (it requires two independent research groups and a protein/gene node on the path; g_1a4f has one group and no protein entity). This run uses --profile default.",
    ],
    dataSources: [
      {
        id: value.graphId,
        kind: "doi",
        role: `Evidence graph the hypotheses were enumerated from — ${value.counts.findings} findings across ${value.counts.papers} papers, each finding carrying a verbatim quote`,
      },
    ],
    decision: {
      honestyLabels: [
        {
          detail:
            "Support/novelty/testability are the generator's own scores over graph structure, not measurements of the world.",
          label: "SIMULATED",
          scope: "the ranking scores on every hypothesis",
        },
      ],
      keyNumbers: [
        {
          basis: `Structural enumeration over the graph at profile "${HYPGEN_PROFILE}"; ids: ${value.ids.join(", ")}`,
          label: "Hypotheses shortlisted",
          unit: "hypotheses",
          value: value.counts.hypotheses,
        },
        {
          basis: "Findings in the source graph, each with a verbatim quote.",
          label: "Findings available",
          unit: "findings",
          value: value.counts.findings,
        },
      ],
      summary: `The generator read graph ${value.graphId} ("${value.question}") and shortlisted ${value.counts.hypotheses} hypotheses without a single model call.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter: "managed/trial-recruitment-forecaster/thesis-bridge.ts",
      payloadSummary: `slate.json with ${value.counts.hypotheses} hypotheses; hypothesis ${DEFAULT_HYPOTHESIS} is the one carried forward (its subject IS the IRAK4 inhibitor).`,
      toNode: "adapter-d (thesis-bridge)",
    },
    inputs,
    node: "hypothesis-generator (hyp_gen)",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 2 — adapter D, the slate → thesis seam.
// ---------------------------------------------------------------------------

type BridgedThesis = {
  assumed: { field: string; label: string; value: string; why: string }[];
  dropped: { detail: string; findingId: string; reason: string }[];
  fieldBasis: Record<string, string>;
  provenance: Record<string, unknown>;
  thesis: IndicationThesis;
};

function runThesisBridge(): StepResult<BridgedThesis> {
  const step = run(
    "bun",
    [
      join(FORECASTER_DIR, "thesis-bridge.ts"),
      SLATE_PATH,
      "--frame",
      FRAME_PATH,
      "--hypothesis",
      DEFAULT_HYPOTHESIS,
    ],
    REPO_ROOT
  );
  if (!step.value) {
    return { error: step.error, ms: step.ms };
  }
  const parsed = JSON.parse(step.value) as BridgedThesis;
  // Parse again HERE, in the runner, rather than trusting the bridge's word:
  // the contract is what makes the rest of the chain legal.
  parsed.thesis = IndicationThesis.parse(parsed.thesis);
  writeFileSync(THESIS_PATH, `${JSON.stringify(parsed, null, 2)}\n`);
  return { ms: step.ms, value: parsed };
}

function thesisEnvelope(step: StepResult<BridgedThesis>): TraceEnvelope {
  const inputs = {
    digest: digest(SLATE_PATH.replace(`${REPO_ROOT}/`, "")),
    humanSummary: `Slate hypothesis ${DEFAULT_HYPOTHESIS} plus the analyst frame that supplies the two things a literature graph cannot: the trial population and the endpoint.`,
    source: `${SLATE_PATH.replace(`${REPO_ROOT}/`, "")} + ${FRAME_PATH.replace(`${REPO_ROOT}/`, "")}`,
  };
  const runner = `bun managed/trial-recruitment-forecaster/thesis-bridge.ts <slate> --frame <frame> --hypothesis ${DEFAULT_HYPOTHESIS}`;
  const { value } = step;
  if (!value) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "adapter-d (thesis-bridge)",
      reason: step.error ?? "unknown error",
      runner,
    });
  }
  const { thesis } = value;
  const labels: HonestyLabel[] = value.assumed.map((a) => ({
    detail: a.why,
    label: "ASSUMED" as const,
    scope: `${a.field} = ${a.value}`,
  }));
  return envelope({
    caveats: [
      ...((value.provenance.slateCaveats as string[] | undefined) ?? []),
      `${value.assumed.length} of this thesis's fields could not come from the graph and were supplied by the analyst frame. They are listed as ASSUMED honesty labels, one per field, with the reason each is not a graph finding.`,
      value.dropped.length > 0
        ? `${value.dropped.length} finding(s) were dropped rather than converted: ${value.dropped.map((d) => `${d.findingId} (${d.reason})`).join(", ")}.`
        : "No finding on this hypothesis's path was dropped: every one converted to a valid Evidence row.",
    ],
    dataSources: capped(
      thesis.evidence.map((e) => e.source),
      MAX_LISTED_SOURCES
    ).map((id) => ({
      id,
      kind: "doi" as const,
      role: "Paper whose verbatim quote became an Evidence row on this thesis",
    })),
    decision: {
      honestyLabels: labels,
      keyNumbers: [
        {
          basis: `asset ${thesis.asset.name} (${thesis.asset.modality}), target ${thesis.target.symbol}${thesis.target.uniprotAccession ? ` / ${thesis.target.uniprotAccession}` : ""}, direction ${thesis.target.direction}, disease ${thesis.disease.name}`,
          label: "Thesis emitted",
          unit: "id",
          value: thesis.id,
        },
        {
          basis: `Rows converted from the hypothesis's own evidence pack, ${value.dropped.length} dropped. Directions: ${thesis.evidence.map((e) => e.direction).join(", ")}.`,
          label: "Evidence rows carried",
          unit: "rows",
          value: thesis.evidence.length,
        },
        {
          basis: `1 − the generator's support score. ${String(value.fieldBasis.uncertainty ?? "")}`,
          label: "Uncertainty",
          unit: "0–1",
          value: thesis.uncertainty ?? "unset",
        },
      ],
      summary: `The slate hypothesis is now a valid IndicationThesis: ${thesis.asset.name} ${thesis.target.direction}ing ${thesis.target.symbol} in ${thesis.disease.name}, carrying ${thesis.evidence.length} sourced evidence rows and ${value.assumed.length} analyst assumptions.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter: "the thesis object itself (thesis.ts is the shared contract)",
      payloadSummary: `IndicationThesis "${thesis.id}" — population "${thesis.biomarkerPopulation.marker}" at ${(thesis.biomarkerPopulation.prevalenceInDisease * PERCENT).toFixed(0)}% prevalence, endpoint "${thesis.endpoint.name}".`,
      toNode: "trial-recruitment-forecaster",
    },
    inputs,
    node: "adapter-d (thesis-bridge)",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 3 — adapter A over the WHOLE graph, so the thesis's evidence can be
// read against everything the graph could have supplied.
// ---------------------------------------------------------------------------

type EvidenceBridgeOut = {
  dropped: { byReason: Record<string, number>; total: number };
  evidence: Evidence[];
  provenance: { schemaDeviations: string[]; strengthFormula: string };
};

function runEvidenceBridge(): StepResult<EvidenceBridgeOut> {
  const step = run(
    "bun",
    [join(FORECASTER_DIR, "evidence-bridge.ts"), GRAPH_PATH],
    REPO_ROOT
  );
  return step.value
    ? { ms: step.ms, value: JSON.parse(step.value) as EvidenceBridgeOut }
    : { error: step.error, ms: step.ms };
}

function evidenceEnvelope(
  step: StepResult<EvidenceBridgeOut>,
  thesis: IndicationThesis | undefined
): TraceEnvelope {
  const inputs = {
    digest: digest(GRAPH_PATH.replace(`${REPO_ROOT}/`, "")),
    humanSummary:
      "Every finding in the whole graph, not just the ones on the chosen hypothesis's path.",
    source: GRAPH_PATH.replace(`${REPO_ROOT}/`, ""),
  };
  const runner =
    "bun managed/trial-recruitment-forecaster/evidence-bridge.ts <graph>";
  const { value } = step;
  if (!value) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "adapter-a (evidence-bridge)",
      reason: step.error ?? "unknown error",
      runner,
    });
  }
  const onThesis = thesis?.evidence.length ?? 0;
  const dropReasons = Object.entries(value.dropped.byReason)
    .map(([reason, n]) => `${n}× ${reason}`)
    .join(", ");
  return envelope({
    caveats: [
      ...value.provenance.schemaDeviations.map(
        (d) =>
          `SCHEMA DEVIATION in the source graph (reported to its owner, never repaired here): ${d}`
      ),
      value.dropped.total > 0
        ? `${value.dropped.total} finding(s) dropped: ${dropReasons}. Drops are counted, never silent.`
        : "No finding was dropped.",
      `Coverage check: the thesis carries ${onThesis} of the ${value.evidence.length} actionable rows in the graph. The rest are about entities off this hypothesis's path — present in the graph, deliberately not attached to this thesis.`,
    ],
    dataSources: capped(
      value.evidence.map((e) => e.source),
      MAX_LISTED_SOURCES
    ).map((id) => ({
      id,
      kind: "doi" as const,
      role: "Paper cited by at least one converted finding",
    })),
    decision: {
      honestyLabels: [
        {
          detail: `Strength is not a measurement: ${value.provenance.strengthFormula}`,
          label: "ASSUMED",
          scope: "the strength score on every evidence row",
        },
      ],
      keyNumbers: [
        {
          basis: `Adapter A over the full graph; ${value.dropped.total} dropped (${dropReasons || "none"}).`,
          label: "Actionable evidence rows in the graph",
          unit: "rows",
          value: value.evidence.length,
        },
        {
          basis:
            "Rows the chosen hypothesis's own evidence pack supplied, converted at station 2.",
          label: "Rows on the thesis",
          unit: "rows",
          value: onThesis,
        },
      ],
      summary: `The graph supports ${value.evidence.length} actionable evidence rows in total; ${onThesis} of them sit on this thesis.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter: "reported alongside the thesis, not merged into it",
      payloadSummary:
        "Provenance only. Station 2 already attached the rows this hypothesis's path supports; this station exists so a reader can see what was NOT attached.",
      toNode: "the reader",
    },
    inputs,
    node: "adapter-a (evidence-bridge)",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 4 — adapter C, tractability. The station with the loud caveat.
// ---------------------------------------------------------------------------

type DossierBridgeOut = {
  caveats: string[];
  evidence: Evidence[];
  provenance: { verdict: string; verdictBasis: string };
  skipped: { axis: string; reason: string }[];
  subjectMatch: { detail: string; dossierSymbol: string; matches: boolean };
};

type TractabilityOut = {
  results: { label: string; out: DossierBridgeOut }[];
};

function runDossierBridge(): StepResult<TractabilityOut> {
  const started = Date.now();
  const results: TractabilityOut["results"] = [];
  for (const dossier of DOSSIERS) {
    const step = run(
      "bun",
      [
        join(FORECASTER_DIR, "dossier-bridge.ts"),
        join(TRACTABILITY_EXAMPLES, dossier.file),
        "--thesis-symbol",
        THESIS_TARGET_SYMBOL,
        "--thesis-accession",
        THESIS_TARGET_ACCESSION,
      ],
      REPO_ROOT
    );
    if (!step.value) {
      return {
        error: `${dossier.label}: ${step.error}`,
        ms: Date.now() - started,
      };
    }
    results.push({
      label: dossier.label,
      out: JSON.parse(step.value) as DossierBridgeOut,
    });
  }
  return { ms: Date.now() - started, value: { results } };
}

function tractabilityEnvelope(
  step: StepResult<TractabilityOut>
): TraceEnvelope {
  const inputs = {
    digest: digest(DOSSIERS.map((d) => d.file)),
    humanSummary:
      "The two committed, validator-clean tractability dossiers — JAK1 and TNF. There is no IRAK4 dossier to run.",
    source: TRACTABILITY_EXAMPLES.replace(`${REPO_ROOT}/`, ""),
  };
  const runner =
    "bun managed/trial-recruitment-forecaster/dossier-bridge.ts <dossier> --thesis-symbol IRAK4 --thesis-accession Q9NWZ3";
  const { value } = step;
  if (!value) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "adapter-c (dossier-bridge)",
      reason: step.error ?? "unknown error",
      runner,
    });
  }
  const rows = value.results.flatMap((r) => r.out.evidence);
  const mismatched = value.results.filter((r) => !r.out.subjectMatch.matches);
  const labels: HonestyLabel[] = [
    {
      detail: `NONE of the available dossiers is the thesis target. ${mismatched.map((r) => r.out.subjectMatch.detail).join(" ")} These ${rows.length} rows are therefore QUARANTINED: reported here, and NOT merged into the thesis that station 5 scores. Making this station real needs one thing — an IRAK4 (Q9NWZ3) dossier from the tractability node.`,
      label: "SUBJECT_MISMATCH",
      scope: "every tractability row in this run",
    },
    {
      detail:
        "Computed-axis rows are pocket geometry from fpocket, capped at 0.5 strength and fixed at 0.25, because the tractability node stamps its own druggability `load_bearing: false` and has RETRACTED the calibration that used to interpret pocket volume.",
      label: "SIMULATED",
      scope: "any row with sourceType simulation",
    },
  ];
  const skipped = value.results.flatMap((r) =>
    r.out.skipped.map(
      (s) => `${r.label}: ${s.axis} axis not emitted — ${s.reason}`
    )
  );
  return envelope({
    caveats: [
      "TRACTABILITY DID NOT ENRICH THIS THESIS. The rows below are about other proteins; treating them as IRAK4 evidence would be the exact failure this pipeline is built to prevent.",
      ...value.results.flatMap((r) =>
        r.out.caveats.map((c) => `${r.label}: ${c}`)
      ),
      ...skipped,
    ],
    dataSources: value.results.flatMap((r) =>
      r.out.evidence.map((e) => ({
        id: e.source,
        kind: (e.sourceType === "simulation" ? "structure" : "doi") as
          | "doi"
          | "structure",
        role: `${r.label} dossier, ${e.sourceType} row at strength ${e.strength}`,
      }))
    ),
    decision: {
      honestyLabels: labels,
      keyNumbers: value.results.map((r) => ({
        basis: `verdict "${r.out.provenance.verdict}", basis "${r.out.provenance.verdictBasis}"; ${r.out.evidence.length} row(s) emitted, ${r.out.skipped.length} axis/axes refused.`,
        label: `${r.label} dossier rows`,
        unit: "rows",
        value: r.out.evidence.length,
      })),
      summary: `${rows.length} tractability evidence rows exist and NONE of them is about IRAK4 — both committed dossiers measure a different protein, so this station enriches nothing and says so.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter: "none — rows quarantined on purpose",
      payloadSummary:
        "Nothing crosses this boundary. A subject-mismatched row must never enter a thesis, so the forecaster below sees exactly the thesis station 2 produced.",
      toNode: "(nothing)",
    },
    inputs,
    node: "adapter-c (dossier-bridge)",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 5 — the forecaster, live.
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

function forecasterSources(result: RecruitabilityResult): DataSource[] {
  const precedent = capped(
    result.evidence.precedentTrials,
    MAX_LISTED_SOURCES
  ).map((id) => ({
    id,
    kind: "nct" as const,
    role: "Completed interventional precedent — supplied enrolment velocity, sample-size and site-count anchors",
  }));
  const cited = capped(result.eligibility.citedTrials, MAX_LISTED_SOURCES).map(
    (id) => ({
      id,
      kind: "nct" as const,
      role: "Eligibility prose Claude actually read to estimate the screen-failure rate",
    })
  );
  return [...precedent, ...cited];
}

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
        "Same model at the 75th and 25th percentile of observed precedent velocity (interquartile band, not a confidence interval).",
      label: "Simulated range",
      unit: "months",
      value: `${fast}–${slow}`,
    },
    {
      basis: `Straight-line mapping of months: 1.0 at or under 18 months, 0 at or beyond 48. Here ${result.simulatedMonthsToEnroll} months.`,
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
      basis: `Site count basis: ${result.sitesBasis}.`,
      label: "Sites assumed open",
      unit: "sites",
      value: result.sites,
    },
    {
      basis: `${result.eligibility.reasoning} Drivers: ${result.eligibility.drivers.join("; ")}. Cited: ${result.eligibility.citedTrials.join(", ") || "none"}.`,
      label: "Eligibility pass rate",
      unit: "fraction of marker-positive patients",
      value: result.eligibility.multiplier,
    },
    {
      basis:
        "1 / (biomarker prevalence × eligibility pass rate) — where low prevalence lands as cost rather than time.",
      label: "Patients screened per enrollee",
      unit: "screens",
      value: result.screensPerEnrollee,
    },
  ];
}

/**
 * FOUND BY RUNNING THIS PIPELINE, 2026-08-16, and left standing rather than
 * tuned away: on rheumatoid arthritis the forecaster returns 470 months.
 *
 * The arithmetic is `competitionPenalty = 1 / (1 + 0.08 × recruitingCount)`
 * (recruitability.ts), and RA has ~189 concurrently recruiting interventional
 * trials — so the model divides per-site velocity by ~16 on the premise that
 * each competitor takes 8% of the patient pool. Eight percent each × 189
 * competitors is 1500% of the pool: the share model is being asked a question
 * it was never calibrated for. The forecaster's own counterfactual search says
 * the same thing from the other side ("even all-comers predicts 282 months …
 * feasibility would need ~510 sites").
 *
 * It would have been one constant to make this demo print a comfortable
 * number. That constant is not touched here. The caveat fires whenever the
 * penalty dominates, so the reader sees the model's limit instead of a
 * plausible month count. OWNER: Abhishek (this is the forecaster's own model).
 */
function crowdingCaveat(result: RecruitabilityResult): string[] {
  const competitors = result.evidence.competingTrials;
  const penalty = 1 / (1 + COMPETITION_SHARE * competitors);
  if (penalty >= CROWDING_PENALTY_ALARM) {
    return [];
  }
  return [
    `MODEL LIMIT REACHED — READ THE MONTH COUNT AS A FAILURE SIGNAL, NOT A FORECAST. ${competitors} trials are recruiting this population concurrently, and the competition model gives each one ${(COMPETITION_SHARE * PERCENT).toFixed(0)}% of the patient pool, which divides per-site velocity by ${(1 / penalty).toFixed(1)}×. At this crowding the share model is extrapolating far past anything it was calibrated on (${(COMPETITION_SHARE * competitors * PERCENT).toFixed(0)}% of the pool "claimed" in total), so ${result.simulatedMonthsToEnroll} months means "this design does not close in a crowded indication", not "this trial will take ${(result.simulatedMonthsToEnroll / MONTHS_PER_YEAR).toFixed(0)} years". Found by this pipeline run; the constant was deliberately NOT tuned to make the demo look better. Owner: the forecaster (Abhishek).`,
  ];
}

function forecasterEnvelope(
  thesis: IndicationThesis,
  step: StepResult<RecruitabilityResult>
): TraceEnvelope {
  const inputs = {
    digest: digest(thesis),
    humanSummary: `${thesis.asset.name} (${thesis.asset.modality}) ${thesis.target.direction}ing ${thesis.target.symbol} in ${thesis.disease.name}; enrolling ${thesis.biomarkerPopulation.marker}, assumed present in ${(thesis.biomarkerPopulation.prevalenceInDisease * PERCENT).toFixed(0)}% of patients.`,
    source: `station 2's thesis (${THESIS_PATH.replace(`${REPO_ROOT}/`, "")})`,
  };
  const runner =
    "assessRecruitability() in managed/trial-recruitment-forecaster/recruitability.ts";
  const result = step.value;
  if (!result) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "trial-recruitment-forecaster",
      reason: `${step.error ?? "unknown error"} (this station needs ANTHROPIC_API_KEY and network access to clinicaltrials.gov; without them the chain stops here rather than inventing a month count)`,
      runner,
    });
  }
  const labels: HonestyLabel[] = [
    {
      detail:
        "The field is literally named `simulatedMonthsToEnroll` in recruitability.ts — a model output, not an observed enrolment.",
      label: "SIMULATED",
      scope: "months to enrol, range, score and everything derived from them",
    },
    {
      detail:
        "The eligibility pass rate is Claude's judgement after reading real inclusion/exclusion prose (median of 3 samples). A calibrated estimate, not a measurement.",
      label: "ASSUMED",
      scope: "eligibility pass rate and the drivers list",
    },
    {
      detail:
        "The biomarker prevalence this forecast divides by is the analyst frame's assumed 0.6, not an epidemiological measurement (station 2's ASSUMED labels).",
      label: "ASSUMED",
      scope: "screening burden and therefore the month count itself",
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
  return envelope({
    caveats: [
      "Known limitation (NEXT.md): per-site velocity measured on small precedent pools does not transfer cleanly to 100+ site programmes.",
      result.counterfactual
        ? `Cheapest modelled rescue: ${result.counterfactual.change} (reaches "${result.counterfactual.achieves}", ${result.counterfactual.simulatedMonthsAfter} months). A what-if, not a plan.`
        : "The design already enrols inside the comfortable window, so no counterfactual rescue was searched.",
      `Precedent pool: ${result.evidence.precedentTrials.length} completed trials, ${result.evidence.competingTrials} currently-recruiting competitors.`,
      ...crowdingCaveat(result),
    ],
    dataSources: forecasterSources(result),
    decision: {
      honestyLabels: labels,
      keyNumbers: forecasterNumbers(result),
      summary: `Modelled at ${result.simulatedMonthsToEnroll} months to enrol ${result.requiredN} patients across ${result.sites} sites — recruitability ${result.score.toFixed(2)} of 1.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter: "managed/trial-recruitment-forecaster/economics-bridge.ts",
      payloadSummary: `simulatedMonthsToEnroll=${result.simulatedMonthsToEnroll}, range=[${result.simulatedMonthsRange.join(", ")}], score=${result.score.toFixed(2)}. Nothing else crosses — the NCT ids and eligibility drivers stay behind.`,
      toNode: "adapter-b (economics-bridge)",
    },
    inputs,
    node: "trial-recruitment-forecaster",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 6 — adapter B, months → launch delay.
// ---------------------------------------------------------------------------

type BridgeOutput = {
  basis: Record<string, string>;
  howToApply: Record<string, string>;
  pricing: Record<string, unknown>;
  simulatedLaunchDelayRangeYears: { high: number; low: number; mode: number };
  simulatedLaunchDelayYears: number;
  simulatedLaunchDelayYearsUnrounded: number;
  simulatedMonthsSavedByCounterfactual: number | null;
};

function runEconomicsBridge(savedResultPath: string): StepResult<BridgeOutput> {
  const step = run(
    "bun",
    [
      join(FORECASTER_DIR, "economics-bridge.ts"),
      "--from-json",
      savedResultPath,
      "--planned-months",
      PLANNED_MONTHS,
    ],
    REPO_ROOT
  );
  return step.value
    ? { ms: step.ms, value: JSON.parse(step.value) as BridgeOutput }
    : { error: step.error, ms: step.ms };
}

function bridgeEnvelope(
  step: StepResult<BridgeOutput>,
  upstream: RecruitabilityResult | undefined,
  savedResultPath: string
): TraceEnvelope {
  const inputs = {
    digest: upstream ? digest(upstream) : "n/a (upstream produced nothing)",
    humanSummary: upstream
      ? `Only the timing fields from station 5: ${upstream.simulatedMonthsToEnroll} months against a planned ${PLANNED_MONTHS}-month window.`
      : "Nothing — station 5 produced no result.",
    source: savedResultPath.replace(`${REPO_ROOT}/`, ""),
  };
  const runner = `bun managed/trial-recruitment-forecaster/economics-bridge.ts --from-json <saved> --planned-months ${PLANNED_MONTHS}`;
  const out = step.value;
  if (!out) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "adapter-b (economics-bridge)",
      reason: step.error ?? "station 5 produced nothing to convert",
      runner,
      status: upstream ? "degraded" : "skipped",
    });
  }
  const caveats = [
    "Two obvious-looking wirings are refused on purpose (documented in economics-bridge.ts): a recruitability score is NOT a probability of approval, and stage durations do NOT move the launch year.",
    "This adapter produces an INSTRUCTION, not an applied change: station 7 below is the untouched baseline, and the delay is priced by multiplying the engine's own per-year delay cost.",
  ];
  if (
    out.simulatedLaunchDelayYearsUnrounded > 0 &&
    out.simulatedLaunchDelayYears === 0
  ) {
    caveats.push(
      `ROUNDED AWAY: the forecast slips ${(out.simulatedLaunchDelayYearsUnrounded * MONTHS_PER_YEAR).toFixed(0)} months past the planned window, but whole-year rounding books that as 0 delay years and 0 dollars. The slip is real; the price of it is not being charged.`
    );
  }
  const { pricing } = out;
  const labels: HonestyLabel[] = [
    {
      detail:
        "Every field this adapter emits is named `simulated…`, because its only input is a simulated month count.",
      label: "SIMULATED",
      scope: "launch delay, its range, and the priced delay cost",
    },
  ];
  if (pricing.status === "ok") {
    labels.push({
      detail: String(pricing.pricedAgainst ?? ""),
      label: "SYNTHETIC",
      scope: "the dollar figures — priced against a fictitious programme",
    });
  }
  return envelope({
    caveats,
    dataSources: [
      {
        id: "SYNTHETIC-IRAK4-RA-001",
        kind: "synthetic",
        role: "The programme the delay is priced against — fictitious by construction",
      },
    ],
    decision: {
      honestyLabels: labels,
      keyNumbers: [
        {
          basis: out.basis.simulatedLaunchDelayYears ?? "",
          label: "Simulated launch delay",
          unit: "whole years",
          value: out.simulatedLaunchDelayYears,
        },
        {
          basis:
            "The same delay BEFORE whole-year rounding. Above zero while the rounded figure is zero means the delay was rounded away — a convention, not a finding that the delay is free.",
          label: "Launch delay before rounding",
          unit: "years",
          value: out.simulatedLaunchDelayYearsUnrounded,
        },
        {
          basis: out.basis.simulatedLaunchDelayRangeYears ?? "",
          label: "Delay range (low / mode / high)",
          unit: "whole years",
          value: `${out.simulatedLaunchDelayRangeYears.low} / ${out.simulatedLaunchDelayRangeYears.mode} / ${out.simulatedLaunchDelayRangeYears.high}`,
        },
      ],
      summary: `A ${out.simulatedLaunchDelayYears}-year launch delay is the only thing this adapter passes to the economics engine — the recruitment score itself is deliberately NOT passed on.`,
    },
    durationMs: step.ms,
    handoff: {
      adapter:
        "an analyst applies the overlay; no code re-runs the engine with it",
      payloadSummary:
        `${out.howToApply.launch_delay_years ?? ""} ${out.howToApply.launch_year ?? ""}`.trim(),
      toNode: "therapeutic-program-economics",
    },
    inputs,
    node: "adapter-b (economics-bridge)",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// STATION 7 — the economics engine, on the SYNTHETIC IRAK4/RA programme.
// ---------------------------------------------------------------------------

type EconomicsOutput = {
  decision_grade: string;
  engine_version: string;
  evidence_references: { grade: string; synthetic: boolean }[];
  input_digest: string;
  input_snapshot: {
    comparables: Record<
      string,
      {
        comparable_id: string;
        name: string;
        price: { amount: number; basis: string };
      }[]
    >;
  };
  recommendation: string;
  run_id: string;
  summary: Record<string, number | string | null>;
  warnings: { code: string; message: string; severity: string }[];
};

function runEconomics(): StepResult<EconomicsOutput> {
  const sync = run("uv", ["sync", "--frozen"], ECONOMICS_DIR);
  if (sync.error) {
    return { error: `uv sync failed: ${sync.error}`, ms: sync.ms };
  }
  const step = run(
    "uv",
    [
      "run",
      "labrador",
      "analyze",
      PROGRAM_PATH,
      "--comparables",
      COMPARABLES_PATH,
      "--simulations",
      SIMULATIONS,
      "--seed",
      SEED,
      "--compact",
    ],
    ECONOMICS_DIR
  );
  return step.value
    ? {
        ms: step.ms + sync.ms,
        value: JSON.parse(step.value) as EconomicsOutput,
      }
    : { error: step.error, ms: step.ms + sync.ms };
}

function economicsEnvelope(
  step: StepResult<EconomicsOutput>,
  delayYears: number | undefined
): TraceEnvelope {
  const inputs = {
    digest: step.value?.input_digest ?? "n/a (engine did not run)",
    humanSummary:
      "A SYNTHETIC IRAK4/RA programme and a SYNTHETIC RA comparables catalogue. Identity fields were relabelled for subject coherence; every NUMBER is inherited verbatim from the economics node's own fictitious demo fixture.",
    source: `${PROGRAM_PATH.replace(`${REPO_ROOT}/`, "")} + ${COMPARABLES_PATH.replace(`${REPO_ROOT}/`, "")}`,
  };
  const runner = `uv run labrador analyze <program> --comparables <comparables> --simulations ${SIMULATIONS} --seed ${SEED} --compact`;
  const out = step.value;
  if (!out) {
    return degraded({
      inputs,
      ms: step.ms,
      node: "therapeutic-program-economics",
      reason: step.error ?? "unknown error",
      runner,
    });
  }
  const synthetic = out.evidence_references.filter((e) => e.synthetic).length;
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
    "Every figure here is priced on invented inputs. The purpose of running it is to show the chain reaching money at all, and to expose the per-year delay cost that station 6's delay multiplies."
  );
  const perYear = Number(out.summary.value_lost_per_launch_delay_year ?? 0);
  const numbers: KeyNumber[] = [
    {
      basis: `Median risk-adjusted NPV across ${SIMULATIONS} draws. Engine ${out.engine_version}, run ${out.run_id}, digest ${out.input_digest}, seed ${SEED} — reproducible by re-running the command.`,
      label: "Median rNPV (P50)",
      unit: "USD",
      value: Number(out.summary.p50_rnpv ?? 0),
    },
    {
      basis:
        "10th and 90th percentile of the same draws — percentiles of a declared scenario model, NOT confidence intervals.",
      label: "rNPV range (P10 / P90)",
      unit: "USD",
      value: `${Number(out.summary.p10_rnpv ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })} / ${Number(out.summary.p90_rnpv ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
    },
    {
      basis:
        "The engine's own price of a one-year slip in launch — the rate station 6's delay multiplies.",
      label: "Value lost per year of launch delay",
      unit: "USD per year",
      value: perYear,
    },
    {
      basis:
        "Patent term from filing under the engine's simplified clock, after launch.",
      label: "Effective protected years",
      unit: "years",
      value: Number(out.summary.effective_protected_years ?? 0),
    },
  ];
  if (delayYears !== undefined) {
    numbers.push({
      basis: `${delayYears} delay years (station 6) × ${perYear.toLocaleString("en-US", { maximumFractionDigits: 0 })} USD/yr (this engine). Arithmetic done here, on two numbers that are each already labelled — the engine was NOT re-run with the delay applied.`,
      label: "Simulated cost of the recruitment delay",
      unit: "USD",
      value: Math.round(delayYears * perYear),
    });
  }
  return envelope({
    caveats,
    dataSources: [
      ...Object.values(out.input_snapshot.comparables)
        .flat()
        .map((c) => ({
          id: c.comparable_id,
          kind: "price_observation" as const,
          role: `${c.name}: ${c.price.amount.toLocaleString("en-US")} USD on a ${c.price.basis} basis — SYNTHETIC, inherited from the demo catalogue`,
        })),
      {
        id: String(out.summary.program_id ?? "SYNTHETIC-IRAK4-RA-001"),
        kind: "synthetic",
        role: `The programme being valued. ${synthetic} of ${out.evidence_references.length} evidence references are stamped SYNTHETIC by the engine itself.`,
      },
    ],
    decision: {
      honestyLabels: [
        {
          detail: `The engine stamped this run ${out.decision_grade}; its recommendation field reads ${out.recommendation}. That verdict is the engine's, not the glassbox's.`,
          label: "NOT_DECISION_GRADE",
          scope: "every dollar figure in this panel",
        },
        {
          detail: `${synthetic} of ${out.evidence_references.length} evidence references are graded SYNTHETIC. The programme, its population and its prices are fictitious; only their LABELS were changed to the IRAK4/RA subject.`,
          label: "SYNTHETIC",
          scope: "the programme, its prices and its population",
        },
        {
          detail:
            "Percentiles come from a declared scenario model at a fixed seed. Same seed, same numbers; different assumptions, different numbers.",
          label: "SIMULATED",
          scope: "P10 / P50 / P90 and the delay cost",
        },
      ],
      keyNumbers: numbers,
      summary: `On fictitious inputs the programme's median simulated value is ${Number(out.summary.p50_rnpv ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })} USD, and the engine refuses to call the result decision-grade.`,
    },
    durationMs: step.ms,
    handoff: null,
    inputs,
    node: "therapeutic-program-economics",
    startedAt: new Date(Date.now() - step.ms).toISOString(),
    status: "ok",
    version: { ...VERSION, runner },
  });
}

// ---------------------------------------------------------------------------
// The verdict: what this chain is, and what it is honestly not.
// ---------------------------------------------------------------------------

function headlineFor(envelopes: TraceEnvelope[], complete: boolean): string {
  const labels = new Set(
    envelopes.flatMap((e) => e.decision.honestyLabels.map((l) => l.label))
  );
  const failed = envelopes.filter((e) => e.status !== "ok");
  const money = envelopes
    .at(-1)
    ?.decision.keyNumbers.find((k) => k.label.startsWith("Median rNPV"));
  const ran = complete
    ? `All ${envelopes.length} stations ran: a real evidence graph became a hypothesis, the hypothesis became a validated IndicationThesis, the thesis was scored for recruitability against real ClinicalTrials.gov precedent, and the recruitment delay was priced.`
    : `The chain did NOT complete: ${failed.map((f) => f.node).join(", ")} degraded or was skipped. No number was substituted for a missing station.`;
  const modelLimit = envelopes.some((e) =>
    e.caveats.some((c) => c.startsWith("MODEL LIMIT REACHED"))
  )
    ? " AND ONE STATION HIT ITS OWN MODEL LIMIT: the recruitment forecast fired its crowding alarm, so its month count is a failure signal about the design, not a schedule — the panel says why, and no constant was tuned to hide it."
    : "";
  return `${ran}${modelLimit} WHAT IS NOT REAL HERE, station by station: the thesis's population and endpoint are ASSUMED by an analyst frame (a literature graph has no epidemiology); the tractability station is SUBJECT-MISMATCHED — both committed dossiers measure JAK1 and TNF, not IRAK4, so its rows are quarantined and enrich nothing; the economics station is SYNTHETIC and the engine stamps its own run NOT_DECISION_GRADE. Labels present in this chain: ${[...labels].sort().join(", ")}.${money ? ` Last number: ${money.label} = ${Number(money.value).toLocaleString("en-US", { maximumFractionDigits: 0 })} USD.` : ""}`;
}

// ---------------------------------------------------------------------------
// Main. Reads top to bottom like the pipeline it runs.
// ---------------------------------------------------------------------------

function progress(station: number, text: string): void {
  process.stderr.write(`[${station}/${STATION_COUNT}] ${text}\n`);
}

function report(step: { ms: number }, wrapped: TraceEnvelope): void {
  process.stderr.write(
    `      ${wrapped.status} in ${(step.ms / MS_PER_SECOND).toFixed(1)}s\n`
  );
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: { "skip-forecaster": { type: "boolean" } },
  });
  const envelopes: TraceEnvelope[] = [];

  progress(
    1,
    "hypothesis-generator — hyp_gen dry-run on the real graph g_1a4f…"
  );
  const hypGenStep = runHypGen();
  const hypGenWrapped = hypGenEnvelope(hypGenStep);
  envelopes.push(hypGenWrapped);
  report(hypGenStep, hypGenWrapped);

  progress(
    2,
    "adapter-d — slate hypothesis + analyst frame → IndicationThesis…"
  );
  const thesisStep = hypGenStep.value
    ? runThesisBridge()
    : { error: "station 1 produced no slate", ms: 0 };
  const thesisWrapped = thesisEnvelope(thesisStep);
  envelopes.push(thesisWrapped);
  report(thesisStep, thesisWrapped);
  const thesis = thesisStep.value?.thesis;

  progress(3, "adapter-a — the whole graph's findings → Evidence rows…");
  const evidenceStep = runEvidenceBridge();
  const evidenceWrapped = evidenceEnvelope(evidenceStep, thesis);
  envelopes.push(evidenceWrapped);
  report(evidenceStep, evidenceWrapped);

  progress(4, "adapter-c — tractability dossiers (JAK1, TNF) → Evidence rows…");
  const dossierStep = runDossierBridge();
  const dossierWrapped = tractabilityEnvelope(dossierStep);
  envelopes.push(dossierWrapped);
  report(dossierStep, dossierWrapped);

  progress(
    5,
    "trial-recruitment-forecaster — live CT.gov + Claude eligibility read…"
  );
  const forecastStep = await (async () => {
    if (!thesis) {
      return { error: "station 2 produced no thesis to score", ms: 0 };
    }
    if (values["skip-forecaster"]) {
      return { error: "--skip-forecaster was passed (no live run)", ms: 0 };
    }
    return await runForecaster(thesis);
  })();
  const savedResultPath = join(
    FIXTURES_DIR,
    `recruitability-${thesis?.id ?? "unknown"}.json`
  );
  if (forecastStep.value) {
    writeFileSync(
      savedResultPath,
      `${JSON.stringify(forecastStep.value, null, 2)}\n`
    );
  }
  const forecastWrapped = thesis
    ? forecasterEnvelope(thesis, forecastStep)
    : degraded({
        inputs: {
          digest: "n/a",
          humanSummary: "Nothing — station 2 produced no thesis.",
          source: "station 2",
        },
        ms: 0,
        node: "trial-recruitment-forecaster",
        reason: "no thesis to score",
        runner: "assessRecruitability()",
        status: "skipped",
      });
  envelopes.push(forecastWrapped);
  report(forecastStep, forecastWrapped);

  progress(6, "adapter-b — months → launch-delay overlay…");
  const bridgeStep = forecastStep.value
    ? runEconomicsBridge(savedResultPath)
    : { error: "station 5 produced no result to convert", ms: 0 };
  const bridgeWrapped = bridgeEnvelope(
    bridgeStep,
    forecastStep.value,
    savedResultPath
  );
  envelopes.push(bridgeWrapped);
  report(bridgeStep, bridgeWrapped);

  progress(7, "therapeutic-program-economics — SYNTHETIC IRAK4/RA programme…");
  const economicsStep = runEconomics();
  const economicsWrapped = economicsEnvelope(
    economicsStep,
    bridgeStep.value?.simulatedLaunchDelayYears
  );
  envelopes.push(economicsWrapped);
  report(economicsStep, economicsWrapped);

  const trace: Trace = {
    envelopes,
    generatedAt: new Date().toISOString(),
    run: {
      graph: GRAPH_PATH.replace(`${REPO_ROOT}/`, ""),
      hypothesis: DEFAULT_HYPOTHESIS,
      plannedMonths: PLANNED_MONTHS,
      profile: HYPGEN_PROFILE,
      seed: SEED,
      simulations: SIMULATIONS,
      subject: "IRAK4 inhibitor in rheumatoid arthritis",
    },
    traceVersion: "1.0",
    verdict: buildVerdict(envelopes, (complete) =>
      headlineFor(envelopes, complete)
    ),
  };
  const tracePath = join(FIXTURES_DIR, "pipeline-irak4-ra.trace.json");
  writeFileSync(tracePath, `${JSON.stringify(trace, null, 2)}\n`);
  process.stderr.write(`\nwrote ${tracePath.replace(`${REPO_ROOT}/`, "")}\n`);
  process.stderr.write(
    `${injectTrace(PIPELINE_HTML, trace, "pipeline.ts")}\n\n`
  );
  process.stdout.write(`${trace.verdict.headline}\n`);
  if (trace.verdict.status !== "complete") {
    process.exitCode = 1;
  }
}

await main();
