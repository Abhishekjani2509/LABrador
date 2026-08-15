---
name: falsification-sweep
description: >
  Attacks a druggability claim before it is reported — checks whether reported
  actives collapse to one assay, one series or one lab, whether a holo ligand is
  a known frequent hitter, whether a pocket appears in only one crystal form, and
  what clinical programs were terminated and why. Records checks that found
  nothing as well as checks that found something. It does NOT produce a verdict
  and does NOT adjust any score; it attaches evidence for the reader to weigh.
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
  and cytotoxic. Its site scores 0.346 at best, against 0.708 for the sotorasib
  pocket. Consistent with a micromolar tool compound, not a drug.
- **Cofactors and buffer components.** GDP, ATP, PEG, glycerol, sulfate,
  cryoprotectants. A pocket that exists around a cryoprotectant is an artifact.
- **Covalent warheads** bind sites that may not be addressable non-covalently.

### 5. Does the pocket appear in only one crystal form?

Run the ensemble. Across five apo TNF-alpha trimers the same site gave
volume 206.7–309.2 A^3 but druggability **0.001–0.651, a 650-fold spread** — a
single structure (1A8M, 0.651) would call it druggable and the other four would
call it dead.

A pocket present in one entry and absent in five is a finding. So is a
druggability score that swings by orders of magnitude across an ensemble.

Check the ensemble's composition too: only one wild-type apo TNF-alpha entry
exists, and two of the four others carry K98R — **a residue lining the very
pocket being measured**. An ensemble of mutants is not an ensemble.

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

## Failure modes

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

### Treating absence of terminated programs as a good sign

No terminated programs may mean the target was never tried. For a target with
low actives and no clinical history, that is `insufficient_evidence`, not a clean
safety record. IL-11 has 15 activities from a single SPR assay and no clinical
program — its empty termination list means nothing.

### Searching only the databases

Termination *reasons* are almost never in ChEMBL. VTP-43742's transaminase
signal and LY3509754's DILI came from papers and trial records. Use Paperclip's
`/trials/` and `/papers/`, and cite by line-pinned URL.

## Output

Populate `falsification`:

- `checks_run` — every check from this skill, by name, whether or not it fired
- `findings` — what came back, each with its source
- `survived` — true only if no finding materially undercuts the precedent claim;
  false with an explanation otherwise; never null after a run
