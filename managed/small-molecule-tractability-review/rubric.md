# Grading rubric — druggability-dossier

The deliverable is **one JSON file** at the canonical sandbox path:

```
/mnt/session/outputs/druggability-dossier.json
```

Grade that file. Do not grade the reply text, and do not accept a claim made in
the reply that the file does not itself support.

Most of this rubric is already executable. The skill bundle ships a machine
validator with 13 rules and 14 violation types, and it is pure-stdlib Python, so
it runs in the sandbox with no installation:

```
python3 .claude/skills/assemble-dossier/validate_dossier.py \
        /mnt/session/outputs/druggability-dossier.json
```

It exits **0** with no violations and **1** with them, printing
`[RULE] path: message` for each. Run it first: criteria 1–9 below are exactly
its rules, so a clean exit satisfies all nine at once, and any violation it
prints names the criterion that failed and where.

## Criteria

1. **The file exists, is valid JSON, and is a JSON object.** A dossier that
   cannot be parsed fails everything else by default.
   (`WELL_FORMED`)

2. **Every key in the CLAUDE.md output template is present.** Unretrieved values
   are `null` and empty collections are `[]`; no key is omitted, and no template
   placeholder string (`""` where a value was required, `"small_molecule_tractable | not_tractable | insufficient_evidence"`)
   is left standing. `verdict` is a label, never a number.
   (`WELL_FORMED`)

3. **Every number carries provenance.** Each numeric leaf sits inside a block
   whose `sources` list is non-empty, or carries its own `source`. The four
   blocks that no other key attributes — `target`, `tractability`, `structure`,
   `affinity` — each have their own non-empty `sources`. An empty `sources`
   list attributes nothing and counts as absent.
   (`NUMBER_WITHOUT_PROVENANCE`)

4. **The two axes are reported separately and never averaged.** There is no
   combined or overall score anywhere in the file, and `verdict_basis` is one of
   `retrieved_precedent`, `computed_tractability`, `both`, `none` — naming which
   axis carried the verdict. A verdict with no basis is an average with extra
   steps.
   (`AXES_AVERAGED`)

5. **Modality is separated per drug.** Every entry in
   `target_precedent.approved_small_molecules` and
   `clinical_stage_small_molecules` carries `modality: "small_molecule"` and
   nothing else; antibodies, peptides, fusion proteins and `Unknown`
   `molecule_type` values are not in those lists. Biologics appear under
   `biologic_precedent`; modality-unknown drugs appear in `not_found` and count
   toward neither block. A USAN `-mab` or `-cept` stem inside a small-molecule
   list is an automatic failure.
   (`MODALITY_LEAK`)

6. **Druggability is a range and volume is the primary number.**
   `tractability.pocket_druggability` has both `min` and `max` present whenever
   it is populated at all — never a single point value — and
   `pocket_volume_a3` carries its spread. Any reported fraction gives its
   denominator: `ensemble_consensus_fraction` has `n_structures` **or**
   `n_measurements`, and leaves `meets_consensus_criterion` null when only
   measurements (not structures) were counted.
   (`DRUGGABILITY_POINT_ESTIMATE`, `FRACTION_WITHOUT_N`)

7. **A pooled spread records how the site was chosen.**
   `pocket_volume_a3.site_pocket_selected_by` and
   `pocket_druggability.site_pocket_selected_by` are populated. Values of
   `site_signature_unreliable_homooligomer`, `max_druggability_no_ligand_site`
   or `no_pocket_matched_site_signature` do not identify a site, so numbers
   carrying them are reported per structure and not pooled into one spread.
   (`SAME_SITE_BASIS_MISSING`, `SAME_SITE_BASIS_INVALID`)

8. **A cryptic claim carries its apo census.** `cryptic_evidence.is_cryptic` is
   true or false after a run and never null. When true, `n_apo_examined` and
   `n_apo_site_absent` are both present, more than one apo structure was
   examined, and the site was absent in all or nearly all of them (Vajda 2018);
   `site_present_in_apo_ensemble: true` means **occluded, not cryptic**. A
   `cryptic_mechanism` other than `none` or `undetermined` with no
   `cryptic_evidence` behind it is an assertion, not a finding.
   (`CRYPTIC_MISCLAIM`)

9. **Null says why, and null is not zero.** Every null value has a matching
   entry in `not_found` naming the field and the reason. Nothing that could not
   be retrieved is reported as `0`.
   (`NULL_IS_NOT_ZERO`)

10. **`as_of_date` integrity.** When `as_of_date` is set,
    `target_precedent.as_of_leakage` carries one entry per affected field, and
    `clinical_stage_small_molecules` has an entry **unconditionally** — including
    when the list is empty, because ChEMBL's `max_phase` is a current value with
    no phase history. With no `as_of_date` the list is `[]`.
    (`AS_OF_LEAKAGE`)

11. **Axis disagreement is declared.** When retrieved precedent and computed
    tractability point different ways, `axis_conflict` is populated with a
    non-empty explanation rather than resolved or averaged away. The reference
    case: a target with a strong pocket and zero approved small molecules is
    `verdict_basis: "both"` with `axis_conflict` populated.
    (`AXIS_CONFLICT_UNDECLARED`)

12. **An actives count is a claim about assays until proven otherwise.** Whenever
    `target_precedent.distinct_actives` is populated,
    `assay_concentration.top_assay_description` and `top_assay_share_pct` are
    populated too, and `measures_a_different_target` is answered. A single assay
    above ~30% of all activity is stated as such.
    (`ASSAY_PROVENANCE_MISSING`)

13. **`insufficient_evidence` was reachable.** A target with no structure, no
    actives and no patents returns `verdict: "insufficient_evidence"` with both
    axes null and `next_experiment` naming what would resolve it. A confident
    score on an unstudied target fails this criterion; so does declining without
    naming a resolving experiment.
    (`INSUFFICIENT_EVIDENCE_AVOIDED`)

14. **Blocks that could not be computed are null with a reason, not fabricated.**
    Several dossier axes have no tool available in this deployment — the
    affinity predictor, cofolding, and the Open Targets modality cross-check.
    Their fields (`affinity.*`, `structure.cofold_control`,
    `pocket_neighbour_precedent.*.cofold_transfer`) must be `null` with the
    unavailability recorded in `not_found`. A populated value in any of them is
    recalled, not measured, and fails this criterion outright.

15. **The final reply carries the dossier.** Sandbox files are not retrievable
    through the Files API after the session ends, so the reply is the only
    channel back. This criterion is graded on the file only insofar as the file
    must exist and be complete; the reply requirement is stated in `CLAUDE.md`
    and is not machine-graded here.
