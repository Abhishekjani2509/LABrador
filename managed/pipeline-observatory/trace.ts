/**
 * trace.ts — the trace envelope, and the small machinery every runner shares.
 *
 * Extracted from trace-demo.ts when a SECOND runner (pipeline.ts) needed the
 * same envelope. It is deliberately a move, not a rewrite: the types and the
 * helpers are the ones trace-demo.ts has been emitting all along, so a trace
 * written by either runner is the same shape and the observatory page renders
 * both without knowing which produced it.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE (repo-wide, non-negotiable): the
 * glassbox never upgrades a number's status. A node that says SIMULATED stays
 * SIMULATED downstream; an engine that stamps its own run NOT_DECISION_GRADE
 * keeps that stamp. There is no code path here that removes an honesty label —
 * `collectHonestyLabels` only ever unions them.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
/** Repo root, resolved from this file so runners work from any cwd. */
export const REPO_ROOT = join(HERE, "..", "..");

/** What kind of identifier a reader can go check for themselves. */
export type DataSourceKind =
  | "doi"
  | "nct"
  | "price_observation"
  | "structure"
  | "synthetic";

export type DataSource = {
  /** The checkable id itself: "NCT03633617", "10.1038/…", "CHEMBL2835". */
  id: string;
  kind: DataSourceKind;
  /** Plain language: what this record was USED FOR in this node. */
  role: string;
};

export type KeyNumber = {
  /** Verbatim from the node where the node emits one — never paraphrased. */
  basis: string;
  label: string;
  unit: string;
  value: number | string;
};

/** The vocabulary of honesty. Nothing here is ever removed downstream. */
export type HonestyLabelName =
  | "ASSUMED"
  | "DEGRADED"
  | "INSUFFICIENT_EVIDENCE"
  | "NOT_DECISION_GRADE"
  | "SIMULATED"
  | "SUBJECT_MISMATCH"
  | "SYNTHETIC";

export type HonestyLabel = {
  /** Where the label came from — file, field, or the engine's own output. */
  detail: string;
  label: HonestyLabelName;
  /** Which numbers in this envelope the label applies to. */
  scope: string;
};

export type Handoff = {
  /** The file that does the translation, so the seam is auditable. */
  adapter: string;
  /** Plain language: exactly what crossed the boundary. */
  payloadSummary: string;
  toNode: string;
};

export type TraceEnvelope = {
  /** Known limitations a reader should carry forward. Never empty-by-lazy. */
  caveats: string[];
  dataSources: DataSource[];
  decision: {
    honestyLabels: HonestyLabel[];
    keyNumbers: KeyNumber[];
    /** One plain sentence a non-specialist can read out loud. */
    summary: string;
  };
  durationMs: number;
  inputs: {
    /** sha256 over canonicalised JSON — proves two runs saw the same input. */
    digest: string;
    humanSummary: string;
    /** Where the input came from (file path, upstream node, CLI flag). */
    source: string;
  };
  node: string;
  startedAt: string;
  /** ok = ran; degraded = ran but something was missing; skipped = never ran. */
  status: "degraded" | "ok" | "skipped";
  version: {
    commit: string;
    /** true = the working tree had uncommitted edits when this ran. */
    dirty: boolean;
    /** The exact command or entry point that produced this envelope. */
    runner: string;
  };
  /** null on the terminal node — nothing was handed on. */
  handoff: Handoff | null;
};

export type Verdict = {
  /** Node-by-node ancestry of the final number, oldest first. */
  ancestry: { node: string; status: string; summary: string }[];
  /** The end statement, in plain language. */
  headline: string;
  /** Every honesty label anywhere in the chain, deduplicated. */
  honestyLabels: HonestyLabel[];
  /** Whether the chain completed, and what it means if it did not. */
  status: "complete" | "incomplete";
};

export type Trace = {
  envelopes: TraceEnvelope[];
  generatedAt: string;
  run: Record<string, string>;
  traceVersion: string;
  verdict: Verdict;
};

/** The result of one attempted station: a value, or the error and how long. */
export type StepResult<T> = { error?: string; ms: number; value?: T };

/** Recursively sort object keys, so the same data always digests the same. */
export function canonical(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonical);
  }
  if (value && typeof value === "object") {
    const source = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) {
      out[key] = canonical(source[key]);
    }
    return out;
  }
  return value;
}

/**
 * A short fingerprint of an input payload. A reader who re-runs the pipeline
 * can compare digests to prove two runs really did start from the same data,
 * without reading (or being shown) the payload itself.
 */
export function digest(value: unknown): string {
  const json = JSON.stringify(canonical(value));
  return `sha256:${createHash("sha256").update(json).digest("hex").slice(0, 16)}`;
}

/** Which commit produced this trace, and whether the tree was clean. */
function gitVersion(): { commit: string; dirty: boolean } {
  try {
    const commit = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    }).trim();
    const status = execFileSync("git", ["status", "--porcelain"], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    }).trim();
    return { commit, dirty: status.length > 0 };
  } catch {
    return { commit: "unknown (git unavailable)", dirty: true };
  }
}

export const VERSION = gitVersion();

/** Fill in the boilerplate every envelope shares. */
export function envelope(
  parts: Omit<TraceEnvelope, "version"> & { version?: TraceEnvelope["version"] }
): TraceEnvelope {
  return { ...parts, version: parts.version ?? { ...VERSION, runner: "" } };
}

/** First line of an error, which is the part a human actually reads. */
export function firstLine(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err);
  return text.split("\n")[0] ?? text;
}

/** Cap a list of ids and say plainly how many were left out. */
export function capped(ids: string[], max: number): string[] {
  if (ids.length <= max) {
    return ids;
  }
  const shown = ids.slice(0, max);
  return [...shown, `…and ${ids.length - shown.length} more`];
}

/** Union of every honesty label in the chain, in first-seen order. */
export function collectHonestyLabels(
  envelopes: TraceEnvelope[]
): HonestyLabel[] {
  const seen = new Set<string>();
  const out: HonestyLabel[] = [];
  for (const env of envelopes) {
    for (const label of env.decision.honestyLabels) {
      const key = `${label.label}::${label.scope}`;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(label);
      }
    }
  }
  return out;
}

/**
 * The terminal verdict. The HEADLINE is the caller's, because only the caller
 * knows what its chain was trying to say; everything else — ancestry, the
 * label union, and whether the chain completed — is mechanical.
 */
export function buildVerdict(
  envelopes: TraceEnvelope[],
  headline: (complete: boolean) => string
): Verdict {
  const complete = envelopes.every((e) => e.status === "ok");
  return {
    ancestry: envelopes.map((e) => ({
      node: e.node,
      status: e.status,
      summary: e.decision.summary,
    })),
    headline: headline(complete),
    honestyLabels: collectHonestyLabels(envelopes),
    status: complete ? "complete" : "incomplete",
  };
}

/**
 * The block in a rendered page that holds the trace. Declared at module level
 * because the linter (rightly) wants regexes compiled once, not per call.
 */
const TRACE_BLOCK = /<!-- TRACE-JSON:BEGIN[\s\S]*?<!-- TRACE-JSON:END -->/;
/** `<` inside a <script> block would end the block early; escape it. */
const LT = /</g;

/**
 * Keep the page and the artifact in lockstep: the trace is injected between
 * two marker comments, so a rendered page can never show numbers that are not
 * in the saved JSON.
 */
export function injectTrace(
  htmlPath: string,
  trace: Trace,
  writtenBy: string
): string {
  if (!existsSync(htmlPath)) {
    return `${htmlPath} not found — skipped injection`;
  }
  const html = readFileSync(htmlPath, "utf8");
  if (!TRACE_BLOCK.test(html)) {
    return `${htmlPath} has no TRACE-JSON markers — skipped injection`;
  }
  const safe = JSON.stringify(trace, null, 2).replace(LT, "\\u003c");
  const block = `<!-- TRACE-JSON:BEGIN (regenerated by ${writtenBy} — do not hand-edit) -->\n<script id="trace-data" type="application/json">\n${safe}\n</script>\n<!-- TRACE-JSON:END -->`;
  writeFileSync(
    htmlPath,
    html.replace(TRACE_BLOCK, () => block)
  );
  return `${htmlPath.replace(`${REPO_ROOT}/`, "")} updated with this run's trace`;
}
