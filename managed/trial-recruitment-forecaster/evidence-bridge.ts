/**
 * Adapter A (COORDINATION.md §5): research-evidence-mapper `findings[]` →
 * `IndicationThesis.evidence[]`.
 *
 * Reads ONE research-evidence-mapper graph JSON (the full-graph object the
 * mapper returns, e.g. `managed/research-evidence-mapper/runs/g_1a4f.json`)
 * and emits rows that are valid under the `Evidence` zod schema in
 * `thesis.ts`. Read-only against Soliman's directory — this script never
 * writes into `managed/research-evidence-mapper/`.
 *
 *   bun managed/trial-recruitment-forecaster/evidence-bridge.ts \
 *     managed/research-evidence-mapper/runs/g_1a4f.json
 *
 * Output: `{ evidence, dropped, provenance }` on stdout. Every row in
 * `evidence` has been through `Evidence.parse` before printing — a row that
 * fails validation is dropped and counted, never emitted.
 *
 * FEED IT THE FULL GRAPH, NOT THE PER-ROUND CHUNKS. SCHEMA.md says findings
 * chunk by round and "rounds append, never rewrite", but in the real g_1a4f
 * artifact `findings/r2.json` is a full snapshot that repeats every r1 row
 * (f1…f7) alongside the new ones. Concatenating the chunks double-counts.
 * This bridge dedupes on finding id defensively and reports the collisions,
 * but the full graph is the supported input.
 *
 * ── Mapping rules ────────────────────────────────────────────────────────
 *
 * claim  = the finding's VERBATIM `quote` plus its from/how/to triple,
 *          rendered compactly, plus a `[<graph_id>#<finding_id>]` tag:
 *
 *            IRAK4 inhibition -[suppresses]-> synovial fibroblast driven
 *            inflammation | "…exact sentence…" [g_1a4f#n_f2]
 *
 *          The quote is the inspectability payload and is copied
 *          character-for-character — the mapper string-matches it against the
 *          fetched source (SCHEMA.md, "What Stage 1 guarantees"), so it is the
 *          one part of a finding a reader can check. It is never paraphrased
 *          away, and never replaced by the finding's own `claim` field: that
 *          field is an undocumented model paraphrase (see schema deviations
 *          below), and a paraphrase is exactly what this row must not carry.
 *          The id tag exists because these rows get embedded in an
 *          `IndicationThesis` where the `provenance` envelope below no longer
 *          travels with them; each row must be able to name its own source row.
 *
 * direction = `says` verbatim: yes → supports, no → contradicts,
 *          no_effect → no_effect. `no_effect` is NEVER collapsed into
 *          `contradicts` — thesis.ts §6 item 3 added the third value for
 *          precisely this mapping, because a null result and evidence-against
 *          are different facts.
 *
 * source = the finding's paper's DOI (preferred) as `doi:<doi>`, else its
 *          PMID as `PMID:<pmid>`. thesis.ts requires `source` to be a real
 *          identifier; a finding whose paper carries neither is DROPPED and
 *          counted with reason `no_source_identifier`. Unsourced claims are
 *          unrepresentable in `Evidence` by design, so silently emitting one
 *          with a placeholder would defeat the type.
 *
 * sourceType = "publication", always. Every mapper finding comes from a paper.
 *
 * strength = clamp01(STUDY_QUALITY[paper.study_type] × (is_preprint ? 0.8 : 1))
 *
 *          STUDY_QUALITY mirrors the mapper's own evidence-quality scale
 *          exactly — meta_analysis 1.0, clinical_trial 0.9, human_cohort 0.8,
 *          animal 0.6, test_tube 0.5, computational 0.4, review 0.3, unknown
 *          0.4 — and so does the ×0.8 preprint discount. NOTE for the record:
 *          SCHEMA.md names the field (`links.confidence.evidence_quality`,
 *          "study strength, from study_type") and the study_type vocabulary,
 *          but the NUMBERS live only in
 *          `managed/research-evidence-mapper/.claude/skills/graph-assembly/assemble.py:199`
 *          (`_STUDY_QUALITY`) and `:211` (`evidence_quality`, "Mean of the
 *          study-type table, x0.8 for preprints"). An unknown study_type
 *          scores 0.4 rather than fuzzy-matching a near name, same as there.
 *          Per-finding, so no averaging: at n=1 this IS the mapper's number.
 *
 *          Deliberately NOT folded in: `findings.confidence`. SCHEMA.md note 3
 *          says it is the model's self-reported read-accuracy, while
 *          everything under `links.confidence` is arithmetic — mixing a
 *          self-report into `strength` would make the number unreproducible
 *          from findings + papers. OPEN QUESTION for Soliman: whether a
 *          `hedged: true` finding inside a `mixed` link should take a
 *          discount. It survives at full study-type strength today; inventing
 *          a multiplier the mapper does not define would be worse than saying
 *          this out loud.
 *
 * ── Exclusions (all counted in `dropped`, never silent) ──────────────────
 *
 *  - basis `background_only` or `hedged_only` → non-actionable. Mirrors
 *    Rafal's graph-intake, the other real consumer of this schema:
 *    `managed/small-molecule-tractability-review/.claude/skills/graph-intake/graph_read.py:31`
 *    (`NON_ACTIONABLE_BASIS`) and its SKILL.md:110-111 ("record it, do not act
 *    on it"). Two consumers of one upstream must not disagree about which
 *    rows are actionable. `basis` is a LINK property, so a finding's basis is
 *    read off the link that cites it; an orphan finding (cited by no link —
 *    f6 in the real graph) gets its basis derived the way assemble.py's
 *    `link_basis` would for a one-finding link: not `is_own_result` →
 *    background_only, else `hedged` → hedged_only, else primary.
 *  - `retracted: true` paper → dropped. thesis.ts `Evidence` has nowhere to
 *    carry the retraction, and a retracted claim entering a thesis as ordinary
 *    evidence is a worse failure than a missing row. Reported with the id, so
 *    the drop is inspectable.
 *  - paper id that resolves to no row in `papers[]`, duplicate finding ids,
 *    and any row `Evidence.parse` rejects.
 */
import { readFileSync } from "node:fs";
import { z } from "zod";
import { Evidence } from "./thesis.ts";

/**
 * Mirrors `_STUDY_QUALITY` in the mapper's assemble.py. Keys are exactly the
 * `papers.study_type` vocabulary; anything else scores UNKNOWN_QUALITY.
 */
const STUDY_QUALITY: Record<string, number> = {
  animal: 0.6,
  clinical_trial: 0.9,
  computational: 0.4,
  human_cohort: 0.8,
  meta_analysis: 1.0,
  review: 0.3,
  test_tube: 0.5,
  unknown: 0.4,
};
const UNKNOWN_QUALITY = 0.4;
const PREPRINT_DISCOUNT = 0.8;
const ROUND_4 = 10_000;
const NON_ACTIONABLE_BASIS = new Set(["background_only", "hedged_only"]);
const DIRECTION_BY_SAYS = {
  no: "contradicts",
  no_effect: "no_effect",
  yes: "supports",
} as const;

/**
 * Tolerant on purpose: only the fields this bridge actually reads are
 * required. Fields SCHEMA.md promises but the real artifact omits are
 * reported as `provenance.schemaDeviations` rather than failing the parse —
 * a graph that does not match its own contract is a finding for its owner,
 * not a crash.
 */
const GraphPaper = z.object({
  doi: z.string().optional(),
  flags: z.array(z.string()).optional(),
  id: z.string(),
  is_preprint: z.boolean().optional(),
  pmid: z.string().optional(),
  retracted: z.boolean().optional(),
  round: z.number().optional(),
  study_type: z.string().optional(),
});
const GraphFinding = z.object({
  flags: z.array(z.string()).optional(),
  from: z.string(),
  hedged: z.boolean().optional(),
  how: z.string(),
  id: z.string(),
  is_own_result: z.boolean().optional(),
  paper: z.string(),
  quote: z.string(),
  round: z.number().optional(),
  says: z.enum(["yes", "no", "no_effect"]),
  to: z.string(),
});
const GraphLink = z.object({
  basis: z.string().optional(),
  id: z.string(),
  no: z.array(z.string()).default([]),
  no_effect: z.array(z.string()).default([]),
  yes: z.array(z.string()).default([]),
});
const Graph = z.object({
  findings: z.array(GraphFinding).default([]),
  generated_at: z.string().optional(),
  graph_id: z.string(),
  links: z.array(GraphLink).default([]),
  papers: z.array(GraphPaper).default([]),
  round: z.number().optional(),
  schema_version: z.string().optional(),
  status: z.string().optional(),
  things: z.array(z.object({ id: z.string(), name: z.string() })).default([]),
});
type GraphT = z.infer<typeof Graph>;
type FindingT = z.infer<typeof GraphFinding>;
type PaperT = z.infer<typeof GraphPaper>;

type DropReason =
  | "duplicate_finding_id"
  | "no_source_identifier"
  | "non_actionable_basis"
  | "retracted_paper"
  | "schema_validation_failed"
  | "unresolved_paper";

type DroppedRow = {
  detail: string;
  findingId: string;
  paperId: string;
  reason: DropReason;
};

function usage(): never {
  process.stderr.write(
    "usage: bun evidence-bridge.ts <graph.json>\n  e.g. managed/research-evidence-mapper/runs/g_1a4f.json (the FULL graph, not findings/rN.json)\n"
  );
  process.exit(1);
}

/** `basis` lives on links, so find the link that cites this finding. */
function basisOf(finding: FindingT, graph: GraphT): string {
  const link = graph.links.find(
    (l) =>
      l.yes.includes(finding.id) ||
      l.no.includes(finding.id) ||
      l.no_effect.includes(finding.id)
  );
  if (link?.basis) {
    return link.basis;
  }
  // Orphan finding: derive as assemble.py's link_basis would for n=1.
  if (finding.is_own_result === false) {
    return "background_only";
  }
  return finding.hedged ? "hedged_only" : "primary";
}

function strengthOf(paper: PaperT): number {
  const base = STUDY_QUALITY[paper.study_type ?? "unknown"] ?? UNKNOWN_QUALITY;
  const scaled = paper.is_preprint ? base * PREPRINT_DISCOUNT : base;
  // 4 decimals, the same rounding assemble.py applies to evidence_quality —
  // without it 0.8 x 0.8 prints as 0.6400000000000001.
  return Math.round(Math.min(1, Math.max(0, scaled)) * ROUND_4) / ROUND_4;
}

function sourceOf(paper: PaperT): string | undefined {
  if (paper.doi) {
    return `doi:${paper.doi}`;
  }
  return paper.pmid ? `PMID:${paper.pmid}` : undefined;
}

function claimOf(finding: FindingT, graph: GraphT): string {
  const name = (id: string) =>
    graph.things.find((t) => t.id === id)?.name ?? id;
  const triple = `${name(finding.from)} -[${finding.how}]-> ${name(finding.to)}`;
  return `${triple} | "${finding.quote}" [${graph.graph_id}#${finding.id}]`;
}

/** One finding → one Evidence row, or one drop reason. */
function convert(
  finding: FindingT,
  graph: GraphT
): { drop: DroppedRow } | { row: Evidence } {
  const drop = (reason: DropReason, detail: string) => ({
    drop: { detail, findingId: finding.id, paperId: finding.paper, reason },
  });
  const paper = graph.papers.find((p) => p.id === finding.paper);
  if (!paper) {
    return drop(
      "unresolved_paper",
      `paper id ${finding.paper} is in no row of papers[]`
    );
  }
  if (paper.retracted) {
    return drop("retracted_paper", `paper ${paper.id} is marked retracted`);
  }
  const basis = basisOf(finding, graph);
  if (NON_ACTIONABLE_BASIS.has(basis)) {
    return drop(
      "non_actionable_basis",
      `basis ${basis} (non-actionable, per graph_read.py:31)`
    );
  }
  const source = sourceOf(paper);
  if (!source) {
    return drop(
      "no_source_identifier",
      `paper ${paper.id} has neither doi nor pmid`
    );
  }
  const parsed = Evidence.safeParse({
    claim: claimOf(finding, graph),
    direction: DIRECTION_BY_SAYS[finding.says],
    source,
    sourceType: "publication",
    strength: strengthOf(paper),
  });
  if (!parsed.success) {
    return drop(
      "schema_validation_failed",
      parsed.error.issues
        .map((i) => `${i.path.join(".")}: ${i.message}`)
        .join("; ")
    );
  }
  return { row: parsed.data };
}

function convertAll(graph: GraphT) {
  const evidence: Evidence[] = [];
  const rows: DroppedRow[] = [];
  const seen = new Set<string>();
  for (const finding of graph.findings) {
    if (seen.has(finding.id)) {
      rows.push({
        detail: "finding id already converted in this run (chunk overlap?)",
        findingId: finding.id,
        paperId: finding.paper,
        reason: "duplicate_finding_id",
      });
      continue;
    }
    seen.add(finding.id);
    const out = convert(finding, graph);
    if ("row" in out) {
      evidence.push(out.row);
    } else {
      rows.push(out.drop);
    }
  }
  return { evidence, rows };
}

function summarize(rows: DroppedRow[]) {
  const byReason: Record<string, number> = {};
  for (const r of rows) {
    byReason[r.reason] = (byReason[r.reason] ?? 0) + 1;
  }
  return { byReason, rows, total: rows.length };
}

/**
 * Fields SCHEMA.md promises that the graph does not carry, and fields it
 * carries that SCHEMA.md does not define. Reported, never repaired.
 */
function schemaDeviations(graph: GraphT, raw: unknown): string[] {
  const out: string[] = [];
  const rawGraph = raw as { findings?: Record<string, unknown>[] };
  const missing = (label: string, n: number, total: number) => {
    if (n > 0) {
      out.push(`${n}/${total} ${label}`);
    }
  };
  const f = graph.findings;
  missing(
    "findings lack `round` (SCHEMA.md findings row)",
    f.filter((x) => x.round === undefined).length,
    f.length
  );
  missing(
    "findings lack `flags` (SCHEMA.md findings row)",
    f.filter((x) => x.flags === undefined).length,
    f.length
  );
  missing(
    "papers lack `round` (SCHEMA.md papers row)",
    graph.papers.filter((x) => x.round === undefined).length,
    graph.papers.length
  );
  const undocumented = (rawGraph.findings ?? []).filter(
    (x) => "claim" in x
  ).length;
  missing(
    "findings carry an undocumented `claim` field (a paraphrase; the bridge uses `quote` instead)",
    undocumented,
    f.length
  );
  const orphans = f.filter(
    (x) =>
      !graph.links.some((l) =>
        [...l.yes, ...l.no, ...l.no_effect].includes(x.id)
      )
  );
  missing(
    `findings are cited by no link, so basis was derived (${orphans.map((o) => o.id).join(", ")})`,
    orphans.length,
    f.length
  );
  return out;
}

function main() {
  const [, , graphPath] = process.argv;
  if (!graphPath) {
    usage();
  }
  const rawJson: unknown = JSON.parse(readFileSync(graphPath, "utf8"));
  const parsed = Graph.parse(rawJson);
  const { evidence, rows } = convertAll(parsed);
  process.stdout.write(
    `${JSON.stringify(
      {
        dropped: summarize(rows),
        evidence,
        provenance: {
          generatedAt: parsed.generated_at ?? null,
          graphId: parsed.graph_id,
          round: parsed.round ?? null,
          schemaDeviations: schemaDeviations(parsed, rawJson),
          schemaVersion: parsed.schema_version ?? null,
          source: graphPath,
          status: parsed.status ?? null,
          strengthFormula:
            "clamp01(STUDY_QUALITY[study_type] * (is_preprint ? 0.8 : 1)); table mirrors assemble.py:199",
        },
      },
      null,
      2
    )}\n`
  );
}

main();
