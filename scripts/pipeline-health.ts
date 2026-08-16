/**
 * pipeline-health.ts — the alarm that tells the team a seam broke.
 *
 *   bun run pipeline:health
 *
 * WHAT IT IS FOR. Six people are pushing into one repo through an
 * auto-integrator. The failures that hurt are not compile errors — those are
 * caught — but the ones where a node's artifact silently stops matching what
 * its consumer reads: a renamed field, a schema drift, a fixture that stops
 * validating, an evidence bridge that starts emitting zero rows. This suite
 * runs the deterministic half of the pipeline on every push and says PASS or
 * FAIL per seam, so that class of break is loud within a minute of landing.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. It never calls the Anthropic API and never
 * touches the network. `bun run pipeline` (the real chain) needs a key and
 * clinicaltrials.gov; this suite is what CI can run on every push, so it stops
 * at the last deterministic station. The live half is exercised by hand, and
 * the trace artifact from that run is committed.
 *
 * WHAT IT NEEDS: `bun`, `uv`, and `python3`. A missing tool is reported as a
 * FAIL against the check that needed it, not swallowed.
 *
 * Exit code 0 = every check passed. 1 = at least one failed, and the failing
 * check's own stderr is printed under it.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..");
const MAPPER = join(REPO_ROOT, "managed", "research-evidence-mapper");
const TRACTABILITY = join(
  REPO_ROOT,
  "managed",
  "small-molecule-tractability-review"
);
const FORECASTER = join(REPO_ROOT, "managed", "trial-recruitment-forecaster");
const OBSERVATORY = join(REPO_ROOT, "managed", "pipeline-observatory");
const HYPGEN = join(REPO_ROOT, "managed", "hypothesis-generator");
const GRAPH = join(MAPPER, "runs", "g_1a4f.json");
const DOSSIER_EXAMPLES = join(
  TRACTABILITY,
  ".claude",
  "skills",
  "assemble-dossier",
  "examples"
);

/**
 * The mapper's own bridge found 11 actionable rows in g_1a4f. A drop below 10
 * means the graph changed, the schema drifted, or the bridge started dropping
 * rows — all three are things the team must hear about immediately.
 */
const MIN_EVIDENCE_ROWS = 10;
const SUBPROCESS_TIMEOUT_MS = 600_000;
/** hyp_gen's dry-run tail line, e.g. "5 shortlisted. No model calls made." */
const SHORTLISTED_LINE = /(\d+) shortlisted/;

type Check = {
  detail: string;
  name: string;
  ok: boolean;
  output?: string;
};

function runCommand(
  cmd: string,
  args: string[],
  cwd: string
): { ok: boolean; out: string } {
  try {
    const out = execFileSync(cmd, args, {
      cwd,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      stdio: "pipe",
      timeout: SUBPROCESS_TIMEOUT_MS,
    });
    return { ok: true, out };
  } catch (err) {
    const e = err as { stderr?: string; stdout?: string; message?: string };
    return {
      ok: false,
      out: `${e.stdout ?? ""}${e.stderr ?? ""}${e.message ?? ""}`.trim(),
    };
  }
}

/** assemble.py's own selftest — the mapper's arithmetic, byte-stability included. */
function checkMapperSelftest(): Check {
  const script = join(
    MAPPER,
    ".claude",
    "skills",
    "graph-assembly",
    "assemble.py"
  );
  if (!existsSync(script)) {
    return {
      detail: `assemble.py not found at ${script.replace(`${REPO_ROOT}/`, "")}`,
      name: "mapper assemble.py --selftest",
      ok: false,
    };
  }
  const res = runCommand("python3", [script, "--selftest"], REPO_ROOT);
  const green = res.out.includes("SELFTEST: GREEN");
  return {
    detail: green
      ? "SELFTEST: GREEN (quote verification, dedupe, scoring, byte-identical output)"
      : "selftest did not report GREEN",
    name: "mapper assemble.py --selftest",
    ok: res.ok && green,
    output: green ? undefined : res.out,
  };
}

/** Both committed dossiers must still pass their own validator, unchanged. */
function checkDossierValidator(): Check {
  const script = join(
    TRACTABILITY,
    ".claude",
    "skills",
    "assemble-dossier",
    "validate_dossier.py"
  );
  const files = ["jak1_P23458.json", "tnf_P01375.json"].map((f) =>
    join(DOSSIER_EXAMPLES, f)
  );
  const missing = files.filter((f) => !existsSync(f));
  if (!existsSync(script) || missing.length > 0) {
    return {
      detail: `missing: ${[script, ...missing].filter((p) => !existsSync(p)).join(", ")}`,
      name: "validate_dossier.py on both examples",
      ok: false,
    };
  }
  const res = runCommand("python3", [script, ...files], REPO_ROOT);
  const clean = (res.out.match(/OK {2}0 violations/g) ?? []).length;
  return {
    detail: `${clean}/2 dossiers validate with 0 violations`,
    name: "validate_dossier.py on both examples",
    ok: res.ok && clean === 2,
    output: clean === 2 ? undefined : res.out,
  };
}

/** Adapter A against the real graph — the seam that broke first, historically. */
function checkEvidenceBridge(): Check {
  const res = runCommand(
    "bun",
    [join(FORECASTER, "evidence-bridge.ts"), GRAPH],
    REPO_ROOT
  );
  if (!res.ok) {
    return {
      detail: "evidence-bridge.ts exited non-zero",
      name: `evidence-bridge on g_1a4f (≥${MIN_EVIDENCE_ROWS} rows)`,
      ok: false,
      output: res.out,
    };
  }
  const parsed = JSON.parse(res.out) as {
    dropped: { total: number };
    evidence: unknown[];
  };
  const rows = parsed.evidence.length;
  return {
    detail: `${rows} evidence rows (${parsed.dropped.total} dropped, counted not silent)`,
    name: `evidence-bridge on g_1a4f (≥${MIN_EVIDENCE_ROWS} rows)`,
    ok: rows >= MIN_EVIDENCE_ROWS,
    output: rows >= MIN_EVIDENCE_ROWS ? undefined : res.out.slice(0, 2000),
  };
}

/** Adapter D on the committed slate: the thesis must still parse. */
function checkThesisBridge(): Check {
  const slate = join(OBSERVATORY, "fixtures", "hypgen-irak4-ra.slate.json");
  const frame = join(FORECASTER, "fixtures", "irak4-ra.frame.json");
  const res = runCommand(
    "bun",
    [
      join(FORECASTER, "thesis-bridge.ts"),
      slate,
      "--frame",
      frame,
      "--hypothesis",
      "H-g1",
    ],
    REPO_ROOT
  );
  if (!res.ok) {
    return {
      detail:
        "thesis-bridge.ts exited non-zero (a thesis that fails IndicationThesis.parse is never printed)",
      name: "thesis-bridge on the committed slate",
      ok: false,
      output: res.out,
    };
  }
  const parsed = JSON.parse(res.out) as {
    assumed: unknown[];
    thesis: { evidence: unknown[]; id: string; target: { symbol: string } };
  };
  const ok =
    parsed.thesis.id === "H-g1" &&
    parsed.thesis.target.symbol === "IRAK4" &&
    parsed.thesis.evidence.length > 0;
  return {
    detail: `thesis ${parsed.thesis.id} → ${parsed.thesis.target.symbol}, ${parsed.thesis.evidence.length} evidence rows, ${parsed.assumed.length} ASSUMED fields`,
    name: "thesis-bridge on the committed slate",
    ok,
    output: ok ? undefined : res.out.slice(0, 2000),
  };
}

/** Adapter C: the JAK1 dossier must convert, and must NOT claim to be IRAK4. */
function checkDossierBridge(): Check {
  const res = runCommand(
    "bun",
    [
      join(FORECASTER, "dossier-bridge.ts"),
      join(DOSSIER_EXAMPLES, "jak1_P23458.json"),
      "--thesis-symbol",
      "IRAK4",
      "--thesis-accession",
      "Q9NWZ3",
    ],
    REPO_ROOT
  );
  if (!res.ok) {
    return {
      detail: "dossier-bridge.ts exited non-zero",
      name: "dossier-bridge on JAK1 (subjectMatch must be false)",
      ok: false,
      output: res.out,
    };
  }
  const parsed = JSON.parse(res.out) as {
    evidence: { sourceType: string }[];
    subjectMatch: { matches: boolean };
  };
  // A `true` here would mean the mismatch guard broke — the one failure that
  // would let another protein's verdict enter an IRAK4 thesis unannounced.
  const ok =
    parsed.evidence.length >= 1 && parsed.subjectMatch.matches === false;
  return {
    detail: `${parsed.evidence.length} rows (${parsed.evidence.map((e) => e.sourceType).join(", ")}), subjectMatch=false as required`,
    name: "dossier-bridge on JAK1 (subjectMatch must be false)",
    ok,
    output: ok ? undefined : res.out.slice(0, 2000),
  };
}

/** hyp_gen must still enumerate the same graph structurally, with no key. */
function checkHypGen(): Check {
  const res = runCommand(
    "uv",
    [
      "run",
      "python",
      "-m",
      "hyp_gen.cli",
      "--graph",
      GRAPH,
      "--profile",
      "default",
      "--dry-run",
    ],
    HYPGEN
  );
  const match = res.out.match(SHORTLISTED_LINE);
  const shortlisted = match ? Number(match[1]) : 0;
  return {
    detail: res.ok
      ? `${shortlisted} hypotheses shortlisted, no model calls`
      : "hyp_gen dry-run failed",
    name: "hyp_gen structural dry-run on g_1a4f (≥1 shortlisted)",
    ok: res.ok && shortlisted >= 1,
    output: res.ok && shortlisted >= 1 ? undefined : res.out.slice(-2000),
  };
}

/** The committed trace must still exist and still be a complete 7-station run. */
function checkCommittedTrace(): Check {
  const path = join(OBSERVATORY, "fixtures", "pipeline-irak4-ra.trace.json");
  if (!existsSync(path)) {
    return {
      detail: "no committed pipeline trace — run `bun run pipeline`",
      name: "committed pipeline trace is a complete run",
      ok: false,
    };
  }
  const trace = JSON.parse(readFileSync(path, "utf8")) as {
    envelopes: { node: string; status: string }[];
    verdict: { honestyLabels: { label: string }[]; status: string };
  };
  const labels = new Set(trace.verdict.honestyLabels.map((l) => l.label));
  // The honesty labels are load-bearing: a trace that lost SUBJECT_MISMATCH or
  // SYNTHETIC would be claiming more than the run earned.
  const ok =
    trace.verdict.status === "complete" &&
    trace.envelopes.length >= 7 &&
    labels.has("SUBJECT_MISMATCH") &&
    labels.has("SYNTHETIC") &&
    labels.has("ASSUMED");
  return {
    detail: `${trace.envelopes.length} stations, verdict ${trace.verdict.status}, labels: ${[...labels].sort().join(", ")}`,
    name: "committed pipeline trace is a complete run",
    ok,
  };
}

function main(): void {
  const checks: Check[] = [
    checkMapperSelftest(),
    checkDossierValidator(),
    checkEvidenceBridge(),
    checkThesisBridge(),
    checkDossierBridge(),
    checkHypGen(),
    checkCommittedTrace(),
  ];
  process.stdout.write(
    "LABrador pipeline health — deterministic seams only (no API key, no network)\n\n"
  );
  for (const check of checks) {
    process.stdout.write(
      `${check.ok ? "PASS" : "FAIL"}  ${check.name}\n      ${check.detail}\n`
    );
    if (!check.ok && check.output) {
      process.stdout.write(
        `${check.output
          .split("\n")
          .map((l) => `      | ${l}`)
          .join("\n")}\n`
      );
    }
  }
  const failed = checks.filter((c) => !c.ok);
  process.stdout.write(
    `\n${checks.length - failed.length}/${checks.length} checks passed.\n`
  );
  if (failed.length > 0) {
    process.stdout.write(
      `FAILING SEAMS: ${failed.map((f) => f.name).join("; ")}\n`
    );
    process.exitCode = 1;
  }
}

main();
