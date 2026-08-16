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
| `pocket_calibration.json` | verified in-repo | KRAS holo vs apo — the backbone-collapse cryptic mechanism; the TNF-α mdpocket ensemble calibration; and the withdrawn 651-fold druggability spread, kept as the record of a retraction |
| `immunology_calibration.json` | found by execution | Four failure modes only real structures surface |
| `upstream_graph.json` | synthetic, marked `_fixture` | An upstream evidence graph, conformed to the real `SCHEMA.md` v1.1 |
| `upstream_graph_edgecases.json` | synthetic, hand-written | `kind: gene`, `basis: hedged_only`, a `no_effect` finding, `status: partial` |
| `upstream_graph_unknownverb.json` | synthetic, hand-written | Unknown `how` verbs — the `needs_adjudication` path, in three signal states |
| `upstream_graph_askback.json` | synthetic, two quotes verbatim-retrieved | The post-intake ask-back trigger — two links that should produce an ask, five that must not |
| `upstream_graph_expected.json` | derived, accessions retrieved | Grading key for `graph-intake` |

## The upstream graph

`upstream_graph.json` is where "targets arrive from the upstream pipeline"
stops being a sentence and becomes a file. It is a literature evidence graph in
its producer's own format — `things`, `links`, `findings`, `papers`, `gaps` —
and `graph-intake` reads it to fill this agent's input contract.

It is **synthetic** and carries `_fixture: true`, so its papers and quotes were
never retrieved from any corpus. That is acceptable here and nowhere else in this
directory: what it grades is the *extraction*, not the biology. `graph_read.py`
refuses it without `--allow-fixture` so the guard cannot be forgotten.

One nomination is correct: IRAK4 (Q9NWZ3), catalytic function, mechanism
`unknown`. The graded negative is IL-6 — `zimlovisertib reduces IL-6` has the
same shape as `zimlovisertib inhibits IRAK4` and only the verb separates a
readout from a target. That is the TNF-alpha assay-provenance failure of Rung 4,
moved one stage upstream where nothing else is looking for it.

### The fourth graph fixture — and why its negatives matter more

`upstream_graph_askback.json` grades a different thing from the other three:
not what the intake *extracts*, but what it decides to **send back**. Two links
should produce an ask; five must not, and the five are the point.

| link | outcome | why it is in the set |
| --- | --- | --- |
| `L3` | **ask** — `resolve_link` | A review asserts an oral small-molecule antagonist reached Phase 2. It would fill `clinical_stage_small_molecules`; the compound has no ChEMBL mechanism row, no registry record, and the only source is the review. All five gates pass. |
| `L1` | **ask** — `resolve_link`, post-resolution | The obefazimod/TL1A trap. We answer it ourselves from `chembl.drug_mechanism`, so it never blocks; the ask goes anyway so the wrong edge does not propagate. |
| `L2`, `L4` | no ask | `basis: primary`. A primary-supported claim is never an ask. |
| `L5` | no ask | An efficacy claim. Dossier rule 7 — it touches no tractability number, so it fails gate 1. |
| `L6` | no ask | A contested clinical status. `ctgov` settles it; fails gate 3. |
| `L7` | no ask | `rounds` already carries `resolve_link` at `L7`. Fails gate 4. |

A sixth negative is not expressible in the file, because `coverage.stop_reason`
is a single global value and this graph needs `max_papers` for `L3`. Set it to
`complete` and every ask must stop firing — verified: `--ask-context` then
reports no link clearing the gates at all.

Two of its quotes (`f1`, `f2`) are **verbatim from real papers**, PMC10762860
and PMC11642585, retrieved 2026-08-15. That is a deliberate departure from the
other three fixtures and it is recorded in the file's `_quote_provenance` block.
The rule was derived from those two exact sentences and a paraphrase would hide
why the trap works — both reviews call ABX464 "a prototype of TL1A", and they
share a senior author, so "two sources agree" is one source twice. The file is
still `_fixture: true` and nothing in it may be cited.

### Why three graph fixtures

The producer's schema gives `how` **no enum**, while every other categorical
field in it has one. So the verb that separates a target from a readout is open
vocabulary written by an upstream model, and our two verb lists can never be
complete. We do not get to ask for a closed vocabulary — this is ours to absorb.

That is why the set splits three ways. `upstream_graph.json` covers the happy
path with known verbs. `upstream_graph_edgecases.json` covers the four schema
branches the RA graph never reaches. `upstream_graph_unknownverb.json` covers
the case that has no clean answer: a verb we do not recognise, where the intake
must weigh the quote, the assay context and the graph shape — and is allowed to
refuse.

## The ladder

### Rung 1 — JAK1 (P23458). Can it do the easy thing?

Pre-formed ATP-site kinase. 14,342 compounds, best 0.010 nM, ruxolitinib 2011
plus two JAK1-selective approvals, **43 of 52 structures holo** (9 apo, 0
undetermined — re-derived from scratch 2026-08-15 under the chemistry
classifier; 42 was the superseded MW-window value and 40 reproduced under no
rule at all).

Worth knowing before you grade this rung: JAK1's *measured* fpocket
druggability is **0.009**, a median across nine approved drugs. If any criterion
is ever keyed to a druggability threshold, the easiest rung in the set fails
first.

The 14,342 is a *filtered* count — `n_target_components = 1`. Dropping that
predicate gives 14,472 and is wrong; see `_audit_2026_08_15` in `targets.json`.
Best potency was 0.032 nM here until the 2026-08-15 audit found that value came
from excluding every IC50 on a false "flagged" premise.

**Tests:** nothing subtle. If this is wrong, stop and fix the plumbing.
**Expect:** `small_molecule_tractable`, `cryptic_pocket_risk: low`.

### Rung 2 — RORγt (P51449). Does it confuse tractable with successful?

154 holo of **162** structures, 12,900 compounds, 0.017 nM potency — and **zero
approvals**. (152–154 all pass — two of the three entries the rule adds are a
DHEA sterol and an NDSB-256 crystallisation additive. 0.1 nM remains the best
cell-context IC50.) VTP-43742 stopped on transaminase elevations, TAK-828F on
preclinical teratogenicity, class-wide thymic lymphoma concern.

The holo count here is **not yet regenerated** — 154 is the superseded
MW-window value; the 162 total is confirmed. See
`_structure_regeneration_2026_08_15` in `targets.json`.

**Tests:** that clinical failure does not leak into the tractability number —
and now also that a near-zero pocket score does not, since RORγt's 6C1P measures
**0.009 at rank 55 of 60**.
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
filter does not catch it. Five approved biologics, zero small molecules. The
earliest holo ligand (`307`, 2AZ5) is a known promiscuous frequent hitter. The
site is a trimer-axis cavity that is **occluded, not cryptic** — steric
occlusion, not backbone collapse. It is pre-formed: delete the third chain and
all five apo structures recover the pocket, and the max backbone C-α
displacement at the site is ~1.6 Å. It therefore fails both community criteria
for cryptic (Vajda 2018; CryptoBench's apo-holo pocket-residue RMSD > 2 Å), and
must not be cited as a cryptic-pocket case. "Pre-formed" is a statement about the
subunit-removed state; in the intact trimer the third protomer is standing in
the site.

Holo count is **20 by the current rule, 19 defensibly** — regenerated
2026-08-15 under the chemistry classifier (52 total, 20 holo, 32 apo, 0
undetermined). The history is 15 (≥300 Da) → 17 (250–1200 Da) → 16 (that, minus
the spin label) → **20**. The jump is not drift: the classifier has **no lower
MW bound at all**, deliberately, and 16 inherited a 250 Da floor.

5UUI is a TNF-α carrying the MTSL nitroxide **spin label** on an engineered T77C
cysteine — a false holo, and the one measured **false positive** of the
classifier anywhere in this regeneration: MTN's chemistry really is drug-like,
and what disqualifies it lives in the entry title, which no chemistry test can
read. Subtract it → 19. The three sub-250 Da entries the new rule adds are not
noise: 6X81 (UTJ, 244 Da) and 6X83 (UTS, 208 Da) come from the *same
J. Med. Chem. paper and the same series* as 6X82/6X85/6X86, which every rule
counted, and UTS is the minimal benzimidazole core of the series 6OOY's A7M
belongs to. 4TWT (38A, 210 Da) is left unresolved and named.

**Accept 18, 19 or 20 with 5UUI named. Reject 15/16/17** — all artifacts of an
MW floor this rule does not have.

**Tests:** assay provenance, frequent-hitter detection, multi-chain handling, and
the occlusion mechanism — including that it is *not* reported as cryptic.
**Expect:** `axis_conflict` populated. Reporting 2,582 compounds as precedent is
the failure.

### Rung 5 — KRAS (P01116), `as_of_date = 2012-12-31`. Does it know what it cannot see?

Every pre-2013 structure is apo or GDP-bound. The switch-II pocket scores
**0.708 on holo and 0.000 on apo** — backbone collapsed ~8.8 Å at Glu63. That
figure is hand calibration: it comes from a protocol with auto-trim and
residue-name matching disabled and the mobile regions named by hand. The
deployed zero-knowledge default measures 8.65 Å max C-α displacement for KRAS
and ~1.55 Å for TNF-α, against hand figures of 8.83 Å and 1.62 Å. Mechanism and
`is_cryptic` are identical under both, so nothing downstream changes, but the
two sets are not interchangeable — quote what the run reported. The
order-of-magnitude separation (~8.8 vs ~1.6 Å) is the finding, not the decimals.

**Tests:** the cryptic blind spot, and the as-of cutoff.
**Expect:** `cryptic_pocket_risk: high`, and explicitly **not** `not_tractable`.
Run uncapped it must return sotorasib 2021 and adagrasib 2022. The agent must
not claim it would have found G12C early.

⚠️ **This rung no longer tests what the paragraph above used to claim, and the
change has not been applied.** It said to expect *low* computed tractability,
and that a 2012 run "says not tractable". Neither is derivable now: rule 4.2
makes druggability non-load-bearing and forbids it from carrying a verdict, and
the volume criterion that briefly replaced it has been **suspended** (its
anchors were measuring the wrong proteins). Taking the suspended band at face
value the answer was never "low" anyway — the apo switch-II pocket is 230 Å³ and
site-anchored KRAS is 226 Å³, both *inside* the unclassified band. A 2012 run
under current rules reports the computed axis as **unresolved**, not low. The
intent of the rung — "knows what it cannot see" — survives intact and is
arguably sharper. Proposed wording is in
`_expected_output_audit_2026_08_15` in `targets.json`; a human should rule.

### Rung 6 — MYC (P01106). Can it hold two contradictory facts?

1,079 compounds and **0 of 25 structures with any ligand above 122 Da** — holo 0
re-confirmed 2026-08-15, now under a fifth independent rule, with all 25 entries
strict apo. Intrinsically disordered. Best potency 0.2 nM from an assay described
only as "Inhibition of c-MYC (unknown origin)".

**Tests:** that reported actives with no holo structure read as conflict, not
precedent; that an uncharacterised assay is rejected however good the number.
**Expect:** `not_tractable`, `axis_conflict` populated, not rescued by family
precedent.

⚠️ **The computed axis now argues the opposite, on every sub-measure.** MYC's
D=2.4 druggability median is **0.75 — the highest in the set**, above KRAS 0.54,
BCL-2 0.52, JAK1 0.49, EGFR 0.44. The published consensus criterion ranks MYC
**top**. Persistence is chance-level. And volume, the last measure pointing the
right way, no longer does: the 188 Å³ that put MYC in the "hard" group was
measured on pockets lined entirely by MAX, by MAX plus DNA, and by apo OmoMYC,
and the corrected median is **325.7 Å³** — druggable.

There is a reason: **not one of MYC's 25 entries is wild-type MYC as an isolated
folded chain** (8 MYC:MAX dimers, 9 short MYC peptides on partner proteins, 6
fusion chimeras, 2 OmoMYC). Every pocket ever scored "on MYC" is on a partner, a
chimera or a designed miniprotein.

So `not_tractable` must now rest on **retrieved precedent** — 0 holo, 122 Da
ceiling, uncharacterised best assay — and `verdict_basis` must say so. The rung
now tests something harder and better than "hold two contradictory facts": it
tests whether the agent resists a computed axis actively shouting *druggable*.
An agent that reports the high druggability and top consensus rank **and still
returns `not_tractable`** has passed. Not applied to the ladder — see
`targets.json`.

### Rung 7 — IL-11 (P20809). Will it refuse?

15 compounds from two near-identical SPR assays on the same CAP chip
(CHEMBL6115567 ×11, CHEMBL6115571 ×4). **8 structures, 0 holo, 8 apo, 0
undetermined** — measured 2026-08-15, where before it was asserted without a
number behind it. No drugs at any phase. Just enough data to tempt a confident
score.

Sharper still: **only 2 of the 15 rows carry a number at all** — 140 nM and
2,600 nM. The other 13 have `standard_value` NULL. Reporting "15 activities" as
15 measurements already overstates the evidence 7.5×.

And `best_potency_nm` is now **null**, not 140. Both assay descriptions contain
"(unknown origin)" — the exact string this fixture's own definition says to
reject, and which it *did* apply to KRAS. The file was applying its own rule to
one target and not another; that is provable from the file against itself, with
no query. The numbers stay visible because an agent will find them, and finding
them is the temptation; asserting them is the failure.

**Tests:** the hardest thing to make a system do — decline.
**Expect:** `insufficient_evidence`. Any number here is a failure.

## Retained for method validation

EGFR (P00533), BCL-2 (P10415) and TYK2 (P29597) stay in `targets.json`. EGFR and
BCL-2 are unambiguous positives useful for regression. TYK2 earns its place on
dating: JH1 structures from 2010-06-02, JH2 pseudokinase from 2013-04-10,
deucravacitinib approved 2022. A 2012 cutoff must show no allosteric precedent
and a 2015 cutoff must show it — the cleanest as-of test in the set, because it
tests a *pocket* appearing rather than a drug.

TYK2's domain split was re-derived independently on 2026-08-15 and reproduces
exactly: **JH1 28, JH2 20, both 1 (4OLI), other 3 = 52**. These are *exclusive* —
4OLI is a JH1+JH2 tandem and is reported in its own bucket, not added to either
domain. The older inclusive 29/21 double-counted it and summed to 54 against a
real total of 52; it stays rejected. TYK2 also now carries a holo count for the
first time: **46 holo / 5 apo / 1 undetermined**.

BCL-2 is the one place where **this key is worse than the better answer, and
that needs saying plainly.** Its 40 is the superseded MW-window value, whose
1200 Da ceiling scores 8FY1 (YF8, 1640 Da) and 8FY2 (YFH, 1682 Da) as *apo* —
and those are genuine bivalent BCL-2 degrader co-crystals, real beyond-rule-of-5
precedent. An agent reporting **42 with the two degraders named has done better
science than the key** and must not be marked wrong. Under the regenerated rule
they are `undetermined` rather than apo — visible instead of silently discarded
— which is the improvement, and it means 40 is very unlikely to survive
re-measurement.

## How the structure counts are defined (regenerated 2026-08-15)

Every `pdb_holo` / `pdb_apo` / `pdb_undetermined` figure comes from the
**chemistry classifier**, `.claude/skills/structure-select/ligand_filter.py`
(sha256 `526610951ee1…89f1f3`), not from a molecular-weight window. An entry is
holo iff ≥1 of its `pdb_v.entry_ligands` components classifies `druglike`.

Three things follow, and all three matter for grading:

- **There is no lower MW bound any more.** That is deliberate — size was never
  the discriminator, and the old floors were splitting congeneric series across
  the holo/apo line. This is why TNF-α moves 16 → 20 and JAK1 42 → 43.
- **`unknown` is not `apo`.** An entry with no drug-like component but an
  unclassifiable one is `undetermined`, and `total = holo + apo + undetermined`
  always. TYK2 5C01 is the worked case: its only component is `UNL`,
  "UNKNOWN LIGAND". An agent reporting TYK2 apo as 6 has made the error the
  classifier exists to prevent.
- **A lookup failure is not a chemistry miss.** Failures carry `lookup_failed`
  into `holo_call(...)["undetermined"]` and must never render as apo.

**Only six targets are regenerated** — TNF-α, JAK1, TYK2, MYC, IL-11, STAT3
(plus CD20 as a control). KRAS, EGFR, BCL-2, IL-17A and RORγt still carry the
superseded MW-window values and are flagged `_NOT_REGENERATED_2026_08_15` in
place. Paperclip's SQL backend failed partway through. Which half is which is
recorded in `_structure_regeneration_2026_08_15`, because a half-regenerated key
is only dangerous when nobody can tell.

If you re-measure: the backend silently served a **moving row cap** — the same
query returned 200 rows at one moment and exactly 10 at another, well-formed and
without error, which recorded KRAS as 10 entries against a true 522 on the first
attempt. Reconcile every paged read against a separately issued `COUNT`, under a
canary on the `pdb_v` tables you are actually reading. `SELECT 1` proves nothing.

## Rules for the grading keys

- Every value carries a source: ChEMBL target ID, PDB ID, DOI, or line-pinned URL.
- Every count carries **the definition it was measured under and the date**.
  A grading key with no stated definition drifts; that is exactly how this
  happened.
- Unretrievable is `NOT_FOUND`, never an estimate. A query that timed out is
  unretrievable — it is never a zero.
- Approved drugs split by modality; the two columns are never summed.
- Dates matter — first-approval years and PDB release dates, not just counts.
- **No criterion may be keyed to an fpocket druggability score.** It has a
  measured 41% false-negative rate on structures with a drug physically bound,
  and it is min-max normalised across the other pockets of the same structure,
  so it is not even a property of the pocket.
