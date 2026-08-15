# Fixtures

Targets arrive from the upstream pipeline, so this set is not a domain list —
it is a **ladder of increasing hardness**. Each rung isolates one way the agent
can be wrong, and the rungs are ordered so a failure tells you how far up the
system got before it broke.

Data for every target lives in `targets.json` with an `expected_output` block
that serves as the grading key.

## Files

| File | Status | Contents |
| --- | --- | --- |
| `targets.json` | retrieved and cited | Ten targets, `expected_output` grading keys |
| `pocket_calibration.json` | verified in-repo | KRAS holo vs apo — the backbone-collapse cryptic mechanism |
| `immunology_calibration.json` | found by execution | Four failure modes only real structures surface |

## The ladder

### Rung 1 — JAK1 (P23458). Can it do the easy thing?

Pre-formed ATP-site kinase. 14,342 compounds, best 0.032 nM, ruxolitinib 2011
plus two JAK1-selective approvals, 40 of 52 structures holo.

**Tests:** nothing subtle. If this is wrong, stop and fix the plumbing.
**Expect:** `small_molecule_tractable`, `cryptic_pocket_risk: low`.

### Rung 2 — RORγt (P51449). Does it confuse tractable with successful?

152 holo of 162 structures, 12,900 compounds, 0.1 nM potency — and **zero
approvals**. VTP-43742 stopped on transaminase elevations, TAK-828F on
preclinical teratogenicity, class-wide thymic lymphoma concern.

**Tests:** that clinical failure does not leak into the tractability number.
**Expect:** `small_molecule_tractable` **and** a populated `terminated_programs`.
Downgrading tractability because programs failed is the failure mode.

### Rung 3 — IL-17A (Q16552). Does it fall for modality?

Three approved antibodies (secukinumab 2015, ixekizumab 2016, bimekizumab 2021),
all reporting `action_type: INHIBITOR`, all with no chemical structure. **Zero
approved small molecules.** But 117 compounds exist with a best of 0.79 nM, and
LY3509754 reached Phase 1 before being halted for drug-induced liver injury.

Also the rung where structural plumbing breaks: 9SQX is CIF-only with a
five-character ligand code, and the site is a dimer-interface groove.

**Tests:** modality separation, and that neither "three approved drugs" nor "no
small molecules exist" is accepted as the answer.
**Expect:** zero approved small molecules stated explicitly, biologics in their
own block, real small-molecule chemistry acknowledged, the DILI termination
recorded.

### Rung 4 — TNF-α (P01375). Does it count assays or targets?

2,582 compounds — and **45% of all bioactivity comes from an IRAK4 assay
measuring a different protein**, labelled `assay_type = 'B'` so the obvious
filter does not catch it. Five approved biologics, zero small molecules. The one
holo ligand (`307`, 2AZ5) is a known promiscuous frequent hitter. The site is a
cryptic trimer-axis cavity — steric-occlusion mechanism, not collapse.

**Tests:** assay provenance, frequent-hitter detection, multi-chain handling, and
the second cryptic mechanism.
**Expect:** `axis_conflict` populated. Reporting 2,582 compounds as precedent is
the failure.

### Rung 5 — KRAS (P01116), `as_of_date = 2012-12-31`. Does it know what it cannot see?

Every pre-2013 structure is apo or GDP-bound. The switch-II pocket scores
**0.708 on holo and 0.000 on apo** — backbone collapsed 8.8 Å at Glu63.

**Tests:** the cryptic blind spot, and the as-of cutoff.
**Expect:** low computed tractability **with `cryptic_pocket_risk: high`**, and
explicitly **not** `not_tractable`. Run uncapped it must return sotorasib 2021
and adagrasib 2022. The agent must not claim it would have found G12C early —
run honestly in 2012 this method says "not tractable", reproducing the field's
thirty-year error. Knowing that is the deliverable.

### Rung 6 — MYC (P01106). Can it hold two contradictory facts?

1,079 compounds and **0 of 25 structures with any ligand above 120 Da**.
Intrinsically disordered. Best potency 0.2 nM from an assay described only as
"Inhibition of c-MYC (unknown origin)".

**Tests:** that reported actives with no holo structure read as conflict, not
precedent; that an uncharacterised assay is rejected however good the number.
**Expect:** `not_tractable`, `axis_conflict` populated, not rescued by family
precedent.

### Rung 7 — IL-11 (P20809). Will it refuse?

15 compounds, all from a single SPR assay, best 140 nM. 8 structures, none holo.
No drugs at any phase. Just enough data to tempt a confident score.

**Tests:** the hardest thing to make a system do — decline.
**Expect:** `insufficient_evidence`. Any number here is a failure.

## Retained for method validation

EGFR (P00533), BCL-2 (P10415) and TYK2 (P29597) stay in `targets.json`. EGFR and
BCL-2 are unambiguous positives useful for regression. TYK2 earns its place on
dating: JH1 structures from 2010-06-02, JH2 pseudokinase from 2013-04-10,
deucravacitinib approved 2022. A 2012 cutoff must show no allosteric precedent
and a 2015 cutoff must show it — the cleanest as-of test in the set, because it
tests a *pocket* appearing rather than a drug.

## Rules for the grading keys

- Every value carries a source: ChEMBL target ID, PDB ID, DOI, or line-pinned URL.
- Unretrievable is `NOT_FOUND`, never an estimate.
- Approved drugs split by modality; the two columns are never summed.
- Dates matter — first-approval years and PDB release dates, not just counts.
