# COORDINATION.md — team state + working process

**Read this file first every time you pull `main`.** It is the single source
of truth for who owns what, what is done, what is pending, what nobody owns
yet, and the process we all follow. If you change any of those facts, you
update this file in the same push. Last full update: **2026-08-15 (late
evening — refreshed after every merge per §7.10)**.

---

## 1. The pipeline (who feeds whom)

```
hypothesis (thesis.ts contract)
      │
      ├──> research-evidence-mapper ──── findings[] ──┐   (adapter A, unowned)
      ├──> small-molecule-tractability-review         ├─> IndicationThesis.evidence[]
      │                                               │
      ▼                                               │
trial-recruitment-forecaster  <───────────────────────┘
      │  score, simulatedMonthsToEnroll, counterfactual
      ▼   (adapter B, built: economics-bridge.ts, months -> launch-delay overlay)
therapeutic-program-economics
      │  rNPV, value_lost_per_launch_delay_year, decision grade
      ▼
   verdict
```

The shared contract is [`IndicationThesis`](./managed/trial-recruitment-forecaster/thesis.ts).
**Status: not yet ratified — see §6.** Nothing composes end-to-end today;
adapter B is built (§5), adapter A still has no owner.

## 2. Branch map — who owns what

| Person | Branch | Node (dir under `managed/`) | Merged into main? |
|---|---|---|---|
| Abhishek | `abhishek-jani` | `trial-recruitment-forecaster` | ✅ |
| Rafal | `rafwiewiora/druggability-dossier` | `small-molecule-tractability-review` | ✅ (incl. `f84bfff`: 651x figure withdrawn, cryptic/disorder/interface modules added) |
| Soliman | `msoliman6/literature-graph-mcp` | `research-evidence-mapper` | ✅ |
| Moamen | `moamen` | `sandbox-capability-probe` | ✅ |
| Vince | `vaalessi/program-strategy-valuation` | `therapeutic-program-economics` | ✅ |
| Vince | `vaalessi/hypothesis-highlander` | `hypothesis-highlander` (meta-search ABOVE the pipeline) | ✅ |
| Abraham (+ Sean, Weichi) | `AbrehamT/Hypothesis_Generator` | hypothesis node — **no code pushed yet**; note Vince's highlander now covers hypothesis *enumeration* — coordinate to avoid building the same thing twice | (nothing to merge) |
| Cyrus | works on `main` | infra, merges, renames, README | — |

Note: Cyrus renamed all node dirs on 2026-08-15 (`d6b8451`). Old names
(`simulated-clinical`, `druggability-dossier`, `literature-graph`, `spike`)
are dead — do not create files under them.

## 3. Done — per person

**Abhishek — trial-recruitment-forecaster** *(runnable)*
- Engine: precedent velocity → biomarker narrowing (floored) → Claude-read
  eligibility (median-of-3) → competition → phase-3-floored powering →
  sites-from-precedent → counterfactual bisection search (good/feasible/none).
- 4 fixtures covering all counterfactual tiers; leak-free 2018 retrospective
  (dupilumab-EoE: 12 mo, 100/100, approved 2022); 6-trial backtest.
- 11 adversarial-review findings fixed same day. `thesis.ts` authored (the
  proposed shared contract). Details: [NEXT.md](./managed/trial-recruitment-forecaster/NEXT.md).
- Adapter B shipped (`economics-bridge.ts`, 2026-08-15 late) — see §5 row.

**Rafal — small-molecule-tractability-review** *(partial prototype)*
- 4 real skills (precedent-lookup, structure-select, pocket-scan,
  falsification-sweep), deployed CPU Modal pocket scanner (fpocket + P2Rank),
  10-target calibration fixtures, evidence-rules CLAUDE.md, pipeline.html
  status board. Precedent + structure-selection stages VERIFIED.
- graph-intake stage (2026-08-15 late): reads a research-evidence-mapper
  graph on the REAL SCHEMA.md (first live cross-node edge — mapper →
  tractability) and nominates UniProt targets from it; handles `no_effect`,
  `hedged_only`, failed-graph status, and gene-vs-protein kinds.

**Soliman — research-evidence-mapper** *(DEPLOYED 2026-08-16, agent v7)*
- **Live Managed Agent**: `agent_015feTqKz3Bmtec2RaWaE2sW` v7, three skills
  uploaded, memory store `memstore_01NGZC8ti7PMqpqzUKcxuiaY`, Paperclip MCP
  attached as an `mcp_toolset` (`always_allow`), credential in vault
  `vlt_011Ce5SbT8uAxY9LgM3eTZpS`. Second deployed agent in the repo.
- **Paperclip is a hosted remote MCP** — `https://paperclip.gxl.ai/mcp`,
  streamable HTTP, exposing ONE passthrough tool `paperclip({command})` that
  runs the CLI server-side. Stateless, no shell loops, one command per call.
  An earlier revision of this node's docs wrongly concluded no MCP existed;
  that is retracted in BUILD.md/CONTRACT.md rather than silently rewritten.
- **End-to-end verified on the deployed agent**: graph `g_9d3c` — 28 things,
  6 papers, 23 findings *every one carrying a verbatim quote,
  `no_quote_discarded: 0`*, 22 links, honest `coverage`
  (`found: 46, used: 6, truncated: true`).
- **Liveness**: a canary query runs before any real search; if it fails the
  agent stops and returns `status: "failed"` with `stop_reason:
  "search_unavailable"` and an `error` prefixed `PAPERCLIP UNAVAILABLE:`.
  A dead corpus must never read as "no evidence found". Fired and passed in
  production on its first run.
- **assemble.py is deterministic** — byte-identical across repeated runs and
  varied `PYTHONHASHSEED`. All arithmetic lives there; nothing is scored by
  hand.
- Two defects found only once real output existed, both fixed: the agent
  wrapped its JSON in prose + a ```json fence (breaks any consumer calling
  `JSON.parse`, including Rafal's graph-intake), and gap ranking produced 38
  gaps sharing 6 scores whose top ten were readouts of ONE paper radiating
  off a hub. Ranking now weights basis, paper-independence, a hub penalty and
  multi-route implication → 12 distinct scores, top gap becomes a real
  missing edge (PF-06650833 vs tofacitinib, never directly compared).
- **All four ask types verified in production.** `new_question`, `test_gap`,
  `resolve_link` and `expand_node` have each run against the deployed agent.
  `expand_node` sweeps the node's name and every alias as separate queries.
- **Figure path works, and the gate was the whole cause.** A/B on an identical
  `resolve_link` request: v3 made 21 MCP calls and zero `ask-image`; v4 read a
  figure and produced a `section: "figure_caption"` finding — *"Fig. 2
  Ad-shIRAK4 alleviated the degree of synovitis in the osteoarthritis rabbit
  model"* — carrying the condition data `explain_disagreement` compares. The
  fix was framing: a permission ("only, and only when…") reads as a reason not
  to; an expectation with a budget reads as an instruction.
- **Entity merging on UniProt accession**, with a coalesce pass that repairs
  duplicates ALREADY stored, not just arriving ones. Exact, auditable,
  species-safe (Q9NWZ3 vs Q8R4K2 are different keys), and it refuses to merge
  on a contested identity. A similarity/vector approach was considered and
  rejected: it fails in both directions here — KIC-0101 and PF-06650833 are
  maximally dissimilar strings meaning the same thing, IL-6 and IL-6R are
  near-identical strings meaning different molecules.
- **Every intervention links to its target — verified, 0 orphans.** 7 nodes / 2
  edges before, 8 nodes / 8 edges after. Compounds stay distinct (for "what
  inhibits IRAK4?", eight compounds IS the answer) while evidence pools along
  the mechanism path. Accession merging could not have done this: small
  molecules have no accession.
- **`assemble.py` has a CLI and a copyable `example-round.json`**, so a round
  is one command instead of a hand-authored driver. Confirmed materialized in
  the sandbox and `cat`-ed by the agent. Call ratio moved from 16 MCP / 41
  local to 42 MCP / 36 local.
- **All six BUILD.md acceptance facts verified.** Fact 6 was the last and the
  only genuinely human one: three quotes re-resolved **by DOI** rather than by
  the paper id the agent used, so a wrong id would have surfaced. 3/3 — each DOI
  returned exactly the title the graph recorded and each quote appears
  word-for-word in it (PMC9945759 L6, PMC3583641 L6+L33, PMC7912553 L39). The
  disagreement is real rather than an artifact: one paper concludes antioxidants
  accelerate melanoma metastasis in BRAF-V600E mice, the other that ascorbate
  reduces it by 71% (p=0.005) in Gulo-KO mice. Incidentally confirmed the
  fixture README's own hazard note — the third paper is from the same group
  (Le Gal / Sayin / Bergo) as one camp.
- **Agent README rewritten for v10** — adds what it guarantees and how each is
  enforced (mechanism, not intention), the modelling rules that shape the graph,
  the six-fact acceptance table, and known limits.
- **BUILD.md's blocking acceptance test run, and `explain_disagreement` fired
  in production for the first time.** `fixtures/q-disputed.txt`, graph g_e087:
  22 things, 11 papers, 38 findings, 32 links, 43KB of raw JSON. Fact 3 — the
  one BUILD.md calls out as "zero is a failure, not a clean result" — passed
  with a real boundary condition:
  `L26 Vitamin C --increases--> melanoma metastasis`, `state: "disagreed"`,
  *why: "conditions differ: {braf v600e-driven melanoma, mouse} vs {b16f0
  melanoma, gulo ko mice}"*. It did not just flag the conflict, it identified
  that one camp used Gulo-knockout mice — the model that cannot synthesise
  vitamin C, which is the whole reason the two labs disagree.
- **`how` enum verified on a fresh graph** (g_8ada): 10/10 intervention→target
  edges came back `inhibits`, against 1/8 before. No verb outside the enum. The
  remaining `decreases` uses are correct ones — measured quantities, not
  activity. A `quick` run also surfaced ten distinct IRAK4 inhibitors, each
  arriving with its target edge unprompted.
- **`how` is a closed set** — `inhibits` | `activates` | `binds` | `increases` |
  `decreases` | `drives` | `associated_with`, with the distinction the drift
  exposed: **activity is not abundance**. A kinase inhibitor `inhibits`;
  `decreases` is for a measured level or score. Seven of eight IRAK4 edges had
  been `decreases`, which reads as *lowers IRAK4 protein* — not what any of
  those papers showed. Backward-compatible for graph-intake: same field, more
  reliable values. Caveat for §6: changing a verb on an EXISTING pair forks a
  parallel link, since links key on (from, how, to), so migrating an old graph
  needs a deliberate remap rather than a re-extraction.
- **Missing-tool liveness deliberately tested.** Credential invalidated on
  purpose, agent run, credential restored. Result: `status: "failed"`,
  `stop_reason: "search_unavailable"`, error prefixed `PAPERCLIP UNAVAILABLE`,
  lists empty, found/read/used 0/0/0, and **zero** filesystem hunting — the two
  accidental outages had produced 15 calls of `which paperclip` /
  `find / -iname "*paperclip*"`. Needed a `--mcp-silence` flag on `console`,
  because the MCP watchdog would otherwise kill the run before the agent could
  report the outage it exists to report.
- **Fixtures written** (BUILD.md step 1) — three corpus-validated questions,
  each grading something specific rather than demonstrating success:
  EGFR/TKI (`deep`, dense consensus; sets traps for text-only sponsorship
  disclosure and same-group repetition), antioxidants-and-metastasis
  (`standard`, two labs in direct conflict with one challenging the other in
  its own text — and `quick` fails it on purpose, because the opposing camp is
  unreachable from the obvious phrasing), microbiome-and-FOP (`deep`, one
  primary study appearing as three corpus records that disagree on their own
  effect size). See `fixtures/README.md`.
- **Three of four ask types verified in production.** `new_question`,
  `test_gap` and `resolve_link` have all run against the deployed agent;
  `resolve_link` loaded prior state from memory, recorded both rounds in
  `rounds[]`, and stamped the new link `changed_in_round: 2`.
- **A retried round is now a no-op.** Findings dedupe on content (paper +
  relationship + normalized quote), not on id, because a retry re-extracts the
  same sentences and may assign fresh ids. Previously a retried round doubled
  every finding and inflated `agreement` and `independence` — silently, since
  the graph merely looked richer. Duplicates are reported in
  `coverage.duplicates_dropped`.
- **`assemble.py` has a CLI**: one command per round
  (`--input round.json --memory-dir … --save`) instead of a hand-authored
  driver. The budget win is real (that round spent 35 local calls against 21
  corpus calls on marshalling) but the correctness win matters more: unreviewed
  glue was standing in front of the deterministic core, and a byte-stable
  script reached through a different caller each round is not reproducible.
  `--selftest` covers quote verification, dedupe, scoring, disagreement
  explanation, the missing-directory case and byte-identical output.
- **The liveness path was proven by a real outage, not a synthetic test.** The
  vault token lapsed mid-round and the agent did exactly what it was told to:
  `status: "partial"`, `stop_reason: "search_unavailable"`, an `error` prefixed
  `PAPERCLIP UNAVAILABLE:`, findings verified before the outage retained, and
  candidate quotes that could not be line-anchored **dropped rather than
  emitted unverified**. That last one is the discipline the whole design rests
  on.
- Renamed `literature-graph` → `research-evidence-mapper` and merged `main`
  (2026-08-16). Trap worth knowing repo-wide: **the memory store's NAME sets
  the `/mnt/memory/<slug>` mount path**, and `deploy.ts` only provisions a
  store when `memory_store_id` is absent — so renaming a node while keeping
  that id leaves the agent writing state to a mount that no longer matches
  its prompt, silently.

**Moamen — sandbox-capability-probe** *(done — throwaway, served its purpose)*
- The only deployed Managed Agent. Proved: bundled scripts execute in the
  sandbox, python 3.11 + uv present, memory mounts writable, sqlite3 absent,
  egress open to the 3 tested hosts. Results recorded in Soliman's CONTRACT.md.

**Vince — therapeutic-program-economics** *(runnable, v0.2.0)*
- Deterministic pydantic/numpy economics simulator: pricing corridors, patent
  clock, cash flow, Monte Carlo rNPV, provenance + secret redaction,
  decision-grade gate. CLI + Streamlit.
- v0.2.0 hardening drop (2026-08-15 late): evaluation module with reality
  anchors, run replay, red-team hardening + interpretability-contract docs,
  five new test suites — 87/87 tests pass on merged main.
- **NEW node: `hypothesis-highlander`** (2026-08-15 late) — quality-diversity
  meta-search that sits ABOVE the four nodes: fixes one indication (RA
  example), enumerates biomarkers × hypotheses, runs each through the
  existing nodes, learns across runs (MAP-Elites archive + Pareto front +
  failure ledger). Module-agnostic by design; stdlib core; 18/18 tests pass
  on merged main. Interop with the real node contracts not yet verified —
  see §5.

**Cyrus — infra**
- Merged all branches into `main`, renamed nodes for clarity, rewrote README
  with honest capability boundaries, Managed-Agents harness + deploy/console
  CLIs. `main` is the default branch.

## 4. Pending — per person

**Abhishek**
- [ ] Drive `thesis.ts` ratification (§6) — blocking all composition.
      **Update 2026-08-15 late: the schema legwork is DONE** — all four §6
      items implemented as additive optional fields on `abhishek-jani`
      (old theses still parse; typecheck + check green). What remains is
      sign-offs: checklist now in §6.
- [ ] Wrap forecaster as a Managed Agent (fresh session: `/clear` →
      `/managed-agent-prototype`; engine becomes `tools.ts` handlers). Do
      after ratification.
- [x] ~~Known model limitation: per-site velocity doesn't transfer to 100+
      site scale.~~ **Decided 2026-08-15 late on 22 fresh backtest rows
      across two conditions**: √-dilution REJECTED as a blanket engine term —
      the pool-median anchor degenerates to 1 site and blows predictions
      3–17x; an at-scale anchor helps EoE but wrecks already-calibrated
      atopic dermatitis. Both variants now print as EXPERIMENT columns in
      `backtest.ts` on every run; the remaining open problem (a mismatch
      gate) is documented in NEXT.md and stays in its Known limitations.

**Rafal**
- [x] `f84bfff` merged (2026-08-15 late, rename-aware).
- [ ] Falsification sweep has never been executed; dossier assembly never run
      end-to-end; GPU escalation stage blocked on a Modal payment method.
- [ ] Pocket scanner runs in Rafal's personal Modal workspace — single point
      of failure for any demo; document or share the credential path.
- [ ] Pin the `proto-tools` git dependency (unpinned ref = unreproducible image).

**Soliman**

*§7.6: finished work moves to §3. Nothing with `[x]` belongs in this list.*

- [x] **URGENT data-loss bug fixed (round-local id collision).** Reproduced
      exactly as reported, including with the shipped `example-round.json`
      verbatim. `dedupe_papers` returns an id map for INCOMING rows and `main()`
      was applying it to every finding including stored ones, so a stored
      finding pointing at stored `p1` got repointed to whatever the incoming
      `p1` became, its quote failed against the wrong paper's text, and it was
      discarded as unverifiable. It presented as the system working —
      `no_quote_discarded` incremented, which reads as quote hygiene rather than
      evidence destruction. Fix: stored findings take only the coalesce remap,
      incoming findings take the round map. Verified three ways (synthetic
      collision, the reporter's own repro, and a permanent `--selftest` case).
      SKILL.md now states that round ids are local and translation is the
      assembler's job.
- [x] **findings/r<N>.json is append-only again.** Every round had rewritten the
      whole findings set into that round's file, so a reload counted prior
      findings once per round — the source of the fictitious
      `duplicates_dropped` figures I had been quoting as evidence the dedupe
      worked. Each round's file now holds only its own findings.
- [x] **Schema drift closed**: findings and papers now carry `round`, findings
      carry `flags`.
- [x] **`suppresses` in the enum** and **committed session id scrubbed** — both
      were already shipped before the feedback arrived.
- [ ] **`targets[]` + `uniprot_accession` handoff** for the tractability node.
      The `things[]` half is shipped — `uniprot_accession`, `gene_symbol`,
      `resolved_by`, `ambiguity`. What remains is the ordered `targets[]` block
      and its `supported_by` / `contested_by` / `rests_on_gap` wiring, which is
      a contract change against a LIVE consumer (Rafal's `graph-intake` already
      reads mapper graphs) and needs his sign-off. See §5.

**Moamen**
- [ ] Nothing owed. Optional high-leverage favor: add `clinicaltrials.gov`
      (and any host another node needs) to probe.py's NET list and re-run, so
      sandbox egress is known before anyone's Managed-Agent wrap assumes it.

**Vince**
- [ ] `fixtures/demo_program.json` trips the engine's own consistency gate on
      every run (PoA 0.073 vs stage product ≈0.1066 →
      INCONSISTENT_PROGRAM_APPROVAL_PROBABILITY ERROR). Fix or document as an
      intentional warning-path demo.
- [ ] Modality enum accepts only SMALL_MOLECULE | PEPTIDE — an antibody
      program (e.g. dupilumab, the forecaster's whole fixture set) is
      unrepresentable. Decide: extend, or state the boundary.
- [ ] Component README says "no license selected"; root repo says MIT — align.

**Abraham / Sean / Weichi**
- [ ] Hypothesis node: nothing is pushed. The pipeline's entry point does not
      exist. If it emits `IndicationThesis` (§6), everything downstream is
      already runnable against it.

**Cyrus**
- [x] Rafal's `f84bfff` rename-aware merge (done by the integrator flow).
- [ ] No orchestrator; router has no registered specialists yet.

## 5. Unowned work + active hazards

| Item | What it is | Suggested owner |
|---|---|---|
| **Adapter A** | mapper `findings[]` → thesis `Evidence[]` (mapping is nearly mechanical; `no_effect` needs a convention) | Soliman + Abhishek |
| ~~**Adapter B**~~ | **Built 2026-08-15 late (owner Abhishek)**: `managed/trial-recruitment-forecaster/economics-bridge.ts` — overlay script shipped (delay years + triangular `launch_delay_years` range + counterfactual pricing, best-effort against the demo fixture, read-only on Vince's dir); **Vince to confirm the `launch_year` application convention**. The two "obvious" wirings remain wrong and are documented in the file header: score→PoS is a category error; months→stage_durations only shifts cost timing. The value-bearing slot is launch delay, which the engine already prices (`value_lost_per_launch_delay_year` ≈ $5.06M/yr on the demo fixture). | done (Abhishek; Vince to confirm convention) |
| **Orchestrator** | one command running thesis → evidence → recruitment → economics. NOTE: Vince's `hypothesis-highlander` claims this layer as a meta-search — decide whether it IS the orchestrator or sits above a simpler one | Cyrus + Vince |
| **Highlander↔nodes interop** | highlander says "module-agnostic" but its calls against the real node contracts (thesis.ts, RecruitabilityResult, ProgramInput, mapper graphs) are unverified — its test_interop.py runs against stubs | Vince + node owners |
| ~~HAZARD: rename collision~~ | **Resolved 2026-08-15 late**: git's directory-rename detection mapped both Rafal's and Soliman's old-path commits onto the renamed dirs; new files were accepted at the detected locations. `scripts/integrate.ts` escalates this class and `fixDeadPaths` catches any residue. | done |
| **Mapper `targets[]` schema** | The tractability node's one mandatory input is `uniprot_accession`, and `kind: "protein"` cannot distinguish a drug target from a readout. Proposal: `things[].uniprot_accession` + `gene_symbol` + `resolved_by` + `ambiguity[]`, plus an ordered `targets[]` block. Resolution must key on the **quote, not the entity name** — resolving the string "IL-6" yields P05231 (ligand) while receptor-blockade evidence is P08887, and without an explicit unresolved state the pipeline confidently assesses the wrong protein. Rafal's `graph-intake` already consumes mapper graphs, so this is a contract change against a live consumer. | Soliman + Rafal (needs Rafal's OK before implementation) |
| **README row stale (mapper)** | Root README still says Research Evidence Mapper is *"Design packet only; the agent, skills, deterministic assembler, and fixtures remain to be built"* and *"No implementation currently enforces them"*. All three clauses are now false — the agent is deployed and verified. Not edited here because §7.3 reserves shared files to their owner. Suggested replacement state: **"Deployed Managed Agent (v3) with three skills and a deterministic assembler; fixtures and two of four ask types still outstanding."** | Cyrus (owner of README) |
| **Decision-grade policy** | economics excludes simulation-sourced inputs from decision grade BY DESIGN — a composed demo will always read NOT_DECISION_GRADE unless the team explicitly decides how simulated upstream numbers are graded. Decide before the stage demo, not on it. | Everyone (5-min call) |

## 6. thesis.ts ratification agenda (the blocking conversation)

`IndicationThesis` is declared the shared contract in the README but no other
node consumes it yet. Concrete items, each discovered by reading the other
nodes' actual contracts. **Status 2026-08-15 late: items 1–4 are IMPLEMENTED
in `thesis.ts` on `abhishek-jani` as additive, optional, backward-compatible
changes — every pre-change fixture still parses, typecheck + check green.
Ratification is now a sign-off, not a design session.**

1. Add optional `mechanismHypothesis: "orthosteric" | "allosteric" |
   "oligomer_destabilisation" | "unknown"` — Rafal's node needs the enum
   (load-bearing for chain selection); free-text `mechanism` can't feed it.
   **Implemented** (optional top-level field).
2. Add optional `uniprotAccession` — Rafal's join key (gene symbol requires a
   resolution step he'd rather record than perform).
   **Implemented** (optional `target.uniprotAccession`).
3. `Evidence.direction` has `supports | contradicts`; Soliman's findings also
   emit `no_effect`. Pick a convention (third value, or map to contradicts
   with a note). **Implemented as a third value** — a null result and
   evidence-against are different facts; collapsing them destroys
   information. Consumers may treat `no_effect` as neutral.
4. Modality vocabulary: thesis has 6 values, economics accepts 2. Align or
   declare the boundary. **Boundary declared** in a comment on `Modality`:
   the wide vocabulary stays (upstream must not misdescribe an antibody to
   get a valuation); non-priceable modalities are the economics node's
   documented gap until its owner extends his enum (his §4 item).
5. Confirm the adapters in §5 and their owners (B is built; Vince to
   confirm the `launch_year` application convention; A still unowned,
   suggested Soliman + Abhishek).
6. **SCHEMA.md: `how` needs an enum** (raised by Rafal's graph-intake,
   2026-08-15 late): every other categorical field is enumerated, but `how`
   is open vocabulary — so "drug inhibits IRAK4" (a target) and "drug
   reduces IL-6" (a downstream effect) are structurally identical. Soliman
   to enumerate at least the target-nominating verbs.

Sign-off checklist (a "yes" or a concrete objection each; silence ≠ consent):

- [ ] **Rafal** — items 1–2: enum values + accession placement under `target`.
- [ ] **Soliman** — item 3: `no_effect` as a third `direction` value; and
      item 6: the `how` enum in SCHEMA.md.
- [ ] **Vince** — item 4: boundary declared vs extend his modality enum;
      plus the Adapter B `launch_year` application convention (§5).
- [ ] **Abraham / Sean / Weichi** — as emitters: can the hypothesis node
      populate the required fields (all new fields are optional)?

## 7. The process (what you actually do)

**On every pull of `main`:**
1. `git pull` → **read this file** → check §5 for hazards touching your area.
2. If your plans changed since your last push, update your §3/§4 rows.

**While working:**
3. Work in **your own `managed/<node>/` directory**. Never edit another
   person's node dir; if you need something changed there, add a line to §5
   or ask the owner. Shared files (README, root configs, `thesis.ts` once
   ratified) change only with a §6-style agenda note or the owner's OK.
4. Keep your node's state honest in its own doc (NEXT.md pattern —
   trial-recruitment-forecaster's is the reference). Simulated numbers stay
   *named* simulated (`simulatedMonthsToEnroll`, `NOT_DECISION_GRADE` —
   both nodes already do this; keep the standard).

**Before every push:**
5. Run your node's verification (§8). Green or say why not in the commit.
6. Update this file: move finished items to §3, new debts to §4, new
   cross-node needs to §5.

**Landing work:**
7. Push to **your own branch**. The **auto-integrator** merges it to `main`:
   `bun scripts/integrate.ts` sweeps every branch, `merge --no-ff`s anything
   new, auto-fixes resurrected pre-rename paths, runs typecheck + check, and
   only pushes if green — a merge-log entry lands in §9 each time. It runs
   continuously from Abhishek's watcher session (30s polling) and anyone can
   run it manually. *(Amends the "Cyrus merges by hand" sprint decision —
   Abhishek's call, 2026-08-15 evening; revert by deleting this step.)*
8. **Conflicts and red checks are never auto-pushed.** The integrator reports
   `CONFLICT` / `COLLISION` / `VERIFY-FAILED` and leaves them for a human (or
   the watching Claude session) to resolve with judgment.
9. Small COORDINATION.md-only updates may go straight to `main`.
10. **After every merge lands, this file gets refreshed in two tiers:** the
    integrator appends the §9 log line (branch, commit subjects, checks)
    automatically, and the watcher session (or whoever merged) updates the
    affected person's §3/§4 rows and any §5 items the merge resolved — so
    §2–§5 never drift from what main actually contains.
11. After a merge lands: everyone pulls, GOTO step 1.

## 8. Verification commands per node

| Node | Command(s) |
|---|---|
| repo-wide TS | `bun run typecheck && bun run check` |
| trial-recruitment-forecaster | `bun managed/trial-recruitment-forecaster/demo.ts` (needs `ANTHROPIC_API_KEY`); `bun managed/trial-recruitment-forecaster/backtest.ts` |
| therapeutic-program-economics | `cd managed/therapeutic-program-economics && uv sync --frozen --extra dev && uv run pytest && uv run ruff check .` |
| small-molecule-tractability-review | no runnable end-to-end yet; pipeline.html records per-stage status |
| research-evidence-mapper | `bun run console research-evidence-mapper -- --once '{"graph_id":"g_nope","ask":"resolve_link","target":"L99","depth":"quick"}'` (fast contract check: reply must start `{`, no fence, `status: "failed"`); full run: `--once '{"ask":"new_question","target":"<question>","depth":"standard"}' --timeout 3000` |
| sandbox-capability-probe | `bun run console sandbox-capability-probe -- --once "run the probe"` (deployed) |

---

*Facts in this file were verified against the tree at `9003ad3` plus remote
branch state on 2026-08-15. If you find a stale claim, fixing it here IS the
process working.*

## 9. Merge log (automated)

Appended by `scripts/integrate.ts` on every verified auto-merge (manual tier-2 resolutions logged here too).

- **2026-08-15 23:55 UTC** — merged `msoliman6/literature-graph-mcp` (0941254, tier-2 rename-location resolution); earlier today: `f84bfff` + `1b39569` same class — typecheck+check green.
- **2026-08-15 23:58 UTC** — merged `vaalessi/program-strategy-valuation` (253a04f, tier-2: rename locations + pyproject version conflict — kept Vince's 0.2.0 bump with main's naming; new evaluation/replay/red-team modules) — his pytest 87/87 + typecheck+check green.

- **2026-08-16 00:00 UTC** — merged `vaalessi/program-strategy-valuation` (MERGED) — typecheck+check green.

- **2026-08-16 00:07 UTC** — merged `abhishek-jani` (MERGED) — Adapter B: forecaster -> economics launch-delay overlay (economics-bridge.ts) — typecheck+check green.

- **2026-08-16 00:11 UTC** — merged `rafwiewiora/druggability-dossier` (MERGED) — graph-intake: read the upstream evidence graph, on the real schema — typecheck+check green.
- **2026-08-16 00:23 UTC** — merged `abhishek-jani` (6c3c094, tier-2: par6 checklist union) — thesis.ts ratification legwork (items 1-4, all optional/back-compat, 4/4 fixtures parse) · backtest scale-transfer EXPERIMENT columns (sqrt-dilution rejected on 22 fresh rows) — typecheck+check green.

- **2026-08-16 00:25 UTC** — merged `vaalessi/hypothesis-highlander` (MERGED) — Add hypothesis-highlander: quality-diversity meta-search over the pipeline — typecheck+check green.
