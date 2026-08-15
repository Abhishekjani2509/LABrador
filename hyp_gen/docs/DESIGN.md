# Design — hypothesis generation from a knowledge graph

The brief: read a graph, generate hypotheses purely from it, validate them, and
attach enough information to each one to say why it is worth believing. This
document is the reasoning; [`PARAMETERS.md`](PARAMETERS.md) is the knobs, and
the code is `src/hyp_gen/`.

## The constraint that shapes everything

The generator is blind to Stage 1. It never sees a query, a search strategy, or
a ranking — only the graph, and only through `GraphIndex`. That is a limitation
by design, and it buys two things.

**Checkability.** Every claim in the output resolves to a link id, a finding
id, and a verbatim sentence. A reviewer who distrusts a hypothesis can land on
the exact words a human wrote without leaving the report and without trusting
the model's memory of the field.

**Attribution of failure.** When a hypothesis is wrong, it is wrong because the
graph was thin, or because the parameters were loose. Both are fixable and both
are visible. A system that quietly supplements the graph with model priors
gives up the ability to tell those apart, and with it the ability to improve.

The cost is real: a hypothesis obvious to any pulmonologist but absent from the
graph will not be generated. We take that trade, because Stage 1 is where that
gap should be closed, and the `asks` at the end of every run are how we ask it
to.

## Why structure first, language second

A hypothesis starts as a *shape* in the graph, not as a sentence.

The tempting design is to hand the whole graph to a strong model and ask for
good hypotheses. It fails in a way that is hard to see and hard to fix: the
output is fluent, plausible, unauditable, and different every run. You cannot
tell which claims came from the graph and which came from the model's training,
and there is nothing to tune except the adjective in the prompt.

So enumeration is deterministic. Four motifs (below) find shapes; scoring ranks
them with arithmetic we can defend line by line; selection picks a diverse
slate. Only then does a model see anything, and what it sees is one candidate
and its evidence pack. Its job is articulation and criticism — turning a shape
into a precise, falsifiable sentence — not discovery.

This also means the expensive part scales with `selection.top_k` rather than
with graph size, and the whole pipeline up to that point runs with no API key.

## The four motifs

Each is a different *reason a statement is worth making*, not just a different
graph pattern.

**`gap_closure`.** Stage 1 flagged a pair implied by its own links but never
stated. The hypothesis is that the implied relation is real. These carry an
evidence spine: the shortest confident path between the endpoints, because a
gap the graph already almost connects is a far better proposal than a pair with
no path at all.

**`transitive_chain`.** A→B→C exists, A→C does not, so the hypothesis composes
the chain. Sub-tagged `repurposing` when an intervention-shaped thing lands on
a disease — the shape the ROI stage cares about.

**`analogical_transfer`.** X and Y share neighbours; X has an edge Y lacks;
propose that Y has it too. The only motif that reasons from similarity rather
than from a path, and the one most likely to be fluent and wrong — hence the
Jaccard floor (raw shared-neighbour counts reward hubs), the same-kind default,
and the lowest motif prior.

**`condition_split`.** A link disagrees with itself, and its findings were
observed under different `where` conditions. The hypothesis is that both
results are right and the condition is the variable. Schema note 5 says this is
the common case, so it is a first-class hypothesis rather than a data-quality
ticket — and it is usually the most testable thing on the slate, because the
experiment is already named in the two `where` values.

## Scoring: a vector, not a number

Four axes, reported separately and never collapsed before ranking.

**Support** is recomputed from `findings` + `papers` rather than taken from
`links.confidence` — schema note 3 explicitly invites the disagreement. Study
type sets the ceiling; hedging, secondhand citation, preprint status and the
extractor's own read-accuracy score all discount it; agreement weighs yes
against no by evidence weight rather than by count; independence counts
distinct first authors, because one lab reporting a result five times is one
result. `drift` reports where we differ from Stage 1, in both directions.

Along a chain, support aggregates **weakest-link** by default. `mean` lets one
strong link launder two weak ones, which is exactly the failure mode a
multi-hop generator needs to avoid.

**Novelty** is distance from what is already stated — hops beyond the first,
plus a bonus when Stage 1 itself flagged the pair as a gap, plus more when that
gap was *searched for and not found*. Then two corrections. A popularity
penalty, because novelty judges reliably over-reward densely-connected concepts
and the famous safe pairing discovers nothing. And a hard scaling by
`absence_reliability()`, below.

**Testability** rewards a handle to intervene on or measure, and penalises
length: a four-hop story is harder to settle than a two-hop one.

**Contradiction risk** counts disagreeing and hedged-basis links, and adds a
penalty for chains crossed against a stated arrow.

Support and novelty are kept apart on purpose. A hypothesis with support 1.0
and novelty 0.0 is a textbook fact; any scalar that ranks it first is measuring
the wrong thing. `rank_score` exists only to order a page, and the Pareto front
is available for consumers who weigh the trade differently — ROI and a
validation team genuinely do.

## Absence is not evidence of absence

This is the failure mode most likely to embarrass a literature-based generator,
and it gets structural treatment rather than a caveat in the prose.

Every novelty bonus that rests on something *not* being in the graph is
multiplied by `absence_reliability()`, computed from the coverage block: the
depth tier, whether the search truncated, and whether it hit a limit. At
`quick` the factor is zero — page one lies, and the schema says so outright. On
the demo graph (deep, truncated, hit `max_papers`) it is 0.41, so a gap-derived
hypothesis keeps well under half its nominal novelty.

The same information reaches the model as an explicit caveat in the evidence
pack, and the report refuses to render a truncated graph without a warning
banner.

## Verification: a staged process, not a pile of checks

Individual checks answer "is this satisfied". A reader wants the other
question — "did this hypothesis survive" — and that is a property of the whole
sequence, so the sequence is the artefact. Each articulated hypothesis walks six
gates in a fixed order, and what comes out is a record: what ran, what each one
found, and where it stopped.

```
gate 1 structure       PASS   3 hop(s), path intact, not already stated
gate 2 citations       PASS   4 ids, all legal
gate 3 consistency     PASS   5 claims, 3 grounded in evidence
gate 4 independence    FAIL   F2, F7 share first author Distler — 1 group, run requires 2
gate 5 falsifiability  SKIP   halted at independence
gate 6 adversarial     SKIP   halted at independence
──────────────────────────────────────────────────────────────────────────
VERDICT  unverified (halted: independence)
```

Three properties do the work.

**Order is cost.** Every deterministic gate runs before the one gate that spends
model calls. A hypothesis whose citations are illegal, or whose entire evidence
base is one lab, is rejected for free rather than after three critic calls. The
first four gates need no API key at all, which is why `--dry-run` can already
tell you which candidates would be thrown out.

**A skip is not a pass.** When the process halts, every downstream gate is
recorded as a skip naming the gate that stopped it. This is the failure mode the
design is actually defending against: a report showing five green checks because
the sixth never ran reads as *more* verified than one showing the halt, which is
precisely backwards. It is also why a gate that params turned off is removed
from the table rather than shown as a skip — "we chose not to check" and "we
could not check" must not look alike.

**A gate reports; the params decide.** Which gates run, and which may halt, come
from `params.verification`. No gate decides its own authority, so a run's
strictness is something you diff between profiles rather than something buried
in a check. `independence` is the clearest case: it fails when the run's own
`evidence.min_independent_groups` is unmet, so identical evidence warns under
`default` and halts under `conservative`.

The gates themselves:

**Structure**, against the graph. Do the endpoints exist, does the path connect,
and — the important one — does the graph already state this? A hypothesis that
restates a finding is a summary, and it is blocked before a model call is spent
on it. A stale gap (one whose pair has since acquired a link because an earlier
`test_gap` promoted it) is dropped at enumeration so it cannot take a selection
slot from a real candidate.

Where a path is expected to *start* is motif-dependent, and this is worth
stating because getting it wrong is silent. An `analogical_transfer` candidate's
path is the **donor's** bridge edge, since the whole proposal is that the
receiver lacks that link; checking it from `subject` asks the receiver to
already have the edge the hypothesis exists to propose, and marks every
analogical hypothesis `broken_path` — an error, so all of them vanish before
articulation, in every run, invisibly. Motif-aware origins plus a check that the
path still *ends* at the object is what keeps that honest.

**Citation legality**, against the evidence pack. The pack is the model's entire
world; anything cited that was not in it is an error and the hypothesis is
flagged. This turns "the model was told not to make things up" into something
enforced. Claims with no citation must be marked `inferred`, which makes an
honest reasoning step legitimate and an unmarked leap visible.

**Consistency**, internal to the articulation. The failure here is the one the
citation gate cannot see: prose that is fluent, legally cited, and floating free
of its own candidate — every claim marked `inferred`, or every citation pointing
at a node rather than at evidence. Both are legal. Neither is grounded. This
gate also catches direction laundering: traversal may walk a link backwards, but
a claim citing that link without marking itself inferred is asserting the
reverse relation as something the graph states, and it does not.

**Independence**, off the pack rather than off the scores, so it checks the world
the model was actually shown. One lab reporting a result five times is one
result, and it is the most common way a slate looks better supported than it is.
Also failed by evidence that is entirely secondhand — the graph read papers that
read papers.

**Falsifiability**, before the critics and not after. A hypothesis with no real
falsifier is not something critics can usefully attack, and finding that out
costs nothing here and three model calls there. The check that earns its place
is the vacuous one: `"<statement>, but it is not true"` is a falsifier in shape
only, and it is caught by asking whether the statement was swallowed whole.

**Adversarial**, the one gate that costs money. Separate from articulation on
purpose: one pass asked to both propose and criticise produces a hypothesis
pre-softened to survive its own review. Critics are diversified by **lens**
rather than by resampling — a mechanism critic and an evidence critic fail on
different things, while three identical refuters mostly agree. A single lens
calling a hypothesis unsupported is information, not a ruling; it takes
`refute_threshold` of them to drop it. The gate audits its own critiques'
citations too, because a critic that invents an id is exactly as untrustworthy
as an articulator that does.

One deliberate restraint: **a failed gate never deletes a hypothesis.** `blocked`
keys on error-severity issues and controls whether something reaches the slate;
only structure and citations produce those, exactly as before this existed.
Every gate added here speaks through the verdict instead. A verification process
whose failures are invisible is worse than none, because it reads as assurance.

Sampling temperature does none of this work, because Opus 5 rejects
`temperature` outright. The diversity comes from the lenses, which is a better
mechanism anyway.

## Closing the loop

A hypothesis that cannot say what evidence would move it is a guess. Each one
names the exact Stage 1 request that would move it, in the contract's request
shape and keyed by id:

- `test_gap` when novelty rests on nobody having looked — and only when nobody
  has, since re-searching a searched gap wastes a round.
- `resolve_link` on the weakest link the hypothesis depends on. Under
  weakest-link aggregation that is literally the number that would change.
- `expand_node` on an endpoint the literature discusses constantly but the
  graph has barely connected — the signature of an under-extracted node, which
  is a retrieval hole rather than a knowledge hole.

Asks are deduped across the slate: the same weak link mattering to three
hypotheses is one piece of work, not three.

## What this does not do

- **No retrospective validation yet.** The number worth demoing is: hold out
  round 2, generate from round 1, and check whether the generator proposed what
  round 2 found. The machinery is in place (`asks` are the query, `Slate` is
  comparable across runs) but the harness is not written.
- **No multi-round driving.** The asks are emitted, not executed.
- **No dataset or ROI scoring.** Those are sibling stages; this one hands them
  a slate with per-claim citations so they can attach at claim granularity
  rather than per hypothesis.
- **Nothing outside the graph.** By design, and worth restating: a hypothesis
  this system cannot see is a Stage 1 coverage problem, and the asks are the
  channel for fixing it.
