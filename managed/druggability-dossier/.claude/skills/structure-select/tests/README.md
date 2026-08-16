# `ligand_filter` accuracy harness

**Every accuracy figure quoted for `ligand_filter.py` anywhere in this repo is
produced by running a file in this directory.** Before 2026-08-15 they were not:
the harnesses and their data lived only in session scratch under `/private/tmp`,
so the figures were unverifiable the moment that session ended. That is the same
"not followable from this checkout" failure that let the retracted volume
separation stand as long as it did. It is closed here.

## Run it

```bash
cd .claude/skills/structure-select/tests
python3 test_v2.py            # the master run — every figure, one command
python3 test_ligand_filter.py # ground-truth set alone, with the historical re-run
python3 test_holdout.py       # blind held-out sample alone
```

Pure stdlib, Python 3.13, **fully offline**. `offline.py` forces
`ligand_filter`'s default source offline so no Paperclip call is made and no
network is touched. Nothing here depends on the row cap, the `cli_cwd` bug, or
any live backend — which is the point.

## Measured, 2026-08-15, from this checkout

| figure | value | produced by |
| --- | ---: | --- |
| original ground-truth set | **259/262 = 98.9%** | `test_ligand_filter.py`, `test_v2.py` block `gt262` |
| + 9 chemistry cases | 9/9 = 100% | `test_v2.py` block `gt_add` |
| + 9 named-entry context cases | 9/9 = 100% | `test_v2.py` block `context` |
| **combined ground truth** | **277/280 = 98.9%** | `test_v2.py` |
| blind held-out sample | **61/70 = 87.1%** | `test_holdout.py`, `test_v2.py` |
| **held-out false positives** | **0/70 = 0.0%** | `test_holdout.py`, `test_v2.py` |

The three standing misses are `BTN` (biotin → `druglike`), `ACE` and `NH2`
(polymer capping groups → additive / ion). `ACE` and `NH2` are **correct once a
`StructureContext` is supplied** — the CCD lists them in `_entity_poly_seq`, so
they are residues, not ligands. The context block covers `NH2@8B9P` for exactly
this reason and passes.

All 9 held-out disagreements run in the conservative direction: nothing that was
really a cofactor, lipid or additive was called drug-like. That asymmetry is the
deliberate bias — a false negative costs a holo structure, a false positive
*invents* one, and inventing one is what produced all four historical bugs.

## Two named boundaries on the zero

The zero is a statement about **that 70-component sample**, not about the
classifier. Two counterexamples exist and are not in it:

- **TNF 5UUI's `MTN`** spin label — a genuine false positive that no chemistry
  rule can fix, because the disqualifying fact is *why the component is there*,
  not what it is made of.
- **`LFI`**, a peptide-conjugated crosslinker — the first false positive actually
  measured against the held-out result. Now closed by `StructureContext`, and
  the fix is regression-tested in the `context` block.

Quote the zero with both boundaries attached.

## What is in here

| file | role |
| --- | --- |
| `test_v2.py` | **master runner.** Ground truth + additions + context + held-out in one pass, with the confusion matrix and the flag assertions. |
| `test_ligand_filter.py` | the 262-component ground-truth set, plus the four historical failures re-run as holo/apo calls and the genuinely-holo controls. |
| `test_holdout.py` | the 70-component blind sample and its by-name adjudication. |
| `gt_additions.py` | the 9 chemistry + 9 context cases added by the polymer-conjugate work, with `FLAG_REQUIRED` / `FLAG_FORBIDDEN`. |
| `offline.py` | forces the chem-comp source offline. |
| `chemcomps.json` | cached `pdb_v.chemcomps` rows for the ground-truth set. |
| `extra_recs.json` | cached rows for the added components. |
| `holdout.json` | cached rows for the blind sample. |
| `entry_counts.json` | `n_pdb_entries` per comp_id, for the ubiquity rule. |
| `structures/*.cif` | the 7 mmCIFs the context cases build a `StructureContext` from: 8QFZ, 8B9P, 3QN7, 9Q8N, 5V2P, 6OIM, 4G5J. |

## How the sets were drawn — read this before adding a case

**Ground truth is the expected verdict assigned from chemistry knowledge, never
from the classifier's output.** The 262 set is built from sources the classifier
was never shown: every member of `modal_app.COFACTORS` and `NON_LIGANDS`, every
member of `neighbour_precedent.EXCLUDED_LIGANDS`, the four historical failures,
and known true-positive inhibitors, fragments, peptides, steroids and ions. A
handful of labels were corrected after reading the CCD `name` field — each is
annotated in place with the CCD name that justifies it, and each was corrected
*before* the classifier's answer was consulted.

**The held-out 70 were drawn blind** by `ORDER BY MD5(comp_id) LIMIT 70` over
`pdb_v.chemcomps` — deterministic and unrelated to anything in the tuning set —
then adjudicated by name before the rule set was frozen. Two defects it exposed
were fixed (`9CP`'s sulfamate misread as a Good's buffer; abamectin and
myxopyronin B misread as lipids by a bare chain-length test).

The 9 context cases each name a real entry and a real accession, because a
crosslinker has **no context-free right answer** — putting one in the chemistry
block would be inventing a label the classifier is not allowed to reach. The two
covalent-inhibitor controls (`MOV`@6OIM, `0WN`@4G5J) are in that block precisely
so the fix cannot buy its false-positive reduction with a false negative on a
real covalent drug.

## If a number here disagrees with a number quoted elsewhere

**The measured value wins.** Re-run `test_v2.py`, quote what it prints, and fix
the citation. The figures are cited in six places outside this directory; the
list is in `../SKILL.md` under "Where these figures are quoted".
