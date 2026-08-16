---
name: falsification-sweep
description: >
  Attacks a druggability claim before it is reported — checks whether reported
  actives collapse to one assay, one series or one lab, whether a holo ligand is
  a known frequent hitter, whether a pocket appears in only one crystal form, and
  what clinical programs were terminated and why. Treats a low fpocket
  druggability score as a property of the score rather than of the pocket — 41%
  of pockets with a drug-like ligand physically bound score below 0.1 — so it is
  never entered as a finding against a site. Routes the rare finding that is
  a literature-provenance question back to the upstream graph as an ask, under a
  five-gate rule that refuses anything a local table can settle. Records checks
  that found nothing as well as checks that found something. It does NOT produce
  a verdict, does NOT adjust any score, and an outstanding ask does NOT block a
  verdict or justify a null; it attaches evidence for the reader to weigh.
---

# falsification-sweep

A claim that survived an attack is worth more than a claim nobody tested. Run
this before returning the dossier, and record every check — including the ones
that came back clean, because "we looked and found nothing" is information and
silence is not.

Nothing here changes a number. It populates `falsification.checks_run`,
`falsification.findings` and `falsification.survived`.

## The checks

### 1. Does the actives count collapse to one assay?

```sql
SELECT LEFT(assay_description, 55) AS assay, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM chembl_v.bioactivities_by_accession
WHERE accession = '<ACC>'
GROUP BY assay_description ORDER BY n DESC LIMIT 5
```

Above ~30% for a single assay, the count is about that assay. Then read the
description and ask the harder question: **does it even measure this protein?**

TNF-alpha's top assay is *"IRAK4 Monocyte TNFalpha Cell Based Assay"* at **45.0%
of 6,447 activities**. It measures IRAK4. TNF is the cellular readout. A dossier
that reports "2,582 distinct compounds" as TNF-alpha precedent has been fooled by
this exact thing.

Do not reach for `assay_type = 'B'` as a defence. TNF-alpha's split is B = 5,830
/ F = 617 — about 90% binding — **and the IRAK4 assay is in the B bucket**.

### 2. Is the best potency from a characterised assay?

Pull the assay description behind the headline number. Treat these as unusable
for a potency claim no matter how good the value:

- *"Inhibition assay using TNF-alpha."* — the source of a 0.03 nM Ki
- *"Inhibition of c-MYC (unknown origin)"* — the source of MYC's 0.2 nM

Prefer a slightly weaker number you can characterise. TNF-alpha's best *credible*
direct-binding value is Kd 1.3 nM by SPR against immobilised trimer — three
orders weaker than the uncharacterised figure, and the one worth reporting.

Also check `standard_relation`: `>` is a **failed** measurement. `EC50 > 10000 nM`
means the compound did nothing up to 10 µM. Counting it as an active inflates
precedent with non-results.

### 2b. CROSS-ACCESSION CHECK — the highest-yield query in this skill

Run this before anything else on the potency claim. For the top compounds by
potency, ask what else they hit:

```sql
SELECT accession, standard_type, standard_value, standard_units, pchembl_value, assay_id
FROM chembl_v.bioactivities_by_accession
WHERE compound_chembl_id = '<TOP_COMPOUND>' AND pchembl_value IS NOT NULL
ORDER BY pchembl_value DESC
```

**If a compound is equipotent against another protein, the measurement may
belong to that protein's programme, not yours.** Verified on TNF-alpha:
CHEMBL1288000 registers **Ki 0.074 nM against P01375 (TNF) and Ki 0.07 nM
against P78536 (ADAM17)** — the same measurement, two accessions. The whole
top-100 chemotype is the Schering-Plough hydantoin **TACE/ADAM17** series: the
protease that *sheds* TNF, not TNF.

Combined with the IRAK4 assay, two off-target programmes account for **53.9% of
all TNF activities and 1,215 of 2,582 compounds**. One query found it.

Both are the same failure mode — **readout protein is not measured protein** —
and it is the dominant way a bioactivity table lies.

### 2c. Approved-drug rows in a bioactivity table are not precedent

`bioactivities_by_accession` reported **17 compounds at max_phase 4** for
TNF-alpha. **None of them binds TNF.** Thalidomide and lenalidomide act on
cereblon; dexamethasone on the glucocorticoid receptor; doramapimod on p38;
pentoxifylline on PDE; plus hexachlorophene, gentian violet and methylene blue.
Every one is a TNF *production* readout.

Three of them — digoxin, gentian violet, hexachlorophene — come from a **"qHTS
assay to identify small molecules that STIMULATE TNF"**. The wrong direction
entirely. Thalidomide's row is `IC50 > 10000 nM`, a failed measurement.

Meanwhile the one genuine clinical direct binder, **balinatunfib (SAR441566), is
absent from ChEMBL entirely**. So the table held seventeen false precedents and
zero true ones.

**Approved status in a bioactivity row means the compound is approved for
something. It does not mean it binds your target.** Cross-check every one
against `drugs_by_accession`, which requires a curated direct mechanism.

### 3. Do the actives collapse to one series or one lab?

Look at the compounds behind the top potencies. A hundred analogues from one
paper is one result, not a hundred. Check `assay_id` and document provenance —
if the potent compounds share an assay and a chemotype, say so. IL-17A's **117
distinct compounds against RORgt's 12,900**, despite far greater commercial pull
on IL-17A, is itself evidence of difficulty rather than evidence of nothing.

### 4. Is the holo ligand actually drug-like?

A structure is not evidence just because something is bound. Check the ligand:

- **Frequent hitters.** 2AZ5's ligand — chemical component **`307`**, despite PDB
  titles saying SPD304 — is bis-electrophilic and widely regarded as promiscuous
  and cytotoxic. **That is the finding, and it stands on the chemistry alone.**
  The old supporting clause — "its site scores 0.346 at best against 0.708 for
  the sotorasib pocket, consistent with a micromolar tool compound, not a drug" —
  is **withdrawn as support**. Both numbers are real and the *inference* from
  their gap is not: after check 5a, a 0.35-versus-0.71 gap is well inside the
  spread the score produces across pockets that all have an approved drug bound
  in them — EGFR 6LUD scores **0.013** with osimertinib in it and RORgt 6C1P
  **0.009** with a ligand in it, against KRAS 6OIM's 0.708 — so a gap that size
  discriminates a tool compound from a drug not at all. Judge the ligand on its
  chemistry — bis-electrophile, cytotoxicity, promiscuity reports — never on the
  score of the pocket it sits in.
- **Cofactors and buffer components.** GDP, ATP, PEG, glycerol, sulfate,
  cryoprotectants. A pocket that exists around a cryoprotectant is an artifact.
- **Covalent warheads** bind sites that may not be addressable non-covalently.

### 5. Does the pocket appear in only one crystal form?

Run the ensemble. A pocket present in one entry and absent in five is a finding.
So is a druggability score that swings by orders of magnitude across an ensemble
— **but only if every value in the swing describes the same site**, and that is
exactly what this section used to get wrong.

#### 5a. A LOW DRUGGABILITY SCORE IS NOT A FINDING. Attack it, do not report it.

Added 2026-08-15, and it inverts the direction this check used to point. The
sweep exists to attack claims, and a low druggability score reads like a
falsification result — the pocket looked good, the score says otherwise. It is
not one. Measured over 15 targets, 67 structures and 134 measurements:

- on **37 holo structures where a drug-like ligand is physically bound and the
  scored pocket is anchored to that ligand** — certain positives by construction,
  spanning all 10 known-druggable targets — the median score is **0.320**, **25
  of 37 fall below 0.5** and **15 of 37 (41%) fall below 0.1**;
- EGFR 6LUD with osimertinib bound scores **0.013**; JAK1's median is **0.009**
  across nine approved drugs; RORgt 6C1P is **0.009 at rank 55 of 60**; TYK2
  6NZP with deucravacitinib is **0.169**; BCL-2 6QGK is **0.025**; NLRP3 runs
  **0.001–0.018** across seven holo crystals including one clinical compound;
- target-level AUC is **0.720 with a 95% CI of 0.44–0.94** at D=1.6 — the
  interval includes chance — and **0.520** at D=2.4;
- and it is **inverted** at target level: MYC, zero holo structures and canonical
  undruggable, has a D=2.4 median of **0.75**, above KRAS, BCL-2, JAK1, EGFR and
  NLRP3.

So the honest sweep finding on a low score is about the *score*, not the target:
**record that the pocket scored low, record the 41% false-negative rate beside
it, and do not enter it in `findings` as evidence against the pocket.** A
falsification block that lists "druggability 0.02, site may not be real" has
manufactured a finding out of a measurement error rate.

**What to attack instead, on the same data:** the D=1.6 site volume, which
separated all 15 targets at AUC 1.000. And when volume and druggability
disagree — a 290 Å³ EGFR site scoring 0.013 — that disagreement is the finding.
Report it; do not resolve it in either direction. The volume guide it would be
resolved against (≥240 Å³ druggable, ≤210 Å³ hard) is an **uncalibrated
proposal**, a 17% margin fitted post hoc on n=15 with only 5 hard targets, and
it gates nothing.

**Do not reach for persistence as the replacement.** The site pocket was
detected in 100% of structures for all 15 targets, so persistence is **AUC
0.500** and the published consensus criterion on top of it gives 0.560 while
**ranking MYC first at 0.80**. Substituting it reproduces the same inversion one
rung down.

#### RETRACTED — the 651-fold TNF-alpha druggability spread

This section carried a worked example, and the example was wrong. It is kept
here, marked, rather than deleted: a withdrawn result shown as withdrawn is more
trustworthy than one quietly dropped, and a reader who meets the number in an
older document needs to be able to find out what happened to it.

**What was claimed.** Across five apo TNF-alpha trimers, "the same site" gave
volume 206.7–309.2 A^3 and druggability 0.001 (2ZJC) to 0.651 (1A8M) — a
**651-fold spread**. The reading offered was that a single structure, 1A8M,
would call the site druggable and the other four would call it dead. The figure
appears as **650-fold** in some older copies; the two are the same claim, and
651 is what 0.651/0.001 gives. It is now cited only as retracted.

**What killed it.** The pockets were matched across structures on shared residue
*numbers*, chain-agnostically. mdpocket, run in characterization mode over the
superposed ensemble, showed the matched pocket's centroid sits **7.7 A** from the
SPD304 site it claimed to be measuring, and that the matcher was not even
self-consistent: 1TNF matched a pocket **12.2 A** from where the other four
matched. Within a single structure, the pockets called the same site at
clustering D=1.6 and at D=2.4 sit about **12.3 A** apart — about **18.4 A** on
2AZ5. And the method cannot work here even in principle: a 19-residue reference
on a homotrimer collapses to **11 distinct residue numbers**, because the three
protomers triplicate them, so discarding chain identity makes a C3-symmetric
site unresolvable. No overlap threshold fixes that.

The spread was therefore never a spread of one site. Neither was the volume
range beside it: **206.7–309.2 A^3 is void as well**, because it came from the
same matching step.

**Three further defects in the passage that carried it** (audit 2026-08-15):

- the volume range 206.7–309.2 A^3, void as above;
- the **K98R caveat was attached to the wrong pocket**. K98 does not line the
  SPD304 site — in holo 2AZ5 the nearest Lys98 heavy atom is **8.74 A** from
  ligand `307`, outside the 5 A contact shell (Tyr56 is 7.82 A, also outside).
  K98 lines the *on-axis* cavity, which is the pocket the matcher was actually
  tracking;
- the **mutant count was wrong**. The text said two of four. It is **four of
  five**: 1TNF is the only wild-type apo entry; 1A8M carries R31D, 2ZJC carries
  both K98R and R31A, 2E7A carries K98R, 5TSW carries Y56F.

**What the check should be instead.** The question is still worth asking. Ask it
with the site fixed by construction rather than matched after the fact:

- use mdpocket characterization mode — one grid definition, derived once,
  applied to every superposed structure. `pocket_scan` returns it as
  `mdpocket.sites`;
- prefer `site_from_ligand`, and read `distance_to_donor_ligand_centroid_a`
  before quoting any number off a site entry. A centroid more than ~4 A from the
  donor ligand is a different pocket — and that 4 A is a proposal resting on one
  measured case, not a calibrated threshold, so say so wherever you rely on it;
- read `site_pocket_selected_by`. `max_druggability_no_ligand_site`,
  `site_signature_unreliable_homooligomer` and `no_pocket_matched_site_signature`
  do not identify a site at all, so values carrying them are reported per
  structure and never pooled into a spread;
- **a refusal is a result.** Run this way, the same five apo TNF-alpha trimers
  return **0.00 A^3 in four of five** at the true SPD304 site, because SPD304
  binds only after a subunit is displaced. mdpocket returning zero, rather than
  substituting a cavity 7.7 A away and calling it the site, is the entire reason
  the tool was changed.

Keep the ensemble-composition check, which was right in substance and wrong in
its numbers: only one wild-type apo TNF-alpha entry exists (1TNF) and **four of
the five** carry mutations. An ensemble of mutants is not an ensemble. State the
composition beside any spread you report.

### 6. Is the accession mapping real?

Several PDB entries mapped to P10415 (BCL-2) are actually **Bcl-xL** constructs —
9IGG and 9IGH are titled as such. Accession mapping alone is not identity. Check
entry titles and construct ranges before counting a structure toward your target.

Related: in `chembl_v.target_proteins`, `n_target_components > 1` means a complex
or family, and activity attributed there is inherited, not measured on your
protein.

### 7. What was tried in the clinic, and why did it stop?

Termination reasons are the highest-value evidence in the dossier and they live
in the literature, not the databases. Search Paperclip's trials and papers.

- **IL-17A** — LY3509754 (Lilly) Phase 1 **terminated for drug-induced liver
  injury**: four participants with raised transaminases and acute hepatitis
  despite strong target engagement. Meanwhile DC-806 (DICE) showed Phase 1c
  proof-of-concept, PASI −43.7% at 800 mg BID vs −13.3% placebo.
- **RORgt** — VTP-43742 stopped on reversible transaminase elevations at 700 mg;
  TAK-828F discontinued on preclinical teratogenicity; class-wide RORg1
  cross-reactivity and thymic lymphoma concern.

**Record these without letting them touch the tractability number.** RORgt has
152 holo structures, 12,900 compounds and 0.1 nM potency. It is tractable and it
failed. Both are true, and conflating them destroys the only useful thing the
dossier says.

### 8. Is a look-alike being counted?

Check that clinical or approved agents actually hit *your* target with *your*
modality:

- **Brodalumab** targets IL-17**RA**, the receptor — not IL-17A (Q16552).
- **Icotrokinra / JNJ-77242113** is an oral **peptide** against **IL-23R** — an
  easy false positive for an IL-17A small-molecule search, because "oral" and
  "IL-17 pathway" both match.

### 9. Is this our question at all?

Checks 1–8 attack claims we are the right instrument to settle. This one asks
the opposite: **is this finding a claim about what the literature says, which we
are not equipped to adjudicate and somebody upstream is?**

We are the structural and chemical instrument. The upstream knowledge-graph team
is the literature instrument. "Do these two reviews assert a target relationship
that primary literature supports?" is their question. Until now the sweep either
burned effort on it, reported it unresolved, or dropped it.

**Route it, do not answer it.** The mechanism is `graph-intake`'s existing
ask-back protocol — four verbs, `expand_node` / `resolve_link` / `test_gap` /
`new_question`, pointed at a graph row by id, one ask per request, one round per
request. Read "Asking back after intake" there before issuing anything; the five
gates and the never-ask list live in that file and are not repeated here.

Two things about this check that make it unlike the other eight:

- **It changes no number, same as the rest** — but it also does not change a
  *verdict*, a *null*, or the completion of the run. An outstanding ask never
  blocks a verdict and never licenses a null. Finish the dossier as though the
  ask will never be answered.
- **It is expected to fire almost never.** Run it on every sweep; expect it to
  come back clean nearly every time, and record that it came back clean like any
  other check. The four cases below are the ones that motivated building it, and
  the rule fires on exactly one of them.

Record the check in `checks_run` whether or not it fires, and put any issued ask
in `not_found[]` prefixed `ASK[<verb>:<target id>]`.

#### The four cases that motivated this, run through the rule

Every one of these was a real run. Three of the four are here to show the rule
*not* firing, which is the more useful half.

**Obefazimod / ABX464 on TL1A — FIRES, but only after we answered it.**

PMC10762860: *"One prototype of TL1A, ABX464, is an oral small molecule that
upregulates a single micro-RNA…"*. PMC11642585: *"ABX464, a prototype of TL1A,
is an oral small molecule that modulates a specific microRNA…"*. It is not a
TL1A agent. It is a quinoline miR-124 upregulator, originally an HIV Rev
antiviral, and it matches every surface feature an automated search keys on:
oral, small molecule, IBD, named in the same sentence as anti-TL1A agents.
Swallowing it yields a Phase 2b oral small-molecule TL1A programme that does not
exist.

Gate 3 kills the obvious ask, because **we can settle this ourselves in one
query** — measured, 6 ms:

```sql
SELECT molregno, tid, mechanism_of_action, action_type
FROM chembl.drug_mechanism WHERE molregno = 2335315
-- 2335315 | 120082 | Cap binding complex modulator | MODULATOR
```

So the dossier is not blocked and never was. What survives is the
**post-resolution ask**: the graph carries a wrong edge that will propagate to
every other consumer next round. Verbatim:

```json
{
  "ask": "resolve_link",
  "target": "L1",
  "depth": "deep",
  "question": "POST-RESOLUTION, NOT BLOCKING — we have already answered this for our own purposes and are reporting the answer, not requesting one. L1 asserts obefazimod (ABX464) acts on TL1A. Both supporting findings are review text: PMC10762860 'One prototype of TL1A, ABX464, is an oral small molecule…' and PMC11642585 'ABX464, a prototype of TL1A, is an oral small molecule…'. These two are NOT independent — they share senior author Atilla Ertan. Against: ChEMBL curates obefazimod (molregno 2335315) as 'Cap binding complex modulator' (MODULATOR), not any TNF-superfamily ligand; the primary characterisation is as a quinoline miR-124 upregulator (Vautrin et al., Drug Discov Today 2021, doi 10.1016/j.drudis.2020.12.019, PMID 33387693); and PMC11858795 lists 'anti-TL1A, obefazimod' as separate agents in one enumeration. What would settle it: any primary report of ABX464 binding or antagonising TNFSF15/TL1A protein. We found none. Recommend L1 be retyped or dropped."
}
```

Note what the ask carries that a bare question would not: **the two reviews
share an author**, so the graph's `independence: 0.5` on that link is generous
and "two sources agree" is really one source twice. That is a literature-provenance
fact, it is exactly their domain, and we found it by reading the metadata.

**VTP-43742 on RORgt — DOES NOT FIRE (gate 3).** A Phase 3 claim dated
2023-08-28 is three months *newer* than a termination report dated 2023-05-20,
and "trust the newer paper" gets it backwards. But the registry settles it: ctgov
shows exactly two VTP-43742 studies, both Phase 1, latest posted 2018, no Phase 3
anywhere. The tiebreak is ours and `terminated-programs` Rule 3 already
prescribes it. The underlying stale-review phenomenon is a literature-provenance
question in the abstract; it is not one for *this* claim, because we resolved it.
Report both sources with their dates, per Rule 3. No ask.

**LY3509754's trial ID — DOES NOT FIRE (gate 3), and it was never a conflict.**
Reported unresolved on the grounds that two sources disagreed, NCT04586920
versus NCT04152382. They do not disagree. There are **two trials**, and one
query returns both in 418 ms:

```
NCT04152382 | Terminated | Phase 1 | 30  | Terminated due to liver findings
NCT04586920 | Terminated | Phase 1 | 104 | Terminated due to safety findings
```

PMC13149041 still listing the compound as "currently in clinical development" is
the same stale-review pattern, settled the same way — both NCTs have read
Terminated since 2022. This was a retrieval failure wearing an ambiguity's
clothes, and an ask-back button would have made it permanent by giving it
somewhere respectable to go. **Two identifiers in two sources is not a
contradiction until you have checked whether they name the same thing.**

**IRAK4's contested efficacy claim — DOES NOT FIRE (gate 1).** PMC12325316
argues kinase inhibition "cannot completely block TLR signalling"; the registry
shows Pfizer's Phase 2 programme as Completed — NCT02996500 (n=269), NCT04092452
(n=194), NCT04413617 (n=460) — plus NCT04575610 terminated for lack of
enrollment, which is OPERATIONAL and not a safety or efficacy stop. The claim
fails at gate 1: per dossier rule 7 an efficacy argument does not touch a
tractability number, so it changes no dossier value and there is nothing to ask
about. Reporting it unresolved was correct and remains correct.

**Why obefazimod and not IRAK4.** The asymmetry is not about which claim is
better supported. Obefazimod's claim asserts a *target relationship* — it would
have put a compound into `clinical_stage_small_molecules` and invented a
programme. IRAK4's claim asserts an *efficacy ceiling* — it bears on whether the
drug works, which is another station's question entirely, and touches no field
we own. Gate 1 is about which axis a claim lands on, not how true it is. A
false claim that lands on nothing we report is still not our problem.

#### And one that fires cleanly

The shape the rule is actually for, exercised in
`fixtures/upstream_graph_askback.json` as link `L3`: a pipeline review asserts an
oral small-molecule antagonist of the target reached Phase 2. If true it fills
`target_precedent.clinical_stage_small_molecules`. The compound has no
`drug_mechanism` row, no registry record, and a corpus grep on the code returns
only the review that made the claim. All five gates pass, and the answer is
genuinely somewhere we cannot reach — `coverage.stop_reason` is `max_papers`, so
the literature the graph has not read is where it lives.

```bash
python3 .claude/skills/graph-intake/graph_read.py \
        fixtures/upstream_graph_askback.json --allow-fixture --ask-context
# L1 and L3 clear the mechanical gates; L2/L4 fail on primary basis,
# L5/L6 on mixed, L7 because rounds already carries the ask.
```

## Failure modes

### An ask instead of a query

The regression this skill's ninth check introduces, and the one to watch for.
Every one of the four real cases above turned out to be answerable inside the
pipeline — two by `ctgov.studies`, one by `chembl.drug_mechanism`, one by not
being a tractability question at all. A rule written from those cases and not
tested against them would have fired on all four and forwarded, upstream, four
questions we answer in well under a second each.

**Symptom:** a sweep that ends with more asks than findings, or an ask whose
`not_found` neighbours do not include the null results from ChEMBL, the registry
and a grep on the exact identifiers. **Fix:** run the lookups, write the nulls,
*then* consider the ask. Gate 3 exists to be expensive.

### Reporting only what you found

A sweep that lists three findings and no checks looks thorough and proves
nothing. `checks_run` must list every check attempted; `findings` lists what came
back. A check that found nothing is what makes the ones that found something
credible.

### Letting the sweep become a verdict

This skill attaches evidence. It does not lower a score, flip a verdict, or
resolve `axis_conflict`. If a finding seems to demand a different verdict, put
the finding in the dossier and let the reader decide. The moment falsification
starts adjusting numbers, the numbers stop being measurements.

**The sharpest instance of this is now check 5a.** A low druggability score is
the most verdict-shaped thing this sweep will ever be handed — it looks like the
pocket claim collapsing under attack — and it is a measurement error 41% of the
time on pockets with a drug physically bound in them. `DRUGGABILITY_LOAD_BEARING`
in `validate_dossier.py` blocks it from reaching a `not_tractable` or
`insufficient_evidence` verdict, but the validator only sees structured fields:
writing "the pocket scores 0.02 and is probably not real" into
`falsification.findings` as prose routes around it entirely. Do not.

### Treating absence of terminated programs as a good sign

No terminated programs may mean the target was never tried. For a target with
low actives and no clinical history, that is `insufficient_evidence`, not a clean
safety record. IL-11 has 15 activities from a single SPR assay and no clinical
program — its empty termination list means nothing.

### Searching only the databases

Termination *reasons* are almost never in ChEMBL. VTP-43742's transaminase
signal and LY3509754's DILI came from papers and trial records. Use Paperclip's
`/trials/` and `/papers/`, and cite by line-pinned URL.

### Use `grep` for compound names, NOT `search` — verified, and it matters

`search` is semantic and will miss a named compound entirely while returning
plausible neighbours. Measured:

| query | verb | result |
| --- | --- | --- |
| "LY3509754 IL-17A small molecule hepatotoxicity" | `search -s pmc` | **2 hits, neither about LY3509754** — an alisertib/doxorubicin paper and an unrelated RORgt paper |
| `LY3509754` | `grep /papers/` | **13 papers**, first snippet states the Phase 1 halt for hepatotoxicity |
| `VTP-43742` | `grep /papers/` | **39 papers**, one listing the whole halted RORgt class |

`grep` is full-text regex over every paper's body, not just abstracts. A drug
code, an accession, a gene name or a trial ID is an exact string — grep it.
Reserve `search` for topics.

That VTP-43742 grep also recovered what a database sweep could not: *"GSK2981278,
PF-06763809, JNJ-61803534, VTP-43742 (Vimirogant), TAK-828F, and AZD0284, were
halted or put on hold"* — closing a NOT_FOUND that the structured sources left open.

### Papers disagree, and the older one is often stale

The same grep returned PMC10487560 saying VTP-43742 *"is currently being
evaluated in a phase III clinical trial"* — flatly contradicting the
termination reported elsewhere. The paper predates the stop.

**Do not resolve this by picking one.** Report both with their dates and let the
reader see the disagreement. A finding that a claim's support is time-dependent
is more useful than a confident pick, and silently choosing the convenient
citation is how a dossier becomes untrustworthy.

## Output

Populate `falsification`:

- `checks_run` — every check from this skill, by name, whether or not it fired.
  Check 9 is included on every run; "ran, did not fire" is its normal result.
  **Check 5a is included on every run too, and it can only ever "not fire" as a
  finding** — its result is a note recording the score and the 41% false-negative
  rate beside it. A 5a entry in `findings` is a defect
- `findings` — what came back, each with its source
- `survived` — true only if no finding materially undercuts the precedent claim;
  false with an explanation otherwise; never null after a run

An ask issued by check 9 does **not** go in `findings` — it is not a finding,
it is an open question. It goes in the dossier's `not_found[]`, one entry,
`field` naming the dossier field it would have improved and `reason` beginning
`ASK[<verb>:<target id>]` followed by the question text. `survived` is computed
as if the ask does not exist, because it might never be answered.
