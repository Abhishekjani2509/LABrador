/**
 * The team-wide contract for an indication thesis.
 *
 * This is the integration surface for the whole pipeline: the hypothesis node
 * (Sean / Abraham / Weichi) emits one of these, the dataset node (Rafal)
 * enriches `evidence`, this node scores recruitability, and ROI (Vince)
 * consumes the result. If this file disagrees with what any node actually
 * emits, the demo does not compose — so it lives in one place and everyone
 * imports it.
 *
 * Fields mirror the "computable indication thesis" from the spec doc:
 * asset + target/direction + disease/subtype + biomarker population + tissue
 * + dose/exposure + predicted endpoint + mechanism + evidence + uncertainty.
 */
import { z } from "zod";

export const Modality = z.enum([
  "antibody",
  "small_molecule",
  "peptide",
  "oligonucleotide",
  "cell_therapy",
  "other",
]);

export const Direction = z.enum([
  "inhibit",
  "activate",
  "degrade",
  "block",
  "modulate",
]);

/** How the primary endpoint is measured — drives the powering calculation. */
export const EndpointType = z.enum(["continuous", "binary", "time_to_event"]);

/**
 * One traceable claim. `source` must be a real identifier (NCT id, PMID, DOI,
 * database accession) — the inspectability criterion is won or lost here, so
 * unsourced claims are not representable in this type.
 */
export const Evidence = z.object({
  claim: z.string(),
  direction: z.enum(["supports", "contradicts"]),
  source: z.string(),
  sourceType: z.enum(["trial", "publication", "database", "simulation"]),
  /** 0 = anecdote, 1 = randomised human outcome data. */
  strength: z.number().min(0).max(1),
});
export type Evidence = z.infer<typeof Evidence>;

export const IndicationThesis = z.object({
  asset: z.object({
    modality: Modality,
    name: z.string(),
    sponsor: z.string().optional(),
  }),

  /**
   * The population the trial would actually enrol. `prevalenceInDisease` is
   * the single most important number this node consumes: a marker present in
   * 12% of patients means ~8 screened per enrollee, which is usually what
   * decides whether a trial is runnable.
   */
  biomarkerPopulation: z.object({
    assayAvailable: z.boolean(),
    marker: z.string(),
    prevalenceInDisease: z.number().min(0).max(1),
  }),

  disease: z.object({
    name: z.string(),
    subtype: z.string().optional(),
  }),

  endpoint: z.object({
    /** Standardised effect size (Cohen's d) the thesis predicts, if known. */
    expectedEffectSize: z.number().positive().optional(),
    name: z.string(),
    type: EndpointType,
  }),

  evidence: z.array(Evidence).default([]),

  id: z.string(),

  /** Free-text causal story: target → pathway → cell type → phenotype. */
  mechanism: z.string(),

  target: z.object({
    direction: Direction,
    symbol: z.string(),
  }),

  tissue: z.string().optional(),

  /** 0 = fully determined, 1 = pure speculation. Set by upstream nodes. */
  uncertainty: z.number().min(0).max(1).optional(),
});
export type IndicationThesis = z.infer<typeof IndicationThesis>;
