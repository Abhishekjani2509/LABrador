# Parameters — what steers the hypothesis generator

A hypothesis out of this system is a function of `(graph, params)` and nothing
else. The graph comes from Stage 1 and we do not get to argue with it. The
params are ours, and they are where every judgement call lives: how far to
walk, what counts as new, what counts as supported, how many near-duplicates a
slate may contain.

This document is the reasoning behind each group. The code is
[`src/hyp_gen/params.py`](../src/hyp_gen/params.py); nothing here should
contradict a docstring there.

## Why parameters at all

The alternative is a prompt that says "generate good hypotheses from this
graph", and it fails in a specific way: it is unarguable. When a reviewer says
"this one is too speculative", there is nothing to change except the adjective.
With the knobs exposed, the same objection becomes `max_hops: 3 → 2` or
`min_link_confidence: 0.2 → 0.45`, and the whole slate regenerates under the
new standard. A disagreement about output becomes a disagreement about
parameters.

That is also what makes the demo work: one graph, four profiles, four visibly
different slates, and the diff between them is a JSON file a judge can read.

## Where the defaults come from

Four published traditions, and the parameter groups are named after them.

| Group | Method | Source |
|---|---|---|
| `framing` | Swanson's ABC model — open vs closed discovery | [LBD survey](https://www.sciencedirect.com/science/article/pii/S1532046417301909), [context-based ABC](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0215313) |
| `traversal` | Hetionet/Rephetio — metapaths, degree-weighted path count | [eLife 26726](https://elifesciences.org/articles/26726) |
| `selection` | Maximal marginal relevance | [MMR reranking](https://qdrant.tech/blog/mmr-diversity-aware-reranking/) |
| `ranking` | Co-scientist — generate, debate, evolve; Elo tournament | [Nature](https://www.nature.com/articles/s41586-026-10644-y), [arXiv 2502.18864](https://arxiv.org/pdf/2502.18864v1) |
| `novelty` | Ideation scoring, and its known failure mode | [Limits of LLM-as-judge for novelty](https://arxiv.org/pdf/2606.12071) |

---

## `framing` — what question is being asked

Swanson's split is not cosmetic; it changes what a good answer looks like.

- **open** (`mode: "open"`) — fix A, hunt for any C worth connecting to it.
  This is generation. Output is a ranked slate of new relationships.
- **closed** (`mode: "closed"`) — fix A *and* C, hunt for the B that explains
  them. This is mechanism-finding, and it is the right mode when the clinical
  prompt already names a drug and a disease and the real question is *why*.

`anchors` / `targets` / `exclude` accept ids, names, or aliases, so a clinician
can steer with "IL-6" without ever seeing that the graph calls it `t7`.
`exclude` exists for the hub everyone already knows about — inflammation,
p53 — that otherwise connects everything to everything.

## `traversal` — how far, and along which shapes

The two knobs that matter most pull against each other.

**`max_hops`** is the speculation dial. Every extra hop multiplies the ways the
story can be wrong. Rephetio evaluated all 1206 metapaths of length 2–4 and
found little signal past that, which is why the default is 3 and the
speculative profile only goes to 4.

**`hub_damping`** is the correction for what more hops actually buys you.
Without it, long paths are almost all laundered through one promiscuous node,
and "aspirin → inflammation → everything" is the top hypothesis on every graph.
The DWPC formula divides each edge by `(deg(src) · deg(dst)) ** w`, so a hop
between two sparsely-connected things keeps nearly its full weight and a hop
through a node that touches everything contributes almost nothing. Rephetio
tuned `w = 0.4`; that is the default. `0.0` disables it, `1.0` is aggressive.

Note the interaction: **raise `hub_damping` whenever you raise `max_hops`.**
The speculative profile does exactly that (4 hops, `w = 0.5`). Longer paths are
only worth having if they are not all routed through the same hub.

Shape constraints come in two strengths:

- `seed_kinds` / `intermediate_kinds` / `target_kinds` — the loose version.
  `("small_molecule",) → ("protein","gene","process") → ("disease",)` is the
  repurposing shape without enumerating sequences.
- `metapaths` — the precise version: explicit kind sequences, e.g.
  `["small_molecule","protein","gene","disease"]`, the
  compound–binds–gene–associates–disease shape Rephetio found most predictive.
  When set, this *replaces* the kind filters and prunes the BFS by prefix.

`predicates_deny` defaults to `("correlates_with", "co_occurs_with")`. Two
correlations in a row imply nothing, and chaining them is the classic way an
ABC pipeline produces confident nonsense.

`allow_edge_reversal` plus `reversal_penalty` handle predicate asymmetry.
`binds` is near-symmetric; `inhibits` is not. A chain that silently flips an
arrow is a different, usually wrong claim, so a reversed hop is discounted
rather than banned — and the articulation prompt is told which hops were
reversed.

## `motifs` — the reasons a statement is worth making

Four shapes, each a different argument:

| Motif | The claim | Weight |
|---|---|---|
| `gap_closure` | Stage 1's own links imply a pair nobody states | 1.00 |
| `transitive_chain` | A→B→C exists, A→C does not; compose it | 0.90 |
| `analogical_transfer` | X≈Y, X has an edge Y lacks; Y probably has it too | 0.70 |
| `condition_split` | A `disagreed` link is two conditions, not a conflict | 0.85 |

Analogical transfer is discounted because it reasons from similarity rather
than from a path — it is the motif most likely to be fluent and wrong. It is
also the one guarded hardest: `analogy_min_jaccard` exists because raw
shared-neighbour count rewards hubs, which share many neighbours while being
nothing alike.

`condition_split` is a first-class motif because schema note 5 says the common
case for `state: "disagreed"` is two experimental conditions, not a real
contradiction. `condition_split_requires_where` keeps it honest: without two
distinct `where` values, the hypothesis is "maybe it's conditions" with no
candidate condition in hand.

## `evidence` — support, recomputed

Schema note 3 invites us to disagree with Stage 1's arithmetic, so we do.
Support is recomputed from `findings` + `papers` with our own weights, which
means the number that ranks a hypothesis is one we can defend line by line.

`chain_aggregation` is the honesty knob:

- **`weakest`** (default) — a chain is only as strong as its weakest link. The
  only option that cannot be gamed by padding a chain with strong-but-irrelevant
  hops.
- `mean` — lets one strong link launder two weak ones.
- `noisy_or` — correct for *converging* evidence for one conclusion, wrong for
  a chain. Only sane at `max_hops: 1`.

`min_independent_groups` + `single_group_cap` encode that one lab reporting a
result five times is one result; independence is counted over `first_author`.

## `novelty` — new, and how much of that to believe

The trap: absence in the graph is not absence in the literature. Schema note 2
is blunt — at `quick` depth, absence means unknown, because page one lies.

So every gap-derived bonus is multiplied by the graph's own
`absence_reliability()`, which is derived from `coverage.depth`,
`coverage.truncated` and whether a limit was hit. On a `quick`, truncated graph
that factor is **0.0**, and this system will not mint novelty from a gap at
all. That is the difference between *unexplored* and *unread*, and it is the
single most likely way a co-scientist demo lies to a judge.

`searched_gap_bonus` is the flip side: a gap with `searched_in_round` set is a
pair somebody looked for and did not find, which is a far stronger claim than
one nobody searched.

`popularity_penalty` corrects a documented bias — LLM novelty judges reliably
over-reward densely-connected concepts, so the safe famous pairing scores well
and discovers nothing. The correction is applied deterministically, *before*
any model sees the candidate.

## `selection` — which candidates get the expensive stages

Ranking by score alone returns twelve versions of one idea, because whichever
neighbourhood is densest wins every slot. MMR picks each item by its marginal
value given what is already picked:

```
value = λ · score − (1 − λ) · max_similarity_to_already_picked
```

λ = 1.0 is pure score (redundant slates), 0.0 is pure diversity (a varied slate
of bad ideas). Default 0.7 keeps the top pick — the first selection is always
the highest scorer — and spends the tail on coverage. Conservative runs at
0.85, speculative at 0.5.

`require_pareto` is the alternative to weighting at all. A weighted sum quietly
encodes one taste about how much novelty a point of support is worth; the
Pareto front over (support, novelty, testability) refuses to answer that, which
is the right thing to hand a reviewer who has their own answer.

**Support and novelty are never averaged before this point.** A fully supported
hypothesis is a known fact; averaging the two axes ranks textbook statements
first.

`coverage_report()` reports what the shortlist dropped. A slate with no account
of what it left behind reads as "this is everything", and it never is.

## `ranking` — the model stages

This is the co-scientist generate/debate/evolve loop with one hard constraint:
**nothing here may introduce a fact.** Articulation is pinned to the link and
finding ids the deterministic stages selected, and a critique citing anything
else is rejected with the candidate reopened.

`critic_lenses` gives each critic a different angle (mechanism / evidence /
testability) rather than running N identical refuters, which mostly agree with
each other.

There is deliberately **no temperature or seed knob**. Claude Opus 5 rejects
`temperature`/`top_p`/`top_k` with a 400, so a "hot to write, cold to judge"
dial would be a field that quietly does nothing. What replaces it:
`effort_articulate` / `effort_critique` for depth, the lenses above for
diversity, and deterministic tie-breaks in selection for reproducibility.

`debate_turns` is the number of judging passes per pair, alternating which
hypothesis is shown first. Pairwise judges have a position bias, so one pass
buys a ranking that partly reflects presentation order; two makes that bias
surface as a split verdict that moves Elo by almost nothing.

`tournament` (Elo, pairwise debate) is **off by default**: it costs O(k log k)
model calls for a ranking the deterministic scores already approximate. Turn it
on when the top few are genuinely close and the ordering matters.
`evolution_rounds: 0` likewise — single-pass is the honest MVP.

## `verification` — the staged gates

Each articulated hypothesis walks an ordered sequence of gates, and the record
of that walk — what ran, what it found, where it stopped — is on
`Hypothesis.verification`. Six gates ship, in this order:

| Gate | Costs | Fails when |
|---|---|---|
| `structure` | free | the shape no longer holds, or the graph already states it |
| `citations` | free | the model cited an id that was not in its evidence pack |
| `consistency` | free | no claim rests on a link or finding, or every claim is `inferred` |
| `independence` | free | fewer distinct first authors than `evidence.min_independent_groups`, or no primary results at all |
| `falsifiability` | free | no falsifier, no decisive experiment, or a falsifier that just restates the hypothesis |
| `adversarial` | **model calls** | critics reach `unsupported`/`contradicted`, or a critic cites out of pack |

`gates` is the order, and **the order is cost**: every free check that could
reject a hypothesis runs before the one gate that spends money. Reordering so
`adversarial` comes earlier is legal and works, it just pays for critics on
hypotheses a free check was about to reject. Removing a name skips that gate
entirely rather than recording it as a skip, because "we chose not to check"
and "we could not check" are different things.

`halt_on` names the gates whose failure stops the process. Everything after a
halt is recorded as a skip naming the halting gate — never as a pass. This is
the failure mode the whole group exists to prevent: a report showing five green
checks because the sixth never ran reads as *more* verified than one showing
the halt, which is exactly backwards.

Four verdicts come out of it:

| Verdict | Means |
|---|---|
| `verified` | every enabled gate passed clean |
| `qualified` | passed, with warnings or with something that could not be checked |
| `unverified` | a gate failed, or the process halted on evidence grounds |
| `rejected` | halted on `structure` or `citations` — the output is not trustworthy, which is a different statement from "checked and found wanting" |

`independence` is the gate whose strictness moves between profiles, and it
moves via `evidence.min_independent_groups` rather than anything here. Under
`default` (which asks for 1) single-group support is a **warning**; under
`conservative` (which asks for 2) the same evidence **fails and halts**. Same
gate, same hypothesis, different run — which is the point of putting strictness
in a parameter you can diff.

A gate failing does **not** block a hypothesis from the slate. `blocked` keys on
error-severity issues and controls publication; only `structure` and `citations`
emit those, exactly as before this group existed. Everything else says its piece
through the verdict, so turning verification on never silently deletes a
hypothesis an earlier run published.

## `loop` — closing the loop with Stage 1

The generator is blind to Stage 1's machinery but can name a row by id, which
is all the contract needs. Each trigger maps to exactly one `ask`, because the
contract permits one ask per request:

| Trigger | Ask | Why |
|---|---|---|
| a top-N hypothesis rests on a gap with `searched_in_round: null` | `test_gap` | the whole claim is "nobody looked" — find out |
| a surviving hypothesis depends on a `disagreed`/`single_source` link under `resolve_link_below_confidence` | `resolve_link` | the weakest link decides the chain |
| high `mentions`, low degree | `expand_node` | the signature of an under-read node |

`stop_when_no_score_change` ends the loop when a full extra round moves nothing.
More graph that changes no score is a stopping condition, not a failure. It is
the one parameter here with no effect yet: the asks are emitted but not
executed, so nothing drives a second round to stop. See `docs/DESIGN.md`.

---

## Profiles

| Profile | Shape | Use |
|---|---|---|
| `default` | 3 hops, w=0.4, λ=0.7, top 8 | the balanced slate |
| `conservative` | 2 hops, conf ≥ 0.45, no reversals, 2 labs | for a clinical audience; nearly boring, which is the point when the next step costs money |
| `speculative` | 4 hops, conf ≥ 0.10, w=0.5, 3 critics, 1 evolve round | exploratory; its failure mode is fluent nonsense, hence the extra critics |
| `repurposing` | small_molecule → protein/gene/process → disease | the Rephetio shape |
| `mechanism` | closed discovery, endpoint similarity | both ends given, output is the bridging B terms |
| `valuation` | intervention → protein/gene → disease, ≤2 labels per molecule | shaped for the downstream ROI stage |

```python
from hyp_gen.params import Params
p = Params.profile("repurposing", {"traversal": {"max_hops": 3}})
```

## `craziness` — one dial from super-safe to very ambitious

A profile says *what question* to ask the graph. Craziness says *how far out* to
reach for an answer, as a single float from 0 to 1. They compose.

```bash
hypgen --graph g.json --craziness 0.15    # a hypothesis you could defend today
hypgen --graph g.json --craziness 0.9     # "I read this in a different field…"
hypgen --graph g.json --profile repurposing --craziness 0.8
```

```python
Params.at_craziness(0.8, "repurposing", {"traversal": {"max_hops": 3}})
```

The scale is not invented. `conservative`, `default` and `speculative` were
already three points on this axis, so craziness makes them continuous: 0.0 and
0.5 reproduce the first two, and the profiles remain as names for the places
people actually stop. Precedence is **profile → craziness → `--set`**, last wins,
so an explicit knob is never overwritten by the dial.

What moves, at 0.0 → 0.5 → 1.0:

| Knob | 0.0 | 0.5 | 1.0 | Why |
|---|---|---|---|---|
| `traversal.max_hops` | 2 | 3 | 5 | the speculation dial |
| `traversal.min_link_confidence` | 0.45 | 0.20 | 0.05 | how shaky a stated link may be |
| `traversal.hub_damping` | 0.60 | 0.40 | 0.55 | **not monotonic** — see below |
| `traversal.allow_edge_reversal` | off | on | on | a reversed hop is weaker, not invalid |
| `motifs.analogy_min_jaccard` | 0.30 | 0.15 | 0.05 | how thin a resemblance will do |
| `motifs.analogy_same_kind_only` | on | on | **off** | the literal "different field" guard |
| `motifs.weights.analogical_transfer` | 0.35 | 0.70 | 1.00 | the leap leads only at the top |
| `evidence.min_independent_groups` | 2 | 1 | 1 | how much corroboration you require |
| `novelty.popularity_penalty` | 0.05 | 0.15 | 0.35 | a safe run *wants* the famous pairing |
| `selection.min_support` | 0.40 | 0.00 | 0.00 | |
| `selection.top_k` | 5 | 8 | 12 | |
| `ranking.critics_per_hypothesis` | 2 | 2 | 3 | scrutiny **rises** with ambition |

`hub_damping` dips and comes back up because extra hops are only worth having if
they are not all routed through one promiscuous node. Reaching further and
reaching through a hub are different things, and only the first is ambition.

Below 0.20 the similarity motif does not run at all; below 0.25 chains may not be
read backwards and `independence` halts verification rather than warning. Those
are steps, not slopes, and they are written out as such.

### What craziness must never touch

`CRAZINESS_NEVER_TOUCHES` is the enforced list. In short: the evidence weights
(study type, hedging, secondhand, preprint, basis, aggregation), the
absence-reliability scaling, `motifs.require_unstated`, citation legality, and
the `structure`/`citations` verification halts. **The same chain of links scores
the same support at 0.1 and at 0.9.** Craziness widens the aperture; it never
lowers the audit standard.

Two inference forms stay off at every level, because they are wrong rather than
bold: chaining `correlates_with` (two correlations in a row imply nothing) and
walking through measured non-relationships. Flip them by hand if you want them.

### The one that looks right and is not

Do not raise `selection.min_novelty` with craziness. Novelty here is *distance
from what is already stated* — hops beyond the first, plus gap bonuses — so an
analogical transfer, which is a single bridge edge, scores low on it however
audacious the leap. On the demo graph a `min_novelty` of 0.4 removes **all 90**
enumerated analogical transfers at craziness 1.0 and hands back twelve long
chains. A novelty floor is a path-length filter wearing a novelty label, and
using it as the ambition knob selects for exactly the wrong shape.

This is also why `--craziness 1.0` is not identical to `--profile speculative`:
that profile sets `min_novelty=0.4` and therefore cannot produce the most
ambitious motif it has. The profile is left as it is; the dial does not copy it.

## Tuning, in order of effect

1. **`traversal.max_hops`** — the speculation dial. Change this first.
2. **`traversal.hub_damping`** — raise it whenever you raise hops.
3. **`selection.diversity_lambda`** — if the slate reads repetitive, this is
   why, not the scoring.
4. **`traversal.min_link_confidence`** — the coarse quality floor.
5. **`novelty.popularity_penalty`** — if every hypothesis is about the one
   famous target.
6. **`evidence.chain_aggregation`** — leave on `weakest` unless you can say why.

## What is wired, and what is declared

Honest status, because a parameter that nothing reads is a lie in a config
file.

**Consumed today — all of it.** `framing.*` and `traversal.*` by
`candidates.py`/`graph.py`; `motifs.*` by the enumerators; `evidence.*` and
`novelty.*` by `scoring.py`; `selection.*` by `select.py`; `ranking.*` by
`reason.py` and the adversarial gate; `verification.*` by `verify.py`; `loop.*`
by `asks.py`; `budget.*` by `pipeline.py` and `llm.py`.

`stance.*` is the one group nothing reads to make a decision: it records which
profile and craziness a Params was derived from, so a slate can say where its
numbers came from. That is provenance, and it is labelled as provenance rather
than filed with the knobs.

This section previously said `evidence`, `novelty`, `ranking` and `loop` were
declared but not yet wired. That stopped being true and the note did not keep up
— which is the same lie as a parameter nothing reads, told in the other
direction.
