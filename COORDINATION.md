# COORDINATION.md — team state + working process

**Read this file first every time you pull `main`.** It is the single source
of truth for who owns what, what is done, what is pending, what nobody owns
yet, and the process we all follow. If you change any of those facts, you
update this file in the same push. Last full update: **2026-08-15 (evening)**.

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
      ▼   (adapter B, unowned: months -> launch_year delta)
therapeutic-program-economics
      │  rNPV, value_lost_per_launch_delay_year, decision grade
      ▼
   verdict
```

The shared contract is [`IndicationThesis`](./managed/trial-recruitment-forecaster/thesis.ts).
**Status: not yet ratified — see §6.** Nothing composes end-to-end today; the
two adapters marked above have no owner.

## 2. Branch map — who owns what

| Person | Branch | Node (dir under `managed/`) | Merged into main? |
|---|---|---|---|
| Abhishek | `abhishek-jani` | `trial-recruitment-forecaster` | ✅ |
| Rafal | `rafwiewiora/druggability-dossier` | `small-molecule-tractability-review` | ✅ (incl. `f84bfff`: 651x figure withdrawn, cryptic/disorder/interface modules added) |
| Soliman | `msoliman6/literature-graph-mcp` | `research-evidence-mapper` | ✅ |
| Moamen | `moamen` | `sandbox-capability-probe` | ✅ |
| Vince | `vaalessi/program-strategy-valuation` | `therapeutic-program-economics` | ✅ |
| Abraham (+ Sean, Weichi) | `AbrehamT/Hypothesis_Generator` | hypothesis node — **no code pushed yet** | (nothing to merge) |
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

**Rafal — small-molecule-tractability-review** *(partial prototype)*
- 4 real skills (precedent-lookup, structure-select, pocket-scan,
  falsification-sweep), deployed CPU Modal pocket scanner (fpocket + P2Rank),
  10-target calibration fixtures, evidence-rules CLAUDE.md, pipeline.html
  status board. Precedent + structure-selection stages VERIFIED.

**Soliman — research-evidence-mapper** *(implementation landed 2026-08-15 late)*
- SCHEMA.md / CONTRACT.md / BUILD.md design packet, now plus: agent
  CLAUDE.md, three skills (literature-search, claim-extraction,
  graph-assembly with deterministic assemble.py), and first run artifacts
  (`runs/g_1a4f`). Not yet re-reviewed against BUILD.md's verification
  criteria — owner to update this row.

**Moamen — sandbox-capability-probe** *(done — throwaway, served its purpose)*
- The only deployed Managed Agent. Proved: bundled scripts execute in the
  sandbox, python 3.11 + uv present, memory mounts writable, sqlite3 absent,
  egress open to the 3 tested hosts. Results recorded in Soliman's CONTRACT.md.

**Vince — therapeutic-program-economics** *(runnable)*
- Deterministic pydantic/numpy economics simulator: pricing corridors, patent
  clock, cash flow, Monte Carlo rNPV, provenance + secret redaction,
  decision-grade gate. 61/61 tests pass (verified in-repo), CLI + Streamlit.

**Cyrus — infra**
- Merged all branches into `main`, renamed nodes for clarity, rewrote README
  with honest capability boundaries, Managed-Agents harness + deploy/console
  CLIs. `main` is the default branch.

## 4. Pending — per person

**Abhishek**
- [ ] Drive `thesis.ts` ratification (§6) — blocking all composition.
- [ ] Wrap forecaster as a Managed Agent (fresh session: `/clear` →
      `/managed-agent-prototype`; engine becomes `tools.ts` handlers). Do
      after ratification.
- [ ] Known model limitation: per-site velocity doesn't transfer to 100+ site
      scale (backtest isolates it; candidate √-dilution fix documented in NEXT.md).

**Rafal**
- [x] `f84bfff` merged (2026-08-15 late, rename-aware).
- [ ] Falsification sweep has never been executed; dossier assembly never run
      end-to-end; GPU escalation stage blocked on a Modal payment method.
- [ ] Pocket scanner runs in Rafal's personal Modal workspace — single point
      of failure for any demo; document or share the credential path.
- [ ] Pin the `proto-tools` git dependency (unpinned ref = unreproducible image).

**Soliman**
- [x] First implementation drop merged (CLAUDE.md, 3 skills, assemble.py,
      run artifacts). Remaining per BUILD.md: fixtures, wrapper, and the
      blocking verification criteria — owner to confirm what's left.
- [ ] Long-lived Paperclip auth (which header the MCP accepts for API keys).
- [ ] Committed session id in CONTRACT.md:199 — scrub if repo goes public.

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
| **Adapter B** | forecaster `simulatedMonthsToEnroll` → economics `launch_year` delta + `launch_delay_years` range. ⚠️ The two "obvious" wirings are both wrong: score→PoS is a category error; months→stage_durations only shifts cost timing. The value-bearing slot is launch delay, which the engine already prices (`value_lost_per_launch_delay_year` ≈ $5.06M/yr on the demo fixture). | Abhishek + Vince |
| **Orchestrator** | one command running thesis → evidence → recruitment → economics | Cyrus + whoever's free |
| ~~HAZARD: rename collision~~ | **Resolved 2026-08-15 late**: git's directory-rename detection mapped both Rafal's and Soliman's old-path commits onto the renamed dirs; new files were accepted at the detected locations. `scripts/integrate.ts` escalates this class and `fixDeadPaths` catches any residue. | done |
| **Decision-grade policy** | economics excludes simulation-sourced inputs from decision grade BY DESIGN — a composed demo will always read NOT_DECISION_GRADE unless the team explicitly decides how simulated upstream numbers are graded. Decide before the stage demo, not on it. | Everyone (5-min call) |

## 6. thesis.ts ratification agenda (the blocking conversation)

`IndicationThesis` is declared the shared contract in the README but no other
node consumes it yet. Concrete items, each discovered by reading the other
nodes' actual contracts:

1. Add optional `mechanismHypothesis: "orthosteric" | "allosteric" |
   "oligomer_destabilisation" | "unknown"` — Rafal's node needs the enum
   (load-bearing for chain selection); free-text `mechanism` can't feed it.
2. Add optional `uniprotAccession` — Rafal's join key (gene symbol requires a
   resolution step he'd rather record than perform).
3. `Evidence.direction` has `supports | contradicts`; Soliman's findings also
   emit `no_effect`. Pick a convention (third value, or map to contradicts
   with a note).
4. Modality vocabulary: thesis has 6 values, economics accepts 2. Align or
   declare the boundary.
5. Confirm the two adapters in §5 and their owners.

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
10. After a merge lands: everyone pulls, GOTO step 1.

## 8. Verification commands per node

| Node | Command(s) |
|---|---|
| repo-wide TS | `bun run typecheck && bun run check` |
| trial-recruitment-forecaster | `bun managed/trial-recruitment-forecaster/demo.ts` (needs `ANTHROPIC_API_KEY`); `bun managed/trial-recruitment-forecaster/backtest.ts` |
| therapeutic-program-economics | `cd managed/therapeutic-program-economics && uv sync --frozen --extra dev && uv run pytest && uv run ruff check .` |
| small-molecule-tractability-review | no runnable end-to-end yet; pipeline.html records per-stage status |
| research-evidence-mapper | docs only; BUILD.md lists blocking verification criteria |
| sandbox-capability-probe | `bun run console sandbox-capability-probe -- --once "run the probe"` (deployed) |

---

*Facts in this file were verified against the tree at `9003ad3` plus remote
branch state on 2026-08-15. If you find a stale claim, fixing it here IS the
process working.*
