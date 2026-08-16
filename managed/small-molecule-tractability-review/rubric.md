# Grading rubric — druggability-dossier

The deliverable is **one JSON file** at the canonical sandbox path:

```
/mnt/session/outputs/druggability-dossier.json
```

**Grade that file and nothing else.** Do not grade the reply text, do not accept
a claim made in the reply that the file does not itself support, and do not fail
a run for something the file cannot express. Every criterion below is decided by
reading that file or by re-running a bundled script against it; none of them
turns on prose quality, effort, or thoroughness. A criterion that cannot be
falsified from the file is not a criterion, and a rubric full of them produces
nothing but `max_iterations_reached`.

## Step 1 — run the validator. It settles criteria 1–17.

The skill bundle ships a machine validator. It is pure-stdlib Python, so it runs
in the sandbox with nothing installed:

```
python3 .claude/skills/assemble-dossier/validate_dossier.py \
        /mnt/session/outputs/druggability-dossier.json
```

It carries **17 rule functions emitting 18 violation codes**, and it is covered
by the unit-test suite in `test_validate_dossier.py` beside it — run
`python3 -m unittest test_validate_dossier` for the current count rather than
trusting a number written here, which has now gone stale twice. It exits **0** with no
violations, **1** with them, and **2** if invoked with no argument; on violations
it prints one `  [CODE] path: message` line per finding, sorted.

**A clean exit satisfies criteria 1–17 at once.** Each violation it prints names
the criterion that failed and the JSON path that failed it, so grade from its
output rather than re-deriving the same checks by eye. Criteria 18–21 are the
ones the validator does not cover; they are still decided from the file.

Where this rubric and the validator could ever disagree, **the validator wins**
and this document is the stale one. It is the machine grader; this is its index.

**Known gap in this index, measured 2026-08-15.** The validator emits **18**
codes; the list below enumerates **17**. The one with no entry here is
**`INTERFACE_MIXED_UNRESOLVED`** (rule function
`check_mixed_interface_is_resolvable`, registry position 12 — it sorts between
criteria 12 and 13 below). It fires when
`tractability.pocket_vs_interface.classification` is `mixed` without the four
things that make `mixed` actionable: at least two distinct values in
`classifications_seen`, per-copy values in `pocket_interface_overlap` rather
than one scalar, a `partner_pdb_id`, and `matches_mechanism_hypothesis` not set
to `true` — plus the converse, `classifications_seen` naming two labels while
`classification` reports just one of them. It is **enforced** by the validator
and merely unnumbered here, so a clean exit still covers it; grade it from the
validator's output. Renumbering the list is left to whoever owns the criteria
sequence, since it shifts criteria 13–17 and the 18–21 block below.

## Criteria 1–17 — exactly the validator's rules

Listed in the validator's own registry order, with the trigger that fails them.

1. **`WELL_FORMED` — the file parses and the template is filled.** A JSON object;
   all 16 required top-level keys present — the output template now carries a
   **17th top-level key, `input`**, echoing the five contract fields so a
   consumer can key a cache on
   `(input.uniprot_accession, input.mechanism_hypothesis, input.as_of_date)`,
   but `REQUIRED_TOP_LEVEL` does **not** list it, so a dossier that omits the
   block still passes this criterion today (verified 2026-08-15: the validator
   contains no reference to `input` at all). Treat a missing `input` block as a
   validator gap to be fixed in `validate_dossier.py`, not as a passing
   dossier; every enumerated field
   (`verdict`, `verdict_basis`, `structure.tier`,
   `tractability.cryptic_pocket_risk`, `tractability.cryptic_mechanism`,
   `cryptic_potency_prior.expected_ceiling`,
   `pocket_vs_interface.classification`) non-null and inside its legal set; no
   string anywhere still containing the template's `" | "` alternation; no
   nameless stub entries in the six list blocks; `verdict` a label and never a
   number; `next_experiment.description` and `biologic_precedent.note`
   non-empty; `falsification.survived` an actual boolean and `checks_run`
   non-empty; no NaN or Infinity.

2. **`NUMBER_WITHOUT_PROVENANCE` — every number carries provenance.** Each
   numeric leaf must sit inside a dict holding a non-empty provenance key
   (`source`, `sources`, `_provenance`, `doi`, `pdb_id`, `chembl_target_id`,
   `tool`, `basis`, `ensemble_pdb_ids` and the rest of the 24 the validator
   accepts). Provenance inherits **downward only**, so in practice `target`,
   `tractability`, `structure` and `affinity` each need their own non-empty
   `sources` — nothing else attributes their numbers. An empty list attributes
   nothing.

3. **`AXES_AVERAGED` — the two axes are never merged.** No key named or
   containing `overall`, `composite`, `score`, `averaged`, `axis_average` and
   the rest of the banned set; and no numeric value under a key that mixes a
   precedent token (`precedent`, `actives`, `potency`, `approved`, `clinical`)
   with a tractability token (`druggability`, `pocket`, `tractability`,
   `volume`). There is no overall number in this dossier, by construction.

4. **`MODALITY_LEAK` — modality is separated per drug.** Every entry in
   `approved_small_molecules` and `clinical_stage_small_molecules` carries
   `modality: "small_molecule"`; no name from `biologic_precedent` appears in
   either; no USAN `-mab` or `-cept` stem in either. Also fires when
   `verdict: "small_molecule_tractable"` rests on `retrieved_precedent` or
   `both` with both lists empty and no characterised potency — that is a
   biologic being leaned on — and when a tractable verdict with zero approved
   small molecules and an approved biologic leaves `axis_conflict` empty.

5. **`INSUFFICIENT_EVIDENCE_AVOIDED` — declining is a correct answer and it must
   be reachable.** Fewer than 50 distinct actives, `structure.holo_count` a
   literal `0`, and no approved small molecules, with any verdict other than
   `insufficient_evidence`, fails. So does `insufficient_evidence` with an empty
   `next_experiment.resolves`.

6. **`DRUGGABILITY_POINT_ESTIMATE` — druggability is a range, never a point.**
   `pocket_druggability` and `pocket_volume_a3` are objects, not scalars;
   `min` and `max` are both present or both absent; a populated range requires
   at least two distinct values in `method.clustering_d_swept`, a non-empty
   `method.ensemble_pdb_ids`, and a volume beside it (or the missing volume
   named in `not_found`). No numeric value under any other key containing
   `druggab` is allowed outside `pocket_druggability.min`/`.max`/`.fold_range`.

7. **`DRUGGABILITY_LOAD_BEARING` — the score is reported and carries nothing.**
   This is the rule that changed on 2026-08-15 and it has four parts:
   `pocket_druggability.load_bearing` must be **literally `false`** (missing,
   `true`, `"false"` and `0` all fail); `_false_negative_rate` must be a
   non-empty string wherever a range is reported; a `not_tractable` or
   `insufficient_evidence` verdict on `computed_tractability` or `both` with
   `pocket_druggability.max < 0.5` and **no** volume number anywhere in
   `pocket_volume_a3` (`primary_d1_6_a3`, `min`, `max`) fails outright — decline
   on an **unmeasured volume**, never on a poor score; and a low druggability
   sitting beside a volume of 240 Å³ or more requires a non-empty
   `tractability.caveat` stating the disagreement.

8. **`VOLUME_NOT_PRIMARY` — volume at D=1.6 is the computed axis's number.**
   Whenever any volume or druggability figure is reported,
   `pocket_volume_a3.primary_d1_6_a3` must be numeric (or excused by name in
   `not_found`); it must not exceed **1000 Å³**, which is the signature of sites
   merged with neighbouring cavities rather than a D=1.6 site volume; and a
   reported min/max needs `pocket_volume_a3.clustering_d` populated.

9. **`FRACTION_WITHOUT_N` — a fraction with no denominator is not a
   measurement.** `ensemble_consensus_fraction.fraction_with_strong_pocket`
   requires one of `n_structures`, `n_measurements` or `n`; and a stated
   `n_structures` must equal `len(method.ensemble_pdb_ids)`.

10. **`SAME_SITE_BASIS_MISSING` — a pooled spread records how the site was
    chosen.** `site_pocket_selected_by` is populated on both
    `pocket_volume_a3` and `pocket_druggability` whenever either carries a
    number, and every value is one of the five legal bases
    (`ligand_site_jaccard`, `site_signature_overlap`,
    `site_signature_unreliable_homooligomer`, `max_druggability_no_ligand_site`,
    `no_pocket_matched_site_signature`).

11. **`SAME_SITE_BASIS_INVALID` — three of those five do not identify a site.**
    `site_signature_unreliable_homooligomer`, `max_druggability_no_ligand_site`
    and `no_pocket_matched_site_signature` may not appear on a figure pooled
    across more than one measurement (structures × clustering values). Report
    those per structure instead.

12. **`SITE_INCONSISTENT` — the number must belong to the site being claimed.**
    `mdpocket_site_definition_used: "site_from_density"` with
    `site_centroid_to_ligand_distance_a` above **4 Å** may not have volume or
    druggability reported as the site's — that is a different cavity. And a
    substantive `pocket_vs_interface.classification` requires both
    `partner_pdb_id` and `pocket_interface_overlap`, because rule 2b's
    classification is measured against a partner structure or it is an
    assumption.

13. **`CRYPTIC_MISCLAIM` — a cryptic claim carries its apo census.**
    `cryptic_evidence.is_cryptic` is a real boolean after a run, with a
    non-empty `basis`. When true: `n_apo_examined` ≥ 1 and
    `n_apo_site_absent / n_apo_examined ≥ 0.8` (Vajda 2018's "all or nearly
    all"), `site_present_in_apo_ensemble` not true (true means **occluded, not
    cryptic** — this is the TNF-alpha case), and `cryptic_pocket_risk` not
    `low`. A `cryptic_mechanism` other than `none`/`undetermined` with no census
    is an assertion. Mechanism and prognosis must agree: side-chain or subunit
    occlusion may not claim a nanomolar ceiling, and loop motion may not claim
    micromolar-at-best.

14. **`NULL_IS_NOT_ZERO` — null says why, and null is not zero.** Across the 15
    measured fields, a null needs a matching `not_found` entry naming it; a
    field named in `not_found` may not then be reported as `0`; and no
    measured field is a string. Placeholder strings (`"n/a"`, `"unknown"`,
    `"none"`, `"-"`) under any `_count`/`_nm`/`_pct`/`_a3`/`_fraction`/`_a` key
    fail.

15. **`AS_OF_LEAKAGE` — the cutoff is binding.** With `as_of_date` set it must
    be ISO `YYYY-MM-DD`; `distinct_actives`, `best_potency_nm` and `patents`
    need a leakage entry whenever they carry a value;
    `clinical_stage_small_molecules` needs one **unconditionally, including when
    the list is empty**; no entry `year` may exceed the cutoff year; no
    `release_date` may sort after it. With no `as_of_date`, `as_of_leakage` is
    `[]`.

16. **`AXIS_CONFLICT_UNDECLARED` — disagreement is declared, not resolved.**
    `axis_conflict` must be non-empty when: there are approved biologics and no
    approved small molecules alongside a tractable verdict or ≥500 actives; or
    ≥500 actives with zero holo structures; or a single assay at ≥30% share that
    measures a different target; or a best potency reported as uncharacterised.

17. **`ASSAY_PROVENANCE_MISSING` — an actives count is a claim about assays.**
    A non-zero `distinct_actives` requires `top_assay_description` and
    `top_assay_share_pct`; a share ≥30% requires
    `measures_a_different_target` answered; and a reported `best_potency_nm`
    requires `best_potency_characterised` answered.

## Criteria 18–21 — file-verifiable, not validator-enforced

The validator does not check these. Read them off the JSON directly.

18. **Chain selection was asserted, and recorded.**
    `tractability.method.chains_used` is populated with the chains actually
    scored — `pocket_scan` now takes `chains` and `site_residues`, so rule 2b is
    executable and "chain selection could not be asserted" is no longer a legal
    caveat. The one exception is an input with no `mechanism_hypothesis`: then
    `chains_used` may be null **only if** `tractability.caveat` says the pockets
    are for the biological assembly because no mechanism was specified. A null
    `chains_used` with no such caveat fails, because chain selection changes the
    answer (KRAS 4OBE: 0.442 at rank 1 on chain A, 0.257 at rank 6 on A+B) and a
    silent whole-assembly default is an unstated assertion.

19. **The method block reconstructs the run.** `tractability.method` carries
    `tool`, `clustering_d_swept` with at least two values, and
    `ensemble_pdb_ids` matching `structure.ensemble_used`. The sweep is what
    measures the parameter's own effect — within-structure |D=2.4 − D=1.6| on
    the same site has a median of 0.229 — so a single clustering value is not a
    measurement.

20. **Site rank reports both rankers or neither.** When
    `tractability.site_pocket_rank` carries a number, `fpocket` and `prank` are
    both present (`prank` may be null with a `not_found` entry if PRANK did not
    run), alongside `n_pockets`. PRANK is a site-*finding* aid — it promotes the
    true site in 79% of 70 ligand-anchored measurements and demotes it in 1% —
    and as a druggability classifier its rank is inverted at AUC 0.25, so a rank
    reported alone reads as a quality value and must not.

21. **Unavailable axes are null with a reason, never fabricated.** Two parts,
    and only the first is absolute.

    *Hard:* `affinity.*` (including rule 12's positive control),
    `structure.cofold_control` and every
    `pocket_neighbour_precedent.*.cofold_transfer` are `null`, and
    `structure.tier` is not `cofolded`, `predicted` or `sampled_ensemble`.
    There is no affinity predictor, no cofolding model, no structure predictor
    and no Open Targets client in this deployment, so a populated value in any
    of them is recalled from memory rather than measured. A recalled number is
    indistinguishable from a measured one once it is in the JSON, and it is the
    one error this dossier cannot survive. **Any populated value here fails
    outright.**

    *Stated:* `not_found` names the missing capability, at block level. One
    entry with `field: "affinity"` covers the whole block including the
    positive control — that is how both shipped reference dossiers do it and it
    is sufficient. Where `neighbour_precedent` returned a
    `ModuleNotFoundError`, `structural_neighbour_precedent` is recorded as
    *unavailable* and never as "no structural neighbours found"; the same
    distinction applies to a `pocket_scan` ligand lookup that failed rather than
    missed.

## What this rubric must NOT do

These are failure modes of the *grader*, and they are as costly as a bad
dossier.

- **Do not gate on a volume threshold. The separation behind it is WITHDRAWN
  (rule 4a, 2026-08-15).** This bullet used to justify the prohibition by saying
  the boundary was merely uncalibrated — AUC 1.000 across 15 targets, hard
  ≤207 Å³ and druggable ≥242 Å³, a 17% margin fitted post hoc. **That result is
  now suspended outright**, because the calibration anchors did not all measure
  the proteins they were attributed to: MYC's 188 Å³ pocket contains **zero MYC
  atoms** (lining residues are MAX, MAX plus DNA, or engineered OmoMYC), IL-11's
  164 Å³ came from an IL-11 **receptor** entry, and KRAS's 400 Å³ is a median
  spanning the GDP site rather than switch-II. Correcting them crosses the
  boundary — MYC moves 187.9 → 325.7 Å³ — so **thresholded on volume, MYC would
  have come out druggable.** The prohibition is therefore no longer "pending
  out-of-sample validation"; there is no validated separation to gate on at all.
  A volume is a number about a cavity and nothing more. **Verified in the
  validator, 2026-08-15:** nothing classifies on volume. The only numeric volume
  uses anywhere in the grader are the 1000 Å³ merge-artifact ceiling
  (criterion 8) and a 240 Å³ trigger that merely *requires a caveat* when a low
  druggability sits beside a large volume (criterion 7) — neither calls anything
  druggable or hard, and no criterion may be added that does. Note the 240 Å³
  trigger is now a bare disclosure threshold inherited from a withdrawn
  calibration; it should be re-derived or replaced with a rule that does not name
  a number. `VOLUME_GUIDE_HARD_A3 = 210.0` is defined in the validator and never
  read — dead code from the same withdrawn guide.

- **Do not grade a druggability value against an expected number.** The same
  structure read 0.673 on the deployed path and 0.708 locally; fpocket estimates
  volume by Monte Carlo and the score inherits that noise, and roughly one
  percentage point of any reported CV is the method's own. Never fail a run on
  the third significant figure, and never treat a low druggability as a wrong
  answer — 41% of pockets with a drug physically bound score below 0.1
  (n=37 ligand-anchored holo structures; EGFR with osimertinib scores 0.013).

- **Do not accept persistence as a substitute.** The site pocket was detected in
  100% of structures for all 15 targets, so persistence is constant and its AUC
  is exactly 0.500; the published consensus criterion built on it ranks MYC
  first. `ensemble_consensus_fraction` is an anti-cherry-picking control
  (criterion 9), not a tractability signal, and no criterion may read it as one.

- **Do not require a druggability figure from mdpocket.** Its druggability field
  is **null by design**: fpocket's score is min-max normalised across the other
  pockets of the same structure, and a fixed grid has a population of one, so
  the quantity is undefined there. A null is correct; a number would be the bug.

- **Do not demand a key-by-key `not_found` enumeration where a block-level
  entry covers it.** Provenance and stated-absence both inherit downward. The
  two shipped reference dossiers,
  `.claude/skills/assemble-dossier/examples/jak1_P23458.json` and
  `tnf_P01375.json`, both exit the validator at **0 violations** and are the
  calibration for how much bookkeeping is enough — if a criterion you are about
  to apply would fail either of them, the criterion is wrong, not the dossier.
  Re-run the validator on them in the sandbox to check.

- **Do not grade the reply.** `CLAUDE.md` requires the complete JSON in the
  final reply as well as on disk, because sandbox files are not retrievable
  after the session ends. That requirement is real and it is **not a criterion
  here** — this grader sees only the file, so a reply requirement graded from
  the file would either be vacuous or fail every run. The file's existence,
  parseability and completeness are criterion 1.
