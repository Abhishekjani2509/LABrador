---
name: pocket-scan
description: >
  Detects and measures ligand-binding pockets across an ensemble of structures,
  sweeping fpocket clustering, and quantifies whether a site is cryptic and by
  which mechanism (backbone collapse vs steric occlusion). Reports volume with
  its spread as the primary number and druggability only as a range. It does NOT
  decide whether a target is druggable, does NOT rank targets, and does NOT
  interpret a low score as evidence against tractability.
---

# pocket-scan

Pocket geometry over an ensemble, with the method's blind spot measured rather
than assumed.

Two calibrations drive everything below. Both were run in-repo; the numbers are
ours, not literature.

## Setup

Runs inside the Modal CPU image, which carries `fpocket` (conda-forge, 4.2.3),
**P2Rank 2.5.1** (MIT, needs JDK 17 — Java 11 dies with
`UnsupportedClassVersionError`, class file v61), and `proto-tools`. The fpocket
binary self-reports `fpocket 4.0` in its banner — cosmetic upstream mismatch,
not a wrong install.

## fpocket detects, PRANK ranks

Keep these jobs separate in your head. fpocket's alpha-sphere *detection* is
sound; its *ranking* is the weak link, and its druggability score is a
three-descriptor logistic regression fitted on 21 positives.

The best-recall configuration in the LIGYSIS benchmark of 13 predictors is
**fpocket detection + PRANK rescoring** — 60% top-(N+2) recall, ahead of
DeepPocket at 58% and P2Rank standalone at 52%. Note that even the winner
recovers only 60% of known sites; there is no method here that finds everything.

Measured on isolated fixtures:

| site | fpocket rank | PRANK rank |
| --- | --- | --- |
| 6OIM switch-II (sotorasib) | 9 | **2** |
| 2AZ5 SPD304 | 2 | **1** |
| SPD304 site across 4 apo TNF-alpha trimers | druggability noise | rank 2-3 in all four |

**But do not oversell this — on our own pipeline it has not yet helped, and
once it hurt.** Two things found on integration:

- Our fpocket invocation already ranks 6OIM's switch-II pocket **#1**, so there
  is nothing to promote. The rank-9 figure came from a different invocation
  producing 11 pockets against our 9. The mechanism is proven; on this
  structure it has no work to do.
- At 6OIM D=1.6 PRANK **demotes** the true site, fpocket rank 1 to PRANK rank 3.

So rescoring is not uniformly an improvement. It is a second, independently
trained opinion over the same geometry — valuable because two methods
disagreeing is information, not because one is right.

`prank_rank` is reported **alongside** fpocket's rank, never replacing it. Read
a gap between them as a flag for manual attention, **not** as evidence that
PRANK found something fpocket missed — on our structures it points the other way
at least as often.

### Two P2Rank gotchas, both confirmed by direct test

**The `probability` column is only calibrated in `predict` mode, not `rescore`.**
In rescore mode the true SPD304 site scored 0.011 while a large decoy scored
0.783 — the ranking is usable, the probability is not. `predict` mode on the
same site gives 0.735. So use `rescore` for within-structure ranking and a
separate `predict` run if you need a cross-structure comparable score.

**`-chains A` is silently ignored by `predict`.** Passing it returned all 3,483
atoms of a trimer and an identical score. The documentation shows the flag; it
does nothing. Use the `chains` column of a dataset (`.ds`) file instead.

Also: `rescore` emits no `_residues.csv` — P2Rank only lays SAS points over the
surface in `predict` mode. And skip the `conservation_*` models, which need
HMMER and MSAs; `default` and `rescore_2024` use structure-derived features only.

## Procedure

### 1. Build an ensemble, not a structure

**One structure is not a measurement.** Query every PDB entry for the accession
(`pdb_v.structures_by_accession`), classify each as holo or apo using
`pdb_v.entry_ligands`, and take a set — all of them if few, otherwise the best
resolution across distinct crystal forms. Record which entries you used.

### 2. Prepare each

Protein only, altloc A or blank, hydrogens stripped (high-resolution entries
ship riding hydrogens that skew alpha-sphere volumes). Record missing residues.

**Chain selection is per-target, not a default.** KRAS is a monomer — one chain.
TNF-alpha's site sits on the trimer's 3-fold axis and **vanishes if you take one
chain**. Ask where the site is before deciding, and record the choice.

### 3. Sweep clustering — never pin it

```bash
fpocket -f <prepared>.pdb -D 1.6
fpocket -f <prepared>.pdb -D 2.4
```

Report both. See failure modes for why a single value is a coin flip.

### 4. Measure, in priority order

1. **Volume** at the site, with its spread across the ensemble — the primary number.
2. **Druggability** as a *range* across D and across structures — never a single figure.
3. Hydrophobic density, lining residues with chain IDs.

### 5. Establish which pocket matters — apo is the normal case

**Assume no holo structure.** Most targets worth asking about are apo, cofolded,
or a bioemu ensemble; a bound drug-like ligand is the lucky exception, not the
baseline. A procedure that only works on holo structures is a validation harness,
not a working method.

Ranked by strength, use whichever routes are available and say which you used in
`tractability.site_hypothesis_basis`:

**(a) Holo ligand site — only when it exists.** Residues within 5 A of a
drug-like ligand; report Jaccard against the detected pocket. Strongest, rarely
available.

**(b) Persistence across the ensemble — the primary signal when nothing is
bound.** Run every conformer, map pockets between them by residue overlap, and
rank by *how often a pocket appears*, not by its best score. A pocket found in
most conformers is credible; one appearing in a single frame is noise. This is
what the TNF-alpha ensemble showed: over five apo structures the same site held
volume to +/-16% while druggability swung 650-fold. Persistence and volume are
the reproducible quantities.

Use **mdpocket** (ships with fpocket) rather than N separate fpocket runs when
you have a real ensemble — a bioemu sample set or an MD trajectory. It computes
pocket *density* over the whole set and is built for exactly this, where
per-frame fpocket calls give you a pile of unaligned results to reconcile
yourself.

**(c) Site transfer from a structural neighbour.** Foldseek the apo structure,
find a neighbour that *does* have a drug-like holo entry, superpose, and map its
ligand site onto your model. This manufactures a site hypothesis where the target
itself has none. Flag it clearly as transferred, with the source PDB ID and the
alignment quality — it is a hypothesis, not a measurement.

**(d) Curated annotation.** UniProt `Binding site` features give residue
positions for cofactor and substrate sites. Report the fraction recovered. Weak
on its own — it tells you where the *natural* ligand goes, which is often not
where a drug would.

If none of (a)-(d) apply, report the top pockets by persistence and say plainly
that no site hypothesis could be established. Do not silently promote the
highest-druggability pocket; on an apo structure that number is nearly
uninformative.

### 5b. Cofolded and bioemu ensembles carry an extra caveat

A pocket that appears only in predicted or sampled conformers, and in no
experimental structure, is a prediction about a pocket — two inferences deep.
Record it, mark `structure.tier` accordingly, and do not let it carry the same
weight as a site seen in a crystal.

For **cofolded** structures specifically: a cofold produced *with* a ligand has
had the pocket opened by the ligand you supplied. Finding a pocket there is
close to circular. Where a crystal structure also exists, score the cofold
against it first (`structure.cofold_control`) — if it cannot reproduce a known
structure for this target, its pockets are not evidence.

### 6. Measure cryptic risk — do not flag it from tier

Where both apo and holo exist, superpose on core C-alpha excluding the mobile
region, place the ligand in the apo frame, and compute:

- **max backbone C-alpha displacement at the site**
- **clash attribution** — backbone vs side-chain vs another subunit
- **free-volume fraction** of the ligand in the apo frame

Then classify the mechanism (table below). Where no holo exists, report the
ensemble backbone spread at the site instead and say the mechanism is
undetermined.

## Failure modes

### There is no correct fixed `-D`, and pinning one produces false negatives

`-D 1.6` was tuned on KRAS, where the default `-D 2.4` fuses the nucleotide and
switch-II sites into one 1540 A^3 mega-pocket scoring 0.886 — a cavity no
molecule occupies.

Applied to TNF-alpha, that same pin gives **druggability 0.002 at the site of a
co-crystallised 570 Da ligand in 2AZ5**. A false negative on a *holo* structure.
Diagnosis with `-i 5`: the channel fragments into alpha-sphere clusters of 15,
12 and 5, and in the apo the cluster sitting exactly on the ligand position has
12 spheres — below fpocket's default `-i 15` minimum — so it is **discarded
silently**. The same site at `-D 2.4` scores 0.346, rank 2 of 14, Jaccard 0.74.

Sweep. Report the range. A volume above ~1000 A^3 means sites have merged;
"not detected" at one D and present at another means fragmentation, not absence.

### Druggability is not reproducible across an ensemble; volume is

Five apo TNF-alpha trimers, same site:

| | range | spread |
| --- | --- | --- |
| Volume | 206.7–309.2 A^3 | +/-16% |
| **Druggability** | **0.001–0.651** | **650x** |

1A8M alone scores 0.651 and would have you calling the site druggable. The other
four sit at 0.001–0.008 and would have you calling it dead. Same site, same
protein, same protocol.

**Never build a verdict on a single-structure druggability score.** Volume
carries the signal; druggability carries the noise.

(Honest caveat on that ensemble: 1TNF is the only wild-type apo entry. Two of the
four others carry K98R, which lines the axial channel, so their numbers are
contaminated. Report ensemble composition, not just the spread.)

### Geometric scoring is blind to cryptic pockets — measured, on KRAS

| | 6OIM (holo) | 4OBE (apo) |
| --- | --- | --- |
| switch-II druggability | 0.708 | **0.000** |
| rank | 1 of 9 | 4 of 5 |
| volume | 585 A^3 | 230 A^3 |
| coverage of true site | 17/22 | 7/22 |

Not merely under-scored — physically collapsed. Superposing apo on holo (0.86 A
RMSD over 128 core C-alpha) and placing sotorasib gives 6 heavy-atom clashes
under 2.0 A against a self-control baseline of 1; switch-II backbone moves up to
8.8 A at Glu63.

**A low score on an apo structure means the measurement was not made.** Say it
every time, not once.

### "Cryptic" is two different mechanisms and they need different escalations

| | KRAS | TNF-alpha |
| --- | --- | --- |
| max C-alpha displacement | **8.8 A** | **1.62 A** |
| what blocks the ligand | backbone — site collapsed | 40/66 clashes from the displaced subunit; all 26 others are Tyr119 **side-chain** atoms. **Zero backbone clashes.** |
| ligand free volume, apo | — | 62.1% intact trimer / 85.3% subunit removed / **99.8%** with two Tyr119 rotamers trimmed |
| mechanism | **backbone collapse** | **steric occlusion** |
| what would resolve it | dynamics — mixed-solvent MD, bioemu | rotamer sampling; for oligomers, test the subunit-removed state |

Backbone displacement separates these robustly at every D tested. Druggability
does not. Build the risk signal on geometry.

The subunit-removed control is cheap and decisive for oligomers: delete the third
chain from each apo TNF-alpha trimer and all five immediately recover the SPD304
pocket at 281.8–546.0 A^3 against a holo dimer value of 312.5. The site is
pre-formed in every apo structure; only the subunit stands in it.

### A holo ligand may be a frequent hitter, not a drug

2AZ5's ligand — chemical component **`307`**, not "SPD304" as PDB titles suggest
— is a bis-electrophilic compound widely regarded as promiscuous and cytotoxic.
Its site scores 0.346 at best, well under KRAS's 0.708, which is consistent with
a micromolar tool compound rather than a drug. **A holo structure is evidence
that something bound, not that the site is drug-tractable.** Check what the
ligand is.

### An asymmetric unit is not a biological assembly

2AZ5's ASU is **four chains — two independent TNF dimers**, each with its own
copy of `307`. REMARK 350 calls it "tetrameric", which is crystal packing. Run on
the ASU and the top-ranked pocket (0.298) is a pure crystal-contact site at a
B–D interface. Pick the biological unit deliberately and record it.

### Apo does not mean ligand-free

4OBE is apo only with respect to *drug-like* ligands — it carries GDP and Mg.
1TNF has no HETATM records at all. "Apo" is a property relative to the site being
asked about. State which ligands are present rather than using the label.

### Missing residues near the site invalidate the pocket

6OIM chain A is missing 105–107, far from switch-II, so it does not matter there.
A gap adjacent to the site changes its shape, volume, and enclosure. Record
missing residues and whether they neighbour the pocket.

## Output

Fill the dossier's `tractability` block: volume with ensemble spread as the
primary number, druggability as a range across D and across structures, lining
residues with chain IDs, overlap with any annotated or ligand-derived site,
`cryptic_pocket_risk`, `cryptic_mechanism`, and a `caveat` naming what this run
could not see. Include the method block — tool, version, every D value swept,
and which PDB entries formed the ensemble.

Never return a druggability figure without its structure tier, its D value, and
its ensemble spread beside it. Separated from those, the number is not
interpretable.
