# research-evidence-mapper

A Claude Managed Agent that turns one question about the scientific literature
into one machine-readable knowledge graph, and grows that graph across rounds.

It reads real papers through Paperclip, extracts every claim as a **verbatim
quote** from text it actually fetched, and returns the whole graph as JSON —
nodes, evidence, scored relationships, and the places where the literature has
a hole in it.

**Status: working prototype, not deployed.** The pipeline has run end to end
against real papers in a local session. It has not run in the cloud sandbox.
See [Status and gaps](#status-and-gaps) before relying on it.

---

## What it actually does

Given *"can a small-molecule IRAK4 inhibitor suppress synovial fibroblast-driven
inflammation in rheumatoid arthritis, or is its effect confined to the myeloid
compartment?"* it returned a graph in which:

- round 1 (`new_question`, `standard`) found no direct evidence and emitted the
  missing relationship as **gap `g3`**;
- round 2 (`test_gap` on `g3`, `deep`) **found the paper round 1 missed** and
  promoted the gap into link `L3`, state `disagreed`, with the boundary
  condition spelled out: the drug works on TLR-driven fibroblast inflammation,
  fails on IL-1β-driven cytokines, but does block IL-1β-driven MMP.

That round-1 miss is the point, not an embarrassment. A shallow sweep produced a
confident absence; a deeper targeted round overturned it. The graph records
both, and `changed_in_round` marks what moved.

The distinguishing behaviours:

- **Every claim is a verbatim quote**, string-matched against the fetched text by
  code. A quote that does not match is dropped and counted in
  `coverage.no_quote_discarded`. It is never repaired.
- **Nothing is filtered by score.** Hedged and single-source findings stay in.
  The caller sets its own threshold.
- **Absence is reported as structure.** A pair nobody linked becomes a `gap`; a
  gap that has been *searched for* carries `searched_in_round`, which is a much
  stronger statement than one nobody looked at.
- **Disagreement gets explained, not averaged.** When two camps conflict,
  `explain_disagreement` compares their experimental conditions and reports
  `conditions differ: {A} vs {B}` — because different conditions is the common
  case, not real contradiction.
- **Coverage is honest.** `found` / `read` / `used` / `truncated` /
  `stop_reason` describe what actually happened. Only `complete` means the
  literature was exhausted.

---

## Input / output schema

Full contract in [`SCHEMA.md`](./SCHEMA.md). Summary:

### Input — the task string is one JSON object

```jsonc
{
  "graph_id": "g_7f2a",    // omit only for new_question
  "ask": "resolve_link",   // new_question | expand_node | resolve_link | test_gap
  "target": "L2",          // an id from that graph; free text for new_question
  "depth": "deep",         // quick | standard | deep | exhaustive
  "reason": "..."          // logged, never acted on
}
```

Non-JSON input is treated as `{"ask":"new_question","target":"<the text>","depth":"standard"}`.

| ask | target | does |
|---|---|---|
| `new_question` | free text | mints a new `graph_id` at round 1 |
| `expand_node` | a `things` id | what else connects to this node |
| `resolve_link` | a `links` id | more evidence on one relationship, biased to the under-represented side |
| `test_gap` | a `gaps` id | has anyone actually stated this? sets `searched_in_round` either way |

| depth | papers | queries | extraction |
|---|---|---|---|
| `quick` | 10 | 2 | abstracts only |
| `standard` | 25 | 4 | abstracts, full text on the top few |
| `deep` | 50 | 6 | full text on every paper that yields a finding |
| `exhaustive` | 300 | 12 | full text throughout — minutes, not a demo tier |

`quick` may never report "no evidence" — ten papers is page one, and page one lies.

### Output — always the full graph, never a delta

```jsonc
{
  "schema_version": "1.1", "graph_id": "g_7f2a", "question": "...",
  "round": 2, "status": "ok", "generated_at": "...", "error": null,
  "rounds":   [ { "n": 1, "ask": "...", "outcome": "new_evidence" } ],
  "coverage": { "depth": "deep", "found": 412, "read": 43, "used": 40,
                "truncated": true, "no_quote_discarded": 6,
                "stop_reason": "max_papers" },
  "things":   [ { "id": "t1", "name": "...", "kind": "protein", "aliases": [] } ],
  "papers":   [ { "id": "p2", "doi": "...", "first_author": "...",
                  "study_type": "test_tube", "is_preprint": false } ],
  "findings": [ { "id": "f2", "from": "t2", "how": "binds", "to": "t3",
                  "says": "yes", "quote": "<verbatim>", "paper": "p2",
                  "where": "<conditions>", "is_own_result": true } ],
  "links":    [ { "id": "L2", "from": "t2", "how": "binds", "to": "t3",
                  "state": "disagreed", "why": "conditions differ: ...",
                  "confidence": { "overall": 0.42, "agreement": 0.5,
                                  "evidence_quality": 0.4, "independence": 0.0 } } ],
  "gaps":     [ { "id": "g1", "missing": ["t1","t3"], "implied_by": ["L1","L2"],
                  "confidence": 0.34, "searched_in_round": null } ]
}
```

`confidence.overall = 0.4·agreement + 0.4·evidence_quality + 0.2·independence`,
computed in code and recomputable from `findings` + `papers`. **Scores are valid
for one `(graph_id, round)` pair only** — a link at 0.81 can correctly drop to
0.44 when a contradicting paper arrives. Never cache one across rounds.

**Failure is still a graph.** There is no error blob, ever — one parser handles
every reply. `status` is `ok` | `empty` | `partial` | `failed`; on anything but
`ok` the lists are empty or short, `coverage` still reports real numbers, and
`error` carries a one-line cause.

---

## What it needs

### MCP servers — exactly one

| server | transport | auth |
|---|---|---|
| **Paperclip** — `https://paperclip.gxl.ai/mcp` | remote streamable HTTP | `Authorization: Bearer <token>` |

Paperclip is a virtual filesystem of full-text biomedical papers, regulatory
documents and clinical trials. The MCP exposes **one passthrough tool**,
`paperclip({ command: string })`, which runs the Paperclip CLI server-side — so
the tool surface is the CLI surface, and calling it means writing a command
string. It is **stateless** (nothing carries between calls) and the sandbox it
runs in **blocks shell loops and `xargs`**, so there is no batching: one command
per call.

**Paperclip is the only source of papers.** No `web_fetch`, no second corpus. If
Paperclip cannot supply something, that is a `coverage` fact to report — not a
licence to go around it, because a graph built partly from elsewhere breaks the
guarantee that every quote is verifiable against a Paperclip document id.

Auth rides in a platform credential vault; the credential id goes in
`manifest.vault_ids`. Provisioning is manual — nothing in `scripts/` automates
it. Which header the MCP accepts for a **long-lived API key** is still untested;
`Bearer` is proven with a session token.

### Memory

One memory store, mounted at `/mnt/memory/research-evidence-mapper/`, provisioned by
`bun run deploy`. State survives across sessions and rounds.

```
/mnt/memory/research-evidence-mapper/
  index.json          graph_id -> question, round, updated_at
  g_7f2a/
    meta.json  things.json  papers.json  links.json  gaps.json
    findings/r1.json  findings/r2.json     # appended per round, chunked at 80KB
```

A single memory file caps at 100KB. Ids are stable forever — `t1` stays `t1`,
and gap ids key on the missing pair so `test_gap` targets survive re-ranking.

### Skills — three, uploaded unchanged

| skill | owns |
|---|---|
| `literature-search` | query construction per ask, tier budgets, pagination, the Paperclip seam, normalization, coverage accounting |
| `claim-extraction` | the two extraction modes and quote fidelity |
| `graph-assembly` | runs the bundled `assemble.py` — dedup, scoring, link states, disagreement explanation, gaps |

`assemble.py` is stdlib-only, class-free and deterministic: two runs on the same
input are byte-identical, including across `PYTHONHASHSEED` values. All
arithmetic lives there. Nothing is ever scored by hand, because prose arithmetic
does not reproduce.

### Runtime

Python 3.11 in the sandbox, no extra packages. No `tools.ts` — the agent needs
no host-side handler, because bundled skill scripts execute in the sandbox
(verified) and Paperclip is reached over MCP rather than a local CLI.

---

## Install

There are two different things people mean by this.

### A. Deploy the agent (what you do once)

From the repo root, in a Claude Code session:

```bash
bun install                                   # once per machine
/managed-agent-deploy research-evidence-mapper        # compiles + deploys + smoke tests
```

That compiles `manifest.json`, `acl.ts` and the router wrapper, uploads the
three skills to the Skills API, creates or versions the Managed Agent with
`CLAUDE.md` as its system prompt, provisions the memory store, and does not hand
back until a smoke test against the **deployed** agent passes.

Requirements:

- `ANTHROPIC_API_KEY` in `.env` at the repo root
- a Paperclip credential in a platform vault, id in `manifest.vault_ids`

Re-deploy any time with `bun run deploy research-evidence-mapper` — idempotent, and a
no-op when nothing changed.

### B. Call the deployed agent (what everyone else does)

Nothing to install. It is a server-side agent with an HTTP endpoint.

```bash
bun run console research-evidence-mapper              # opens it in the Claude Console
bun run console research-evidence-mapper -- --once "$(cat fixtures/q-disputed.txt)"
```

Any backend can drive it with three HTTP calls — create a session, send the
task, read the SSE stream. See `lib/claude-managed-agent.ts`.

### C. Prototype it locally (what you do to change it)

Only needed if you want to iterate on the agent itself.

```bash
git clone <repo> && cd <repo>
bun install
cp .env.example .env        # add ANTHROPIC_API_KEY
```

For running the pipeline by hand against the corpus you also need the Paperclip
CLI. Note the vendor installer is currently broken on macOS — its launcher
resolves to the system Python 3.9 while its vendored `urllib3` needs 3.10+, and
it never installs `click` or `rookiepy` at all. A working install:

```bash
python3.11 -m venv ~/.paperclip/venv                       # 3.11 or 3.12; NOT 3.13+
curl -sL -o /tmp/gxl_paperclip-0.7.36-py3-none-any.whl \
     https://paperclip.gxl.ai/paperclip.whl                # served under a name pip rejects
~/.paperclip/venv/bin/pip install /tmp/gxl_paperclip-0.7.36-py3-none-any.whl
ln -sf ~/.paperclip/venv/bin/paperclip ~/.local/bin/paperclip
paperclip login
```

Three traps, all verified: `pip install https://paperclip.gxl.ai/paperclip.whl`
fails because the served filename violates PEP 427 and pip rejects it before
downloading; `pip install gxl-paperclip` fails because the PyPI index returns
200 with no distributions; and `rookiepy` publishes wheels only for cp37–cp312,
so on Python 3.13+ it tries a Rust source build and fails.

The agent's own skills are **not loadable** while prototyping — the session's
cwd is the repo root, so `managed/research-evidence-mapper/.claude/skills/` is outside
what the Skill tool discovers. Read the SKILL.md files and follow them by hand;
the deploy smoke test is what proves real skill loading.

---

## When Paperclip is down

A dead search tool and an empty literature look identical in the output, and
confusing them is the worst failure this agent can produce. "No evidence found"
is a scientific claim; emitting it because the corpus was unreachable is a
fabricated one, and the caller cannot tell.

So the agent probes before it concludes:

```
search -s pmc "rheumatoid arthritis" -n 1     # a healthy corpus cannot return nothing
```

If that canary fails, it stops — it does not run the planned queries, does not
fall back to another source, and returns:

```jsonc
{ "status": "failed", "error": "<the tool's own message, verbatim>",
  "coverage": { "found": 0, "read": 0, "used": 0,
                "stop_reason": "search_unavailable" },
  "things": [], "papers": [], "findings": [], "links": [], "gaps": [] }
```

For an extending ask the prior graph is left **unchanged** in memory — a failed
round never overwrites good state. If Paperclip dies mid-round, whatever was
already quote-verified is kept and the reply is `status: "partial"` with the
same `stop_reason`. And a `test_gap` that could not query never sets
`searched_in_round`: nothing was searched.

---

## Status and gaps

| | |
|---|---|
| Sandbox affordances (bundled scripts, python3, `/mnt/memory`, egress) | verified via the `spike` agent |
| `new_question` | run against real papers |
| `test_gap` | run against real papers; overturned a round-1 answer |
| `expand_node`, `resolve_link` | **never executed** |
| Figure reading (`ask-image`) | **never executed** |
| Deployment | **never run** — `manifest.json` does not exist yet |
| Long-lived API key auth against the MCP | **untested** |

`resolve_link` is the likeliest to break first: it is the ask that biases
queries toward the under-represented side *and* reads figures, and neither path
has run.

Known rough edge: `explain_disagreement` concatenates every `where` value into
one string, so its output is correct but reads poorly when findings differ along
more than one axis. Worth tightening before this is demo material.

## Files

```
CLAUDE.md                                  SOURCE — the deployed system prompt, verbatim
.claude/skills/literature-search/          SOURCE — uploaded unchanged
.claude/skills/claim-extraction/           SOURCE
.claude/skills/graph-assembly/             SOURCE — SKILL.md + assemble.py
SCHEMA.md                                  the data contract
CONTRACT.md                                deliverables, MCP details, assemble.py spec
BUILD.md                                   build plan and risks
runs/                                      local output from hand-run rounds; not uploaded
manifest.json                              COMPILED by /managed-agent-deploy — absent until then
```
