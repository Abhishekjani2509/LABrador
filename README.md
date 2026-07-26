# mvp — prototype in Claude Code, ship on the Claude Developer Platform

The transcript where your agent finally worked *is* the spec. This starter
turns it into a deployed agent.

You prototype the way you already do: open Claude Code, iterate until the
thing works — `/managed-agent-prototype` takes a braindump about the customer
and sets that session up for you. Then run one more skill —
`/managed-agent-deploy` — and Claude compiles that
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
`/managed-agent-deploy` compile that session into a deployed agent. Works on my
machine → production, hands-free, in about twenty minutes. Then go get the next
customer.

What that deletes is the detour. Should I use LangChain? LangGraph? the Agent
SDK? Do I need eve? Where does state live? Who hosts the sandbox? That's a week
of engineering exercise and it onboards nobody. The answers are already wired
up here, so you don't have to have the argument.

The story, end to end:

1. **Prototype** — `claude` in this repo, then
   `/managed-agent-prototype <braindump>`. Type or dictate the whole picture —
   the customer, the job, what goes in, what should come out, what to test
   against. The skill asks
   one question at a time (each with a recommended answer), scaffolds
   `managed/<your-agent>/` fixtures-first, and then does the agent's job
   right there in the session against those fixtures until it works. Snags
   included — they're the good part.
2. **Compile & deploy** — `/managed-agent-deploy <your-agent>`. Claude mines the
   transcript (including the debugging lessons), asks you a few questions — each
   with a recommended answer — and emits the rest of the artifact: manifest,
   custom-tool handlers, the access list, the router wrapper, plus a grading
   rubric if you opt into defining an outcome. Then it uploads the skills,
   creates (or versions) the agent on the Managed Agents API, and doesn't hand
   back until a smoke test against the *deployed* agent passes. (`bun run deploy
   <your-agent>` re-runs that upload on its own any time; it's idempotent.)
3. **Call it** — `bun run console <your-agent>` opens the deployed agent in
   the Claude Console's visual session runner (`-- --once "…"` runs one task
   headless — that path also answers custom tools, which the web Console
   can't). This is the endpoint: any backend can drive it with three HTTP
   calls.
4. **Put it in front of users** — the included [eve](https://eve.dev) router
   (Vercel's agent framework, running Claude) treats your deployed agents
   as tools. `bun run dev` and you have a streaming HTTP endpoint; eve's
   channels are the integration layer for a frontend, Slack, email —
   the part Vercel is genuinely good at, so this repo doesn't rebuild it.

## Quickstart

```bash
git clone <this repo> && cd mvp
claude                 # then, in the session:
                       #   /managed-agent-setup    ← installs deps, sets up .env, checks your key
                       #   /managed-agent-prototype what customer-1 needs, in your own words …
                       #   /managed-agent-deploy customer-1-agent   ← once it works
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
process executes the handler from `managed/<name>/tools.ts`, posts the result,
and the agent continues. The process calling the agent *is* the tool server —
no extra infrastructure.

## Repo layout

```
managed/<name>/        # one dir per agent — the workspace you prototype in
                       #   AND the thing that gets deployed
                       #   (empty until your first /managed-agent-prototype)
  CLAUDE.md            #   SOURCE — the agent's instructions, deployed verbatim
  .claude/skills/      #   SOURCE — uploaded to the Skills API straight from here
  fixtures/            #   SOURCE — what you test against; never uploaded
  manifest.json        #   COMPILED — the deployed agent's config
  tools.ts             #   COMPILED — custom-tool handlers, run in your process
  acl.ts               #   COMPILED — who may call this agent through the router
  rubric.md            #   COMPILED — only if you defined an outcome
.claude/skills/
  managed-agent-prototype/   # braindump → an agent that works in-session
  managed-agent-deploy/      # that session → a deployed agent
  managed-agent-setup/       # make the repo yours: version agents, wire auth
agent/                 # the eve router app
  tools/<name>.ts      # COMPILED — eve tool wrapper (file name = tool name)
lib/claude-managed-agent.ts  # session runtime: SSE loop + custom-tool answering
scripts/               # deploy.ts, console.ts
```

One directory, both roles: you write the instructions, skills and fixtures;
the four `COMPILED` files plus `agent/tools/<name>.ts` are build output — but
build output you can edit. Recompiling three-way-merges your hand-edits with
the new derivation; it never clobbers them.

Agents are untracked by default — fixtures often carry real customer data —
so `git status` stays quiet as you build. When the repo becomes yours, run
`/managed-agent-setup`: it removes that `.gitignore` block so your agents
version, and walks you through wiring your auth (Supabase, WorkOS, Clerk,
better-auth, your own JWT) into the router so per-agent ACLs enforce.

## And there's more

- **Remote MCP servers** (streamable-HTTP) carry over to the deployed agent's
  `mcp_servers`, with OAuth handled by platform credential vaults. You
  prototype against a repo-root `.mcp.json` you add; a `managed/<name>/.mcp.json`
  is for when one agent should deploy with a set of its own.
- **Dreaming** (research preview): the platform consolidates memory across
  your agent's sessions while it's idle — comes with the platform, nothing to
  wire here.
- **Scheduled deployments**: run any of these agents on a cron straight from
  the API — no worker of your own, and nothing in this repo to set up.
- The eve router deploys to Vercel as-is; when you want this in front of
  users — your app's frontend, Slack, email — eve's channels are built for
  exactly that, with your compiled agents already wired in as tools.
- **Per-caller access**: `/managed-agent-deploy` asks who may call the agent —
  everyone, one org, a named list of users — and writes the answer to
  `managed/<name>/acl.ts`. Wire your auth into the router ([eve auth
  guide](https://eve.dev/docs/guides/auth-and-route-protection)) and
  `lib/access.ts` enforces it, so each customer's session only sees their own
  agents ([how it works](https://eve.dev/docs/guides/dynamic-capabilities)).
