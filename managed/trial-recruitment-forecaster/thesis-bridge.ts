/**
 * Adapter D (COORDINATION.md §11 row 6): hypothesis-generator `slate.json` →
 * `IndicationThesis`.
 *
 * This is the pipeline's MISSING ENTRY POINT. Today hyp_gen joins the economics
 * node directly through its own `valuation.py`, skipping recruitability
 * entirely (COORDINATION §3, "⚠️ Integration notes"). This bridge gives the
 * thesis-based chain a front door: a slate hypothesis becomes an
 * `IndicationThesis` that the forecaster, the tractability node and
 * economics-bridge all already consume.
 *
 *   bun managed/trial-recruitment-forecaster/thesis-bridge.ts <slate.json> \
 *     --frame managed/trial-recruitment-forecaster/fixtures/irak4-ra.frame.json \
 *     [--hypothesis H-g1] [--out thesis.json]
 *
 * Read-only against `managed/hypothesis-generator/` — this script never writes
 * into Abraham's directory, and it imports nothing from it. It reads the slate
 * as data, exactly as evidence-bridge.ts reads Soliman's graphs.
 *
 * ── WHY A FRAME IS MANDATORY ─────────────────────────────────────────────
 *
 * `IndicationThesis` requires `biomarkerPopulation{marker,
 * prevalenceInDisease, assayAvailable}` and `endpoint{name, type}`. A
 * literature graph contains none of those: no epidemiology, no assay
 * availability, no endpoint, no effect size. hyp_gen's own valuation adapter
 * reached the same conclusion and refuses to guess its four year fields
 * (`valuation.ProgramFrame.template`, "a guessed filing_year looks exactly
 * like one they sourced once it is in the file"). This bridge follows that
 * precedent exactly: the analyst supplies those fields in a frame file, and
 * every frame-supplied value comes back out in `assumed[]` labelled ASSUMED,
 * so the honesty label travels with the number instead of being lost at the
 * seam.
 *
 * ── MAPPING ──────────────────────────────────────────────────────────────
 *
 * asset.name      = `subject_name` verbatim. NOT prettified: the real graph's
 *                   subject is literally named "IRAK4 inhibition", and
 *                   rewriting it to "PF-06650833" would be the bridge choosing
 *                   which of three aliases is the asset. The aliases are
 *                   reported in provenance instead.
 * asset.modality  = `evidence.things[subject].kind`: `small_molecule` →
 *                   small_molecule, everything else → `other`. A graph
 *                   `protein` node is almost always a TARGET, not a peptide
 *                   drug — the same trap valuation.py:407 documents.
 * disease.name    = `object_name`, UNLESS the frame supplies
 *                   `diseaseNameOverride`. On g_1a4f the override is
 *                   unavoidable: the graph has no `disease` entity, so every
 *                   object_name is a process. The override is reported with
 *                   the graph's own question quoted verbatim, so a reader can
 *                   check the substitution against the thing the search asked.
 * target.symbol   = the first interior path node whose thing kind is `protein`
 *                   or `gene` (same rule as valuation.py:428). g_1a4f has no
 *                   such node — the real graph carries no protein/gene entities
 *                   at all, the wall Rafal's graph-intake hit (COORDINATION §3)
 *                   — so the frame's `targetSymbolOverride` is the fallback.
 *                   `uniprotAccession` is frame-only: a graph thing that
 *                   carries `uniprot_accession` (mapper's newer schema) is used
 *                   when present, otherwise the frame's.
 * target.direction= `path[0].how` through a table over the mapper's CLOSED
 *                   `how` enum only. A verb outside that enum maps to
 *                   `modulate` and says so; it is never fuzzy-matched to a
 *                   stronger verb. g_1a4f predates the enum and uses
 *                   `suppresses`/`blocks`, so this fires on the real artifact —
 *                   the frame's `targetDirectionOverride` is how an analyst
 *                   states the direction they actually mean.
 * mechanism       = the rendered chain, name -[verb]-> name, with link ids.
 * evidence[]      = evidence-bridge.ts's recipe, unchanged: verbatim quote as
 *                   the claim, `says` → direction (no_effect passthrough),
 *                   `doi:`/`PMID:` source, STUDY_QUALITY × preprint discount.
 *                   The slate nests findings/papers/links as DICTS keyed by id
 *                   rather than the graph's arrays, so the shapes are read
 *                   differently and the mapping is identical.
 * id              = the hypothesis id (`H-g1`).
 * uncertainty     = 1 − `scores.support`.
 *
 * EVERY emitted thesis goes through `IndicationThesis.parse` before it is
 * printed. A thesis that does not validate is not written — the bridge exits
 * non-zero with the zod issues, because a half-valid thesis silently entering
 * the pipeline is the failure this contract exists to prevent.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { z } from "zod";
import {
  type Evidence,
  IndicationThesis,
  MechanismHypothesis,
} from "./thesis.ts";

/** Mirrors `_STUDY_QUALITY` in the mapper's assemble.py:199, via Adapter A. */
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
 * The mapper's CLOSED `how` enum (SCHEMA.md, closed by Soliman in b3049ae) and
 * nothing else. `suppresses` and `blocks` — the verbs the real g_1a4f graph
 * actually uses — are deliberately ABSENT: that graph predates the enum, and a
 * verb this table does not know maps to `modulate` with a note rather than
 * being guessed into `inhibit`.
 */
const DIRECTION_BY_HOW: Record<string, string> = {
  activates: "activate",
  associated_with: "modulate",
  binds: "modulate",
  decreases: "inhibit",
  drives: "activate",
  increases: "activate",
  inhibits: "inhibit",
};

const MECHANISM_KINDS = new Set(["gene", "protein"]);

// ---------------------------------------------------------------------------
// Input shapes. Tolerant on purpose — only what the bridge reads is required,
// and anything the slate omits is reported rather than crashed on.
// ---------------------------------------------------------------------------

const SlatePaper = z.object({
  doi: z.string().nullish(),
  is_preprint: z.boolean().nullish(),
  pmid: z.string().nullish(),
  retracted: z.boolean().nullish(),
  study_type: z.string().nullish(),
  title: z.string().nullish(),
});
const SlateFinding = z.object({
  from: z.string(),
  hedged: z.boolean().nullish(),
  how: z.string(),
  is_own_result: z.boolean().nullish(),
  paper: z.string(),
  quote: z.string(),
  says: z.enum(["yes", "no", "no_effect"]),
  to: z.string(),
});
const SlateLink = z.object({
  basis: z.string().nullish(),
  no: z.array(z.string()).default([]),
  no_effect: z.array(z.string()).default([]),
  yes: z.array(z.string()).default([]),
});
const SlateThing = z.object({
  aliases: z.array(z.string()).default([]),
  kind: z.string().nullish(),
  name: z.string(),
  uniprot_accession: z.string().nullish(),
});
const SlatePathStep = z.object({
  from: z.string(),
  from_name: z.string().nullish(),
  how: z.string(),
  link: z.string().nullish(),
  reversed: z.boolean().nullish(),
  to: z.string(),
  to_name: z.string().nullish(),
});
const SlateHypothesis = z.object({
  caveats: z.array(z.string()).default([]),
  evidence: z
    .object({
      findings: z.record(z.string(), SlateFinding).default({}),
      links: z.record(z.string(), SlateLink).default({}),
      papers: z.record(z.string(), SlatePaper).default({}),
      things: z.record(z.string(), SlateThing).default({}),
    })
    .default({ findings: {}, links: {}, papers: {}, things: {} }),
  id: z.string(),
  motif: z.string(),
  object: z.string(),
  object_name: z.string(),
  path: z.array(SlatePathStep).default([]),
  scores: z.record(z.string(), z.number()).default({}),
  subject: z.string(),
  subject_name: z.string(),
});
const Slate = z.object({
  generated_at: z.string().nullish(),
  graph_id: z.string(),
  hypotheses: z.array(SlateHypothesis).default([]),
  question: z.string().default(""),
  round: z.number().nullish(),
});

/**
 * The analyst frame. The five `*_why` strings are free-form documentation that
 * the bridge copies into `assumed[]` verbatim — they are the reason each number
 * exists, and dropping them would leave an unlabelled guess in the thesis.
 */
const Frame = z.object({
  biomarkerPopulation: z.object({
    _why: z.string().default(""),
    assayAvailable: z.boolean(),
    marker: z.string(),
    prevalenceInDisease: z.number().min(0).max(1),
  }),
  diseaseNameOverride: z.string().optional(),
  diseaseNameOverride_why: z.string().default(""),
  endpoint: z.object({
    _why: z.string().default(""),
    expectedEffectSize: z.number().positive().optional(),
    name: z.string(),
    type: z.enum(["continuous", "binary", "time_to_event"]),
  }),
  mechanismHypothesis: MechanismHypothesis.optional(),
  sponsor: z.string().optional(),
  targetDirectionOverride: z
    .enum(["inhibit", "activate", "degrade", "block", "modulate"])
    .optional(),
  targetDirectionOverride_why: z.string().default(""),
  targetSymbolOverride: z.string().optional(),
  targetSymbolOverride_why: z.string().default(""),
  tissue: z.string().optional(),
  uniprotAccession: z.string().optional(),
  uniprotAccession_why: z.string().default(""),
});

type SlateT = z.infer<typeof Slate>;
type HypothesisT = z.infer<typeof SlateHypothesis>;
type FrameT = z.infer<typeof Frame>;
type PaperT = z.infer<typeof SlatePaper>;
type FindingT = z.infer<typeof SlateFinding>;

/** One frame-supplied value, carrying the reason it is not a graph finding. */
type Assumption = {
  field: string;
  label: "ASSUMED";
  value: string;
  why: string;
};

type DroppedRow = { detail: string; findingId: string; reason: string };

// ---------------------------------------------------------------------------
// Evidence — Adapter A's recipe, over the slate's dict-shaped evidence pack.
// ---------------------------------------------------------------------------

function strengthOf(paper: PaperT): number {
  const base = STUDY_QUALITY[paper.study_type ?? "unknown"] ?? UNKNOWN_QUALITY;
  const scaled = paper.is_preprint ? base * PREPRINT_DISCOUNT : base;
  return Math.round(Math.min(1, Math.max(0, scaled)) * ROUND_4) / ROUND_4;
}

function sourceOf(paper: PaperT): string | undefined {
  if (paper.doi) {
    return `doi:${paper.doi}`;
  }
  return paper.pmid ? `PMID:${paper.pmid}` : undefined;
}

/** `basis` is a link property, so read it off the link citing this finding. */
function basisOf(findingId: string, hypothesis: HypothesisT): string {
  for (const link of Object.values(hypothesis.evidence.links)) {
    const cited = [...link.yes, ...link.no, ...link.no_effect];
    if (cited.includes(findingId)) {
      return link.basis ?? "primary";
    }
  }
  const finding = hypothesis.evidence.findings[findingId];
  if (finding?.is_own_result === false) {
    return "background_only";
  }
  return finding?.hedged ? "hedged_only" : "primary";
}

function claimOf(
  findingId: string,
  finding: FindingT,
  hypothesis: HypothesisT,
  slate: SlateT
): string {
  const name = (id: string) => hypothesis.evidence.things[id]?.name ?? id;
  const triple = `${name(finding.from)} -[${finding.how}]-> ${name(finding.to)}`;
  return `${triple} | "${finding.quote}" [${slate.graph_id}#${findingId}]`;
}

function convertFinding(
  findingId: string,
  finding: FindingT,
  hypothesis: HypothesisT,
  slate: SlateT
): { drop: DroppedRow } | { row: Evidence } {
  const drop = (reason: string, detail: string) => ({
    drop: { detail, findingId, reason },
  });
  const paper = hypothesis.evidence.papers[finding.paper];
  if (!paper) {
    return drop(
      "unresolved_paper",
      `paper id ${finding.paper} is in no row of the evidence pack`
    );
  }
  if (paper.retracted) {
    return drop(
      "retracted_paper",
      `paper ${finding.paper} is marked retracted`
    );
  }
  const basis = basisOf(findingId, hypothesis);
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
      `paper ${finding.paper} has neither doi nor pmid`
    );
  }
  const parsed = z
    .object({
      claim: z.string(),
      direction: z.enum(["supports", "contradicts", "no_effect"]),
      source: z.string(),
      sourceType: z.enum(["trial", "publication", "database", "simulation"]),
      strength: z.number().min(0).max(1),
    })
    .safeParse({
      claim: claimOf(findingId, finding, hypothesis, slate),
      direction: DIRECTION_BY_SAYS[finding.says],
      source,
      sourceType: "publication",
      strength: strengthOf(paper),
    });
  if (!parsed.success) {
    return drop(
      "schema_validation_failed",
      parsed.error.issues.map((i) => i.message).join("; ")
    );
  }
  return { row: parsed.data };
}

function buildEvidence(hypothesis: HypothesisT, slate: SlateT) {
  const evidence: Evidence[] = [];
  const dropped: DroppedRow[] = [];
  for (const [findingId, finding] of Object.entries(
    hypothesis.evidence.findings
  )) {
    const out = convertFinding(findingId, finding, hypothesis, slate);
    if ("row" in out) {
      evidence.push(out.row);
    } else {
      dropped.push(out.drop);
    }
  }
  return { dropped, evidence };
}

// ---------------------------------------------------------------------------
// The structural fields.
// ---------------------------------------------------------------------------

function modalityOf(hypothesis: HypothesisT): { value: string; why: string } {
  const kind =
    hypothesis.evidence.things[hypothesis.subject]?.kind ?? "unknown";
  if (kind === "small_molecule") {
    return {
      value: "small_molecule",
      why: `graph types subject ${hypothesis.subject} as small_molecule`,
    };
  }
  return {
    value: "other",
    why: `graph kind of subject ${hypothesis.subject} is "${kind}" — mapped to "other" rather than inferred; a graph protein node is a target, not a peptide drug`,
  };
}

/** Interior path nodes, subject-side first, excluding the object. */
function interiorNodes(hypothesis: HypothesisT): string[] {
  const out: string[] = [];
  for (const step of hypothesis.path) {
    if (step.to !== hypothesis.object && !out.includes(step.to)) {
      out.push(step.to);
    }
  }
  return out;
}

function targetFrom(
  hypothesis: HypothesisT,
  frame: FrameT
): { accession?: string; symbol: string; why: string } {
  for (const nodeId of interiorNodes(hypothesis)) {
    const thing = hypothesis.evidence.things[nodeId];
    if (thing && MECHANISM_KINDS.has(thing.kind ?? "")) {
      return {
        accession: thing.uniprot_accession ?? frame.uniprotAccession,
        symbol: thing.name,
        why: `first ${thing.kind} node on the path (${nodeId}) — read from the graph, not the frame`,
      };
    }
  }
  if (frame.targetSymbolOverride) {
    return {
      accession: frame.uniprotAccession,
      symbol: frame.targetSymbolOverride,
      why: `NO protein/gene node exists on this path (graph carries none), so the frame's targetSymbolOverride was used: ${frame.targetSymbolOverride_why}`,
    };
  }
  return {
    accession: frame.uniprotAccession,
    symbol: "UNSPECIFIED",
    why: "no protein/gene node on the path and no targetSymbolOverride in the frame — target left UNSPECIFIED rather than guessed",
  };
}

function directionFrom(
  hypothesis: HypothesisT,
  frame: FrameT
): { value: string; why: string } {
  const verb = hypothesis.path[0]?.how ?? "";
  const mapped = DIRECTION_BY_HOW[verb];
  if (frame.targetDirectionOverride) {
    return {
      value: frame.targetDirectionOverride,
      why: `frame override (${frame.targetDirectionOverride_why || "no reason given"}); the graph verb is "${verb}", which maps to "${mapped ?? "modulate"}"`,
    };
  }
  if (mapped) {
    return { value: mapped, why: `path[0].how = "${verb}"` };
  }
  return {
    value: "modulate",
    why: `path[0].how = "${verb}" is not in the mapper's closed how enum, so it maps to "modulate" rather than being guessed into a stronger verb`,
  };
}

function mechanismOf(hypothesis: HypothesisT): string {
  const steps = hypothesis.path.map((step) => {
    const from = step.from_name ?? step.from;
    const to = step.to_name ?? step.to;
    const link = step.link
      ? ` (${step.link}${step.reversed ? ", TRAVERSED AGAINST ITS STATED DIRECTION" : ""})`
      : "";
    return `${from} -[${step.how}]-> ${to}${link}`;
  });
  return steps.length > 0
    ? `${hypothesis.motif}: ${steps.join("; ")}`
    : `${hypothesis.motif}: ${hypothesis.subject_name} → ${hypothesis.object_name} (no path steps in the slate)`;
}

function assumptionsFrom(
  frame: FrameT,
  disease: { name: string; why: string },
  target: { symbol: string; why: string },
  direction: { value: string; why: string }
): Assumption[] {
  const rows: Assumption[] = [
    {
      field: "biomarkerPopulation",
      label: "ASSUMED",
      value: `${frame.biomarkerPopulation.marker} @ prevalence ${frame.biomarkerPopulation.prevalenceInDisease}, assay ${frame.biomarkerPopulation.assayAvailable}`,
      why: frame.biomarkerPopulation._why,
    },
    {
      field: "endpoint",
      label: "ASSUMED",
      value: `${frame.endpoint.name} (${frame.endpoint.type}, d=${frame.endpoint.expectedEffectSize ?? "unset"})`,
      why: frame.endpoint._why,
    },
  ];
  if (frame.diseaseNameOverride) {
    rows.push({
      field: "disease.name",
      label: "ASSUMED",
      value: disease.name,
      why: disease.why,
    });
  }
  if (frame.targetSymbolOverride) {
    rows.push({
      field: "target.symbol",
      label: "ASSUMED",
      value: target.symbol,
      why: target.why,
    });
  }
  if (frame.uniprotAccession) {
    rows.push({
      field: "target.uniprotAccession",
      label: "ASSUMED",
      value: frame.uniprotAccession,
      why: frame.uniprotAccession_why,
    });
  }
  if (frame.targetDirectionOverride) {
    rows.push({
      field: "target.direction",
      label: "ASSUMED",
      value: direction.value,
      why: direction.why,
    });
  }
  if (frame.tissue) {
    rows.push({
      field: "tissue",
      label: "ASSUMED",
      value: frame.tissue,
      why: "the graph has no tissue field; this is the analyst's reading of where the findings were measured",
    });
  }
  return rows;
}

/**
 * The whole conversion. Returns the parsed thesis plus everything a reader
 * needs to check it: what was assumed, what was dropped, and where each
 * structural field came from.
 */
function convert(hypothesis: HypothesisT, slate: SlateT, frame: FrameT) {
  const modality = modalityOf(hypothesis);
  const target = targetFrom(hypothesis, frame);
  const direction = directionFrom(hypothesis, frame);
  const disease = frame.diseaseNameOverride
    ? {
        name: frame.diseaseNameOverride,
        why: `${frame.diseaseNameOverride_why} Slate question, verbatim: "${slate.question}". object_name the override replaced: "${hypothesis.object_name}" (thing kind: ${hypothesis.evidence.things[hypothesis.object]?.kind ?? "unknown"}).`,
      }
    : {
        name: hypothesis.object_name,
        why: `object_name, straight from the slate (thing kind: ${hypothesis.evidence.things[hypothesis.object]?.kind ?? "unknown"})`,
      };
  const { dropped, evidence } = buildEvidence(hypothesis, slate);
  const { support } = hypothesis.scores;
  const candidate = {
    asset: {
      modality: modality.value,
      name: hypothesis.subject_name,
      sponsor: frame.sponsor,
    },
    biomarkerPopulation: {
      assayAvailable: frame.biomarkerPopulation.assayAvailable,
      marker: frame.biomarkerPopulation.marker,
      prevalenceInDisease: frame.biomarkerPopulation.prevalenceInDisease,
    },
    disease: { name: disease.name },
    endpoint: {
      expectedEffectSize: frame.endpoint.expectedEffectSize,
      name: frame.endpoint.name,
      type: frame.endpoint.type,
    },
    evidence,
    id: hypothesis.id,
    mechanism: mechanismOf(hypothesis),
    mechanismHypothesis: frame.mechanismHypothesis,
    target: {
      direction: direction.value,
      symbol: target.symbol,
      uniprotAccession: target.accession,
    },
    tissue: frame.tissue,
    uncertainty:
      support === undefined
        ? undefined
        : Math.round((1 - support) * ROUND_4) / ROUND_4,
  };
  const parsed = IndicationThesis.safeParse(candidate);
  return {
    assumed: assumptionsFrom(frame, disease, target, direction),
    dropped,
    fieldBasis: {
      "asset.modality": modality.why,
      "asset.name": `subject_name verbatim; graph aliases for this thing: ${(hypothesis.evidence.things[hypothesis.subject]?.aliases ?? []).join(", ") || "none"}`,
      "disease.name": disease.why,
      mechanism: `rendered from the slate path (motif ${hypothesis.motif})`,
      "target.direction": direction.why,
      "target.symbol": target.why,
      uncertainty: `1 − scores.support (${support ?? "absent"})`,
    },
    parsed,
  };
}

// ---------------------------------------------------------------------------
// CLI.
// ---------------------------------------------------------------------------

function usage(): never {
  process.stderr.write(
    "usage: bun thesis-bridge.ts <slate.json> --frame <frame.json> [--hypothesis <id>] [--out <path>]\n"
  );
  process.exit(1);
}

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf8"));
}

function pickHypothesis(slate: SlateT, wanted?: string): HypothesisT {
  if (slate.hypotheses.length === 0) {
    process.stderr.write(
      "slate contains no hypotheses — nothing to convert. (Run hyp_gen with a profile that shortlists something: `--profile valuation` returns 0 on g_1a4f because that graph has no protein/gene node and only one research group.)\n"
    );
    process.exit(1);
  }
  if (!wanted) {
    return slate.hypotheses[0] as HypothesisT;
  }
  const found = slate.hypotheses.find((h) => h.id === wanted);
  if (!found) {
    process.stderr.write(
      `unknown hypothesis "${wanted}"; slate has: ${slate.hypotheses.map((h) => h.id).join(", ")}\n`
    );
    process.exit(1);
  }
  return found;
}

function main(): void {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    args: process.argv.slice(2),
    options: {
      frame: { type: "string" },
      hypothesis: { type: "string" },
      out: { type: "string" },
    },
  });
  const [slatePath] = positionals;
  if (!(slatePath && values.frame)) {
    usage();
  }
  const slate = Slate.parse(readJson(slatePath));
  const frame = Frame.parse(readJson(values.frame as string));
  const hypothesis = pickHypothesis(slate, values.hypothesis);
  const { assumed, dropped, fieldBasis, parsed } = convert(
    hypothesis,
    slate,
    frame
  );
  if (!parsed.success) {
    process.stderr.write(
      `thesis FAILED IndicationThesis.parse — nothing written:\n${parsed.error.issues
        .map((i) => `  ${i.path.join(".")}: ${i.message}`)
        .join("\n")}\n`
    );
    process.exit(1);
  }
  const output = {
    assumed,
    dropped,
    fieldBasis,
    provenance: {
      frame: values.frame,
      generatedAt: slate.generated_at ?? null,
      graphId: slate.graph_id,
      hypothesisId: hypothesis.id,
      motif: hypothesis.motif,
      question: slate.question,
      round: slate.round ?? null,
      slate: slatePath,
      slateCaveats: hypothesis.caveats,
      strengthFormula:
        "clamp01(STUDY_QUALITY[study_type] * (is_preprint ? 0.8 : 1)); table mirrors assemble.py:199 via evidence-bridge.ts",
    },
    thesis: parsed.data,
  };
  const text = `${JSON.stringify(output, null, 2)}\n`;
  if (values.out) {
    writeFileSync(values.out, text);
    process.stderr.write(`wrote ${values.out}\n`);
  } else {
    process.stdout.write(text);
  }
}

main();
