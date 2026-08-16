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

## Ligand identity — `ligand_filter.py`, not a denylist

**There is no `$EXCL` list any more.** It was a hardcoded set of ~160 comp_ids
paired with a 250-1200 Da window, and that pairing cannot decide holo — see the
failure mode "A comp_id denylist plus a size floor CANNOT decide holo" below,
which is the systemic one on this page.

Holo is now decided from chemistry:

```python
from ligand_filter import classify_ligands, holo_call
v = classify_ligands(["MOV", "GNP", "L44"])   # one Paperclip trip per 40
v["L44"].verdict        # 'lipid_or_detergent'
v["L44"].reason         # '...unbranched aliphatic carbon chain is 21...'
holo_call(["GNP", "GOL"])["is_holo"]          # False
holo_call(["GNP", "GOL"])["determined"]       # True — and check this
```

`neighbour_precedent.py` uses it. Two rules that come with it:

- **`unknown` is not apo.** A failed CCD lookup returns `unknown` with a
  `lookup_failed` flag. Read `holo_call(...)["determined"]`, and on this axis
  especially — "no drug-like holo among the neighbours" is a real finding, and
  a lookup failure wearing that costume is the worst confusion available.
- **Select candidates in SQL, classify in Python.** The SQL predicate cannot
  express chemistry. Pull the comp_ids unfiltered and decide afterwards.

## 1. Candidate structures with holo/apo classification

Pull the candidates, then classify them. **The SQL does not decide holo.**

```sql
SELECT s.entry_id, s.resolution, s.exptl_method, s.release_date,
  COALESCE(STRING_AGG(DISTINCT l.comp_id, ' '), '-') AS candidate_ligands,
  COALESCE(STRING_AGG(DISTINCT l.comp_id||':'||COALESCE(l.drugbank_id,'-'), ' '), '-') AS all_ligands
FROM pdb_v.structures_by_accession s
LEFT JOIN pdb_v.entry_ligands l ON l.entry_id = s.entry_id
WHERE s.accession = '<ACC>'
GROUP BY s.entry_id, s.resolution, s.exptl_method, s.release_date
ORDER BY s.resolution NULLS LAST, s.release_date DESC
LIMIT 25
```

Then `holo_call(candidate_ligands.split())` per entry.

**Do NOT add `AND l.comp_type='non-polymer'` to that WHERE clause**, however
tempting. Measured on a 25-entry list: without it the query returns in **6 ms**,
with it the identical query **times out** (>120 s, `[error] Request timed out`).
The column is not usefully indexed, and it does not separate cofactors from
drugs anyway — `ligand_filter` reads the CCD type itself.

**Do not order by the state column.** An earlier version of this query used
`ORDER BY 5 DESC`, where column 5 is the `'HOLO'|'APO'` CASE string. Since
`'HOLO' > 'APO'` alphabetically, every apo entry falls past the row limit and
becomes invisible — TNF-alpha looked like it had no apo structures at all when
the real split is **17 holo / 35 apo**. Order by resolution, and get the counts
from a separate `GROUP BY state` query rather than by reading the first page.

**Controls: 4OBE must return APO, 6OIM must return HOLO (MOV).** If either
flips, `ligand_filter` has regressed.

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

## 5. Neighbour precedent — `neighbour_precedent.py`

This is wired up. Run the module in this directory rather than reassembling the
steps by hand:

```bash
$PROTO_PY neighbour_precedent.py <structure.pdb> <ACCESSION> \
    [--max-neighbours 25] [--min-alignment-length N] [--cache hits.json] \
    [--multimer auto|yes|no]
```

or `from neighbour_precedent import neighbour_precedent` under the proto-tools
python. It needs `paperclip` on PATH and `PAPERCLIP_API_KEY`; the module reads
`/Users/bb/repos/claude-agent-starter/.env` by default (`env_file=`).

The procedure it implements, in order:

0. **Count the chains and pick the search.** `>1` chain routes to
   `foldseek-multimer-search` (`mode='complex-3diaa'`), one chain to
   `foldseek-search`. This is not a preference — `foldseek-search` reads only
   ONE chain of a multi-chain file, so on an oligomer it answers a different
   question. `--multimer no` pins the old path; a multimer failure falls back
   to it and records the error in `foldseek.multimer_attempted_and_failed`.
1. **Foldseek against `pdb100`**, remote. Single-chain path: `mode='3diaa'`
   plus a second `mode='tmalign'` search joined on `target_id` for TM-scores.
   Multimer path: **no second search** — the complex TM-score is already in the
   raw m8 (column 21), which the module re-downloads from `result_url`.
2. **Filter to fold-not-sequence neighbours**: `sequence_identity < 0.30 AND
   alignment_length >= 120`. Both halves matter — without the identity ceiling
   this is `family_precedent` wearing a Foldseek hat, and without the length
   floor it is a motif match.
3. **Resolve the aligned CHAIN(s) to accessions**, not the entry's accessions —
   see the failure mode below, it changes answers. On the multimer path a
   neighbour is a *set* of matched chains and all of them are resolved.
4. **Ask whether those proteins have drug-like holo entries**, classifying
   every candidate ligand with `ligand_filter`, reported as an entry-level
   upper bound *and* a single-protein-entry floor, with `pdb_v.entries.title`
   attached and a `rejected_ligands` line per neighbour saying *why* each
   candidate was dropped.

Output keys worth knowing: **`search_path`** (`multimer` | `single_chain` — read
this first; it decides whether the block is evidence about an interface),
`n_query_chains_in_file` / `n_query_chains_searched`, `neighbours` (per entry —
`tm_score` with `tm_score_kind`, `chains`, `n_query_chains_matched`,
`probability`, `evalue`, `has_druglike_holo`, `ligands`, `ligand_names`,
`attribution`, `title`), `neighbour_accessions` (per accession across *all* its
PDB entries, with `holo_titles`), `filter.auto_relaxed`, and `caveats`.

Fills `structural_neighbour_precedent`. Keep it separate from
`family_precedent` — fold neighbours and sequence family are different signals
and are allowed to disagree.

### Measured on both calibration targets

| | KRAS 6OIM_A (P01116) | IL-17A 8DYG asm1 (Q16552) |
| --- | --- | --- |
| Foldseek hits | 992 | 283 |
| passing the filter | 285 | **2** (relaxed to 81) |
| neighbourhood | Rab / Ran / Rac / Ypt GTPases, TM 0.73-0.89 | cystine-knot growth factors: IL-25, VEGF-A/B/C/F, NGF/NT-3, BMP-2, PDGF-B, TGF-beta2, sclerostin, coagulogen; TM 0.34-0.78 |
| entries apo / holo | **24 / 1** (4PHH) | **24 / 1** (4EC7) |
| the one "holo" | 2UK = a GppNHp analog | L44 = a 625 Da diacylglycerol |
| honest read | **no small-molecule precedent** | **no small-molecule precedent** |

Both "holo" hits are exclusion-list leaks, so the defensible count on both
targets is **0 of 25**. This is why `ligand_names` is returned alongside
`comp_id`: a comp_id tells you nothing, `"5'-O-[(R)-hydroxy…]guanosine"` tells
you it is a nucleotide.

### Multimer versus single chain on the same IL-17A input

`8DYG-assembly1.cif`, Q16552, both paths, same filter:

| | single-chain | multimer |
| --- | --- | --- |
| rows | 283 | 863 |
| query chains searched | 1 of 2 | **2 of 2** |
| passing strict 120 | 2 | 2 rows / **1** entry |
| relaxed floor | 67 | **67 — same** |
| entries after relaxation | 81 | 137 |
| carried (top 25) | 25 | 25 |
| entries apo / holo | 24 / 1 | **23 / 2** |
| the "holo" | 4EC7 `L44` diacylglycerol | 4EC7 `L44` + 4XPJ `LPY` lysophospholipid |
| defensible small-molecule holo | **0 of 25** | **0 of 25** |
| neighbourhood | cystine-knot superfamily | **cystine-knot superfamily** |

The 42 chain accessions across the whole 137-entry multimer neighbourhood are
VEGF-A/B/C/D and PlGF, NGF / NT-3 / NT-4 / BDNF, PDGF-A/B, TGF-beta1/2, GDF-15,
BMP-2, GDF-5, sclerostin, noggin, norrin, the glycoprotein hormones, von
Willebrand factor, AMH, and IL-25 — the cystine-knot superfamily, which is the
same answer the single-chain search gave. Every one is an antibody-drugged PPI
target with no small-molecule holo structure.

**So on IL-17A the single-chain limit was harmless, and the precedent call does
not change.** Say that plainly rather than manufacturing a difference. What
does change is what the result *ranks*: multimer orders by complex TM-score, so
true homodimers (IL-25 at 0.74, then the neurotrophins) come first and
single-protomer matches sink. That is the right ordering for an interface site,
and it is a better-justified neighbourhood, not a different conclusion.

The reason to keep the multimer path is therefore **not** that it changed this
answer. It is that on this target we can *check* that it did not, and on the
next oligomer we cannot.

IL-17A is the interesting one and the prediction held. Its fold neighbourhood is
the cystine-knot superfamily — VEGF, NGF, BMP, PDGF, TGF-beta — every one of
them a PPI target approached with antibodies, none with a small-molecule holo
structure. Meanwhile IL-17A *itself* has 44 structures and 20 holo, the
macrocycle series. So `target_precedent` is strong and
`structural_neighbour_precedent` is empty **on the same target**. Report the
disagreement; it is the informative thing on the page.

The underlying family-level query, if you need it standalone:

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
     AND l.comp_id IN (<the comp_ids ligand_filter classified `druglike`>)
GROUP BY a.acc HAVING COUNT(DISTINCT a.entry_id) FILTER (WHERE l.comp_id IS NOT NULL) > 0
ORDER BY 3 DESC LIMIT 20
```

**This bare form is an upper bound only** — it has no chain attribution and no
title check. Use the module, or read the two failure modes below first.

## Failure modes

### A comp_id denylist plus a size floor CANNOT decide holo — use `ligand_filter.py`

This is the systemic one. Several failure modes below are symptoms of it.

Every "is this entry holo?" decision in this pipeline was made two ways, and
both are wrong:

1. **`comp_id` against a hardcoded exclusion set** — the former §1 `$EXCL`,
   `neighbour_precedent.EXCLUDED_LIGANDS`, `modal_app.COFACTORS`.
2. **A heavy-atom or MW floor** — `modal_app.DRUGLIKE_MIN_HEAVY_ATOMS = 18`,
   `neighbour_precedent.MW_MIN/MW_MAX`.

Both fail, and **both fail in the flattering direction**: they invent holo
structures that do not exist, which inflates apparent druggability. Four
measured wrong answers, on four different targets:

| target | reported | the "ligand" | truth |
| --- | --- | --- | --- |
| CD20 | 3 holo | `Y01` cholesteryl hemisuccinate, phosphatidylcholine — cryo-EM sample additives | **0 holo** |
| KRAS fold neighbours | 1/25 holo (4PHH) | `2UK`, a GppNHp analog — a nucleotide cofactor with a comp_id nobody listed | **0 of 25** |
| IL-17A fold neighbours | 1/25 holo (4EC7) | `L44`, a 625 Da diacylglycerol — clears an 18-heavy-atom floor because it is a big greasy lipid | **0 of 25** |
| NLRP3 | ADP entry called holo | `ADP`, ~27 heavy atoms in the NACHT domain | **apo** |

The pattern: **a hardcoded comp_id list cannot enumerate chemistry, and
molecular size does not distinguish a drug from a lipid.** Both a 625 Da
diacylglycerol and a 625 Da inhibitor clear a size gate; only chemistry
separates them. Extending the list is not a fix — it is the bug, applied again.

**Use `ligand_filter.py`** (same directory). It classifies on chemistry read out
of `pdb_v.chemcomps` — the CCD, via Paperclip, nothing external:

```python
from ligand_filter import classify_ligand, is_druglike_ligand, classify_ligands, holo_call

classify_ligand("L44").verdict     # 'lipid_or_detergent'
is_druglike_ligand("2UK")          # False
classify_ligands([...])            # batch: ONE round trip per 40 comp_ids
holo_call(["MOV", "GDP", "MG"])    # {'is_holo': True, 'druglike_ligands': ['MOV'], ...}
```

Verdicts: `druglike`, `cofactor`, `lipid_or_detergent`,
`crystallisation_additive`, `sugar_or_glycan`, `ion_or_solvent`,
`peptide_or_polymer`, `unknown`. Only `druglike` is evidence of a bindable site.
Every verdict carries a `reason` string and the `evidence` it rests on.

What it keys on, none of which the old code read:

- **`_chem_comp.type`.** Decisive on its own for polymers. It is how 6OIM's GDP
  is caught — the CCD types GDP as `RNA linking`, not `non-polymer`. Peptide-
  and saccharide-linking components are never small-molecule evidence.
- **Element composition.** Drug-like ligands are overwhelmingly N-containing; a
  pure C/H/O molecule with a long aliphatic run is a lipid.
- **Nucleotide signature** — purine base + ribose + phosphate. Catches ADP, ATP,
  GDP, GTP, GNP and analogs like `2UK` without naming any of them.
- **Sterol signature** — steroid nucleus *plus an aliphatic side chain*. The
  side chain is what separates cholesterol (tail of 8) and bile salts from a
  steroid DRUG like dexamethasone (tail of 2), which stays `druglike`.
- **Phospho-headgroup plus acyl chains** — phosphatidylcholines and detergents.
- **Any free phosphate ester** — the signature of endogenous metabolites.
- **Longest unbranched alkyl chain**, as a fraction of the molecule.

Measured, not claimed:

- **259/262 = 98.9%** on a ground-truth set that includes the four failures
  above, every member of `modal_app.COFACTORS` and `NON_LIGANDS`, and every
  member of `neighbour_precedent.EXCLUDED_LIGANDS` — none of which the
  classifier was told. Misses: `BTN` (biotin → `druglike`), `ACE`/`NH2` (capping
  groups).
- **61/70 = 87.1%** on a blind held-out sample from `pdb_v.chemcomps`, with
  **0 false positives**. Nothing that was really a cofactor, lipid or additive
  was called drug-like.

Known false negatives — deliberate, since a false positive is what caused all
four bugs: nucleoside/SAM-analog inhibitors and bisphosphonates → `cofactor`;
metallodrugs → `cofactor`; long-tailed natural-product antibiotics → `lipid`;
glycosylated natural products → `sugar_or_glycan`; peptidomimetic drugs typed
`peptide-like` → `peptide_or_polymer`. Read `evidence` and `flags`, not just
`verdict`, if any of those classes matter to the target in hand.

Two behaviours to respect:

- **`unknown` is not `apo`.** An unclassified ligand is not evidence of a site,
  so `is_druglike_ligand` returns False — but do not write "apo" on the strength
  of it. Check `holo_call(...)["determined"]`.
- **A lookup failure is not a CCD miss.** Paperclip's endpoint intermittently
  exceeds its statement timeout. Those verdicts carry the flag `lookup_failed`
  and appear in `holo_call(...)["undetermined"]`. Reporting such an entry as apo
  reintroduces the original bug in a new place.

It has no dependencies outside the standard library — no RDKit, which
`pocket-scan`'s Modal image does not have — so the verdict cannot vary with the
environment it is evaluated in.

### `comp_type` does not separate cofactors from drugs

**Still true, and now a reason not to filter on `comp_type` at all** — see the
section above; `ligand_filter` reads the CCD type itself and decides on
chemistry.

GDP and UDP are `'RNA linking'`, but **ATP (507 Da), GTP (523), GNP/GppNHp (522),
NAD (663), FAD (786), COA (768), HEM (617) are all `'non-polymer'`** and sit
inside any sensible MW window. GNP is the KRAS *active-state* analog, so a
`comp_type` filter both admits every GppNHp KRAS structure as HOLO *and* drops
the `'RNA linking'` nucleotides it should have caught. It discriminates in
neither direction.

There is a second, unrelated reason: putting `comp_type` in a WHERE clause is
**slow enough to fail**. Measured on the same 25-entry list, `SELECT DISTINCT
l.comp_id ... WHERE l.entry_id IN (...)` returns in 6 ms and the identical query
with `AND l.comp_type='non-polymer'` times out past 120 s.

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

`neighbour_precedent.py` implements this rather than merely warning about it.
Every holo count comes back twice:

- `n_holo_entry_level` — the naive count, the **upper bound**;
- `n_holo_single_protein_entries` — only entries with one distinct UniProt
  accession *and* one polypeptide entity, where attribution is unambiguous;
- `holo_titles` — up to three PDB IDs with ligands, an `attribution` flag and
  the entry title, so a reader can adjudicate the gap.

Re-measured on the KRAS neighbourhood, the gap is enormous:

| accession | structures | holo entry-level | holo single-protein |
| --- | --- | --- | --- |
| P62826 RAN | 139 | **36** | **0** |
| P63000 RAC1 | 80 | 11 | 0 |
| P32939 Ypt7 | 5 | 3 | 3 |

**But `ambiguous` does not mean `wrong`, and the flag must not be used as a
filter.** Two cases from the same run make the point:

- P62826 RAN's 36 are `4GMX / 4GPT / 4HAT` — "KPT185 / KPT251 / Leptomycin B in
  complex with CRM1-Ran-RanBP1". The ligand is a CRM1 inhibitor. RAN is a
  bystander and the count is **spurious**.
- P63000 RAC1's `5QQE / 5QQG` are a PanDDA fragment screen on a **RAC1-Kalirin
  complex**. Same flag, and the fragments are **genuine RAC1 precedent**.

Identical `ambiguous_multiprotein` label, opposite truth. The flag exists to
route a human to the title, not to decide.

### The same attribution bug exists one level up, on the protein side

A Foldseek hit names a **chain**. Taking the entry's accessions wholesale
imports that chain's crystallisation partners as if they were fold neighbours.

Verified: searching IL-17A returned 2XAC, "Structural Insights into the Binding
of VEGF-B by VEGFR1". Foldseek matched **chain A = P49765, VEGF-B** — a
cystine-knot cytokine, correctly. The entry also contains chains C/X = **P17948,
VEGFR1**, a receptor tyrosine kinase. Reading entry accessions pulled VEGFR1
into a cytokine's fold neighbourhood, and with it **3HNG's genuine kinase
inhibitor** — the only real drug-like small molecule in the whole IL-17A result,
and it did not belong there.

Resolve the chain instead:

```sql
JOIN pdb_v.polymer_entities pe
  ON pe.entry_id = <hit entry> AND pe.auth_asym_ids @> to_jsonb('<chain>'::text)
```

`auth_asym_ids` is `jsonb`. Use `@> to_jsonb(x::text)` rather than the `?`
operator — `?` is a placeholder in several drivers.

Fixing this dropped KRAS from 29 neighbour accessions to 19 (7 holo accessions
to 4, correctly losing Rabphilin P47709, the *effector* in 1ZBD) and IL-17A from
23 to 17 (6 holo to 4). The module reports `chain_accession_resolved` and lists
what it excluded in `other_accessions_in_entry`; when the chain cannot be
matched it falls back to entry accessions and says so.

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

Two things the obvious parse gets wrong. The chain token can be **multi-character
(`6T9D_CCC`)**, so do not assume one letter. And because targets are
`-assembly1` files, a repeated auth chain id is disambiguated with a **`-N`
suffix — `7AG0_A-2`, `1BTG_B-3`** — which is not a deposited chain id and will
not match `auth_asym_ids`. Split on `-` and keep the head. Missing this silently
cost five of twenty-five IL-17A neighbours their chain resolution; they fell
back to entry accessions without erroring.

### `alignment_length` counts gap columns, so the length filter is a *target* filter

It is not query coverage. Measured on the IL-17A run: hit 6YW8 has
`query_range [9, 93]` — 85 query residues — `target_range [1, 118]`, and
`alignment_length 123`. The 38 extra columns are gaps.

So `alignment_length >= 120` on a short query is mostly asking *the target* to
be long. It is a reasonable domain-level filter when the query is a ~170-residue
domain like KRAS (285 of 992 hits pass). It is close to useless on a small
protein: IL-17A's `8DYG` assembly resolves 93-95 residues per protomer, and the
strict filter left **2 hits out of 283** — a neighbourhood of exactly two NGF
structures, which would have been reported as "IL-17A has almost no fold
neighbours" when in fact it has 81.

The module relaxes automatically: when fewer than `relax_if_fewer_than` (5)
neighbours pass, it drops to `max(60, 0.7 * query_span)` and records the whole
decision — both thresholds, both counts, the query span — in
`filter.auto_relaxed`. **Never report a relaxed run without that block**, and
pass `--min-alignment-length` explicitly if you want the behaviour pinned.

### A multi-chain input is NOT searched as a multimer by `foldseek-search`

`foldseek-search` takes the file, but only one chain reaches the query.
Measured: `8DYG` assembly 1 was handed in as two chains, 188 residues, 1,532
ATOM records. Across all 283 hits the maximum `query_end` is **95** — one
protomer. The self-hit comes back as `8DYG_A` only; chain B never appears.

This matters exactly where it hurts most. IL-17A's site is a groove at the
**homodimer interface** and TNF-alpha's is a cavity on the **trimer 3-fold
axis**; neither is a property of one chain. A single-chain fold search cannot
be evidence about an oligomeric site.

**`foldseek-multimer-search` fixes it, has now been run, and the module routes
to it automatically when the file has more than one chain.** Same input, 8DYG
assembly 1:

| | `foldseek-search` | `foldseek-multimer-search` |
| --- | --- | --- |
| wire mode | `3diaa` | `complex-3diaa` |
| rows returned | 283 | **863** |
| query chains reaching the search | `job_A` only | **`job_A` 433 + `job_B` 430** |
| max `query_end` | 95 | **95 — identical, see below** |
| entries after the relaxed filter | 81 hits | 137 entries |
| entries matching BOTH query chains | n/a | **135 of 137** |
| TM-score | second `mode='tmalign'` search | complex TM, already in the result |
| wall clock | 2.6 s – 323 s | **405 s** |

### The measurement that exposed the single-chain limit does NOT detect it

`query_end` in a multimer result is numbered **within a protomer**, not across
the assembly. IL-17A's max `query_end` is **95 on both paths**. So the exact
diagnostic that found this bug — "188 residues went in, nothing above 95 came
back" — reads identically on a search that did use both chains.

Test `meta['query_chains']` (raw m8 column 1: `job_A`, `job_B`, …) instead.
That is the only field that distinguishes the two searches, and the shared
parser throws it away — see the next failure mode.

The upside is that the auto-relaxed length floor is unaffected: `query_span`
stays ~95, so the relaxed floor comes out at the same `max(60, 0.7*95) = 67` on
both paths, and the multimer query does *not* inflate it into a starved result.
That was the worry; it is measured and it does not happen.

### `foldseek-multimer-search` returns 26 columns and the wrapper parses 12

Its own docstring says the opposite, verbatim:

```python
FoldseekMultimerHit = FoldseekHit
"""Same shape as FoldseekHit — multimer search returns the standard 12-column M8."""
```

It does not. Verified on two inputs (the shipped 1HSG fixture, 1,830 rows; IL-17A
8DYG assembly1, 863 rows): **every row has 26 columns**, and `_parse_m8_text` —
shared with the single-chain path — reads twelve fixed positions and drops the
rest. What gets dropped is precisely the multimer information:

| column | content | fate |
| --- | --- | --- |
| 1 | **query chain** (`job_A` / `job_B`) | **dropped** |
| 2-12 | target, identity, lengths, coords, prob, E-value | parsed |
| 20 | **`complexassignid`** — groups the rows of one complex match | **dropped** |
| 21 | **complex TM-score, query-normalised** | **dropped** |
| 22 | **complex TM-score, target-normalised** | **dropped** |
| 23-24 | rotation matrix, translation vector | dropped |

So `run_foldseek_multimer_search(...).hits` is a flat list of **chain-pair
rows** that is shape-identical to a single-chain result. Two rows for one entry
look exactly like one entry hit twice. **Do not consume `.hits` directly.**
`neighbour_precedent.py` re-downloads `result_url` — a static archive, already
computed, one GET, no queue time — and parses the 26 columns itself.

The grouping semantics, verified on the 1HSG fixture: 1,830 rows → **915
`complexassignid` groups, every one of size 2, none spanning two target
entries, one TM-score per group**. On 8DYG: 863 rows → 570 groups, 293 of size
2 and 277 of size 1 (a query chain that matched a protomer with no partner
assignment). Rows arrive sorted by complex TM-score, so **list order is still
the safe ranking** — the same rule as the single-chain path.

Gotcha 1 is unchanged on `/foldmulti`: column 11 is the probability, column 12
the E-value, so `hit.evalue` and `hit.bit_score` are mislabeled identically.
Confirmed on both fixtures.

### A multimer hit names several chains — the chain-attribution fix still holds

This was the thing most likely to break, and it does not. **Each m8 row still
names exactly one target chain**, so `auth_asym_ids @> to_jsonb(chain)` is
unchanged. What changes is that one entry now appears in several rows, so a
neighbour is a *set* of matched chains and the module resolves **all** of them
rather than deduplicating down to the first.

That is the correct generalisation and it does not reintroduce the VEGFR1 bug:
P17948 (VEGFR1) is **absent** from all 42 chain accessions of IL-17A's
137-entry multimer neighbourhood, exactly as it should be.

But the entry-level *ligand* bug is untouched and multimer search makes it
easier to trip over, because a complex match pulls in bigger entries. Measured
on the full 137-entry IL-17A multimer neighbourhood, 8 entries flagged
`has_druglike_holo` and **all 8 are false**:

| entry | ligand | what it actually is |
| --- | --- | --- |
| 1RV6 | `B3P` | bis-tris propane — a **buffer**; `ligand_filter` still calls it druglike |
| 4MQW | `JEF` | Jeffamine — a **crystallisation additive**; `ligand_filter` still calls it druglike |
| 4QAF | `OMA` | a cyclopropane fatty acid |
| 4EC7 | `L44` | diacylglycerol (already known) |
| 4XPJ | `LPY` | lysophospholipid (already known) |
| 7W9M / 7W9P | `9SR` / `9SL` | guanidinium channel toxins bound to **Nav1.7**, not to the matched chain |
| 8I2G | `O6F` | a **genuine 468 Da drug** — an FSHR allosteric agonist. Foldseek matched chains **X/Y = the FSH cystine-knot hormone**; the compound binds **FSHR**, the receptor. |

8I2G is the 2XAC/VEGFR1 pattern exactly, one entry later: a real small molecule,
correctly retrieved, bound to the wrong protein in the entry. The chain fix
keeps FSHR out of `accessions`, but `has_druglike_holo` is entry-level and will
still read `true` with `attribution: ambiguous_multiprotein`. **Read
`ligand_names` and the title.** `ligand_filter` removes the cofactor and lipid
rows of that table (`L44`, `LPY`, `OMA`, and the `9SR`/`9SL` lipids alongside
them) but not `B3P` or `JEF` — see "What `ligand_filter` fixed here, and what it
did NOT" below.

### What `ligand_filter` fixed here, and what it did NOT

Superseded: this section used to argue that `$EXCL` leaks and that the fix was
to read `ligand_names` by eye. The list is gone and the classifier decides. Both
of this axis's historical false positives now classify correctly, **without the
classifier having been shown either case**:

| | ligand | old verdict | `ligand_filter` verdict |
| --- | --- | --- | --- |
| KRAS → 4PHH | `2UK` | holo (635 Da, comp_id not listed) | `cofactor` — purine + ribose + phosphate |
| IL-17A → 4EC7 | `L44` | holo (625 Da, comp_id not listed) | `lipid_or_detergent` — 21-carbon chain, 48% of the molecule |
| IL-17A → 4XPJ | `LPY` | holo | `lipid_or_detergent` — phosphate head, 12-carbon chain |

IL-17A multimer accordingly went from 23 apo / 2 holo to **25 apo / 0 holo, 0
undetermined**, which is the answer the previous run argued for by hand.

**But it opens a new gap, and it is a regression in one place.** The classifier
has no crystallisation-additive rule for small aromatic amines or polyol
buffers, so three known artifacts come back `druglike`:

| comp_id | what it is | MW / heavy atoms | verdict |
| --- | --- | --- | --- |
| `BEN` | **benzamidine** — a protease crystallisation additive | 120 / 9 | `druglike` |
| `B3P` | bis-tris propane — a buffer | 282 / 19 | `druglike` |
| `JEF` | Jeffamine — a crystallisation additive | 598 / 41 | `druglike` |

`BEN` is the regression: at 120 Da the old `MW_MIN = 250` floor excluded it, and
the classifier does not. It is the single holo call in the IL-17A **single-chain**
top 25 (2GNN, an Orf virus VEGF variant), and the defensible count there is still
**0 of 25**. `B3P` and `JEF` sit in the multimer neighbourhood's tail.

So the reason to read `ligand_names` and `rejected_ligands` has not gone away —
it has moved from cofactors and lipids, which are now handled, to bench
chemistry that happens to have a ring. Report `BEN`, `B3P` and `JEF` upstream
rather than adding a local denylist; a local list is the defect this replaced.

### The public server's latency varies by two orders of magnitude

Same query, same day: KRAS 6OIM_A took **4.4 s**, then 8.4 s. IL-17A's 283-hit
search took **323 s** on one attempt and **2.6 s** on the next, with a
`ReadTimeoutError` on the ticket poll in between (the client retried and
recovered). Multimer is slower again: IL-17A 8DYG multimer took **405 s**. Keep
`timeout_seconds=900`, expect transient connection warnings on stderr, and do
not treat a slow run as a hung one.

### Run ONE search at a time, or you will wedge the queue

**Do not parallelise Foldseek searches.** Six were launched at once (3 multimer,
3 single-chain). Exactly one completed; the other five sat in `PENDING` and
never scheduled, failing after 15 minutes with:

```
ERROR: Tool foldseek-multimer-search: failed with TimeoutError: Timeout after 900.0s
polling https://search.foldseek.com/api/ticket/PQVvYFbyRzyvpxr_nFidnRHkFdEtXfAPHnxGjg;
last status='PENDING'
```

They were still `PENDING` **85 minutes later**, long after every client had
exited — so they were not slow, they were abandoned. A freshly submitted job
went `RUNNING` within seconds at the same moment, which is how you tell the two
apart.

Two operational consequences:

- **`PENDING` for more than a few minutes is a wedged ticket, not a slow one.**
  `RUNNING` is the state that means progress. Diagnose by submitting something
  small and fresh; if that schedules instantly, the old ticket is dead.
- **Resubmitting does not retry.** The server keys tickets on content, so the
  identical file rejoins the same wedged ticket (verified: a curl submit of
  8DYG returned the ticket a running client already held). To force a fresh
  ticket, change the bytes without changing the structure — prepend a
  `REMARK` line, which Foldseek ignores.

`--cache` writes the parsed hits to JSON so re-filtering never costs another
search. **Version any such cache.** Ours stores parsed hits, so adding the
`-N` chain-suffix strip silently invalidated every existing file — the module now
carries a `cache_version` and re-runs on mismatch.

### Paperclip truncates wide cells and caps at 200 rows

`sql -s proteins` enforces a 200-row limit and a 15 s timeout, and it truncates
a long value with a literal `...`. `json_agg(t)::text` looks like a way around
the row cap and is not — a 200-row aggregate came back cut off mid-array at
~880 characters. Aggregate server-side into short columns instead
(`LEFT(title, 78)`), and rank with a window function when you need N per group.

Parse the output by the `---+---` rule's `+` positions, not by splitting on
`|` — titles contain pipes.

Three more query shapes that fail, all measured on `pdb_v.entry_ligands`:

- **`comp_type` in a WHERE clause times out.** 6 ms without it, >120 s with it,
  same 25 entries. See the `comp_type` section.
- **`IN (SELECT ...)` is the fast plan; a direct JOIN is not.** For P15692
  (VEGF-A, 75+ entries), `WHERE l.entry_id IN (SELECT entry_id FROM s)` returns
  in **9 ms**, while `FROM structures_by_accession st JOIN entry_ligands l ON
  l.entry_id = st.entry_id WHERE st.accession = ...` **times out**. Same rows,
  same accession.
- **One accession at a time, and even then expect one to fail.** Sweeping the
  17 accessions of the IL-17A single-chain neighbourhood as one `unnest` array
  timed out; per accession, 16 of 17 returned in ~1.4 s and **P67861 timed out
  reproducibly at 120 s**. So the sweep retries and, on persistent failure,
  marks that accession `lookup_failed` / `holo_determined: false` rather than
  recording it as having no drug-like ligands. A timeout is not a zero.

`neighbour_precedent.py` also short-circuits the accession aggregation entirely
when nothing classified drug-like: the `n_dl > 0` filter is then unsatisfiable,
and running it anyway costs 120+ s to prove an already-known empty result.

### Untested, do not assume

- **Foldseek local mode** — no binary present; remote is the only tested path.
  `search_mode='local'` also requires `local_db`, which we do not have.
- **`mode='complex-tmalign'`** — never run. The multimer path takes its
  TM-scores from column 21 of the `complex-3diaa` result instead, so there has
  been no reason to try it.
- Databases other than `pdb100`.
- **The relaxed alignment-length floor** (`0.7 * query_span`, min 60) is a
  judgement call, not a calibrated threshold. It was chosen so IL-17A returned a
  neighbourhood at all. It has one sanity check — the 81 hits it admits are the
  cystine-knot superfamily, which is the correct fold answer for IL-17A — and no
  other validation. The strict 120 floor is the verified one. It has now been
  checked on the multimer path and behaves identically (`query_span` is
  per-protomer, so the floor does not move), but it is still uncalibrated.
- **The multimer path's ranking has one target's worth of evidence.** Rows come
  back sorted by complex TM-score and that ordering looked right on IL-17A
  (IL-25 first, then the neurotrophins). It has not been checked against a case
  where the correct answer is known to be a low-TM complex.
- **`complexassignid` groups of size 1** — 277 of 8DYG's 570 groups. Read as "a
  query chain matched a target chain with no partner correspondence", but the
  server's assignment rules were not confirmed against Foldseek's source. The
  module reports `n_query_chains_matched` per neighbour so a size-1 match is
  visible rather than assumed away.

## Output

Fill the dossier's `structure` block: chosen tier, entry ID, resolution,
biological unit, the ligand with its heavy-atom count and whether it is
drug-like, total and holo counts, and the ensemble actually used. Fill
`structural_neighbour_precedent` from step 5. Record the as-of cutoff if one was
applied and how many entries it removed.

For `structural_neighbour_precedent` specifically, carry through: the TM-score
(never the raw `evalue`/`bit_score`), **both** holo counts per neighbour with
the entry-level one named as an upper bound, the ligand *names* not just
comp_ids, and `filter.auto_relaxed` whenever it fired. If the query was an
oligomer, state that only one chain was searched.

A neighbourhood with no small-molecule precedent is a real and reportable
finding — it was the answer on both calibration targets — not a retrieval
failure. Do not pad it.
