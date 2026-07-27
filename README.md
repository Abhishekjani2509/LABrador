# mvp — prototype in Claude Code, ship on the Claude Developer Platform

## tl;dr

What you build for customer 1 is wrong by customer 12 — so spend the batch on
customers, not agent frameworks. Two skills take you from "works in my Claude
Code" => "works for my customer":

- `/managed-agent-prototype {voice-mode braindump}` — an agent that does the
  job, live in your session
- `/managed-agent-deploy` => a deployed agent endpoint, in minutes not days

Clone it and have your agent set it up (`/managed-agent-setup`). Built on
Claude Managed Agents with an [eve](https://eve.dev) router in front, so
frontends, Slack, and email are config, not code.

---

The transcript where your agent finally worked *is* the spec. This starter
turns it into a deployed agent.

You prototype the way you already do: open Claude Code and iterate until the
thing works — `/managed-agent-prototype` turns a braindump about the customer
into that working session. Then `/managed-agent-deploy` compiles the session
into a **Claude Managed Agent**: a server-side agent on Anthropic's
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
`/managed-agent-deploy` compile that session into a deployed agent. "It works
locally" → shipped, in one afternoon. Then go get the next customer.

What that deletes is the detour. You closed the deal — now what, a week of
architecture? LangChain? LangGraph? Agent SDK? AI SDK? Temporal? queues? where
does state live? sandbox? tools? streaming? auth? That's an engineering
exercise, and it onboards nobody. The answers are already wired up here.
Talk to customers, ship product.

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
4. **Put it in front of users** — `bun run dev` starts the included
   [eve](https://eve.dev) router (Vercel's agent framework, running Claude)
   with your deployed agents wired in as its tools. The eve wrapper exists
   for exactly one reason: integration. eve is the best thing going at
   building *around* an agent — a streaming frontend, Slack, email, whatever
   channel your users live in — so putting a compiled agent in front of a
   customer is channel config, not a relay service you write. This repo
   doesn't rebuild the part Vercel is genuinely good at.

## Quickstart

```bash
git clone <this repo> && cd mvp
claude                 # then, in the session:
                       #   /managed-agent-setup    ← installs deps, sets up .env, checks your key
                       #   (/clear after setup — your transcript is compiler input)
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

## Why Managed Agents, and not agents inside eve?

Fair question — eve can host agents of its own. The answer is the harness:
your prototype runs on Claude Code (CLAUDE.md, skills, fixtures), and Managed
Agents run that same harness in the cloud. Keeping the dev environment (local,
Claude Code) and the deployed environment (cloud, Managed Agents) as close to
identical as possible is what makes the compile trustworthy — same
instructions, same `SKILL.md`s, so you get the same results, outcomes, and
outputs you watched work in the session. eve is the integration layer around
that runtime, not a substitute for it.

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
agent/                 # the eve router app — the integration layer (step 4)
  tools/<name>.ts      # COMPILED — eve tool wrapper (file name = tool name)
lib/claude-managed-agent.ts  # session runtime: SSE loop + custom-tool answering
scripts/               # deploy.ts, console.ts
docs/                  # frame.md (why this exists), audience.md (who it's for)
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
- The eve router deploys to Vercel as-is; add channels (Slack, email, your
  app's frontend) from eve's catalog when you want them — your agents are
  already wired in as its tools.
- **Per-caller access**: `/managed-agent-deploy` asks who may call the agent —
  everyone, one org, a named list of users — and writes the answer to
  `managed/<name>/acl.ts`. Wire your auth into the router ([eve auth
  guide](https://eve.dev/docs/guides/auth-and-route-protection)) and
  `lib/access.ts` enforces it, so each customer's session only sees their own
  agents ([how it works](https://eve.dev/docs/guides/dynamic-capabilities)).

## Next steps

- **Stream tool-call results through the router.** Today a dispatched Managed
  Agent is a long-running tool call: the router waits for it to finish, then
  folds the final answer into the reply stream. eve doesn't yet support
  streaming a tool call's results as they happen — as soon as it does, your
  users watch the specialist work instead of waiting on it.

## License

MIT — see [LICENSE](./LICENSE).
