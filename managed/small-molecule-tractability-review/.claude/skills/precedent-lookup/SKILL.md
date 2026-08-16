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

A fourth is reachable and you need it: the **raw** `chembl.*` tables, same
`sql -s proteins` connection. `chembl.molecule_dictionary` is the one that
matters here — it carries `molecule_type` and `structure_type`, the fields no
`chembl_v` view exposes, and modality classification depends on them entirely.

## Procedure

### 1. Identity

```sql
SELECT accession, gene_name, protein_name, organism, sequence_length
FROM uniprot_v.proteins WHERE accession = '<ACC>'
```

### 2. Drugs with modality — one query, one authoritative field

Modality is **not** inferred. It is read off `chembl.molecule_dictionary`, the
raw ChEMBL schema, which carries explicit `molecule_type` and `structure_type`
columns. `sql -s proteins` reaches the raw `chembl.*` tables as well as the
`chembl_v.*` views, so this is one query, not two:

```sql
SELECT DISTINCT d.drug_name, d.max_phase, d.first_approval,
       md.molecule_type, md.structure_type
FROM chembl_v.drugs_by_accession d
JOIN chembl.molecule_dictionary md ON md.molregno = d.molregno
WHERE d.accession = '<ACC>'
ORDER BY d.max_phase DESC, d.first_approval NULLS LAST
```

`max_phase` 4.0 = approved. `molecule_type` is the discriminator, and it is the
only one that has survived testing — see the superseded tests in failure modes.

The full enum, with counts over the whole `molecule_dictionary` (12 values):

| `molecule_type` | rows | modality | where it goes |
| --- | --- | --- | --- |
| `Small molecule` | 1,920,259 | `small_molecule` | `target_precedent` |
| `Protein` | 22,799 | `fusion_protein` or `other` — read the drug | `biologic_precedent` |
| `Antibody` | 1,032 | `antibody` | `biologic_precedent` |
| `Oligonucleotide` / `Gene` / `Enzyme` / `Antibody drug conjugate` / `Vaccine component` / `Cell` / `Oligosaccharide` | 260 / 191 / 129 / 109 / 90 / 85 / 81 | `other` | `biologic_precedent` |
| **`Unknown`** | 404,621 | **modality-unknown** | neither block — see below |
| **NULL** | 571,492 | **modality-unknown** | neither block |

Verified on the three calibration accessions:

| accession | result |
| --- | --- |
| P23458 (JAK1) | **11 of 11** approved rows `Small molecule` / `MOL`; 23 rows total, 21 `Small molecule`, 2 `Unknown`/`NONE` (INCB-047986, GLPG-0555) |
| P01375 (TNF-alpha) | 5 approved: 4 `Antibody`/`SEQ` (infliximab, adalimumab, certolizumab pegol, golimumab) + etanercept `Protein`/`SEQ`. 15 rows total, 2 `Unknown` (ABBV-3373, AZ9773) |
| Q16552 (IL-17A) | 3 approved, **all `Antibody`/`SEQ`** (secukinumab, ixekizumab, bimekizumab); izokibep `Protein`/`SEQ`; 11 rows total, 2 `Unknown` (M-1095, CJM-112) |

The classes separate cleanly. This is a local field — no external API call is
needed for the common case.

**`Unknown` is a real value and must not be guessed.** Two TNF-alpha drugs and
two IL-17A drugs return it. Map `Unknown` (and NULL) to modality-unknown, put it in
`not_found` with the drug name, and do **not** let it count toward either
`target_precedent` or `biologic_precedent`. If a call matters for the dossier,
corroborate it against an independent source with an explicit modality field
(CLAUDE.md rule 10b) and report both readings rather than picking one.

**`structure_type` is a hint, not the test.** It is `MOL` for small molecules and
`SEQ` for sequence-based entities, but it goes `NONE` for entries with no
structure of either kind — and `NONE` appears on genuine antibodies
(VUNAKIZUMAB, REMTOLUMAB on Q16552 are `Antibody`/`NONE`) as well as on
`Unknown` rows. Read `molecule_type`; use `structure_type` only to describe why
a record is thin. AZ9773 is `Unknown`/`SEQ` — sequence-based, so almost
certainly a biologic, but ChEMBL declines to say and so do you.

### 2b. Collapse salt and parent forms before counting

Salt, hydrate and parent forms are **distinct molregnos**, so deduplicating on
`molregno` does not deduplicate drugs. Verified on JAK1 (P23458): the 11 approved
rows carry 11 distinct molregnos but represent **9 real drugs**. Two parents
appear alongside their own salts —

- FILGOTINIB `1763569` and FILGOTINIB MALEATE `2336138`
- MOMELOTINIB `617563` and MOMELOTINIB DIHYDROCHLORIDE MONOHYDRATE `3283827`

— while four others appear *only* in salt form (ruxolitinib phosphate,
tofacitinib citrate, upadacitinib hemihydrate, deuruxolitinib phosphate), so you
cannot simply drop rows whose name contains a counter-ion.

Collapse by stripping trailing salt/hydrate tokens from `drug_name` —
`PHOSPHATE`, `CITRATE`, `MALEATE`, `MESYLATE`, `SUCCINATE`, `HEMIHYDRATE`,
`MONOHYDRATE`, `DIHYDROCHLORIDE`, `HYDROCHLORIDE`, `TOSYLATE`, `FUMARATE`,
`SODIUM`, `POTASSIUM` — and group on the remaining stem, keeping the earliest
`first_approval` for the group. If you do not collapse, report the raw count as
what it is: **11 approved rows for 9 approved drugs on JAK1, an inflation of 2**.
Never present a row count as a drug count without saying which you did.

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

| drug | max_phase | first_approval | action_type | molecule_type |
| --- | --- | --- | --- | --- |
| SECUKINUMAB | 4.0 | 2015 | INHIBITOR | **Antibody** |
| IXEKIZUMAB | 4.0 | 2016 | INHIBITOR | **Antibody** |
| BIMEKIZUMAB | 4.0 | 2021 | INHIBITOR | **Antibody** |

All three are monoclonal antibodies. All three say `INHIBITOR`. Nothing in
`drugs_by_accession` itself marks them as biologics. An agent that reports "three
approved inhibitors" for IL-17A has produced the wrong answer to the only
question this dossier asks.

**The discriminator is `chembl.molecule_dictionary.molecule_type`** (step 2). On
Q16552 it returns `Antibody` for all three, and `Small molecule` for none of the
eleven. Apply that test to every drug, always, before it enters
`target_precedent`.

A name ending in `-mab` is a useful cross-check but not the test — `IZOKIBEP`
(`Protein`) and `M-1095` (`Unknown`) are also biologics and neither ends in
`-mab`.

### SUPERSEDED — the NULL-SMILES test and its cross-accession confirmation

**Both of these are void. Do not reinstate either.** They are recorded here
because they were the documented procedure, they look plausible, and a reader who
does not know they were tried will invent them again.

*The earlier procedure was:* (1) treat a NULL `canonical_smiles` in
`chembl_v.compounds_by_accession` as a candidate biologic; (2) confirm it with a
cross-accession query asking whether that molregno has SMILES under **any**
accession, on the theory that salt forms of small molecules carry no bioactivity
against the target in hand and would otherwise read as biologics.

Step 1 is a real signal but it over-fires, exactly as previously documented: on
EGFR, nine drugs returned no SMILES and only four were real biologics
(cetuximab, panitumumab, necitumumab, amivantamab) — the rest were salt forms
(osimertinib mesylate, neratinib maleate, mobocertinib succinate, lazertinib
mesylate). That part of the finding stands.

**Step 2 does not work, and it was the part that was supposed to fix step 1.**
Verified by execution: the confirmation query returns **0 rows for both
classes**.

| molregnos queried | rows returned |
| --- | --- |
| JAK1 salt forms — upadacitinib hemihydrate `2832770`, filgotinib maleate `2336138`, deuruxolitinib phosphate `2464813`, momelotinib dihydrochloride monohydrate `3283827` | **0** |
| TNF-alpha biologics — etanercept `675371`, adalimumab `675482`, infliximab `675617`, certolizumab pegol `675782`, golimumab `675784` | **0** |

Salt forms are absent from `compounds_by_accession` entirely — no bioactivity
under any accession — and so are antibodies. The output is *identical* for
approved small molecules and approved antibodies, so `has_smiles_anywhere` can
never be `1` for the cases it was written to rescue, and the check cannot
discriminate. It produces false biologic calls on every JAK1 salt form it sees.

The claim that `SALIRASIB` "has SMILES under 33 other accessions" is not a
counter-example: a compound with broad bioactivity is a case the check never
needed to rescue.

Use step 2's `molecule_type` instead. It calls all four JAK1 salt forms
`Small molecule` and all four TNF-alpha antibodies `Antibody`.

**Also superseded:** the previous instruction to read `structure_type: NONE` as
"unresolvable" (APG-2575, JTE-151). `structure_type` is not the modality field —
`NONE` appears on drugs whose `molecule_type` is a confident `Antibody`. Decide
on `molecule_type`, and reserve modality-unknown for `molecule_type = 'Unknown'`.

### `drugs_by_accession` returns one row per mechanism, not per drug

LAZERTINIB appears three times in the EGFR small-molecule bucket and twice more
with NULL SMILES. Counting rows overstates drug counts. Deduplicate on
`molregno` before reporting any total.

**And `molregno` deduplication is not enough** — salt and parent forms are
*distinct* molregnos, so JAK1 still returns 11 approved rows for 9 approved
drugs after deduplicating. Collapse salt/parent pairs as well; step 2b says how.

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

There is a 200-row cap and a statement timeout. A well-studied target has far
more. Aggregate server-side with `COUNT`, `MAX`, `STRING_AGG ... GROUP BY` rather
than pulling rows and counting them yourself, or use `paperclip export` for large
result sets. A count derived from a capped result is wrong and looks fine.

**Keep an accession predicate on `compounds_by_accession`, always.** A query
against it whose only filter was `molregno IN (SELECT ... FROM
chembl.molecule_dictionary WHERE pref_name IN (...))` was **cancelled by the
statement timeout at 85s**. Rewriting the same query with the molregnos as
literals returned in **13 ms**. Resolve molregnos in a separate query and inline
them; never make the planner scan that view unfiltered.

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
