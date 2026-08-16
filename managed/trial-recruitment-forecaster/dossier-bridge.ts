/**
 * Adapter C (COORDINATION.md §11 row 5): small-molecule-tractability-review
 * dossier JSON → `IndicationThesis.evidence[]`.
 *
 *   bun managed/trial-recruitment-forecaster/dossier-bridge.ts <dossier.json> \
 *     [--thesis-symbol IRAK4] [--thesis-accession Q9NWZ3] [--out rows.json]
 *
 * Read-only against `managed/small-molecule-tractability-review/` — the two
 * committed, validator-clean examples are the supported inputs:
 *   .claude/skills/assemble-dossier/examples/jak1_P23458.json
 *   .claude/skills/assemble-dossier/examples/tnf_P01375.json
 *
 * ── THE TWO AXES BECOME TWO DIFFERENT KINDS OF EVIDENCE ──────────────────
 *
 * The dossier is deliberately two-axis and refuses to average them
 * (assemble-dossier: "does NOT average the two axes into a score"). This
 * bridge keeps them apart in the only way `Evidence` can express, its
 * `sourceType`:
 *
 *   RETRIEVED axis → sourceType "database", source = target_precedent
 *                    .chembl_target_id. This is measured chemistry someone
 *                    else recorded: actives, approved molecules, potency.
 *   COMPUTED  axis → sourceType "simulation", source = structure.pdb_id. This
 *                    is a pocket geometry this repo calculated. It is a
 *                    simulation and is typed as one.
 *
 * A reader who trusts ChEMBL more than fpocket can therefore filter on
 * `sourceType` alone, without reading the claim text.
 *
 * ── STRENGTH IS CONSERVATIVE, AND THE CEILINGS ARE THE POINT ─────────────
 *
 * `thesis.ts` defines strength 1 as "randomised human outcome data". A
 * druggability dossier is not that, on either axis, so both are capped well
 * below it:
 *
 *   RETRIEVED cap 0.6 — 0.6 with at least one APPROVED small molecule against
 *     the target (the strongest tractability fact that exists short of an
 *     outcome trial), 0.4 with ≥1000 distinct actives but no approval, 0.3
 *     otherwise.
 *   COMPUTED cap 0.5 (hard clamp), value 0.25 — the tractability node itself
 *     stamps `pocket_druggability.load_bearing: false` and RETRACTED the
 *     AUC-1.000 calibration that used to interpret pocket volume ("the
 *     calibration anchors did not measure the proteins they were attributed
 *     to"). A number whose own author says it carries no verdict must not
 *     enter a thesis at retrieved-evidence weight.
 *
 * FALSIFICATION PENALTY: a `falsification.findings[]` row whose `result`
 * starts with "FOUND" against `single-assay dominance` or `best potency from a
 * characterised assay` drops the retrieved row to the 0.2 floor and copies the
 * finding verbatim into `caveats`. On the real TNF dossier this fires twice —
 * and one of them says the dominant assay measures IRAK4 rather than TNF.
 *
 * ── WHAT THIS BRIDGE REFUSES TO DO ───────────────────────────────────────
 *
 *  - It never invents a computed row. If the pocket run refused (TNF: every
 *    volume and druggability value null, "REFUSED, not missing"), no
 *    simulation row is emitted and the refusal is reported with the dossier's
 *    own words. A missing row is honest; a row built from nulls is not.
 *  - It never claims the dossier is about the thesis's target. Neither
 *    committed example is IRAK4, so `subjectMatch.matches` comes back FALSE
 *    and every emitted row's claim is PREFIXED with the mismatch. The runner
 *    surfaces it as a caveat; nothing downstream can mistake a JAK1 dossier
 *    for an IRAK4 one.
 *  - It never rewrites a verdict. `claim` carries `verdict` and
 *    `verdict_basis` verbatim, and `insufficient_evidence` maps to the
 *    `no_effect` direction rather than to `contradicts`, mirroring thesis.ts
 *    §6 item 3: "a null result and evidence against are different facts".
 */
import { readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { z } from "zod";
import { Evidence } from "./thesis.ts";

/** verdict → Evidence.direction. Three verdicts, three distinct facts. */
const DIRECTION_BY_VERDICT = {
  insufficient_evidence: "no_effect",
  not_tractable: "contradicts",
  small_molecule_tractable: "supports",
} as const;

const RETRIEVED_APPROVED = 0.6;
const RETRIEVED_MANY_ACTIVES = 0.4;
const RETRIEVED_BASE = 0.3;
const RETRIEVED_FALSIFIED_FLOOR = 0.2;
const MANY_ACTIVES = 1000;
/** Hard ceiling on any simulation-sourced row. Never raise this. */
const COMPUTED_CAP = 0.5;
const COMPUTED_VALUE = 0.25;
/** Falsification checks that undercut the retrieved axis specifically. */
const PRECEDENT_CHECKS = new Set([
  "best potency from a characterised assay",
  "single-assay dominance",
]);
const FOUND_PREFIX = "FOUND";
const MAX_CLAIM_CHARS = 900;

const Falsification = z.object({
  findings: z
    .array(z.object({ check: z.string(), result: z.string() }))
    .default([]),
  survived: z.boolean().nullish(),
});

const Dossier = z.object({
  as_of_date: z.string().nullish(),
  axis_conflict: z.string().nullish(),
  falsification: Falsification.default({ findings: [] }),
  structure: z
    .object({
      ensemble_used: z.array(z.string()).nullish(),
      pdb_id: z.string().nullish(),
      tier: z.string().nullish(),
    })
    .nullish(),
  target: z.object({
    gene_symbol: z.string().nullish(),
    protein_name: z.string().nullish(),
    uniprot_accession: z.string(),
  }),
  target_precedent: z
    .object({
      approved_small_molecules_count: z.number().nullish(),
      best_potency_assay: z.string().nullish(),
      best_potency_nm: z.number().nullish(),
      chembl_target_id: z.string().nullish(),
      distinct_actives: z.number().nullish(),
    })
    .nullish(),
  tractability: z
    .object({
      caveat: z.string().nullish(),
      pocket_druggability: z
        .object({
          load_bearing: z.boolean().nullish(),
          max: z.number().nullish(),
          min: z.number().nullish(),
        })
        .nullish(),
      pocket_volume_a3: z
        .object({
          max: z.number().nullish(),
          min: z.number().nullish(),
          primary_d1_6_a3: z.number().nullish(),
        })
        .nullish(),
    })
    .nullish(),
  verdict: z.enum([
    "small_molecule_tractable",
    "not_tractable",
    "insufficient_evidence",
  ]),
  verdict_basis: z.string(),
});
type DossierT = z.infer<typeof Dossier>;

type SubjectMatch = {
  detail: string;
  dossierAccession: string;
  dossierSymbol: string;
  matches: boolean;
  thesisSymbol: string;
};

type Skipped = { axis: string; reason: string };

/** Keep a long dossier sentence readable without altering its wording. */
function clip(text: string): string {
  return text.length <= MAX_CLAIM_CHARS
    ? text
    : `${text.slice(0, MAX_CLAIM_CHARS)}…[truncated; full text in the dossier]`;
}

function subjectMatchOf(
  dossier: DossierT,
  thesisSymbol: string,
  thesisAccession: string | undefined
): SubjectMatch {
  const symbol = dossier.target.gene_symbol ?? "unknown";
  const accession = dossier.target.uniprot_accession;
  const matches =
    symbol.toUpperCase() === thesisSymbol.toUpperCase() ||
    (thesisAccession !== undefined && accession === thesisAccession);
  return {
    detail: matches
      ? `dossier target ${symbol} (${accession}) IS the thesis target ${thesisSymbol}`
      : `SUBJECT MISMATCH: this dossier measures ${symbol} (${accession}), NOT the thesis target ${thesisSymbol}${thesisAccession ? ` (${thesisAccession})` : ""}. The rows below are about a DIFFERENT protein and are evidence about the tractability pipeline, not about this thesis's target.`,
    dossierAccession: accession,
    dossierSymbol: symbol,
    matches,
    thesisSymbol,
  };
}

/** Falsification rows that specifically undercut the retrieved axis. */
function precedentFalsifications(dossier: DossierT): string[] {
  return dossier.falsification.findings
    .filter(
      (f) => PRECEDENT_CHECKS.has(f.check) && f.result.startsWith(FOUND_PREFIX)
    )
    .map((f) => `${f.check}: ${f.result}`);
}

function retrievedStrength(dossier: DossierT, falsified: boolean): number {
  if (falsified) {
    return RETRIEVED_FALSIFIED_FLOOR;
  }
  const precedent = dossier.target_precedent;
  if ((precedent?.approved_small_molecules_count ?? 0) >= 1) {
    return RETRIEVED_APPROVED;
  }
  return (precedent?.distinct_actives ?? 0) >= MANY_ACTIVES
    ? RETRIEVED_MANY_ACTIVES
    : RETRIEVED_BASE;
}

function retrievedClaim(
  dossier: DossierT,
  match: SubjectMatch,
  falsifications: string[]
): string {
  const precedent = dossier.target_precedent;
  const counts = [
    `${precedent?.distinct_actives ?? "unknown"} distinct actives`,
    `${precedent?.approved_small_molecules_count ?? 0} approved small molecules`,
    precedent?.best_potency_nm === null ||
    precedent?.best_potency_nm === undefined
      ? "no reported potency"
      : `best potency ${precedent.best_potency_nm} nM (${precedent.best_potency_assay ?? "assay unnamed"})`,
  ].join(", ");
  const prefix = match.matches ? "" : `[${match.detail}] `;
  const undercut =
    falsifications.length > 0
      ? ` FALSIFICATION FOUND, verbatim: ${falsifications.join(" || ")}`
      : "";
  return clip(
    `${prefix}${match.dossierSymbol} (${match.dossierAccession}) tractability verdict "${dossier.verdict}", basis "${dossier.verdict_basis}". Retrieved axis: ${counts}.${undercut}`
  );
}

function computedClaim(dossier: DossierT, match: SubjectMatch): string {
  const volume = dossier.tractability?.pocket_volume_a3;
  const drug = dossier.tractability?.pocket_druggability;
  const prefix = match.matches ? "" : `[${match.detail}] `;
  const geometry =
    volume?.primary_d1_6_a3 === null || volume?.primary_d1_6_a3 === undefined
      ? `pocket volume ${volume?.min ?? "?"}–${volume?.max ?? "?"} Å³ across the ensemble (no single D=1.6 primary volume reported)`
      : `pocket volume ${volume.primary_d1_6_a3} Å³ at D=1.6`;
  const drugText =
    drug?.min === null || drug?.min === undefined
      ? "druggability not reported"
      : `fpocket druggability ${drug.min}–${drug.max}, load_bearing ${String(drug.load_bearing)}`;
  return clip(
    `${prefix}${match.dossierSymbol} (${match.dossierAccession}) computed axis on PDB ${dossier.structure?.pdb_id ?? "unknown"} (${dossier.structure?.tier ?? "tier unknown"}): ${geometry}; ${drugText}. NO THRESHOLD INTERPRETS THIS NUMBER — the dossier's own volume calibration is RETRACTED, so this row is geometry, not a verdict.`
  );
}

/** True when the computed axis actually produced a number worth carrying. */
function computedReported(dossier: DossierT): boolean {
  const volume = dossier.tractability?.pocket_volume_a3;
  const measured = [volume?.primary_d1_6_a3, volume?.min, volume?.max].some(
    (v) => typeof v === "number"
  );
  return Boolean(dossier.structure?.pdb_id) && measured;
}

function buildRows(dossier: DossierT, match: SubjectMatch) {
  const rows: Evidence[] = [];
  const skipped: Skipped[] = [];
  const falsifications = precedentFalsifications(dossier);
  const chembl = dossier.target_precedent?.chembl_target_id;
  if (chembl) {
    rows.push(
      Evidence.parse({
        claim: retrievedClaim(dossier, match, falsifications),
        direction: DIRECTION_BY_VERDICT[dossier.verdict],
        source: chembl,
        sourceType: "database",
        strength: retrievedStrength(dossier, falsifications.length > 0),
      })
    );
  } else {
    skipped.push({
      axis: "retrieved",
      reason:
        "no target_precedent.chembl_target_id — thesis.ts requires a real identifier in `source`, so no row is emitted",
    });
  }
  if (computedReported(dossier)) {
    rows.push(
      Evidence.parse({
        claim: computedClaim(dossier, match),
        direction: DIRECTION_BY_VERDICT[dossier.verdict],
        source: dossier.structure?.pdb_id ?? "",
        sourceType: "simulation",
        strength: Math.min(COMPUTED_VALUE, COMPUTED_CAP),
      })
    );
  } else {
    skipped.push({
      axis: "computed",
      reason: `the pocket run reported no volume (structure.pdb_id ${dossier.structure?.pdb_id ?? "absent"}); the dossier's own caveat: ${clip(dossier.tractability?.caveat ?? "none recorded")}`,
    });
  }
  return { falsifications, rows, skipped };
}

function usage(): never {
  process.stderr.write(
    "usage: bun dossier-bridge.ts <dossier.json> [--thesis-symbol IRAK4] [--thesis-accession Q9NWZ3] [--out <path>]\n"
  );
  process.exit(1);
}

function main(): void {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    args: process.argv.slice(2),
    options: {
      out: { type: "string" },
      "thesis-accession": { type: "string" },
      "thesis-symbol": { type: "string" },
    },
  });
  const [dossierPath] = positionals;
  if (!dossierPath) {
    usage();
  }
  const dossier = Dossier.parse(
    JSON.parse(readFileSync(dossierPath, "utf8")) as unknown
  );
  const match = subjectMatchOf(
    dossier,
    values["thesis-symbol"] ?? "IRAK4",
    values["thesis-accession"] ?? "Q9NWZ3"
  );
  const { falsifications, rows, skipped } = buildRows(dossier, match);
  const output = {
    caveats: [
      ...falsifications,
      ...(dossier.axis_conflict
        ? [`axis_conflict: ${dossier.axis_conflict}`]
        : []),
      ...(match.matches ? [] : [match.detail]),
    ],
    evidence: rows,
    provenance: {
      asOfDate: dossier.as_of_date ?? null,
      dossier: dossierPath,
      falsificationChecksRun: dossier.falsification.findings.length,
      strengthPolicy: `retrieved cap ${RETRIEVED_APPROVED} (approved molecules) / ${RETRIEVED_MANY_ACTIVES} (≥${MANY_ACTIVES} actives) / ${RETRIEVED_BASE} otherwise, floored to ${RETRIEVED_FALSIFIED_FLOOR} when a precedent falsification check reports FOUND; computed rows fixed at ${COMPUTED_VALUE} and hard-capped at ${COMPUTED_CAP}`,
      verdict: dossier.verdict,
      verdictBasis: dossier.verdict_basis,
    },
    skipped,
    subjectMatch: match,
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
