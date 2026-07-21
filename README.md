# mvp — prototype in Claude Code, ship on the Claude Developer Platform

The transcript where your agent finally worked *is* the spec. This starter
turns it into a deployed agent.

You prototype the way you already do: open Claude Code, iterate until the
thing works. Then run one skill — `/make-managed-agent` — and Claude compiles that
session into a **Claude Managed Agent**: a server-side agent on Anthropic's
infrastructure with its own sandbox, versioned config, sessions that survive
restarts, and an event API you can call from anywhere. The skills you wrote
while prototyping upload to the platform **unchanged** — same `SKILL.md`
format on your laptop and in production. That continuity is the point: no
rewrite between "works on my machine" and "deployed".

The story, end to end:

1. **Prototype** — `claude` in this repo, work in `managed/<your-agent>/`.
   Drop in fixtures, write skills, hit snags, fix them.
2. **Compile** — `/make-managed-agent <your-agent>`. Claude mines the transcript
   (including the debugging lessons), asks you a few questions — each with a
   recommended answer — and emits a complete artifact: instructions, skills,
   a quality rubric, custom-tool handlers.
3. **Deploy** — `bun run deploy-agent <your-agent>` uploads the skills and
   creates (or versions) the agent on the Managed Agents API.
4. **Call it** — `bun run run-agent <your-agent>` chats with the deployed
   agent over its session event stream. This is the endpoint: any backend
   can drive it with three HTTP calls.
5. **Put it in front of users** — the included [eve](https://eve.dev) router
   (Vercel's agent framework, running Claude) exposes HTTP and Slack
   channels and treats your deployed agents as tools. `bun run dev` and
   you have a streaming endpoint.

## Quickstart

```bash
git clone <this repo> && cd mvp
bun install
cp .env.example .env   # add your ANTHROPIC_API_KEY
claude                 # prototype in managed/<name>/ … then: /make-managed-agent <name>
```

Three worked examples ship in `managed/` — each was prototyped in a real
Claude Code session and compiled with `/make-managed-agent`:

| Example | What it shows |
| --- | --- |
| `contract-reviewer` | Document processing: a client contract in, parties/dates/obligations/red-flags out. Authored skill uploads unchanged. |
| `social-reporter` | Automation over external systems: reads and writes posts through **custom tools** — the deployed agent calls back into *your* process for anything that touches your systems. (Mocked here; swap the handlers for your real API.) |
| `metrics-reporter` | Deliverable mode: CSV in, weekly report out, graded by a rubric via `user.define_outcome` — the platform's built-in grader iterates until the report passes. Its skill ships executable `scripts/`. |

## How a compiled agent runs

```
you / eve router / your backend
        │  task
        ▼
lib/claude-managed-agent.ts ── create session ──► Managed Agents API
        │                                │ agent runs in its cloud sandbox
        │◄─── SSE event stream ──────────┤
        │                                │
        │◄── requires_action ────────────┤ agent calls a custom tool
        ├─── user.custom_tool_result ───►│ handler ran in YOUR process
        │                                │
        └◄── final agent.message ────────┘
```

Custom tools are the bridge to your systems: the deployed agent pauses, your
process executes the handler from the compiled `tools.ts`, posts the result,
and the agent continues. The process calling the agent *is* the tool server —
no extra infrastructure.

## Repo layout

```
managed/<name>/        # SOURCE — your prototypes (fixtures, .claude/skills, .mcp.json)
.claude/skills/
  make-managed-agent/        # the compiler skill
agent/                 # the eve router app
  tools/<name>.ts      # COMPILED — eve tool wrapper (file name = tool name)
  compiled/<name>/     # COMPILED — instructions.md, rubric.md, skills/,
                       #   manifest.json, tools.ts (custom-tool handlers,
                       #   run in your process)
lib/claude-managed-agent.ts  # session runtime: SSE loop + custom-tool answering
scripts/               # deploy-agent.ts, run-agent.ts
```

`managed/` is source, `agent/tools/*.ts` + `agent/compiled/` are build output — but build output you
can edit. Recompiling three-way-merges your hand-edits with the new
derivation; it never clobbers them.

## And there's more

- **Remote MCP servers** in your prototype's `.mcp.json` (streamable-HTTP)
  carry over to the deployed agent's `mcp_servers`, with OAuth handled by
  platform credential vaults.
- **Dreaming** (research preview): the platform consolidates memory across
  your agent's sessions while it's idle.
- **Scheduled deployments**: run any of these agents on a cron straight from
  the API — no worker of your own.
- The eve router deploys to Vercel as-is; `agent/channels/` adds Slack and
  friends when you're ready.
