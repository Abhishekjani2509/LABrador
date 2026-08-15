---
name: precedent-lookup
description: >
  Retrieves what has actually been made against a protein target — measured
  bioactivities, approved and clinical drugs split by modality, structures, and
  family activity — from the Paperclip protein database, joined on UniProt
  accession. Fills the retrieved-precedent axis of the dossier. It does NOT
  compute tractability, does NOT score druggability, and does NOT merge target
  activity with family activity.
---

# precedent-lookup

Everything on this axis comes from one place: Paperclip's protein database,
three schemas joined on UniProt accession. One tool, one join key, dated fields
throughout — which is what makes the `as_of_date` rule enforceable.

## Setup

`PAPERCLIP_API_KEY` in the environment. Then, **before writing any query**:

```bash
paperclip skill proteins
```

This is mandatory, not advisory. The schema is not guessable and wrong column
names are the most common failure. Run it once per task and read it.

## The three schemas

| Schema | Scale | What you take from it |
| --- | --- | --- |
| `uniprot_v` | 574K proteins | identity, sequence, `features` (binding sites with positions), Pfam via `cross_references` |
| `pdb_v` | 177K structures | `structures_by_accession` (with `release_date`), `entry_ligands` (**holo detection**), `entries` (resolution, deposit date) |
| `chembl_v` | ~24M bioactivities | `bioactivities_by_accession`, `compounds_by_accession`, `drugs_by_accession` (with `first_approval`) |

## Procedure

### 1. Identity

```sql
SELECT accession, gene_name, protein_name, organism, sequence_length
FROM uniprot_v.proteins WHERE accession = '<ACC>'
```

### 2. Drugs, then modality — in that order, never skip the second step

```sql
SELECT d.drug_name, d.max_phase, d.first_approval, d.action_type,
       d.mechanism_of_action, c.canonical_smiles
FROM chembl_v.drugs_by_accession d
LEFT JOIN chembl_v.compounds_by_accession c
       ON c.molregno = d.molregno AND c.accession = d.accession
WHERE d.accession = '<ACC>'
ORDER BY d.first_approval NULLS LAST
```

`max_phase` 4.0 = approved. A NULL `canonical_smiles` here is a *candidate*
biologic — **you must then confirm it with the cross-accession check in step 2b
before believing it.** See failure modes: the naive test produces false biologic
calls.

### 2b. Confirm modality across ALL accessions — mandatory

The join in step 2 is scoped to one accession, so a drug with no bioactivity
record *at that accession* returns NULL whether or not it is a small molecule.
Re-check every candidate biologic against the whole table:

```sql
SELECT molregno, compound_name,
       MAX(CASE WHEN canonical_smiles IS NOT NULL THEN 1 ELSE 0 END) AS has_smiles_anywhere
FROM chembl_v.compounds_by_accession
WHERE molregno IN (<molregnos with NULL smiles from step 2>)
GROUP BY molregno, compound_name
```

`has_smiles_anywhere = 1` means **small molecule**, and step 2 was wrong about
it. Only `0` is a genuine biologic.

### 3. Compound-level potency

```sql
SELECT COUNT(*) AS n_compounds, MAX(best_pchembl_value) AS best_pchembl
FROM chembl_v.compounds_by_accession WHERE accession = '<ACC>'
```

`pchembl` is −log10(molar): 9.0 = 1 nM, 6.0 = 1 µM. Convert to nM for the
dossier. Pull the top compounds with SMILES to confirm they are small molecules.

### 4. Assay provenance — run this BEFORE reporting any actives count

```sql
SELECT LEFT(assay_description, 55) AS assay, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM chembl_v.bioactivities_by_accession
WHERE accession = '<ACC>'
GROUP BY assay_description ORDER BY n DESC LIMIT 5
```

If one assay exceeds ~30% of all activity, the count describes that assay, not
the target. Put the assay name and share in
`target_precedent.assay_concentration` and read the description carefully — it
may be measuring a different protein entirely.

Also take the type split, but see the failure mode below before trusting it:

```sql
SELECT assay_type, COUNT(*) AS n FROM chembl_v.bioactivities_by_accession
WHERE accession = '<ACC>' GROUP BY assay_type ORDER BY n DESC
```

### 5. Assay-level detail when potency looks surprising

```sql
SELECT standard_type, standard_relation, standard_value, standard_units,
       pchembl_value, confidence_score, assay_description
FROM chembl_v.bioactivities_by_accession
WHERE accession = '<ACC>' AND pchembl_value IS NOT NULL
ORDER BY pchembl_value DESC LIMIT 20
```

`confidence_score` is ChEMBL's target-assignment confidence, 9 high to 0 low.
`standard_relation` of `>` is a **non-result** — see failure modes.

### 5. Structures, with holo detection

```sql
SELECT s.entry_id, s.resolution, s.exptl_method, s.release_date,
       l.comp_id, l.ligand_name, l.formula_weight, l.drugbank_id
FROM pdb_v.structures_by_accession s
LEFT JOIN pdb_v.entry_ligands l ON l.entry_id = s.entry_id
WHERE s.accession = '<ACC>'
ORDER BY s.resolution NULLS LAST
```

`entry_ligands` carries `comp_id`, `smiles`, `inchikey`, `formula_weight` and
`drugbank_id` per entry — this is how you find a holo structure without leaving
Paperclip. `release_date` is what the `as_of_date` filter keys on.

### 6. Family precedent — separately, never merged

Get the Pfam from `uniprot_v.cross_references` (`database = 'Pfam'`), find sibling
accessions, and query their activity. Report as its own object with its own
sources. Never fold it into target precedent, never apply a discount.

## Failure modes

### The `modality` column is empty — do not use it

`chembl_v.bioactivities_by_accession` has a `modality` column. It is NULL.
Verified on IL-17A: all 305 rows return `modality = NULL`, one group. It exists
in the schema and carries nothing.

### `action_type` does not distinguish antibodies from small molecules

This is the trap this skill exists to prevent. IL-17A (Q16552) returns eleven
drugs, three approved:

| drug | max_phase | first_approval | action_type | canonical_smiles |
| --- | --- | --- | --- | --- |
| SECUKINUMAB | 4.0 | 2015 | INHIBITOR | **NULL** |
| IXEKIZUMAB | 4.0 | 2016 | INHIBITOR | **NULL** |
| BIMEKIZUMAB | 4.0 | 2021 | INHIBITOR | **NULL** |

All three are monoclonal antibodies. All three say `INHIBITOR`. Nothing in
`drugs_by_accession` marks them as biologics. An agent that reports "three
approved inhibitors" for IL-17A has produced the wrong answer to the only
question this dossier asks.

**The discriminator is `canonical_smiles`.** Every one of the eleven IL-17A
drugs joins to a NULL SMILES; the small molecules in
`compounds_by_accession` carry SMILES of 83–97 characters. A drug with no
structure is not a small molecule. Apply this test to every drug, always, before
it enters `target_precedent`.

A name ending in `-mab` is a useful cross-check but not the test — `IZOKIBEP`
and `M-1095` are also biologics and neither ends in `-mab`.

### …but a NULL SMILES alone gives FALSE biologic calls — salt forms

The accession-scoped join returns NULL for any drug lacking a bioactivity record
*at that accession*, regardless of modality. On EGFR, nine drugs came back with
no SMILES and **only four are real biologics** (cetuximab, panitumumab,
necitumumab, amivantamab). The other five are **salt forms of small molecules**
whose parent compounds sit in the SMILES bucket:

- osimertinib mesylate, neratinib maleate, mobocertinib succinate,
  lazertinib mesylate
- same pattern elsewhere: upadacitinib hemihydrate, filgotinib maleate,
  deuruxolitinib phosphate, momelotinib dihydrochloride monohydrate

Verified: `SALIRASIB` has SMILES under 33 other accessions. So the step-2b
cross-accession check is not optional — without it, EGFR reports nine approved
biologics and JAK-family targets invent biologics that do not exist.

The rule happens to hold cleanly on IL-17A and TNF-alpha, where every drug is
genuinely an antibody or protein. Do not generalise from those two.

**Unresolvable cases:** APG-2575 (lisaftoclax) and JTE-151 have
`structure_type: NONE` in ChEMBL — no structure recorded either way. Report them
as modality-unknown rather than forcing a call.

### `drugs_by_accession` returns one row per mechanism, not per drug

LAZERTINIB appears three times in the EGFR small-molecule bucket and twice more
with NULL SMILES. Counting rows overstates drug counts. Deduplicate on
`molregno` before reporting any total.

### Approved biologics and tractable small molecules can coexist

Same target, both true: IL-17A has three approved antibodies **and** 117
compounds in ChEMBL with a best pchembl of 9.10 — 0.79 nM, genuine fluorinated
med-chem, real SMILES. So IL-17A is *not* "no small molecules exist". It is
"the approved drugs are biologics, and potent small molecules exist but none
approved."

Report both facts. Collapsing either direction is wrong: "druggable, three
approved drugs" ignores modality; "not small-molecule druggable" ignores 0.79 nM
compounds. This is why `biologic_precedent` is its own block.

### `standard_relation` of `>` is a failed measurement

`EC50 > 10000 nM` means the compound did **not** work up to 10 µM. Filtering on
`standard_value` alone silently turns non-results into weak actives and inflates
the count. Always read `standard_relation`; only `=` is a measurement.

### An actives count can be dominated by an assay for a different protein

TNF-alpha (P01375) has 6,447 activities. The single largest contributor:

| assay | n | pct |
| --- | --- | --- |
| IRAK4 Monocyte TNFalpha Cell Based Assay: Cryopreserved | 2901 | **45.0** |
| Inhibition Assay: Inhibition assay using TNF-alpha. | 577 | 8.9 |
| TNF-alpha Secretion Assay: Monocytic THP-1 cells | 321 | 5.0 |

**45% of TNF-alpha's bioactivity is an IRAK4 assay** — a different target, using
TNF only as a cellular readout. Report the count without this check and TNF-alpha
looks heavily precedented. It has zero approved small molecules.

### `assay_type = 'B'` does NOT mean the assay is clean

The obvious defence — filter to binding assays — does not work. Verified on
TNF-alpha: the split is **B = 5,830 / F = 617**, so ~90% are labelled binding,
**and the IRAK4 cellular assay is among them**. The type field is too coarse to
separate a direct-binding measurement from a cellular readout.

Report the split, but do not treat `B` as a filter. The assay *description* is
the only reliable signal, which is why step 4 is mandatory rather than optional.

### `n_target_components > 1` means the hit is inherited

In `target_proteins`, `n_target_components = 1` is a clean single-protein target.
Greater than 1 means a complex or family, and activity attributed there is not
necessarily activity against your protein. Check it before counting actives.

### `drugs_by_accession` empty does not mean no chemistry

The view only includes drugs with an annotated **direct mechanism of action**. A
target can have thousands of bioactivities and no rows here. Empty means "no
drug with a curated direct mechanism", not "nothing has ever been made". Say
which you mean.

### SQL returns 200 rows maximum, silently

There is a 200-row cap and a 15s timeout. A well-studied target has far more.
Aggregate server-side with `COUNT`, `MAX`, `STRING_AGG ... GROUP BY` rather than
pulling rows and counting them yourself, or use `paperclip export` for large
result sets. A count derived from a capped result is wrong and looks fine.

### The per-protein document is not the database

`paperclip cat /proteins/<ACC>/content.lines` returns a pre-generated 8-line
summary with PDB and DrugBank cross-references. It contains **no ChEMBL data**.
Concluding from it that Paperclip lacks bioactivity is wrong — the data is in
`chembl_v` via `sql -s proteins`. The document is a summary; the SQL views are
the source.

### `scan` re-dumps the whole document per pattern

`paperclip scan <file> "A" "B" "C"` prints the entire document once per pattern.
Four patterns on an 8-line document produced ~200 lines. Use `grep` on the
section you want.

## As-of filtering

When `as_of_date` is set, filter at the source:

- structures — `WHERE s.release_date <= '<DATE>'`
- approvals — `WHERE d.first_approval <= EXTRACT(YEAR FROM DATE '<DATE>')`
- bioactivities — `bioactivities_by_accession` has no date column; join through
  `chembl.activities` / the document year, or mark the count `leakage_risk: true`
  and say so. **Do not silently report a current count under a past date.**

## Output

Fill `target_precedent`, `biologic_precedent`, `family_precedent`, and the
`structure` block. Every number carries its source — ChEMBL target ID, PDB ID, or
the query itself. Anything not retrieved is `null` with a line in `not_found`.
