---
name: structure-select
description: >
  Picks the structures a pocket scan should run on — classifying holo vs apo by
  actual ligand chemistry rather than by label, assembling an ensemble, applying
  an as-of date cutoff, and finding structural neighbours with Foldseek to
  establish structural-homolog precedent. It does NOT score pockets, does NOT
  predict structures, and does NOT decide tractability.
---

# structure-select

Everything here runs against Paperclip's `pdb_v` views plus Proto's Foldseek.
All queries below were tested; the controls are stated so a regression is
visible.

## The exclusion list — every holo query depends on it

Cofactors, buffers, cryoprotectants, detergents, lipids and sugars. Call it
`$EXCL`:

```
'ATP','ADP','AMP','ANP','AGS','ACP','APC','GTP','GDP','GNP','GSP','GCP','UTP','UDP','UMP',
'CTP','CDP','CMP','TTP','TDP','IMP','5GP','FMN','FAD','NAD','NAI','NAP','NDP','COA','ACO',
'SAM','SAH','TPP','PLP','BTN','HEM','HEC','HEA','SF4','FES','F3S','MTE','MGD','B12','COB',
'GSH','GDS','UPG','UD1','PAP','PPS','PEG','PGE','PG4','P6G','1PE','2PE','7PE','12P','15P',
'XPE','P33','PE4','PE8','M2M','MPO','MPD','SUC','TRE','MAN','BGC','GLC','NAG','GAL','FUC',
'SIA','BMA','XYL','MLI','MLA','TLA','TAR','EPE','MES','TRS','BTB','BIS','CIT','FLC','ACY',
'ACT','FMT','OXL','SIN','BME','DTT','DTV','DTU','IPA','IPH','DMS','EDO','GOL','SO4','PO4',
'NO3','CO3','AZI','SCN','IOD','URE','IMD','BCT','BOG','LDA','LMT','C8E','OGA','SDS','TWT',
'P4C','HTG','HEZ','PIN','CXS','MYR','PLM','OLA','STE','DAO','D12','UND','PC1','PEE','PGV',
'PEF','PCW','LMN','CDL','CLR','CHD','Y01','OCT','HEX','DEP','BU1','BU3','PDO','PGO','PGR',
'1BO','MRD','MRY','SPD','SPM','PUT','CAC','WO4','MOO','VO4','PER','PPV','POP','AF3','ALF',
'BEF','MGF'
```

Hand-curated from the ~160 commonest entries, **not exhaustive** over the 38K-row
`chemcomps` dictionary. Rare cofactors will leak through as false HOLO — eyeball
`all_ligands` on anything surprising.

## 1. Candidate structures with holo/apo classification

```sql
SELECT s.entry_id, s.resolution, s.exptl_method, s.release_date,
  CASE WHEN COUNT(l.comp_id) FILTER (
         WHERE l.comp_type='non-polymer'
           AND l.formula_weight BETWEEN 250 AND 1200
           AND l.comp_id NOT IN ($EXCL)) > 0
       THEN 'HOLO' ELSE 'APO' END AS state,
  COALESCE(STRING_AGG(DISTINCT CASE WHEN l.comp_type='non-polymer'
             AND l.formula_weight BETWEEN 250 AND 1200
             AND l.comp_id NOT IN ($EXCL)
           THEN l.comp_id||'('||ROUND(l.formula_weight::numeric,0)||')' END, ' '), '-') AS druglike,
  COALESCE(STRING_AGG(DISTINCT l.comp_id||':'||COALESCE(l.drugbank_id,'-'), ' '), '-') AS all_ligands
FROM pdb_v.structures_by_accession s
LEFT JOIN pdb_v.entry_ligands l ON l.entry_id = s.entry_id
WHERE s.accession = '<ACC>'
GROUP BY s.entry_id, s.resolution, s.exptl_method, s.release_date
ORDER BY 5 DESC, s.resolution NULLS LAST
LIMIT 25
```

**Controls: 4OBE must return APO, 6OIM must return HOLO (MOV).** If either
flips, the exclusion list or the MW window has broken.

Verified on KRAS: 4LYH HOLO 21F(516), 6OIM HOLO MOV(563), 8AZX HOLO OFU(467);
4OBE APO, 6P0Z APO. On TNF-alpha: 9OJO A1CB1(384) 1.36 A, 2AZ5 307(548) 2.1 A.

## 2. As-of filtering

`release_date` is `date`-typed and **100% populated** — 508,687 of 508,687 rows,
spanning 1976-05-19 to 2026-07-01. Future-dated entries exist, so clamp to today
if that matters.

```sql
... WHERE s.accession='<ACC>' AND s.release_date < DATE '<CUTOFF>'
```

Composes with the query above by adding the predicate. KRAS before 2013-01-01
returns 15 entries, earliest 1D8D (2000-02-09), latest 2012-05-23 — and none of
them holo with a drug-like ligand, which is the whole retrospective story.

## 3. Domain-restricted selection

When a target has multiple domains and the drug binds one of them, select on it.
Use **overlap fraction, never containment**:

```sql
WITH ranges AS (
  SELECT r.entry_id,
    GREATEST(0, LEAST(r.max_uniprot_pos,<D1_HI>) - GREATEST(r.min_uniprot_pos,<D1_LO>) + 1)::float
      / (<D1_HI>-<D1_LO>+1) AS d1_frac,
    GREATEST(0, LEAST(r.max_uniprot_pos,<D2_HI>) - GREATEST(r.min_uniprot_pos,<D2_LO>) + 1)::float
      / (<D2_HI>-<D2_LO>+1) AS d2_frac
  FROM pdb_v.uniprot_alignment_ranges r WHERE r.accession='<ACC>'
), dom AS (
  SELECT entry_id,
    CASE WHEN MAX(d1_frac)>=0.7 AND MAX(d2_frac)>=0.7 THEN 'BOTH'
         WHEN MAX(d1_frac)>=0.7 THEN 'D1'
         WHEN MAX(d2_frac)>=0.7 THEN 'D2'
         ELSE 'other' END AS domain
  FROM ranges GROUP BY entry_id
)
SELECT d.domain, COUNT(DISTINCT d.entry_id) n, MIN(s.release_date) earliest
FROM dom d JOIN pdb_v.structures_by_accession s
  ON s.entry_id=d.entry_id AND s.accession='<ACC>'
GROUP BY d.domain ORDER BY 1
```

Domain boundaries come from `uniprot_v.features WHERE feature_type='Domain'`.

Verified on TYK2 (JH1 897-1176, JH2 575-869): JH1 28 entries earliest
**2010-06-02**, JH2 20 entries earliest **2013-04-10**, plus one JH1+JH2 tandem
(4OLI) and three "other" (FERM-SH2 23-583) correctly separated out.

## 4. Foldseek — structural neighbours

```python
from proto_tools.tools.structure_alignment.foldseek.foldseek_search import (
    FoldseekSearchConfig, FoldseekSearchInput, run_foldseek_search)

result = run_foldseek_search(
    FoldseekSearchInput(structure="/path/to/query.pdb"),
    FoldseekSearchConfig(search_mode="remote", databases=["pdb100"],
                         mode="3diaa", timeout_seconds=900.0))
```

One required field, `structure`: a `Structure` object, **a file path**, or raw
PDB/CIF text. **It does not accept a PDB ID or a URL** — resolve those to a file
first.

Verified: 6OIM chain A against `pdb100` returned **992 hits in 13.3 s**, no
database download, no local disk. `mode='tmalign'`: 8.0 s, 989 hits. Remote mode
POSTs to `search.foldseek.com`; no Modal, no GPU.

Databases: `pdb100, afdb50, afdb-swissprot, afdb-proteome, mgnify_esm30,
gmgcl_id, BFVD, cath50, bfmd`. Use `pdb100` when you need PDB IDs back —
afdb/BFVD return AlphaFold/UniProt accessions and need a different parse.

## 5. Neighbour precedent handoff

Keep structural-but-not-sequence neighbours (`sequence_identity < 0.30 AND
alignment_length >= 120`), then ask whether *their* accessions have drug-like
holo structures:

```sql
WITH hits AS (
  SELECT DISTINCT pe.uniprot_accession AS acc FROM pdb_v.polymer_entities pe
  WHERE pe.entry_id IN (<foldseek hit pdb ids>) AND pe.uniprot_accession IS NOT NULL),
all_s AS (
  SELECT DISTINCT h.acc, s.entry_id FROM hits h
  JOIN pdb_v.structures_by_accession s ON s.accession = h.acc)
SELECT a.acc, COUNT(DISTINCT a.entry_id) n_struct,
       COUNT(DISTINCT a.entry_id) FILTER (WHERE l.comp_id IS NOT NULL) n_holo,
       COALESCE(STRING_AGG(DISTINCT l.comp_id,' '),'-') druglike
FROM all_s a
LEFT JOIN pdb_v.entry_ligands l ON l.entry_id = a.entry_id
     AND l.comp_type='non-polymer' AND l.formula_weight BETWEEN 250 AND 1200
     AND l.comp_id NOT IN ($EXCL)
GROUP BY a.acc HAVING COUNT(DISTINCT a.entry_id) FILTER (WHERE l.comp_id IS NOT NULL) > 0
ORDER BY 3 DESC LIMIT 20
```

Fills `structural_neighbour_precedent`. Keep it separate from `family_precedent`
— fold neighbours and sequence family are different signals and may disagree.

## Failure modes

### `comp_type` does not separate cofactors from drugs

GDP and UDP are `'RNA linking'`, but **ATP (507 Da), GTP (523), GNP/GppNHp (522),
NAD (663), FAD (786), COA (768), HEM (617) are all `'non-polymer'`** and sit
inside any sensible MW window. GNP is the KRAS *active-state* analog — without
explicit `comp_id` exclusion, every GppNHp KRAS structure misclassifies as HOLO.
The exclusion list is load-bearing.

### `drugbank_id` is not a druglikeness signal

Glycerol is `DB09462`. Sulfate is `DB14546`. GDP is `DB04315`. **Never gate HOLO
on `drugbank_id IS NOT NULL`.** Report it; do not filter on it.

### Containment tests silently miss domain structures

Selecting JH2 entries with `min_uniprot_pos>=560 AND max_uniprot_pos<=880` gives
earliest 2015-03-18 — wrong by two years. The true earliest, **3ZON
(2013-04-10)**, spans 541-873 and overhangs the domain boundary, so containment
drops it. Use overlap fraction.

### `entry_ligands` cannot attribute a ligand to a chain

It is keyed at **entry** level, and its `entity_id` is the ligand's own
nonpolymer entity, not the protein chain it touches (verified: 2AZ5's ligand is
entity `2AZ5_2`, the protein is `2AZ5_1`). In a multi-protein complex a ligand
bound to the *partner* still counts toward the entry.

This inflates neighbour precedent badly — RAN (P62826) showed 36/139 holo, but
the leptomycin-class ligands bind exportin, not RAN. **Treat family-level holo
counts as an upper bound** and check `pdb_v.entries.title` before believing them.
Single-protein targets like KRAS and TNF-alpha are unaffected.

### Foldseek's `evalue` and `bit_score` are mislabeled in remote mode

The public server emits a 17-column m8, but the parser reads columns 10 and 11
per the standard 12-column layout. Confirmed against the raw m8:

| field | actually holds | best hit | worst hit |
| --- | --- | --- | --- |
| `hit.evalue` | Foldseek **probability** (higher = better) | 1.000 | 0.045 |
| `hit.bit_score` | the **true E-value** (lower = better) | 5.6e-36 | 3.542 |

**Do not sort or threshold on `hit.evalue`.** Hits arrive best-first, so ranking
by list order is safe; if you must threshold, use `hit.bit_score` as the E-value.
The real bit score (1338) is in column 12 and is dropped entirely.

### There is no TM-score field — but `mode='tmalign'` hides it in `bit_score`

With `mode='tmalign'`, `hit.bit_score` carries the TM-score (verified: 0.9899 for
the self-hit, then 0.965, 0.9639). This is the only route to a TM-score from this
tool, and it works only *because* of the column mislabeling above.

### `target_id` is not an ID

It is `"7r0n-assembly1.cif.gz_A KRasG12C in complex with GDP and compound 2"`.
Parse `pdb_id = target_id[:4].upper()`, chain from the `_X` before the first
space, and treat the remainder as a free title.

### Untested, do not assume

- **`foldseek-multimer-search` has never been run** — signature only. It is the
  obviously right tool for an oligomeric site like TNF-alpha's trimer axis, but
  there is no timing, no hit-quality data, and no confirmation the column
  mislabeling behaves the same on the `/foldmulti` endpoint. Verify before relying.
- **Foldseek local mode** — no binary present; remote is the only tested path.
- Databases other than `pdb100`.

## Output

Fill the dossier's `structure` block: chosen tier, entry ID, resolution,
biological unit, the ligand with its heavy-atom count and whether it is
drug-like, total and holo counts, and the ensemble actually used. Fill
`structural_neighbour_precedent` from step 5. Record the as-of cutoff if one was
applied and how many entries it removed.
