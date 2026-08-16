---
name: graph-intake
description: >
  Reads an upstream literature evidence graph and extracts the dossier's input
  contract from it — which things are protein targets, what the molecule is
  meant to stop, and which UniProt accession that is. Emits follow-up asks back
  to the graph when the answer is missing or rests only on review citations. It
  does NOT assess tractability, does NOT rank targets against each other, does
  NOT decide a mechanism the evidence has not stated, and does NOT treat a
  computed result as literature evidence.
---

# graph-intake

The dossier's required input is a UniProt accession. Two optional inputs —
`interaction_to_disrupt` and `mechanism_hypothesis` — decide which chains get
scored, and therefore change the druggability number (rule 2b: KRAS 4OBE is
0.442 at rank 1 on chain A and 0.257 at rank 6 on chains A+B). This skill gets
all three out of an upstream evidence graph, or asks the graph for what is
missing.

It reads the graph. It does not ask the graph to change format.

## Setup

`PAPERCLIP_API_KEY` in the environment, for accession resolution:

```bash
set -a; . <repo>/.env; set +a
```

The upstream graph is a JSON file with `things`, `links`, `findings`, `papers`
and `gaps`. Its `rounds` array records the asks already issued against it.

## Procedure

### 0. Check `status` before anything else

`status` is `ok | empty | partial | failed`, and SCHEMA.md note 7 is explicit
that failure is still a graph — the lists are simply empty and `coverage` is
still real. So a `failed` graph parses cleanly and returns zero nominations,
which reads exactly like "no targets in this literature."

Never report zero nominations without quoting `status` alongside it.

### 1. Traverse — mechanical, use the helper

```bash
python3 graph_read.py <graph.json>
```

If you were handed a `graph_id` rather than a file, load it from the mapper's
store first. SCHEMA.md's contract is that Stage 1 owns storage and Stage 2 sends
an id, never a graph; the MCP transport for that does not exist yet, but the
store does, on disk in the documented layout:

```bash
python3 graph_store.py <store_dir> --list                 # what graphs exist
python3 graph_store.py <store_dir> --graph-id g_1a4f > g.json
```

`graph_store.py` reassembles `meta/things/papers/links/gaps` plus the per-round
`findings/r<N>.json` chunks. **It dedupes findings by id rather than
concatenating them**, because the shipped store does not behave the way the
schema documents: SCHEMA.md says rounds append and never rewrite, but on
`g_1a4f` r1 holds 7 findings and r2 holds 12 *including all 7 of r1's*. Each
chunk is a full snapshot. Concatenating gives 19, and the seven duplicates would
land in the `yes`/`no` counts that feed `agreement` and `independence`.

It also reports two things worth reading before you trust the graph.
`_undocumented_fields` lists fields the store emits that the schema does not
describe — currently `papers.pmid` and `findings.claim`. `_dangling_refs` lists
ids that do not resolve, which the schema guarantees cannot happen, so any entry
there means you are reading a torn write rather than a sparse graph.

Stdlib only, no dependencies. It returns `nominations`, `rejected` and
`needs_adjudication`. Read all three. `rejected` is where a wrongly-dropped
target would be hiding, and `needs_adjudication` is a decision waiting for you —
neither is a log to skim.

Nomination rule, both halves required:

- **`kind` is `protein` or `gene`**, and
- either the object of a direct-action edge from a `small_molecule` (`inhibits`,
  `binds`, `blocks`, `degrades`, …), **or** named in a `gaps[].missing` pair.

The gap half is what carries undrugged candidates. Without it the intake can
only ever return targets somebody has already made a molecule against, which
inverts the point of the pipeline.

Both kinds, because the same target is typed either way depending on how a
paper phrased it — "IRAK4 knockdown" reads as a gene, "IRAK4 kinase activity"
reads as a protein. Keying on `protein` alone drops half of them into
`rejected`, where nobody looks.

The helper classifies an edge by the **subject's kind**, not by the verb alone.
`activates` from a small molecule is an agonist; `activates` from a receptor is
pathway biology.

**`how` has no enum.** Every other categorical field in SCHEMA.md carries an
explicit `a|b|c` comment. `how` does not — it is open vocabulary written by the
upstream extraction model. So `DIRECT_ACTION` and `DOWNSTREAM_EFFECT` are a best
guess against an unbounded space, and `needs_adjudication` is load-bearing rather
than a corner case. Read it on every run. An unrecognised verb there is a target
the intake could not classify, not a rare edge.

### 2. Read the mechanism out of the quotes — judgment, yours

`how` is too coarse. `inhibits` does not say what is inhibited. The mechanism is
in the `quote` text, and it is why the helper hands you quotes rather than a
verdict.

`interaction_to_disrupt` accepts exactly three shapes. Match the quote to one:

| shape | quote looks like | example |
| --- | --- | --- |
| catalytic function | "…inhibited IRAK4 **kinase activity**…" | kinase, protease, ATPase |
| named partner | "…**nucleates assembly** of the MyD88 signalosome…" | a PPI |
| oligomeric state | "…displaces a subunit of the **trimer**…" | TNF-alpha |

A target can have more than one. Report every shape the evidence supports —
see failure mode 6.

### 3. Apply the three-state basis rule

This is the rule that keeps a weak answer from driving a hard output. The tier
comes from the **link's `basis`**, never from the finding's own confidence. A
0.88-confidence quote from a review is still background.

| tier | what to do |
| --- | --- |
| `primary` | usable. Set `interaction_to_disrupt`. |
| `mixed` | usable, but carry the disagreement into `notes`. |
| `hedged_only` | **record it, do not act on it.** Every supporting finding said "may" or "suggests". Same treatment as background. |
| `background_only` | **record it, do not act on it.** Treat as unstated for chain selection, and issue a `resolve_link` ask. |
| absent | unstated. Issue a `new_question` ask. |

`background_only` is more dangerous than absence. Absence trips the dossier's
existing refusal to guess. A review citation does not — it produces a confident
looking answer from a single secondary source.

### 4. Resolve the accession — from the quote, not the name

```sql
SELECT accession, gene_name, protein_name, organism, sequence_length
FROM uniprot_v.proteins
WHERE gene_name IN ('<SYM>', …) AND organism = 'Homo sapiens'
```

Resolve using what the **quotes** say, not the node's `name` string. See failure
mode 3 — this is the one that silently assesses the wrong protein.

If two accessions both fit, populate `ambiguity` with both and leave
`uniprot_accession` null. An unresolved target is a correct output. A confidently
wrong accession poisons every number downstream of it.

#### Verifying `symbol_candidates`

When no node is typed `protein` or `gene`, the helper scans names and aliases and
hands you `symbol_candidates` — each with the thing it came from, the matched
token and the action word beside it. Those are proposals, not nominations. Run
the SQL above over the proposed symbols in one `IN` list and keep only what comes
back with a human accession: `MYD88` returns Q99836 and verifies, `ST2825` and
`TLR` return nothing and do not.

A phrase carrying several candidates stays ambiguous unless exactly one verifies
**and** the rest were false regex hits — compound codes, assay names, anything
that was never a biological entity. A candidate that fails because it names a
complex or a family is not eliminated, it is unresolved, and one unresolved
candidate keeps the whole phrase ambiguous. That is why `t5` stays ambiguous
though MYD88 alone resolves: NF-kB and TLR failed as a complex and a family, not
as noise. Populate `ambiguity` with all three and leave `uniprot_accession` null.

The rule above applies unchanged, and it is what makes this route safe to add at
all: an unresolved target is a correct output, a confidently wrong accession
poisons every number downstream of it.

### 5. Emit

One object per nomination, matching the dossier's Contract table:

```json
{
  "uniprot_accession": "Q9NWZ3",
  "gene_symbol": "IRAK4",
  "disease_context": "rheumatoid arthritis",
  "interaction_to_disrupt": "kinase activity (catalytic function)",
  "mechanism_hypothesis": "unknown",
  "provenance": {
    "graph_id": "g_ra4k", "round": 2, "thing": "t1",
    "primary_findings": ["f1", "f5"],
    "recorded_not_acted_on": ["f4", "f3"]
  },
  "asks": []
}
```

Leave `mechanism_hypothesis` as `unknown` unless a quote states the site. See
failure mode 5.

## Asking back

Use the graph's own verbs. SCHEMA.md defines **four**: `expand_node`,
`resolve_link`, `test_gap`, `new_question`. Point at a row by id, never in prose.
One ask per request, one round per request.

| situation | ask |
| --- | --- |
| we have a target and want everything touching it | `{"ask": "expand_node", "target": "<thing id>", "depth": "deep"}` |
| mechanism only in `background_only` | `{"ask": "resolve_link", "target": "<link id>", "depth": "deep"}` |
| mechanism absent entirely | `{"ask": "new_question", "target": null, "depth": "deep", "question": "<specific>"}` |
| a gap names our target | `{"ask": "test_gap", "target": "<gap id>", "depth": "deep"}` |

Before reporting anything as "not stated", check `coverage.truncated` and
`coverage.stop_reason`. Of the five stop reasons — `max_papers`,
`queries_exhausted`, `no_new_results`, `time_limit`, `complete` — **only
`complete` means the literature was exhausted.** The other four mean the run
ran out of budget, so absence proves nothing. The helper surfaces this as
`coverage_warning`.

At `depth: "quick"` absence never means anything at all: SCHEMA.md note 2 says
`quick` reads page 1, and page 1 lies.

## Adjudicating an unknown verb

`how` has no enum. Every other categorical field in SCHEMA.md carries an explicit
`a|b|c` comment; `how` does not, because it is open vocabulary written by the
upstream extraction model. `DIRECT_ACTION` holds seventeen verbs and
`DOWNSTREAM_EFFECT` fourteen — several of them only `-ise`/`-ize` spellings of
each other — against an unbounded space, so the two sets can never be complete.
We cannot ask the upstream team to close the vocabulary. This is ours to solve.

So an unmatched verb is not dropped and is not a rare edge. It is a target the
intake could not classify, and the helper hands it back in `needs_adjudication`
with a `signals` block and a `decide` field pointing here.

The decision is one thing: **is this edge a direct action on a target, or a
downstream effect on a readout?** Getting it wrong sends the dossier to score
pockets on a secreted cytokine — failure mode 2, arriving through a verb the
helper had never seen.

`upstream_graph_unknownverb.json` exercises this path directly, with three
invented verbs chosen to land in three different signal states: `clamps` on a
kinase with an IC50 and a biochemical `where` (direct), `quenches` on IL-6 with
ACR50 and serum levels (downstream), and `perturbs` on MRTFA with quotes that
match nothing either way (refuse). All three objects are `protein` or `gene`, so
`eligible_kind` is true for all three and cannot break the tie.

The table below uses the RA graph instead, because `L1` (zimlovisertib → IRAK4)
and `L3` (zimlovisertib → IL-6) are the shape-identical pair an adjudication has
to separate, and every value in it is real output from `signals()` rather than
an illustration.

| field | evidence for | how it misleads alone |
| --- | --- | --- |
| `object_kind` | only `protein` or `gene` can be a target at all | IRAK4 and IL-6 are **both** `protein`. Kind never separates a target from a readout; it only rules out `process` and `disease` — see failure mode 7. |
| `object_has_edge_to_disease` | a readout usually carries the chain onward. IL-6 has `L6` (IL-6 drives RA); IRAK4 has none. | a well-studied target has disease edges too. IRAK4's is empty only because no paper here wrote "IRAK4 drives RA". One more round and it would not be. |
| `assay_contexts` | the `where` string of every finding on the edge | descriptive free text, not a category. `L1` carries `human whole blood` and is a direct action; `L3` carries `LPS-stimulated whole blood` and is not. Cellular does not mean downstream. |
| `direct_context` | a `where` naming a biochemical, cell-free or purified system. `L1` has `biochemical assay`. | empty means the field was empty. `f3` and `f4` have `where: null` outright, so a blank here is a missing field far more often than an absent experiment. |
| `direct_terms_in_quotes` | the vocabulary of a binding measurement. `L1` matches `ic50`, `target engagement`, `kinase activity`. | `L3` **also** matches `target engagement` — from `f10`, *"serum IL-6 trended lower in the treatment arm, which may reflect target engagement"*. The engagement is against IRAK4, and the sentence is hedged. Term matching cannot see whose engagement, or whether anything was asserted. |
| `downstream_terms_in_quotes` | outcome vocabulary. `L3` matches `release`, `output`, `serum`. | `levels` and `expression` sit happily in a direct quote — "receptor occupancy levels" matches. One hit is not a readout. |

These are evidence, not a verdict, and no single one decides. `L3` carries a
direct term and `L1` carries a cellular assay context; either read alone gets the
call backwards.

The procedure weights the quote above all of it:

1. **Read the quotes, all of them, first.** Every signal is an index computed
   over the quotes. The quote is the one thing SCHEMA.md guarantees is
   verbatim — its guarantees section says every quote is string-matched against
   the fetched abstract before a finding is written, and claims that fail to
   match are dropped and counted in `coverage.no_quote_discarded`. Nothing else
   in the packet carries that guarantee.
2. **Ask what was measured, and on what.** *"inhibited IRAK4 kinase activity
   with an IC50 of 0.2 nM"* measures the object of the edge. *"suppressed
   LPS-induced IL-6 release"* measures what happened downstream of something
   else that was measured. That distinction survives any verb the extractor
   invents.
3. **Then read the signals, as corroboration for the reading you already have.**
   If they contradict the quote, re-read the quote — do not switch on the
   signals. They are keyword matches; the quote is the sentence.
4. **Check `says` and `hedged` before acting either way.** `f10` is hedged
   (*"may reflect"*), and a hedged quote settles nothing in either direction.
   `no_effect` on a direct-action edge is real tractability evidence; on a
   downstream edge it is someone else's question — failure mode 10.

Refusing is a legitimate outcome. When the quotes do not settle it, leave the
edge unresolved, report it as unresolved, and issue `{"ask": "resolve_link",
"target": "<link id>", "depth": "deep"}` on that link. Do not promote it to a
nomination and do not file it under `rejected`; both are guesses wearing an
answer's clothes. This is the same rule as accession ambiguity in step 4 — an
unresolved target is a correct output, and a confidently wrong one poisons every
number downstream of it. A refused edge costs one round. A wrong one costs the
whole dossier.

## Failure modes

Longest section on purpose. The procedure above is the easy half.

### 1. Reading `how` instead of the quote

`L1` is `zimlovisertib inhibits IRAK4`. That verb supports a nomination and
nothing else. Every mechanism claim in this graph lives in quote text. An intake
built on the verb vocabulary returns targets with no `interaction_to_disrupt`
and silently hands the dossier its weakest input.

### 2. Readouts look exactly like targets

In the RA fixture, `L3` is `zimlovisertib reduces IL-6`. A small molecule acting
on a protein — the same shape as `L1`. But `reduces` is an outcome measurement
and IL-6 is a downstream cytokine, not the drug's target.

This is the same error the dossier already defends against one stage lower.
`targets.json` records that 45% of TNF-alpha's bioactivity comes from an "IRAK4
Monocyte TNFalpha Cell Based Assay" measuring a different protein, with TNF as
the cellular readout. Same conflation, one stage earlier, and here nothing is
looking for it. The verb split in the helper is the whole defence — keep the
two verb sets separate and send unrecognised verbs to `needs_adjudication`,
where they get decided rather than dropped.

### 3. The name resolves to a different protein than the evidence

The worst failure in this skill, because it is silent and everything downstream
still runs.

Node `t5` is named `IL-6`, alias `interleukin-6`. That string-matches **P05231**
(Interleukin-6), the ligand. Its supporting quote, `f7`, reads *"IL-6 **receptor**
blockade reduced ACR20 non-response across 14 randomized trials"* — tocilizumab
and sarilumab, which target **P08887** (IL-6 receptor subunit alpha). Those are
different proteins with different tractability.

`rheumatoid_arthritis.json` lists P08887 in `biologic_only` with an expected
verdict of `not_tractable OR insufficient_evidence`. Resolve by name and the
dossier assesses a protein the evidence never supported, while the target the
evidence does support is never assessed at all.

The same trap appears twice more in that fixture: anakinra targets IL1RN, not
IL1B; brodalumab targets IL-17RA, not IL-17A. Always read the quote before
resolving.

### 4. A review citation that looks like a finding

IRAK4's two PPI statements — `f4` (nucleates the MyD88 signalosome) and `f3`
(recruited to the receptor complex) — carry finding confidences of 0.88 and
0.85. Both come from one review, both are flagged `background`, and both sit on
links with `basis: background_only` and link confidence 0.38 and 0.35.

Taking `interaction_to_disrupt: "MyD88 signalosome assembly"` from that is a
single secondary source deciding chain selection, and therefore the druggability
number. Record it, ask `resolve_link` on L2, and do not act on it until a
primary result comes back.

### 5. Catalytic function does not imply orthosteric

`interaction_to_disrupt: "kinase activity"` says what to stop. It does not say
where to bind.

TYK2 is in your own fixture set for exactly this reason: deucravacitinib is an
approved kinase inhibitor that binds the **JH2 pseudokinase domain**
allosterically, not the ATP site. Structures split 29 entries for JH1 and 21 for
JH2, and picking the wrong domain scores the wrong pocket.

So set `mechanism_hypothesis: "unknown"` unless a quote states ATP-competitive,
allosteric, or a residue range. The dossier already handles `unknown`: it reports
pockets for the biological assembly and records in `tractability.caveat` that no
mechanism was specified. That is a correct output. A guess is not.

### 6. One target, two functions, and a drug that only hits one

IRAK4's four links say two different things about it. `f1` and `f5` are about
kinase activity. `f4` is about scaffolding — nucleating the signalosome. These
are separable functions, and a kinase inhibitor stops only the first.

No single link states this. It appears only when a target's whole neighbourhood
is read at once, which is why the helper returns the neighbourhood rather than
one edge. Report every function shape the evidence supports, and never let the
drug's mechanism stand in for the target's biology.

For this graph it also matters for the question being asked. The graph asks
whether the effect is confined to the myeloid compartment. A second explanation
sits in the same data: the molecule may be blocking half of what IRAK4 does, in
every compartment. That belongs in `notes`, not in a verdict.

### 7. Complexes and pathways are not proteins

`t3` is "MyD88 signalosome" and `t7` is "TLR/IL-1R signaling". Both are typed
`process`. Neither has a sequence, so neither can be handed to a structural step.

`t3` resolves to a component list (MYD88 Q99836, IRAK4 Q9NWZ3, IRAK1 P51617,
IRAK2 O43187). `t7` is a pathway name and does not resolve at all — TLR4
(O00206) and IL1R1 (P14778) are both plausible and the graph gives no way to
choose. Return a list with `ambiguity` populated; do not pick.

### 8. Synthetic fixtures

A graph carrying `_fixture: true` has papers, DOIs and quotes that were never
retrieved from any corpus. The helper refuses these unless `--allow-fixture` is
passed. Never lift that guard for a real run, and never cite a fixture quote.

### 9. Computed results are not literature evidence

If a downstream method (pocket scan, protein-protein cofold, interface
computation) produces a result that gets written back into a graph, it must not
re-enter this intake as a `finding`. Their `findings` require a verbatim quote —
`coverage.no_quote_discarded` shows the upstream pipeline drops entries without
one — and a computed result has provenance but no quote.

The specific hazard is laundering: a cofold contaminated by PDB training data
becomes an ordinary-looking finding on the next round, and the `leakage_risk`
flag the dossier template already carries is gone. Keep computed results in
their own type, with `leakage_risk` required rather than optional.

### 10. `no_effect` is not `no`

`says` has three values — `yes | no | no_effect` — and `links` carries three
arrays to match. A `no` finding is evidence against a claim. A `no_effect`
finding is a measurement that came back null. They are different, and folding
them together loses the more useful one.

For this node the difference is load-bearing. A `no_effect` finding on a
direct-action edge says the compound did not engage the target, which is real
tractability evidence. On a downstream edge it says the pathway did not move,
which is a biology result and someone else's question.

Two consequences. Read all three arrays — an intake that reads `yes` and `no`
silently drops every null result. And when the shared `Evidence.direction`
mapping is settled, argue for a third value rather than mapping `no_effect` onto
`contradicts`.

### 11. The target lives in an intervention node, not an entity node

The first real graph the upstream mapper produced — `upstream_graph_real.json`,
`g_1a4f`, round 2, status `ok` — made this intake nominate nothing. Its five
things are the whole graph:

| id | kind | name |
| --- | --- | --- |
| `t1` | `small_molecule` | IRAK4 inhibition |
| `t2` | `process` | myeloid inflammatory signalling |
| `t3` | `process` | synovial fibroblast driven inflammation |
| `t4` | `small_molecule` | MyD88 dimerization inhibition |
| `t5` | `process` | TLR/MyD88/NF-kB signalling axis |

Not one node is typed `protein` or `gene`, so the first half of the nomination
rule is false for all five and the intake returned an empty list against a graph
whose own `question` names IRAK4. Every protein is present — IRAK4, MyD88, NF-kB
— but only inside intervention names and aliases (`PF-06650833`, `ST2825`).

`kind: small_molecule` on "IRAK4 inhibition" is not a lie. The mapper is naming
what the experiments manipulated, and what they manipulated was an intervention:
a compound class defined by its mechanism of action. That is one level coarser
than the entity we expected, and our expectation came from reading SCHEMA.md
rather than from data. It survived until first contact with a real graph.

The second nomination route exists for this — scan `name` and `aliases` for
gene-symbol-shaped tokens, capture the adjacent action word, emit
`symbol_candidates` with provenance. **The regex only proposes. UniProt
confirms.** A token that looks like a symbol is not a protein until an accession
comes back; `ST2825` and `KIC-0101` are symbol-shaped and are compound codes.
Nominating off a regex hit alone is failure mode 3 with a new entry point.

`t5` is where that has to hold. "TLR/MyD88/NF-kB signalling axis" yields three
candidates, and three is the answer — it stays ambiguous. TLR is a receptor
family, MYD88 resolves cleanly to Q99836, and NF-kB is a transcription factor
complex — a dimer of subunits such as RELA and NFKB1 — with no single gene to
resolve to. NF-kB failing verification is the correct outcome, not a gap to paper
over by picking RELA, and one clean resolution among three does not collapse the
phrase onto MYD88. Same refusal as failure mode 7, one node-kind over.

The action word carries the rest. `t1` says "IRAK4 **inhibition**" and stops
there; `t4` says "MyD88 **dimerization** inhibition", which names the interaction
rather than just the intent. Disrupting a dimerization interface is the
oligomeric-state shape from step 2, and `f3` states it verbatim: *"the effect of
disrupting MyD88 dimerization by ST2825"*. So `t4` supports
`interaction_to_disrupt: "dimerization interface (oligomeric state)"` and,
unusually, a real `mechanism_hypothesis` rather than `unknown` — the rare case
where the graph hands us mechanism failure mode 5 would otherwise force us to
leave unstated. Take it, but only after MYD88 verifies as Q99836. The action word
never substitutes for the accession.

## What this skill does not do

- It does not assess tractability. That is the dossier.
- It does not rank nominations against each other.
- It does not choose between two plausible accessions.
- It does not assign a mechanism the evidence has not stated.
- It does not write anything back into the upstream graph.
