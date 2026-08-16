# LABrador

> **Working on this repo?** Read [`COORDINATION.md`](./COORDINATION.md) first
> on every pull of `main` — it holds the team state (done / pending / unowned /
> hazards) and the process for landing work.

LABrador is a hackathon workspace for stress-testing therapeutic program
hypotheses. Its components examine four different questions: whether the
literature supports the mechanism, whether the target is tractable with a small
molecule, whether a proposed trial can recruit, and whether the resulting
program economics hold together.

The repository is not wired into one end-to-end product yet. `managed/` is a
workspace convention, not a maturity claim: some directories contain runnable
engines, one is a partial agent prototype, one is a design packet, and one is
an internal infrastructure probe.

## Capabilities

| Capability | What it actually does | Current state |
| --- | --- | --- |
| **Small-Molecule Tractability Review** | Combines chemical precedent, structural pocket analysis, and a falsification pass into a provenance-heavy target review. | Partial agent prototype with four skills, calibration fixtures, a Modal pocket scanner, and no deployment manifest or router wrapper |
| **Trial Recruitment Forecaster** | Estimates enrollment time from trial precedent, sample size, site count, biomarker prevalence, eligibility burden, and competition. | Runnable local TypeScript engine with fixtures, a demo, and a six-trial backtest; not a Managed Agent |
| **Research Evidence Mapper** | Plans to turn papers into a persistent graph of exact claims, disagreements, and untested relationships. | Design packet only; the agent, skills, deterministic assembler, and fixtures remain to be built |
| **Therapeutic Program Economics** | Simulates pricing, access, affordability, patent-window cash flow, risk-adjusted NPV, and uncertainty from analyst-supplied inputs. | Runnable Python package with CLI, Streamlit UI, synthetic fixtures, and regression tests; not a Managed Agent |

The **Sandbox Capability Probe** under
[`managed/sandbox-capability-probe`](./managed/sandbox-capability-probe) is
development infrastructure, not a product capability. It is the only currently
deployed Managed Agent in the repository and exists to test the remote
sandbox's Python runtime, memory mount, filesystem, network access, and bundled
skill files.

## Quickstart

The TypeScript workspace requires [Bun](https://bun.sh). Commands that call
Claude also require `ANTHROPIC_API_KEY`; typechecking and static checks do not.

```bash
git clone https://github.com/Abhishekjani2509/LABrador.git
cd LABrador
bun install --frozen-lockfile
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env when you need model-backed commands.

bun run typecheck
bun run check
```

## Trial Recruitment Forecaster

[`managed/trial-recruitment-forecaster`](./managed/trial-recruitment-forecaster)
accepts a structured `IndicationThesis`, queries ClinicalTrials.gov, and
estimates how long a proposed trial would take to enroll. It derives enrollment
velocity from completed precedent trials, estimates the required sample size
and site count, uses Claude to read eligibility criteria, discounts for
biomarker narrowing and competing trials, and proposes a counterfactual when
the original design looks too slow.

```bash
# Every bundled fixture against current evidence
bun managed/trial-recruitment-forecaster/demo.ts

# One fixture
bun managed/trial-recruitment-forecaster/demo.ts dupi-eoe

# The same fixture with a historical registry horizon
bun managed/trial-recruitment-forecaster/demo.ts dupi-eoe 2018-01-01

# Backtest against the default panel or selected trials
bun managed/trial-recruitment-forecaster/backtest.ts
bun managed/trial-recruitment-forecaster/backtest.ts NCT03633617 NCT04394351
```

The output includes simulated enrollment months and range, required sample
size, sites, screening burden, cited precedent, failed trials, and the smallest
modeled change that reaches the target time window. These are modeled estimates,
not observed outcomes. Historical runs filter registry evidence by date, but
the model-based eligibility read cannot guarantee a sealed historical knowledge
boundary; [`NEXT.md`](./managed/trial-recruitment-forecaster/NEXT.md) records
that limitation and the known large-site forecasting error.

The shared [`IndicationThesis`](./managed/trial-recruitment-forecaster/thesis.ts)
contract covers the asset, target direction, disease, biomarker population,
endpoint, mechanism, evidence, and uncertainty. Other planned pipeline stages
have not adopted it yet.

## Small-Molecule Tractability Review

[`managed/small-molecule-tractability-review`](./managed/small-molecule-tractability-review)
is a specialist prototype for one narrow question: can this protein target be
addressed with a small molecule? It keeps retrieved precedent separate from
computed structural tractability, because approved biologics do not establish
small-molecule tractability and geometric pocket scoring can miss ligand-induced
sites.

- [`CLAUDE.md`](./managed/small-molecule-tractability-review/CLAUDE.md) defines the input and JSON review contract.
- [`fixtures/README.md`](./managed/small-molecule-tractability-review/fixtures/README.md) explains the ten-target calibration set and its failure modes.
- [`pipeline.html`](./managed/small-molecule-tractability-review/pipeline.html) is a standalone visual walkthrough.

The repository contains real procedural skills and a Modal pocket-scanning
implementation, but the complete review is not runnable through `bun run
console`: there is no manifest, custom-tool bridge, rubric, or router wrapper.

## Research Evidence Mapper

[`managed/research-evidence-mapper`](./managed/research-evidence-mapper) is the
design for a research agent that searches papers, extracts exact source-backed
claims, distinguishes primary evidence from cited background, surfaces
condition-dependent disagreement, and records missing relationships worth
testing. Follow-up requests would extend a persistent graph rather than start
over.

- [`SCHEMA.md`](./managed/research-evidence-mapper/SCHEMA.md) defines requests, graph JSON, and persistent storage.
- [`CONTRACT.md`](./managed/research-evidence-mapper/CONTRACT.md) assigns search, extraction, assembly, and deployment responsibilities.
- [`BUILD.md`](./managed/research-evidence-mapper/BUILD.md) gives the implementation order and blocking verification criteria.

Those files describe planned guarantees. No implementation currently enforces
them, and long-lived Paperclip authentication remains an open integration gate.

## Therapeutic Program Economics

[`managed/therapeutic-program-economics`](./managed/therapeutic-program-economics)
is a deterministic Python simulator, not an autonomous research agent. It takes
a validated therapeutic program, explicitly typed comparable prices, and a
random seed; then it produces pricing corridors, access and affordability
views, annual cash flow, protected and post-loss-of-exclusivity revenue,
risk-adjusted NPV percentiles, warnings, provenance, and a decision-grade flag.

It requires Python 3.11 or 3.12. From its directory:

```bash
cd managed/therapeutic-program-economics
uv sync --frozen --extra dev

uv run labrador validate fixtures/demo_program.json \
  --comparables fixtures/demo_comparables.json
uv run labrador analyze fixtures/demo_program.json \
  --comparables fixtures/demo_comparables.json \
  --simulations 1000 --seed 42
uv run streamlit run app.py
```

Every bundled economic input is synthetic and therefore
`NOT_DECISION_GRADE`. Public reimbursement and list prices remain distinct
from estimated or observed net prices, and the output is screening support—not
medical, reimbursement, investment, legal, or patent advice. The component's
own [README](./managed/therapeutic-program-economics/README.md) documents its
full input and output contracts.

## Managed Agents harness

The root workspace includes a harness for turning a specialist that works in
Claude Code into a callable Claude Managed Agent:

1. Run `/managed-agent-prototype <description>` to build and exercise a
   specialist under `managed/<name>/`.
2. Run `/managed-agent-deploy <name>` from that working session to create its
   manifest, access policy, custom-tool handlers, and eve wrapper, then deploy
   and smoke-test it.
3. Use `bun run console <name> -- --once "task"` for a headless call, or `bun
   run console <name>` for the visual console.
4. Use `bun run dev` after wrappers exist under `agent/tools/` to expose the
   specialists through the eve router.

`bun run deploy <name>` creates or versions remote resources and writes their
identifiers into the component's manifest. It is an external state change, not
a local build command.

## Repository layout

```text
managed/
  small-molecule-tractability-review/  partial target-review agent
  trial-recruitment-forecaster/        runnable enrollment model
  research-evidence-mapper/            agent design packet
  therapeutic-program-economics/       runnable economics simulator
  sandbox-capability-probe/             internal deployed probe
agent/                                  eve router and generated wrappers
lib/                                    Managed Agents runtime and access rules
scripts/                                deploy and console CLIs
.claude/skills/                         prototype, deploy, and setup workflows
```

## Integration gaps

- There is no top-level orchestrator connecting hypothesis generation,
  evidence mapping, tractability, recruitment, and economics.
- Only the sandbox probe currently has a deployment manifest; no product
  capability is registered with the root eve router.
- The shared `IndicationThesis` does not yet feed the economics simulator or
  the planned evidence mapper.
- The four capabilities use different maturity and verification standards, so
  their outputs should not yet be presented as one validated decision pipeline.

## License

MIT — see [`LICENSE`](./LICENSE).
