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

**Settled at n = 70 ligand-anchored measurements across 8 targets: PRANK
promotes 79% and demotes 1%.** Median rank **5 → 1**; top-3 recall **37% → 91%**.
The single demotion is the known KRAS case below. Earlier versions of this file
said rescoring "has not yet helped, and once it hurt" — **that is falsified** and
is void.

Supporting per-target runs, in the order they were measured:

- **IL-17A** promoted the ligand site in all three structures: fpocket rank 6 to
  PRANK 2, rank 5 to PRANK 2, rank 11 to PRANK 1.
- **NLRP3**, the clearest single case: fpocket ranked the true site 3rd to 34th,
  **median 18**. PRANK put it at **rank 2 in 11 of 14 instances and never worse
  than 4.**

**But PRANK rank is a site finder, not a quality score, and used as the latter it
is inverted.** As a *druggability* classifier its AUC is **0.25** — worse than
chance, in the systematic direction — because on a target with no ligand to
anchor to, the top-ranked pocket is top-ranked by construction, so "rank 1"
carries no information about whether the site is good. **It finds sites. It says
nothing about their quality.** Never let a PRANK rank stand in for a
druggability judgement.

**The KRAS negative still stands and is not deleted.** A method that helps on
three targets and hurt on one is a more useful thing to know than a method that
always helps:

- Our fpocket invocation already ranks 6OIM's switch-II pocket **#1**, so there
  was nothing to promote. The rank-9 figure came from a different invocation
  producing 11 pockets against our 9. On that structure it has no work to do.
- At 6OIM D=1.6 PRANK **demotes** the true site, fpocket rank 1 to PRANK rank 3.

Read the two together: rescoring helps most where fpocket's own ranking has
buried the site (IL-17A ranks 5-11, NLRP3 median 18) and can hurt where fpocket
already has it at rank 1 (KRAS). It is not uniformly an improvement, and it is
not a tiebreaker. It is a second, independently trained opinion over the same
geometry — valuable because two methods disagreeing is information, not because
one is right.

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

| how the site was established | volume CV across the ensemble |
| --- | --- |
| post-hoc residue-number matching | ~28% (measured 28.1% at D=1.6) |
| **site fixed by construction (mode 2)** | **~10%** (measured 9.9%) |

The matching heuristic inflated the spread roughly **2.8-fold**, and essentially
all of that came from the single structure that matched a pocket 12 A away from
the others. The spread we were reporting was mostly the matcher, not the protein.

**Two significant figures, never three.** fpocket estimates pocket volume by
Monte Carlo and mdpocket inherits it. Three *identical* reruns of one 5-structure
ensemble gave volumes of 280.6 / 276.1 / 274.6 A^3 and CVs of 12.1 / 11.3 /
10.8%; the deployed run gave 9.9%. So **about 1 percentage point of any CV here
is fpocket's own volume estimator**, and a CV difference smaller than that is not
a difference between sites. An earlier version of this table read "27.8% to
10.2%" — the improvement is real, the third digit never was.

**This CV was measured on `site_from_density`, which is not the ligand site.**
See the next section. It measures reproducibility, not correctness.

### The two site definitions, and which one is the pocket

`pocket_scan` returns `mdpocket.sites` with up to two entries, and **fixing the
site by construction buys reproducibility, not correctness**. It guarantees every
structure was measured at the same grid points; it says nothing about whether
those points are the site anyone asked about.

| key | definition | is it the pocket? |
| --- | --- | --- |
| `site_from_ligand` | grid points within 3.0 A of the holo ligand, transferred by superposition | **yes**, by construction |
| `site_from_density` | largest connected cluster of grid points open in *every* structure | **not necessarily** — the most *persistent* cavity |

On the apo TNF-alpha ensemble the density site's centroid sits **7.73 A** from
the transferred SPD304 ligand. It is the on-axis cavity — real, well-formed,
reproducible, and **precisely the pocket the withdrawn residue-number matcher
reported as "the SPD304 site"** (see the failure mode below). Detecting it is not
the error. Calling it the ligand site is, and doing so reproduces the retracted
finding in a form that looks like a result.

So, before quoting any number off a site entry:

1. **Prefer `site_from_ligand` when it exists.**
2. **Read `distance_to_donor_ligand_centroid_a`.** Every entry carries it
   unconditionally, plus `ligand_anchored` and an `off_site_warning`. A number
   quoted without it is unverified.
3. **A proposed — not calibrated — threshold: 4 A.** Beyond that, treat the
   centroid as a *different pocket*. It is roughly half the single 7.73 A error
   we have measured and well above the ~1 A grid spacing, and it rests on one
   case. Label it a proposal wherever you use it. It gates a warning, never a
   refusal; no number is dropped because of it.
4. **A null distance is itself the finding.** A pure-apo ensemble with no
   transferable ligand can return `site_from_density` as the *only* site with
   `mdpocket_status: "ok"` — a confident single answer about a cavity of unknown
   identity. `distance_reason` says why. Carry it into the caveat.

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

**The gap between 1 and 2 is much wider than "volume is more reproducible".**
Measured across 15 targets, 67 structures, 134 measurements:

| | |
| --- | --- |
| volume at D=1.6, target-level | **AUC 1.000**, stable under all 15 leave-one-out refits. Every hard target ≤ 207 A^3, every druggable one ≥ 242 A^3 |
| druggability at D=1.6, target-level | AUC **0.720, 95% CI 0.44–0.94** — the interval includes chance |
| druggability at D=2.4 | AUC **0.520** — chance |
| pockets with a drug physically bound scoring **< 0.1** at D=1.6 | **41%** (n=37 ligand-anchored holo structures across all 10 known-druggable targets) |

Individual cases: EGFR with osimertinib bound scores **0.013**; JAK1's median is
**0.009** across nine approved drugs; RORgt 6C1P is **0.009 at rank 55 of 60**.
And the clustering choice does **1.5x more work than the biology** — median
within-structure swing across D is 0.229, maximum 0.955.

So volume is not merely the better number, it is the **load-bearing** one, and
anything affecting volume accuracy matters accordingly. Report druggability as a
range with its provenance and never let it carry a verdict.

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

### VOID: the 651-fold druggability spread across five apo TNF-alpha trimers

Earlier versions of this file reported, in two places, that five apo TNF-alpha
trimers held volume to +/-16% at "the same site" while druggability swung
**651-fold** (0.001 in 2ZJC to 0.651 in 1A8M, volumes 206.7–309.2 A^3; the same
claim appears as 650-fold in older copies — 651 is what 0.651/0.001 gives, and
it is the form used everywhere the retraction is now cited). **That figure is
WITHDRAWN — and so is the volume range printed beside it.** Both came
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
claim never rested on the 651x figure — it rests on the KRAS holo/apo collapse
and on the provenance of the score itself.

### What replaces it: the spread was mostly the matcher

Fixing the site by construction rather than by post-hoc matching cut the
across-ensemble volume CV from **~28% to ~10%** (measured 28.1% at D=1.6 against
9.9%) — roughly a **2.8-fold** inflation, essentially all of it contributed by
the one structure that matched 12 A away. Quote two significant figures: ~1
percentage point of either number is fpocket's Monte-Carlo volume noise.

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
structure recovers the pocket immediately (~280–550 A^3 — see the
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

### `mdpocket.sites.*` reports NO druggability, and that is the honest answer

`druggability_by_structure` used to be populated from mdpocket's `volume_score`
column. Observed values were **3.35 to 4.00 on IRAK4 and 4.36 to 4.57 on NLRP3** —
impossible for a score bounded at 1, and matching the `volume_score` descriptor
exactly on both. A plausible number under a field name that invites it to be
quoted as something else is the worst class of bug this pipeline produces, and it
was quoted.

**There is no right column to swap in.** mdpocket's characterisation table is
fixed at 22 descriptors plus 20 amino-acid counts (`M_MDP_OUTP_HEADER` in
fpocket's `mdpocket.h`) and none of them is a druggability score. Nor can it be
reconstructed: fpocket's shipped score (`pscoring.c`, `drug_score_pocket`) is

    sigmoid(-9.5699 + 7.4798*mean_loc_hyd_dens_norm
            + 0.3696*as_max_dst - 0.04672*surf_pol_vdw22)

and `mean_loc_hyd_dens_norm` is **min-max normalised across the other pockets of
the same structure** (`pocket.c`, `set_normalized_descriptors`). So a
druggability score is not a property of a pocket — it is a property of a pocket
*relative to the pocket population it was detected with*. A fixed grid has a
population of one, and the normalisation has no referent. Applying fpocket's
single-pocket fallback constants to the 6OIM switch-II row gives a saturated
1.000, which is not a measurement either.

**This is a result, not a workaround, and it generalises: fpocket druggability is
not a property of a pocket.** It is a property of a pocket *relative to the
population of pockets detected in the same structure*. A fixed grid has a
population of one, so the quantity is **undefined by construction** — not merely
unavailable, not missing from the output, not something a future mdpocket release
might add.

**Do not "fix" this by applying fpocket's single-pocket fallback constants.**
`set_normalized_descriptors` has a branch for structures with only one pocket
that substitutes `(mlhd - 8.23) / (24.20 - 8.23)`, fitted on a PDB-wide pocket
distribution. Applied to the 6OIM switch-II row (`mean_loc_hyd_dens` 185.78) it
gives a normalised 11.1 and a **saturated 1.000** for every structure. That is a
number, it is in range, it would pass the assertion, and it means nothing. It is
the most tempting wrong fix here, which is why it is written down.

So the field is `null` with `druggability_status: "not_available"` and a reason.
The descriptor is reported under its own name as `volume_score_by_structure`.
**Take druggability from the fpocket path only**, and note that it is a
per-structure number, not an mdpocket fixed-site one.

Every `[0,1]` field now passes a range assertion before it leaves the function.
A score named as a probability that comes back at 4.00 should never have escaped.

**And the loss is small, because the number was never worth much.** The
15-target evaluation in "Measure, in priority order" above puts fpocket
druggability at target-level AUC 0.720 with a confidence interval that includes
chance, with 41% of pockets that have a drug physically bound scoring below 0.1 —
while **volume at D=1.6 separated all 15 targets perfectly**. The quantity that
turned out to be undefined here is the one we should not have been leading with
anyway. Lead with volume.

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

**6. Deposited entries do not share a residue numbering, and a length check
cannot tell.** This was the worst bug the app carried. C-alpha were indexed by
raw *author* residue number, and TL1A's ensemble uses three conventions at once —
2O0O at offset 0, five entries at **+67**, 2RE9 at **+71**:

| numbering | core CA | best 3-chain RMSD, 2O0O vs the rest |
| --- | --- | --- |
| raw author | 67 | **18.70 – 20.06 A** |
| aligned | 138 | **0.51 – 1.45 A**, clean C3 split (1.3 vs 22.7) |

The ensemble superposes essentially perfectly. What was reported was
`2QE3: best chain mapping RMSD 14.84 A exceeds 5.0 A; not a superposition` —
which reads as a conformational problem and is not one. **The error message
misdiagnosed its own failure**, and the whole mdpocket stage was lost on a
target class where mdpocket is the mandated method. S1PR1 failed the same way
with `only 8 C-alpha positions are common to every chain of every structure`.

The old guard could not catch it: `len(core) < 20` tests a **count**, and 67
residues aligned by accident at a constant offset clear a count of 20
comfortably. Its message even said "the entries do not share a numbering" — it
just could not detect it.

**Align numbering first, then assert residue IDENTITY at every core position,
not just how many there are.** The app now recovers the offset by voting on
residue-name agreement against the reference and drops any core position whose
residue name disagrees between structures.

### One bad structure must not cost the ensemble

`6UYA: best chain mapping RMSD 23.87 A exceeds 5.0 A` — a 4-chain assembly
against a 2-chain reference — used to abort the entire IRAK4 run, and the same
shape killed TL1A on 2QE3. **The refusal is correct; aborting is not.** A frame
that will not superpose is dropped, recorded in `mdpocket.frames_dropped` with
its RMSD and reason, and the rest continue; the common core is then recomputed
over the survivors so a dropped entry does not shrink a measurement it is no
longer part of.

**This does not weaken failure mode 1.** Our deliberate drop happens *before*
submission, and `frame_count_check` carries three numbers —
`n_input_structures`, `n_submitted_to_mdpocket`, `n_processed` — with the
assertion made against `n_submitted`. A frame we dropped on purpose and a frame
mdpocket silently lost remain distinguishable, which is the whole point.

Below **3 surviving structures once a drop has occurred** (or 2 in any case) the
run refuses rather than reporting a CV over the survivors of a partial ensemble.

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
| max C-alpha displacement | **~8.8 A** | **~1.6 A** |
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

### The cryptic call needs a superposition gate, and it needed one badly

Three targets found this independently. In every case the module returned
`cryptic_status: "ok"` on top of a fit its own output block showed was broken:

| target | what it reported | what its own superposition said | truth |
| --- | --- | --- | --- |
| **NLRP3** (8SWF) | `is_cryptic: true`, **21.6 A**, `loop_or_backbone_motion`, prior **nanomolar** | `core_ca_rmsd: 16.627` over 487 CA, `n_excluded_ca: 0`, all four mappings at 16.629 | re-run against 7ZGU superposes at **1.248 A** and gives **0.95 A, mechanism `none`, not cryptic** — the site is pre-formed |
| **S1PR1** (8G94) | `subunit_occlusion`, **0.00 A**, 28 contacts "from a displaced chain" → prior **micromolar_at_best** | `chain_mapping {"R": "F"}`, `n_equivalent_ca: 5`, `n_residue_name_mismatches: 15` — it mapped the receptor onto **CD69, a 25-residue peptide** | 257 core CA at 1.03 A gives **1.33 A, zero clashes, mechanism `none`** |
| **TL1A** | — | numbering offsets (above) | — |

The NLRP3 case is the sharpest: **mdpocket refused the identical pair in the same
payload** (`8SWF: best chain mapping RMSD 16.22 A exceeds 5.0 A`) while the
cryptic stage built a confident mechanistic call on it. Two stages, one pair,
opposite verdicts, and only one of them had a gate.

The S1PR1 case is the most damaging: `subunit_occlusion` maps through rule 5 to a
**micromolar-at-best** ceiling, on a target with 600 sub-nanomolar compounds and
five approved drugs. **Four log units wrong, in the direction that kills a
program.**

**Gate on all three of RMSD, equivalent-Cα count and residue-name agreement** —
not RMSD alone. The S1PR1 fit had a *low* RMSD precisely because it was fitted on
five atoms. The deployed thresholds are core RMSD ≤ 5.0 A (the same value
mdpocket uses, deliberately, so the two stages cannot disagree), ≥ 20 equivalent
Cα, and ≤ 10% residue-name mismatches. On failure, refuse — `cryptic_status:
"failed"` with the gate's own numbers in `superposition_gate`.

**And whatever drops a structure from the call must drop it from every statistic
derived from it.** After the NLRP3 re-run the block reported `is_cryptic: false,
mechanism: "none"` (from 7ZGU) while still carrying
`max_backbone_ca_displacement_a: 21.6` — from the **rejected** 8SWF. Those cannot
both be true. Every headline field now comes from one named
`representative_apo_pdb_id`, chosen as the best-superposed apo entry, with the
per-structure values beside it and rejected entries listed separately.

**The displacement figures are protocol-dependent — quote what the run
measured.** 8.83 A (KRAS) and 1.62 A (TNF-alpha) are **hand-calibration**
numbers, from a protocol that disabled auto-trim and residue-name matching and
named the mobile regions by hand. The deployed default does neither — it finds
mobile regions nobody named and drops construct differences (KRAS
G12C/C51S/C80L/C118S, TNF L143D) out of the fit — and lands 0.1-0.2 A below:
**8.65 A for KRAS, ~1.55 A for TNF-alpha**. Mechanism and `is_cryptic` are
**identical** under both protocols, so no label changes; only the decimals do.
`pocket_scan` reports the default in `cryptic.max_backbone_ca_displacement_a` and
re-runs the calibration protocol into `calibration_protocol` beside it. Say which
one you are quoting, and do not present 8.83 or 1.62 as figures this pipeline
reproduces. The 5-fold separation is the finding; the decimals are not.

The subunit-removed control is cheap and decisive for oligomers: delete the third
chain from each apo TNF-alpha trimer and all five immediately recover the SPD304
pocket at ~280–550 A^3 against a holo dimer value of ~310 (raw 281.8–546.0 and
312.5; the same Monte-Carlo volume estimator that puts ~1 pp of noise into every
CV puts the fourth digit here out of reach). In the *intact*
apo trimer the same site measures **0.00 A^3** by mdpocket in four of five — so
"pre-formed" is a statement about the two-chain state. The site is there; the
third protomer is standing in it.

The clash attribution is what makes that reading a measurement rather than a
story, and it repeats across the whole ensemble: placing the ligand into each
intact apo trimer gives **27–29 heavy-atom clashes under 2.0 A** (minimum
interatomic distance 0.28–0.53 A), attributed **identically in all five** to
chain C — S60, Y119, L120, G121 — plus the Tyr119 triad. Five independent
crystals, one answer.

### Which chain is the target is a lookup, not the longest one

Anything that identifies the target by chain **length** is wrong the moment a
partner is longer, and on a GPCR–G-protein complex it always is. Measured on
S1PR1: G-beta-1 is 331–338 residues against the receptor's 278–290 in all four
entries. The interface stage therefore split 7TD4 into target `["B"]` and partner
`["A","G","R"]` — **chain B is G-beta-1, chain R is S1PR1** — computed the
G-beta/G-alpha–G-gamma interface, reported it as the target's epitope with
`interface_status: ok` and 93 interface residues, and warned about nothing.

The same longest-chain sequence was the disorder fallback, so without an explicit
accession disorder would have been computed on G-beta-1.

**Resolve chains by UniProt accession**, which every entry declares in
`_struct_ref` / `_struct_ref_seq`. Two traps in doing so:

- **the assembly mmCIF does not carry `_struct_ref`.** RCSB strips it. Fetch
  `files.rcsb.org/header/<ID>.cif` for it.
- **that header file is not valid mmCIF as served.** It is the full entry with
  the coordinate loops deleted, and the deletion leaves bare `loop_` keywords
  with no tags — at the end of the file and in the middle of it (4OBE has three
  in a row). gemmi rejects the whole document. Strip any `loop_` not followed by
  a tag before parsing, or every accession lookup silently returns empty and you
  are back to longest-wins.

**The second trap is invisible from every angle except the parse.** The fetch
returns HTTP 200 and ~100 kB of plausible mmCIF. `gemmi.cif.read` raises, the
`except` returns `[]`, and the caller falls back to longest-chain **without a
word** — the accession machinery is present, wired, and doing nothing. It was
caught only by testing the parse rather than the fetch, and everything the
accession fix buys depends on that parse working: without it we analyse Gβ1
instead of the receptor, measure disorder on the wrong chain, and let a partner's
homodimer disqualify the target's site signature.

**So: assert on the value you came for, not on the transport.** A 200 is not a
parse, a parse is not a populated field, and a populated field is not the field
you needed. The SMILES trap below is the same failure in a different module, and
neither would have shown up in any status field.

The homo-oligomer guard has the same dependency: 8G94 reported
`is_homo_oligomer: true, identical_chains: ["F","G"]` — that is the **CD69
homodimer**, 25 and 27 residues, a partner — and disqualified an apo structure
whose rank-1 pocket matches the holo pockets at Jaccard 0.79/0.94/0.94. Measure
it over the target's chains only.

### `match_by: "seqid"` needs a residue-name check or it is silently wrong

Matching pocket residues to interface residues on residue **number** is only
legal if both entries number the protein the same way. Measured on TL1A, where
they do not:

- 2O0O at D=2.4 reported shared `A:HIS118`. 3K51's residue 118 is **THR**118.
- 2RE9 reported shared `A:THR34, A:PRO35, A:THR36` against 3K51's **VAL**34,
  **VAL**35, **ARG**36 — a spurious `overlap_fraction 0.227`, flagged
  `borderline`, with no numbering warning.
- The three entries sharing 3K51's convention are genuine and name-match.

Right where the numbering agrees, silently wrong where it does not, **no signal
either way**. A one-line residue-name assertion catches all of it; the geometric
`min_distance_to_interface_a` is unaffected, which is why the destabiliser call
still stood. `pocket_vs_interface.<D>.numbering_check` now carries the identity
fraction and the mismatching positions.

### A near-sealed hydrophobic pocket is a domain core, not a site

IRAK4's death domain gave the **top-ranked pocket of 134, druggability 0.890** —
and it is the hydrophobic core of the domain. Lining: nine Leu/Ile/Val/Phe, one
Arg, one Tyr. `enclosure = 0.998` (sealed, no solvent mouth),
`subunit_enclosure_gain = 0.020` (partner chains contribute nothing to the
burial, so it is buried within one chain), `interface_coverage = 0.026`.

fpocket's druggability regression rewards exactly that shape — large, sealed,
greasy — so a core will outscore a real site. The supporting fields caught it,
which is the system working, but nothing in the payload said so.

`buried_core_suspected` now fires on the **geometry**, never on the score:
enclosure ≥ 0.98, subunit gain ≤ 0.05, apolar lining fraction ≥ 0.7. **These are
a PROPOSAL, not calibrated** — one observed case, no held-out set. They gate a
flag and nothing else: no pocket is dropped, reordered or rescored, and a flagged
pocket still carries its rank and its score. Read the flag as "this druggability
value is uninterpretable", not as "this pocket is not there".

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

### Holo vs apo is a chemistry question, and no size floor or list can answer it

The old test was `>= 18 heavy atoms` plus two hardcoded comp_id lists. Both are
now deleted, and both halves failed measurably:

- **ADP has 27 heavy atoms. So does `A1IPJ`, the genuine inhibitor in 9GU4.** No
  threshold separates them, ever.
- Identity filtering gave **16 holo / 8 apo** on NLRP3 where a naive
  molecular-weight window gave **19 / 5** — three false holo entries, a 19%
  overstatement.
- `CPS` (CHAPS, 615 Da) was simply missing from the list and passed straight
  through. **Adding it would have been a stopgap, not a fix**; a denylist cannot
  be complete, and the next detergent is the same bug again.
- The same shape produced wrong answers on CD20 (sterol tails on Y01/CLR,
  phospho-plus-two-acyl on PC1), KRAS neighbours (2UK read as purine + ribose +
  phosphate) and IL-17A neighbours (L44's 21-carbon chain).

`ligand_filter.classify_record` reads the component's actual structure from its
SMILES graph: **259/262 on ground truth, 61/70 on a blind held-out set with zero
false positives**, and it reproduces the deleted cofactor list without having
been shown it. Every remaining error is conservative — it calls a drug a cofactor
rather than the reverse.

Two behaviours to preserve wherever it is wired in:

- **`unknown` is not `apo`.** An unclassifiable component leaves the entry at
  tier **`undetermined`**, a third tier. Reporting it as apo is the same class of
  error as reporting a credential failure as "no data".
- **A lookup failure is not a CCD miss.** Records that could not be retrieved
  carry `lookup_failed` and land in `holo_call.undetermined`, so a flaky network
  cannot silently render holo structures apo.

Note it does **not** exclude 2AZ5's `307`: that comes back `druglike` with a
`promiscuity_advisory` flag. A frequent hitter is still a ligand; promiscuity
belongs to falsification, not to the holo call.

#### The classifier is useless without SMILES, and it fails silently

**This is the most dangerous thing on this page.** `ligand_filter` classifies on
the component's SMILES graph. Hand it records with no SMILES and it correctly
returns `unknown` for **every** component — and `unknown` is not `druglike`, so
every structure comes back apo or `undetermined`. The payload is well-formed,
every `<stage>_status` says `ok`, and the entire ensemble is silently holo-free.
Verified directly: MOV, GDP, ADP, CPS and `307` all return
`unknown — "the CCD row has no SMILES, so no chemistry test can run"` when the
record carries only type, name, formula and weight.

| record source | carries SMILES? |
| --- | --- |
| RCSB REST `data.rcsb.org/rest/v1/core/chemcomp/<ID>` | **yes** — `pdbx_chem_comp_descriptor`, type `SMILES_CANONICAL` or `SMILES` |
| Paperclip `pdb_v.chemcomps` | **yes** — the `smiles` column (the classifier's own default source) |
| CCD ligand file `files.rcsb.org/ligands/download/<ID>.cif` | **yes** |
| **the entry's own mmCIF `_chem_comp` block** | **NO — id, type, name, formula, formula_weight, and nothing else** |

The last row is the trap. It is the obvious source to reach for, because the file
is already fetched and parsed and on disk, and it is the one that does not work.

`modal_app.py` refuses it: `_assert_records_carry_smiles` raises
`LigandSourceError` when records *were* retrieved and not one carries a SMILES
string, and that exception is deliberately **not** caught by the per-structure
handler — a misconfigured record source is a run-level fault and must kill the
run rather than produce a full, clean, holo-free payload. A genuine 404 caches as
"no record" and does not trip it; a network failure has its own `lookup_failed`
path and its own `undetermined` tier.

**The general shape, which is worth carrying beyond this one case: test that
your source returns the FIELD the consumer needs, not that the fetch succeeded.**
Both of the invisible bugs on this page are that shape — see the header-file trap
above, where the fetch returns 200 and 100 kB and the parse silently yields
nothing.

Inside the Modal image the records come from
`data.rcsb.org/rest/v1/core/chemcomp/<ID>` rather than Paperclip, because the
`paperclip` binary is not in that image.

### A fusion chaperone inflates the pocket count and never fabricates an answer

Worth knowing so nobody spends a day on it. On the T4-lysozyme-fusion S1PR1
structures 3V2W and 3V2Y, fpocket puts **6 of 30 pockets entirely on the
lysozyme**, one of them inside the top five. But the **maximum druggability of
any lysozyme pocket is 0.003**, and the top-ranked pocket is on the receptor at
both clustering values. The chaperone inflates pocket count by roughly 30% and
never produces a druggable false positive.

It does leak elsewhere: **3 of 14 Foldseek neighbour accessions** on that target
were BRIL, thioredoxin and haemagglutinin.

Note also that a chain flag alone would not fix 3V2Y — the lysozyme sits *inside*
chain A at residues 1002-1161, alongside the receptor at 16-330. A residue-range
selection is needed as well as a chain selection.

### Missing residues near the site invalidate the pocket

6OIM chain A is missing 105–107, far from switch-II, so it does not matter there.
A gap adjacent to the site changes its shape, volume, and enclosure. Record
missing residues and whether they neighbour the pocket.

### Symmetry copies of one ligand can classify differently — aggregate, never take the first

Two copies of the same ligand in one structure can land either side of the
interface-overlap boundary. Measured on **8DYG, ligand U5Q**: copy A classified
`allosteric_candidate` at overlap **0.22**, copy B `orthosteric_candidate` at
**0.36**, both flagged `[borderline]` against the 0.25 boundary. The module is
being honest — the pocket genuinely sits on the boundary — but a caller that
reaches into `pocket_vs_interface.per_structure` and takes whichever copy came
first is tossing a coin between two different mechanistic claims.

**The rule for the caller:** quote `pocket_vs_interface.classification` (the
consensus over every pocket classified in the run) or
`per_structure_consensus[<pdb_id>]`, never a single per-D entry. When they
disagree the value is **`mixed`**, and `mixed` must be reported as `mixed` — say
the pocket sits on the boundary and give both overlaps. Do not collapse it to one
label, and do not pick the one that matches `mechanism_hypothesis`.

### A disorder number measured on the construct is about a different molecule

IRAK4 returned **0.0 over 284 residues** — the crystallised kinase domain — where
the full 460-residue protein is **0.1413**, with a disordered region at 101-162.
The old code only used the full sequence if the *caller* passed
`uniprot_accession`; with it omitted it silently fell back to the deposited
construct. A deposited construct is the ordered part of a protein **by
selection**, so that is not an understatement, it is an answer to a different
question — and a bare `0.0` in `tractability.disorder_fraction` reads as "no
disorder", not as "not measured".

Two changes, both binding:

- **The full-length path is the default wherever an accession exists**, and one
  usually does without the caller supplying it: every entry declares its own in
  `_struct_ref` (see the header-file traps above). When several are declared,
  the accession present in the **most entries of the ensemble** is the target —
  partners, fusion chaperones and scaffolds vary, the target does not — and a
  tie is reported as ambiguous rather than resolved by depositor ordering.
- **The construct-only path never populates `disorder_fraction`.** The number
  goes in `construct_disorder_fraction` alongside `scope`,
  `is_full_length_sequence: false` and `n_residues_measured`, so it cannot be
  read as the protein's. Quote it as "disorder *x* over *n* residues of the
  crystallised construct (*source*)", or supply the accession and re-run.

### A disorder number needs its method attached

`disorder.py` falls back when metapredict is unavailable, and the fallback is not
the same number: the deployed Modal image has metapredict and returned **0.3419**
where a local environment without it fell back to MobiDB and returned **0.277** —
a 23% difference on one target. The module behaved correctly (it warned, recorded
`method`, and never returned 0.0, per the cardinal rule). But a disorder fraction
quoted without `disorder.method` beside it is not comparable to any other
disorder fraction. Always carry the method.

### Never difference two centroids that were never superposed

`ensemble.site_centroid_control.max_pairwise_centroid_distance_a` is **removed**,
not nulled. It differenced pocket centroids across structures this module does
not superpose, so it was a real site displacement *plus* two arbitrary
rigid-body offsets — an IRAK4 run reported **103.9 A**, under the heading of a
control. It was not a measurement of anything.

Comparing pockets across structures without a common frame is the exact error
that retracted the 651-fold claim, and a caveat printed beside the number did not
stop it being quoted. Use **`max_radius_difference_a`** — each pocket's distance
from its own structure's protein centre, differenced across structures. It is
frame-invariant, it measures the same thing, and it already existed.

A related thing that is **not** a bug: a `site_pocket_centroid` of exactly
`[5.75, 5.75, 5.75]`, with `centroid_spread_across_clustering_a: 0.0`. That is an
on-axis pocket in an assembly whose 3-fold runs along the body diagonal — 2QE3's
assembly operators are literally `x,y,z` / `z,x,y` / `y,z,x`, so any C3-symmetric
cavity has equal coordinates by construction. It is the crystal frame showing
through, which is the same reason cross-entry centroid distances are meaningless.

### One pocket per structure makes rule 2b unsatisfiable

The app used to return only the selected site pocket. Rule 2b asks for **every**
detected pocket to be classified against the interface, so it could not be
satisfied from the output at all: the IRAK4 agent re-ran fpocket locally to see
the other 133 and reproduced the app's counts exactly, so the data existed and
was being thrown away.

Worse than lost data — on TL1A, 2RE9 reported `n_pockets: 31` while carrying only
rank 28. The agent could not tell whether the axial cavity was **absent** in that
structure or merely **unselected**, so it could honestly report neither a
persistence figure nor a zero. **A truncated payload does not just lose data; it
makes an honest answer unavailable.**

`by_clustering.<D>.pockets` now carries the top 30 by fpocket rank plus the
selected site pocket whatever its rank, each marked `is_site_pocket`. What was
left out is stated: `pockets_omitted`, the omitted rank range, and
`pockets_omitted_summary` bounding their maximum volume, druggability and site
overlap — so a reader can *check* that nothing large or site-overlapping was
hidden rather than take it on trust. Silent truncation reads as completeness.

Interface classification runs on the top 10 ranks plus the site pocket
(enclosure casts 512 rays per probe point per chain, so all 134 is not
affordable), with `n_pockets_not_classified` and the reason stated. The residue
lists for every returned pocket are present, so the overlap half of rule 2b can
be computed from `interface_residues` without re-running fpocket.

## Output

**Parse the CLI's JSON with care, or use `--out`.** `modal run` writes its own
progress banner to stdout *before and after* anything the entrypoint prints, so
`modal run modal_app.py ... > out.json` produces invalid JSON and stripping a
prefix is not enough — there is a trailing `Stopping app...` too. Either pass
`--out <path>` (the payload never touches stdout) or read with
`json.JSONDecoder().raw_decode(text[text.index("{"):])`. Without `--out` the
payload goes to **stderr**, which the banner does not share.

**Every parameter is reachable from the CLI**, including the two that matter most
on an oligomer:

```bash
modal run modal_app.py --pdb-ids 1TNF,2ZJC --chains '1TNF=A,B;2ZJC=A,B' \
    --mdpocket-site-donor 2AZ5 --ligand-codes 307 --out scan.json
```

`--chains` was missing, which made the **subunit-removed control unreachable**
without editing the file — and that control is the single experiment separating
"the cavity is too small" from "a protomer is standing in it". On TNF-alpha the
SPD304 site measures 0.00 A^3 intact and ~280-550 A^3 with a protomer deleted.
TL1A's axial cavity was reported at 49.5-141.1 A^3 intact and the control was
never run, because the CLI could not ask for it.

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
