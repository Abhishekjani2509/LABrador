# Prior art — what is standard, what is contested, what is ours

Researched 2026-08-15 via Paperclip full text and web. Every number here is
cited. The purpose is to stop us claiming as novel what the field settled years
ago, and to stop us quoting numbers whose provenance we do not know.

## Things we must stop claiming

**"Use an ensemble instead of one structure" is table stakes, not a
contribution.** It is the explicit design principle of CryptoBank, LIGYSIS and
HOTPocket as of 2024–25. Claim the *magnitude* we measured, never the idea.

**KRAS switch-II is the field's most-used illustration** — PocketMiner,
CryptoBank, Bowman's review and HOTPocket all use it. Good sanity check, weak
differentiator.

**"Cryptic pockets expand the druggable proteome"** is boilerplate in every
paper on the topic.

**"Cytokines are undruggable" is dead.** A 32-cytokine small-molecule-microarray
campaign against 65,000 compounds gave 864 chemotypes → 296 thermal-shift
validated binders (32.5% translation) → cellular inhibitors for IL-17, IL-13 and
IL-23 (Raevi et al., bioRxiv 2026, doi:10.64898/2026.04.20.719718).

## Things we were quoting without knowing what they were

**The fpocket druggability score is a 3-descriptor logistic regression fitted on
21 positives.** From `src/pscoring.c`, `drug_score_pocket()`:

```
score = 1/(1+exp(-(-9.5698768
                   + 7.479844   * mean_loc_hyd_dens_norm
                   + 0.3696134  * as_max_dst
                   - 0.04671833 * surf_pol_vdw22)))
```

In-code note: "21 druggable pockets vs 292". The **published** 2010
nested-logistic model (Schmidtke & Barril, *J Med Chem* 53:5858) is present in
the same file **commented out** — so the score in any current binary is not the
equation the paper describes. fpocket's own detection paper says the pocket
score "does not reflect drugability" and that rank-1 performance "drops" on apo
structures.

**Halgren's SiteMap benchmark contained exactly one PPI** (MDM2/p53). Applying
his thresholds to a curated PPI set classifies **46% of proteins as "difficult"
despite their having clinically viable inhibitors** (*Sci Rep* 2022,
doi:10.1038/s41598-022-12105-8). Our domain is PPI-heavy.

## Standard practice we are missing

| Gap | Evidence |
| --- | --- |
| **A rescorer on top of fpocket** | fpocket + PRANK or DeepPocket is the best-recall configuration in two independent benchmarks; best recall of *any* method is only 60% (Utgés & Barton, *J Cheminform* 2024, doi:10.1186/s13321-024-00923-z) |
| **A cryptic predictor** | PocketMiner, ROC-AUC 0.87, sub-second (Meller et al., *Nat Commun* 2023). But see the warning below |
| **Interface hot-spot detection** | PPI-hotspot ID: F1 0.71 / sensitivity 0.67 vs FTMap 0.13/0.07 (*eLife* 2024, doi:10.7554/eLife.96643). **27.6% of true hot spots make no cross-interface contact at all** |
| **A defensible negative-label treatment** | canSAR's PocketBagger uses positive–unlabelled learning precisely because "defining genuinely 'undruggable' pockets is nearly impossible" |
| **Cluster-aware and time-aware splits** | Random splits over homologous pockets inflate every reported metric |

**Do not put PocketMiner in a general ranking.** HOTPocket measured it at
**5–9% DCA precision on ordinary pockets**, over-predicting to 119 pockets per
structure. It is a cryptic-site *trigger* only.

**Do not build a naive consensus.** HOTPocket found that intersecting seven
pocket finders **underperformed the best single method**; ensembling only paid
off with a learned rescorer on top. This retires the consensus-of-scores idea we
sketched early on.

## The evaluation problem — and why our as-of design matters

There is an accepted way to evaluate *pocket detection*, a partial one for
*cryptic pockets*, and **essentially nothing for druggability**.

- **NRDLD**, the de facto standard, is 71 druggable + 44 less-druggable = 115
  pockets, with a **test set of 35–37**. It is **62% positive by construction**;
  the deployment base rate — proteins with an approved drug — is **~3.5%**
  (704 Tclin of ~20,000). Every published accuracy figure (DrugPred 91%,
  DoGSiteScorer 88%, PockDrug MCC 0.885) was computed at a prior ~18× too
  generous.
- A one-class model scored **more than half of NRDLD's "less druggable" pockets
  as highly druggable** (*Front Pharmacol* 2022, doi:10.3389/fphar.2022.870479).
  Their framing: "any pocket is only non-druggable until a drug is found for it."
- **Nobody hindcasts.** No study of the form "run predictor X as of year Z,
  check whether it called the now-drugged targets druggable" was found.
- The one real time-split study is at the association layer and is damning for
  the incumbent: **OTRec** trained on Open Targets 2022 and evaluated on 2025
  trial outcomes found the **Open Targets association score scores ROC-AUC 0.559
  prospectively** — a coin flip plus epsilon (bioRxiv 2025,
  doi:10.64898/2025.12.21.695803).
- Blind prospective ligandability, for calibration: **CACHE #2 confirmed 0.7% of
  1,957 computationally nominated compounds** as binders by SPR.

So our retrospective `as_of_date` design is not a nice-to-have — it is the
missing evaluation the field has not built.

## Open Targets — measured by query, release 26.06

I claimed earlier that mechanically enforced modality separation was uncommon.
**That was wrong and is retracted.** Open Targets does it, and does it
correctly:

- `Target.tractability` returns **28 independent booleans** across four
  modalities (SM 8, AB 9, PROTAC 8, other-clinical 3). No score, no rank, no
  aggregate.
- The IL-17A / TNF test passes cleanly. `{"modality":"SM","label":"Approved
  Drug","value":false}` for both, alongside `{"modality":"AB","label":"Approved
  Drug","value":true}`. Three approved antibodies do not leak into the
  small-molecule row.

So the trap we built rule 1 around is already handled by the field's most-used
platform, at least on the clinical-precedence buckets. What survives as ours is
narrower and needs stating precisely.

**Where it is exploitably weak — all confirmed by query, not inferred:**

| Weakness | Evidence |
| --- | --- |
| The structural half is a single frozen source | Both `High-Quality Pocket` and `Med-Quality Pocket` derive from **DrugEBIlity alone**, a legacy EBI dataset with no ongoing releases |
| …and it fires wrongly on our domain | **TNF scores `SM:High-Quality Pocket = true` AND `Druggable Family = true`** — a secreted trimeric cytokine with zero small-molecule clinical candidates |
| `Structure with Ligand` conflates two questions | It requires a solved structure *and* a bound small molecule, so it cannot fire for a good apo pocket with no ligand |
| Silent all-false is indistinguishable from unassessed | **49% of 298 sampled targets have all 8 SM buckets false.** No abstention state exists |
| No confidence, no provenance, no evidence trail | The API exposes no provenance field at all; "conf" appears only inside bucket *names* |
| **No versioning — and it looks like there is** | `tractability(version:"24.06")` errors, but the URL param `?version=24.06` returns **HTTP 200 and is silently ignored** — `meta.dataVersion` still reports 26.06. Historical data exists only as 28 FTP parquet dumps |
| The adjacent numeric field is modality-blind | `Target.prioritisation.maxClinicalStage = 1` (max) for **both IL-17A and TNF**, driven entirely by approved antibodies with no modality qualifier |

**Base rates over 298 targets, useful for calibrating how much a `true` carries:**
`SM:High-Quality Pocket` fires at **10.4%** (the sharpest structural
discriminator), `SM:Approved Drug` 16.4%, `SM:Phase 1 Clinical` **0.0%**,
`PR:Database Ubiquitination` 60.1% (near-noise).

**Two things to use rather than compete with:**

1. `drugAndClinicalCandidates.drug.drugType` is a clean modality label
   (`Antibody` / `Protein` / `Small molecule` / `Unknown`) and is **more
   trustworthy than the tractability buckets themselves**. Use it as an
   independent cross-check on our SMILES-null test.
2. The 28 booleans across all targets are the **weak validation labels we
   lack**. Not ground truth, but the only broad labelled set available.

API note for whoever writes the integration: `Target.knownDrugs` no longer
exists in 26.06, and `Drug.isApproved`, `Drug.maximumClinicalTrialPhase` and
`Drug.hasBeenWithdrawn` are gone. Use `drugAndClinicalCandidates` and
`Drug.maximumClinicalStage`.

## Architecture — we are not alone, and that is good

**canSAR** keeps four axes separate (3D pocket, ligand-based, network
target-likeness, antibody accessibility) and **refuses to make negative calls**:
"The notion of a negative 'undruggable' pocket is scientifically intangible…
it is impossible to quantify the negative recall or the precision of our
predictions." That is the closest published position to ours.

**TargetDB** (SGC Oxford, GPL-3.0) emits **eight separate 0–1 component scores**
with a user-weighted MPO, and keeps fpocket-derived druggability distinct from
ChEMBL-derived chemistry. It also ships **dated SQLite snapshots pinned to
ChEMBL versions** — the best as-of story in any public tool.

**The theoretical argument for refusing to average**, which we should make
explicitly: ML pocket scorers are trained on liganded pockets, so **they already
encode precedent and cannot serve as an independent second axis**. Averaging a
precedent axis with a scorer trained on precedent double-counts.

## Where we may genuinely be novel

**Retracted from this list:** mechanically enforced modality separation. Open
Targets already does it correctly on clinical precedence (see above). Our rule 1
is still necessary — a dossier that got IL-17A wrong would be wrong — but it is
table stakes, not a differentiator. What differentiates is that we carry
*provenance and a potency figure* alongside the modality call, where Open
Targets carries a bare boolean.

1. **The magnitude of druggability-score irreproducibility.** Detection
   instability is published (~85% pocket identity under mere rotation, ~59%
   PDB-vs-AF2); score inflation on uncleaned holo is published as a distribution
   shift. **No published fold-range of the score across an apo ensemble with
   volume held constant.** Ours: 650× with ±16% volume.
2. **Mechanism as a routing decision.** Existing taxonomies (PocketMiner's
   forward/reverse + four backbone rearrangements; CryptoBank's
   buried/superficial × fragment/ligand) are descriptive. Using mechanism class
   to decide *which computation is valid* was not found.
3. **Subunit displacement as a first-class occlusion mechanism.** Absent from
   PocketMiner's four backbone-centric classes, excluded by CryptoBench's 2 Å
   RMSD filter, and structurally unhandleable by PocketMiner (it refuses
   multi-chain input, and failed on 38 multi-chain structures of ~220 in
   CryptoBench's test set).
4. **The clustering-parameter sweep.** No paper treats fpocket's `-D` as a
   variance source to be swept.

## Definitions we must respect

**Vajda et al. 2018** (*Curr Opin Chem Biol* 44:1, PMC6088748): a cryptic site
"forms a pocket in a ligand-bound structure, but not in the unbound protein
structure", with the stringent form being absent in **all, or nearly all**
unbound structures. **Beglov et al. extended CryptoSite from 186 to 4,950
structures and found bound-like pockets partially formed in some unbound
structure for close to 50% of the 93 proteins**, with BACE-1 druggability
ranging 0.2–0.6 across 52 apo structures. So ensemble score variation was
published in 2018 — our contribution is magnitude on the raw score, not the
observation.

**CryptoBench** operationalises crypticity as pocket-residue RMSD > 2 Å. **Our
TNF-alpha case at 1.62 Å sits below that threshold and the site is present in
all five apo structures — so it is NOT cryptic by either standard.** Report it
as occluded.

## Method lesson

`paperclip grep "<title>" /papers/` returns papers that **cite** a work, not the
work. Vajda 2018 looked absent from the corpus by grep (127 reference-list hits)
and was found instantly by `paperclip lookup doi "10.1016/j.cbpa.2018.05.003"`.
Use `lookup` for a known work, `grep` for named entities inside text.
