# Fixtures

One row per distinct failure mode. The `why_in_set` column is the point — a
fixture that does not name the failure mode it guards is decoration.

Domain focus is **immunology**. The oncology targets are retained deliberately:
they are the cases where druggability ground truth is unambiguous and dated, so
they validate the method before it is trusted on the actual domain.

## Files

| File | Status | Contents |
| --- | --- | --- |
| `pocket_calibration.json` | **complete, verified in-repo** | fpocket run on KRAS holo (6OIM) vs apo (4OBE). Ground truth for the cryptic-pocket blindness. Every number produced by running the tool, not retrieved. |
| `targets.csv` | pending retrieval | One row per target. Values must be retrieved and cited, never recalled. |

## The set

### Method validation (oncology, unambiguous ground truth)

| Target | UniProt | why_in_set |
| --- | --- | --- |
| KRAS | P01116 | "Undruggable" for 30 years, then cracked by covalent G12C chemistry. Drives the as-of retrospective. Its switch-II pocket is invisible on apo structures — see `pocket_calibration.json`. Tests that no-precedent is not read as not-druggable. |
| EGFR | P00533 | Heavy precedent, pre-formed ATP pocket, many holo structures. Positive control. If this one is wrong nothing else matters. |
| BCL-2 | P10415 | PPI interface long considered hopeless, cracked by venetoclax. Tests that target class is not used to over-penalize. |
| MYC | P01106 | Intrinsically disordered, no pocket, still undrugged after decades of effort. True negative control. Must not be rescued by family precedent. |

### Domain (immunology)

| Target | UniProt | why_in_set |
| --- | --- | --- |
| TYK2 | P29597 | Deucravacitinib binds the pseudokinase JH2 domain — an allosteric, non-ATP site. Tests whether the agent finds a non-obvious pocket, and whether it notices the JH2 structures postdate the JH1 ones. |
| JAK1 | P23458 | Heavily drugged ATP-site kinase. Immunology positive control. |
| IL-17A | Q16552 | **The trap.** Approved antibodies (secukinumab, ixekizumab), no viable small molecule. A dossier reporting "approved drugs exist" here is wrong in exactly the way the modality rule exists to prevent. This is the highest-value row in the set. |
| RORC / RORγt | P51449 | Real ligand-binding pocket, genuinely small-molecule tractable, but a clinical failure history. Separates *tractable* from *successful* — the agent must not read program termination as evidence of poor druggability, nor tractability as evidence of clinical viability. |

### Open slots

| Slot | Requirement |
| --- | --- |
| precedent/structure conflict | Substantial ChEMBL bioactivity but no credible pocket, or actives that are suspect (aggregators, PAINS, single-series). The case where the two axes disagree and the agent must report the disagreement rather than resolve it. Biased toward immunology. |
| recent orphan | Proposed in the last ~3 years, no approved drug, no or few structures, minimal ChEMBL. Correct output is `insufficient_evidence`, not a number. Biased toward immunology. |

## Rules for filling `targets.csv`

- Every value carries a source: ChEMBL target ID, PDB ID, DOI, or line-pinned URL.
- A value that could not be retrieved is `NOT_FOUND`, never an estimate.
- Approved drugs are split by modality. `approved_small_molecules` and
  `approved_biologics` are different columns and must never be summed.
- Dates matter — the as-of retrospective needs first-approval years and PDB
  deposition dates, not just current counts.
