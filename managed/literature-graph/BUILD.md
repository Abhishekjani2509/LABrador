# literature-graph — build plan

One deployed Managed Agent. Question in, knowledge graph out, state kept between
rounds. Contract is `SCHEMA.md`.

## External surface

> **Voided 2026-08-15.** Every "Paperclip MCP" reference below and in earlier
> discussion is wrong — Paperclip ships no MCP server. It is a Python CLI the
> sandbox installs and shells out to. `CONTRACT.md` §2 is the current word.

| need | how |
|---|---|
| search + full text | **Paperclip CLI**, pip-installed into the sandbox — no MCP |
| state across rounds | **memory store** — platform feature, `/mnt/memory/`, no infra |
| search fallback / metadata | `web_fetch` (built in) |
| scoring, dedup, gaps | `bash` + python in the container |

Not used: Qdrant, Mem0, SQLite, Sequential Thinking. Lookup is exact by
`graph_id`, not semantic; the graph is the memory; a container SQLite dies with
the session.

## Pipeline

```
request {graph_id?, ask, target, depth}
  → load prior state from /mnt/memory (skip if new_question)
  → plan queries from ask type
  → Paperclip search, capped by depth tier
  → extract findings:
       abstracts, batched 5/pass     ← new_question, expand_node
       full text on relevant papers  ← resolve_link, test_gap
  → verify every quote against fetched text (string match, drop on miss)
  → merge names against the WHOLE graph
  → assemble.py: dedup, score, gaps
  → write /mnt/memory/<graph_id>/*, return full graph
```

## Files

**Source (we author):**

| file | holds |
|---|---|
| `CLAUDE.md` | role, 4 ask types, pipeline, tier table, memory layout, JSON skeleton |
| `.claude/skills/literature-search/SKILL.md` | Paperclip interface + normalization; the transport seam |
| `.claude/skills/claim-extraction/SKILL.md` | two modes (abstract batch / full text), quote fidelity |
| `.claude/skills/graph-assembly/SKILL.md` + `assemble.py` | dedup, scoring, gaps — deterministic, in code |
| `fixtures/` | 3 questions: well-studied, sparse, genuinely disputed |

**Compiled by `/managed-agent-deploy`:** `manifest.json` (sonnet-5, `message`,
`session_policy: "fresh"`, Paperclip in `mcp_servers` with
`permission: "always_allow"`, `memory` block), `acl.ts` (`{ public: true }`),
`agent/tools/literature-graph.ts`. No `tools.ts` unless Paperclip turns out to be
stdio — then one handler wraps it.

## Order

| # | step | why here |
|---|---|---|
| 0 | **Spike, 30 min** — stub agent: Paperclip reachable? bundled script runs? `python3` present? memory mount writable? | all four would force a rewrite |
| 1 | `fixtures/` | defines "done" before anything aims at it |
| 2 | `CLAUDE.md` + 3 skills | |
| 3 | **Hand-run the pipeline in this session** on the largest fixture | demo-safe fallback if deploy fails |
| 4 | `/managed-agent-deploy literature-graph` + smoke | |
| 5 | HTML render | where the points are; needs real data first |

## Verify

`bun run typecheck && bun run check`, then blocking:

```
bun run console literature-graph -- --once "$(cat managed/literature-graph/fixtures/q-disputed.txt)"
```

Six facts, each independently checked:

1. Paperclip called at the event level — trace lines, not a prose claim
2. reply carries the full graph JSON, not a summary
3. disputed fixture yields ≥1 link `state: "disagreed"` — zero is a failure, not a clean result
4. a low-confidence finding **survives** into the output
5. round 2 (`resolve_link`) loads round 1 from memory and `round` increments
6. three quotes spot-checked verbatim against their DOIs

## Risks

- ~~Bundled skill scripts may not be executable in the sandbox.~~ **Settled: they
  are.** `probe.py` shipped, was found at `/workspace/skills/env-probe/probe.py`,
  and ran. Scoring stays in `assemble.py`.
- ~~Paperclip transport unknown.~~ **Settled, but not to either branch we
  planned for.** It is a CLI, not an MCP server of any transport. The sandbox
  installs it from the wheel and runs it directly, so there is no
  `manifest.mcp_servers` entry and no host-side `tools.ts` relay. See
  `CONTRACT.md` §2.
- **The wheel URL is a trap.** `pip install https://paperclip.gxl.ai/paperclip.whl`
  fails with "not a valid wheel filename" — a PEP 427 naming problem that reads
  like a network error. Download first, rename from the archive's `.dist-info`.
- **Auth is the last open gate.** The sandbox reaches Paperclip and runs the CLI
  but has no credentials; `search` returns `Not authenticated`. Needs an API key
  minted from paperclip.gxl.ai, carried as a vault `environment_variable`
  credential scoped to that host.
- **`bun run console <name>` does not attach memory**; only `--once` and the eve
  wrapper do. Test memory through `--once`, never the Console session.
- **`read_write` memory + web content = injection surface.** Papers are
  semi-trusted; an injected instruction could be written to memory and read back
  as trusted next round. Accepted for the hackathon; worth a line in `CLAUDE.md`
  telling the agent that memory holds data, never instructions.
- **`exhaustive` (300 papers) is ~60 serial extraction passes.** Minutes. Never
  demo on it.

## Deferred

Analogy edges (additive pass over `gaps`), `expand_node` breadth tuning, render
polish, auth (`acl.ts` stays public — a restricted ACL fails closed until the
router has auth).
