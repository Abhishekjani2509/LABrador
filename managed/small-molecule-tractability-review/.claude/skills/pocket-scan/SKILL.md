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

**`mdpocket` is already installed** — it ships inside the same conda package as
`fpocket`, so there is nothing to add. It is not an optional extra here; it is
how a site gets fixed across an ensemble (see below).

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

**Read the third row narrowly.** "The SPD304 site" in those apo structures was
assigned by the residue-number matching heuristic that is now **withdrawn**
(failure modes below): mdpocket places that matched pocket 7.7 A from the real
SPD304 site. So that row says PRANK ranks *a* consistently-detected pocket
highly across apo trimers — it does not say PRANK found the SPD304 site. The two
holo rows are unaffected, because there the site is defined by the bound ligand
rather than by matching.

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

## mdpocket: fix the site by construction, not by matching

Across an ensemble, the hard part is not detecting pockets — it is asserting
that two detected pockets are *the same site*. Matching them after the fact on
shared residue numbers is the single worst thing this skill has done, and the
failure modes below record exactly how it broke. mdpocket removes the step:
you define the site once, as a grid, and apply that one definition to every
superposed structure.

Two modes, both verified:

```bash
# mode 1 — exploration: pocket density over the whole set
micromamba run -n druggability mdpocket --pdb_list list.txt -o PREFIX

# mode 2 — characterization: one fixed site, measured per structure
micromamba run -n druggability mdpocket --pdb_list list.txt \
    --selected_pocket sel.pdb -o PREFIX
```

**Mode 1 (exploration)** emits `PREFIX_dens.dx` and `PREFIX_freq.dx` on a 1.0 A
grid, plus isosurface PDBs. Use it to find where a pocket is and how often it is
open.

**Mode 2 (characterization)** emits `PREFIX_descriptors.txt` with **one row per
snapshot and 41 columns**. This is the mode that makes an ensemble comparable,
because every row was measured inside the same grid.

Runtime is **0.85 s for five ~3.5k-atom trimers**. Compute is not a factor in
this decision — use it whenever there is more than one structure.

### What it bought, measured

Fixing the site by construction instead of by post-hoc matching cut the
across-ensemble CV on the TNF-alpha apo set:

| how the site was established | CV across the ensemble |
| --- | --- |
| post-hoc residue-number matching | 27.8% |
| **site fixed by construction (mode 2)** | **10.2%** |

The matching heuristic inflated the spread **2.7-fold**, and essentially all of
that came from the single structure that matched a pocket 12 A away from the
others. The spread we were reporting was mostly the matcher, not the protein.

### KRAS is the richer case, because the pocket only partially collapses

TNF-alpha gives a clean zero (below), which is honest but not very informative.
KRAS shows what mode 2 is actually for:

| mdpocket characterization | 6OIM holo (ligand stripped) | 4OBE apo |
| --- | --- | --- |
| volume | **1152.3 A^3** | **452.1 A^3** |
| alpha spheres | 500 | 182 |
| mean local hydrophobic density | **185.8** | **12.6** |

And mode 1 over the same two structures localises *which part* of the site goes
away: **179 grid points at frequency 1.0** — the nucleotide-adjacent shelf,
present in both — against **322 points at frequency 0.5** — the cryptic
switch-II sub-pocket, present only in the ligand-bound conformer. The site does
not vanish; a specific sub-pocket does, and mdpocket says which one.

(With N=2, "frequency 0.5" is presence-in-one-of-two, not a frequency. It is
being used here to *localise*, not to quantify how often the pocket is open.
See failure mode 3.)

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
bound.** Run every conformer and rank by *how often a pocket appears*, not by its
best score. A pocket found in most conformers is credible; one appearing in a
single frame is noise. Persistence and volume are the reproducible quantities.

**Do not establish "the same pocket" by matching residue numbers across
independently detected pockets.** That step is withdrawn, and it took a headline
finding down with it — see the failure modes. On any homo-oligomer it cannot
work even in principle.

Instead: superpose the ensemble, define the site once, and push that one
definition through every structure with **mdpocket** characterization mode.
Exploration mode over the same set gives pocket *density*, which is the honest
form of "how often is it open". Both are covered above. Per-frame fpocket calls
leave you a pile of unaligned results to reconcile by hand, and the
reconciliation is the part that breaks.

If for some reason you must match pockets post hoc, **report the matched
centroid distance across the ensemble**, not an overlap fraction. Two pockets
sharing residue numbers can be 12 A apart and the overlap score will not tell
you.

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

### VOID: the 650-fold druggability spread across five apo TNF-alpha trimers

Earlier versions of this file reported, in two places, that five apo TNF-alpha
trimers held volume to +/-16% at "the same site" while druggability swung
**650-fold** (0.001 in 2ZJC to 0.651 in 1A8M, volumes 206.7–309.2 A^3). **That
figure is WITHDRAWN — and so is the volume range printed beside it.** Both came
out of one step: matching pockets across structures on shared residue *numbers*.

mdpocket over the superposed ensemble showed what that matcher was actually
tracking:

- the matched pocket's centroid sits **7.7 A** from the SPD304 site it claimed
  to be measuring;
- it was not even self-consistent — **1TNF matched a pocket 12.2 A away** from
  where the other four matched. "The same site" spanned 12 A across five
  structures;
- the cause is structural, not a threshold to tune. A 19-residue reference on a
  homotrimer collapses to only **11 distinct residue numbers**, because the
  three protomers triplicate them. Throw away chain identity and a C3-symmetric
  site is **unresolvable in principle**.

The pocket it matched is real, just not the one claimed: an **on-axis cavity
lined symmetrically by Q61/K98/P117/I118/Y119 from all three chains, 107 A^3 at
frequency 1.0**. Well-formed, reproducible, and the wrong pocket.

Do not cite 650x, 651x, +/-16%, or 206.7–309.2 A^3. If you meet them in an older
dossier, they are void. What replaces them is below.

Note what does *not* change: **never build a verdict on a single-structure
druggability score**, and volume remains the reproducible number while
druggability remains a 3-descriptor regression fitted on 21 positives. That
claim never rested on the 650x figure — it rests on the KRAS holo/apo collapse
and on the provenance of the score itself.

### What replaces it: the spread was mostly the matcher

Fixing the site by construction rather than by post-hoc matching cut the
across-ensemble CV from **27.8% to 10.2%** — a **2.7-fold** inflation,
essentially all of it contributed by the one structure that matched 12 A away.

**A pocket-matching step is itself a measurement, and it needs its own
controls.** It was never treated as one, which is why a 12 A error survived to
become a headline number.

### At the true SPD304 site, the honest answer is that there is no pocket

mdpocket returns **0.00 A^3 in four of the five apo structures**. Not a low
score — nothing.

That is consistent with the physics rather than in tension with it. Place the
ligand into each *intact* apo trimer and you get **27–29 heavy-atom clashes
under 2.0 A**, minimum interatomic distance **0.28–0.53 A**, attributed
**identically in all five** to the third protomer (chain C: S60, Y119, L120,
G121) plus the Tyr119 triad. SPD304 does not bind this site as a trimer; it
binds after displacing a subunit. Delete that third chain and every apo
structure recovers the pocket immediately (281.8–546.0 A^3 — see the
subunit-removed control below). Both measurements say the same thing: the site
is pre-formed, and a protomer is standing in it.

The part worth carrying to other targets is the *behaviour*, not the number:
**mdpocket returned 0.00 rather than silently substituting a nearby pocket.**
The residue-number matcher, handed the same structures, returned a confident
value for a cavity 7.7 A away. A refusal instead of a wrong number is the entire
defensibility gain here.

(Ensemble composition, **corrected**: **four** of the five apo entries differ
from wild type, not three — 1A8M is R31D, 2ZJC is **both** K98R and R31A, 2E7A
is K98R, 5TSW is Y56F. Only 1TNF is wild-type at all three positions. And the
mutation caveat does **not** attach to the SPD304 site: in holo 2AZ5 the nearest
Lys98 heavy atom is **8.74 A** from ligand `307`, and residue 56 is **7.82 A**.
Neither is in the 5 A shell — residue 98 does not line the SPD304 site at all.
The K98R concern is real, but it belongs to the *other* pocket, the on-axis
cavity above. Report ensemble composition either way.)

### mdpocket's own failure modes, all confirmed by direct test

It is the right tool and it is quiet about being wrong. Five things:

**1. Silent frame dropping — check this before reading any grid.** A missing
file in the list prints a message and then **exits 0**. The resulting `freq.dx`
is normalised over the frames that actually ran, so a dropped structure
**silently inflates every frequency in the grid** — the failure looks like a
stronger result. The only detector is that `time.txt` carries exactly one line
per processed frame. **Assert `len(time.txt) == len(list.txt)` before reading
any grid.** Non-negotiable.

**2. It does not superpose.** Unaligned input exits 0. Two *different proteins*
in one list also exit 0, with a non-fatal warning. Superposition and site
definition are the caller's job, and nothing downstream will notice if you skip
them.

**3. Frequency is quantised at 1/N.** With N=5 the only attainable values are
{0, 0.2, 0.4, 0.6, 0.8, 1.0}, so a genuine 1-in-5 signal is indistinguishable
from single-structure noise. **Require N >= 10 structures, or do not report a
frequency at all** — report presence/absence and say so.

**4. `_all_atom_pdensities.pdb` uses the first structure's topology only.** It
is meaningless whenever atom counts differ across the ensemble, which is the
normal case for crystal structures with different disordered regions.

**5. Superposing a homo-oligomer requires searching chain permutations.** For a
C3 trimer the three cyclic mappings agree within **0.03 A**, while the three
anticyclic ones give **~22 A** and must be rejected. Take the best mapping; do
not assume A→A, B→B, C→C.

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
| what blocks the ligand | **side chains, carried in by a collapsing loop** — 12 clashes at 2.0 A, all side-chain (Arg68, Met72, His95). Backbone atoms first appear at 2.5 A. | 40/66 clashes from the displaced subunit; all 26 others are Tyr119 **side-chain** atoms. **Zero backbone clashes.** |

**Both columns show side-chain clashes, so clash composition does not separate
these mechanisms — classify on C-alpha displacement instead.** KRAS's switch-II
loop moves 8.8 A and carries its side chains with it, so the atoms sitting *in*
the site are side-chain even though the *cause* is backbone motion. Keying the
classification on which atoms clash would label KRAS as side-chain occlusion and
hand the canonical nanomolar target a micromolar prognosis.
| ligand free volume, apo | — | 62.1% intact trimer / 85.3% subunit removed / **99.8%** with two Tyr119 rotamers trimmed |
| mechanism | **backbone collapse** | **steric occlusion** |
| what would resolve it | dynamics — mixed-solvent MD, bioemu | rotamer sampling; for oligomers, test the subunit-removed state |

Backbone displacement separates these robustly at every D tested. Druggability
does not. Build the risk signal on geometry.

The subunit-removed control is cheap and decisive for oligomers: delete the third
chain from each apo TNF-alpha trimer and all five immediately recover the SPD304
pocket at 281.8–546.0 A^3 against a holo dimer value of 312.5. In the *intact*
apo trimer the same site measures **0.00 A^3** by mdpocket in four of five — so
"pre-formed" is a statement about the two-chain state. The site is there; the
third protomer is standing in it.

The clash attribution is what makes that reading a measurement rather than a
story, and it repeats across the whole ensemble: placing the ligand into each
intact apo trimer gives **27–29 heavy-atom clashes under 2.0 A** (minimum
interatomic distance 0.28–0.53 A), attributed **identically in all five** to
chain C — S60, Y119, L120, G121 — plus the Tyr119 triad. Five independent
crystals, one answer.

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

When the ensemble number came through mdpocket, the method block also carries
**how the site was established** (grid definition, not residue matching), the
**number of frames actually processed** against the number submitted, and — if
any frequency is reported — **N**. A frequency from N < 10 is not reportable as
a frequency; give presence/absence instead.

Never return a druggability figure without its structure tier, its D value, and
its ensemble spread beside it. Separated from those, the number is not
interpretable.

And a volume of **0.00 A^3 is a result, not a failed run.** Report it. It is the
one output that cannot be an over-claim, and substituting the nearest pocket
that *does* have volume is how this skill got a headline finding wrong.
