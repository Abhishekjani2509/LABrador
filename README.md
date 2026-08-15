# LABrador

LABrador is a hackathon prototype for stress-testing life-science indication
theses with specialist agents. It turns an asset–indication hypothesis into
inspectable evidence about the literature, small-molecule tractability, and
clinical recruitability.

The repository is a merged workspace, not yet a finished end-to-end product.
The recruitability engine and Managed Agents runtime are runnable; the
druggability specialist has a detailed evidence contract and calibration set;
the literature graph is currently specified but not implemented.

## What is here

| Workstream | Question it answers | Current state |
| --- | --- | --- |
| `simulated-clinical` | Could the proposed trial recruit the required population in a credible time window? | Runnable engine, fixtures, demo, and six-trial backtest |
| `druggability-dossier` | Can the target be addressed with a small molecule, and what evidence supports that conclusion? | Specialist instructions, ten-target calibration data, and a static pipeline view |
| `literature-graph` | What does the literature claim, where does it disagree, and which relationships remain untested? | Schema, delivery contract, and build plan; implementation remains open |
| `spike` | Can the deployed sandbox run bundled scripts, use memory, and reach Paperclip? | Deployed environment probe used to settle platform assumptions |
| Managed Agents harness | How do local specialist prototypes become callable cloud agents? | Runtime, deployment CLI, console CLI, and eve router scaffold |

The shared contract is
[`IndicationThesis`](./managed/simulated-clinical/thesis.ts). It makes the
asset, target direction, disease, biomarker population, endpoint, mechanism,
evidence, and uncertainty explicit so downstream nodes can exchange evidence
without relying on prose conventions.

## Quickstart

You need [Bun](https://bun.sh) and an Anthropic API key. The key is required for
commands that call Claude; typechecking and static checks do not use it.

```bash
git clone https://github.com/Abhishekjani2509/LABrador.git
cd LABrador
bun install --frozen-lockfile
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

bun run typecheck
bun run check
```

## Run the clinical-recruitability demo

The demo evaluates the included indication theses with current
ClinicalTrials.gov data and Claude-assisted eligibility analysis:

```bash
# Run every fixture against current evidence
bun managed/simulated-clinical/demo.ts

# Run one fixture
bun managed/simulated-clinical/demo.ts dupi-eoe

# Re-run the same thesis with a historical evidence horizon
bun managed/simulated-clinical/demo.ts dupi-eoe 2018-01-01
```

Each result reports estimated enrollment time, required sample size, site
count, screening burden, supporting trials, failed precedents, and the smallest
counterfactual change that could make the design recruitable. Historical runs
filter registry evidence by the supplied date, though the model-based
eligibility read cannot provide a perfectly sealed historical knowledge
boundary; [`NEXT.md`](./managed/simulated-clinical/NEXT.md) tracks that and the
remaining validation limits.

The backtest compares predictions with completed trials:

```bash
bun managed/simulated-clinical/backtest.ts
bun managed/simulated-clinical/backtest.ts NCT03633617 NCT04394351
bun managed/simulated-clinical/backtest.ts --condition "Eosinophilic Esophagitis" 10
```

These commands call external services and can take time. A transient failure
for one fixture is reported without discarding completed runs for the others.

## Explore the evidence workstreams

The druggability dossier deliberately keeps retrieved precedent separate from
computed tractability. That distinction matters because a target can have
strong biological validation but no small-molecule precedent, while geometric
pocket scoring can miss cryptic sites that appear only in ligand-bound
structures.

- [`CLAUDE.md`](./managed/druggability-dossier/CLAUDE.md) defines the specialist's input, output, evidence rules, and refusal conditions.
- [`fixtures/README.md`](./managed/druggability-dossier/fixtures/README.md) explains the calibration ladder from straightforward kinase targets through modality traps, cryptic pockets, contradictory evidence, and insufficient data.
- [`pipeline.html`](./managed/druggability-dossier/pipeline.html) is a standalone visual walkthrough that can be opened directly in a browser.

The literature graph is designed around mechanically verifiable quotes,
stable graph identifiers, explicit disagreement, and persistent state across
research rounds. Its current artifacts are contracts for the implementation:

- [`SCHEMA.md`](./managed/literature-graph/SCHEMA.md) defines requests, graph JSON, storage, and guarantees.
- [`CONTRACT.md`](./managed/literature-graph/CONTRACT.md) assigns the search, extraction, assembly, and deployment responsibilities.
- [`BUILD.md`](./managed/literature-graph/BUILD.md) gives the implementation order and blocking verification criteria.

## Managed Agents workflow

The repository includes a harness for taking a specialist that works in Claude
Code and deploying the same instructions and skills as a Claude Managed Agent:

1. **Prototype.** Run `/managed-agent-prototype <description>` in Claude Code.
   The specialist's instructions, skills, and fixtures live together under
   `managed/<name>/`.
2. **Compile and deploy.** Run `/managed-agent-deploy <name>` from the working
   prototype session. The transcript supplies the debugging context, while the
   skill emits a manifest, access policy, local custom-tool handlers, and an eve
   wrapper.
3. **Call the agent.** Use `bun run console <name>` for the visual console or
   `bun run console <name> -- --once "task"` for a headless run.
4. **Expose the router.** Use `bun run dev` to start the eve router after at
   least one specialist wrapper has been generated under `agent/tools/`.

To redeploy an already compiled specialist without recompiling its prototype
session:

```bash
bun run deploy <name>
```

Deployment creates or versions remote resources and writes their identifiers
back to `managed/<name>/manifest.json`. Treat it as an external state change,
not as a local build command.

## Runtime model

```text
caller / eve router
        |
        | task
        v
lib/claude-managed-agent.ts ---- create session ----> Managed Agents API
        ^                                                   |
        |                                                   | agent events
        +---------------------- SSE stream ------------------+
        |
        +---- run local custom tool ---- return result ----->
```

The calling process is the custom-tool server. When a remote agent requests a
custom tool, the runtime executes the handler from `managed/<name>/tools.ts`,
posts the result to the session, and continues consuming events until the agent
finishes. This keeps credentials and system integrations in the caller's
process instead of copying them into the remote sandbox.

## Repository layout

```text
managed/
  simulated-clinical/     recruitability engine, fixtures, demo, backtest
  druggability-dossier/   specialist contract, calibration data, visualizer
  literature-graph/       schema, delivery contract, build plan
  spike/                  deployed sandbox capability probe
agent/                    eve router and generated specialist wrappers
lib/                      Managed Agents runtime and access control
scripts/                  deploy and console CLIs
.claude/skills/           prototype, deploy, and setup workflows
docs/                     original Managed Agents starter framing
```

## Known integration gaps

- There is no top-level orchestrator connecting hypothesis generation,
  evidence enrichment, recruitability, and ROI into one command.
- The `IndicationThesis` contract has not yet been adopted by every planned
  node, so composition across branches still needs an integration pass.
- The literature graph has design artifacts but lacks its agent instructions,
  skills, deterministic assembler, fixtures, and router wrapper.
- The root eve router has no registered specialists yet; generated wrappers are
  added only when a managed agent is compiled.
- Restricting an agent's ACL before router authentication is wired makes that
  tool unavailable to every router caller. Direct console calls bypass the
  router and do not validate ACL behavior.

## License

MIT — see [`LICENSE`](./LICENSE).
