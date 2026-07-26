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

## Why it's shaped like this

Revenue is king and distribution is the moat. Every day of the batch counts,
and it counts in customers onboarded — not in architecture. Whatever you
engineer against customer one is already wrong; the real product shows up
somewhere around customer 10, 20, 30.

So treat every customer as forward-deployed engineering. Sit with them, get the
agent working on *their* use case in a single Claude Code session, then let
`/make-managed-agent` compile that session into a deployed agent. Works on my
machine → production, hands-free, in about twenty minutes. Then go get the next
customer.

What that deletes is the detour. Should I use LangChain? LangGraph? the Agent
SDK? Do I need eve? Where does state live? Who hosts the sandbox? That's a week
of engineering exercise and it onboards nobody. The answers are already wired
up here, so you don't have to have the argument.

The story, end to end:

1. **Prototype** — `claude` in this repo, work in `prototypes/<your-agent>/`.
   Drop in fixtures, write skills, hit snags, fix them.
2. **Compile** — `/make-managed-agent <your-agent>`. Claude mines the transcript
   (including the debugging lessons), asks you a few questions — each with a
   recommended answer — and emits a complete artifact: instructions, skills,
   custom-tool handlers, plus a grading rubric if you opt into defining an
   outcome.
3. **Deploy** — `bun run deploy <your-agent>` uploads the skills and
   creates (or versions) the agent on the Managed Agents API.
4. **Call it** — `bun run console <your-agent>` opens the deployed agent in
   the Claude Console's visual session runner (`-- --once "…"` runs one task
   headless — that path also answers custom tools, which the web Console
   can't). This is the endpoint: any backend can drive it with three HTTP
   calls.
5. **Put it in front of users** — the included [eve](https://eve.dev) router
   (Vercel's agent framework, running Claude) exposes HTTP and Slack
   channels and treats your deployed agents as tools. `bun run dev` and
   you have a streaming endpoint.

## Quickstart

```bash
git clone <this repo> && cd mvp
bun install
cp .env.example .env   # add your ANTHROPIC_API_KEY
bun run prototype customer-1-agent   # create/enter prototypes/customer-1-agent + auto-mode claude there … then: /make-managed-agent customer-1-agent
```

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
prototypes/<name>/     # SOURCE — your prototypes (fixtures, .claude/skills, .mcp.json)
.claude/skills/
  make-managed-agent/        # the compiler skill
agent/                 # the eve router app
  tools/<name>.ts      # COMPILED — eve tool wrapper (file name = tool name)
  compiled/<name>/     # COMPILED — instructions.md, skills/, manifest.json,
                       #   tools.ts (custom-tool handlers, run in your
                       #   process), rubric.md if you defined an outcome
lib/claude-managed-agent.ts  # session runtime: SSE loop + custom-tool answering
scripts/               # prototype.sh, deploy.ts, console.ts
```

`prototypes/` is source, `agent/tools/*.ts` + `agent/compiled/` are build output — but build output you
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
