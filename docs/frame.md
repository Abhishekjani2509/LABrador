# Claude Agent Starter — Frame

Why this repo exists: the problem it removes and the outcome it's aimed at.
Companion to `audience.md` (who it's written for).

## Source

The user story the repo was built backwards from (shaping session, 2026-07-21):

> 1. "I have an idea for what an agent can do, I want to see if it can do it" => do this in claude code
> 2. "Okay I went through it, and I had to debug something / configure something (eg doing an mcp, creating a tool)"
> 3. "Alright now in my current transcript this works great, I wonder, how can I package this and make this repeatable?"
> 4. "Ah, I know, I can use the /make-managed [...] skill to turn this into a Claude Managed agent [...]"
> 5. "Wow, yay, it works! I have an endpoint that now I can integrate into my app"

> What if the starter repo had 1 eve agent at the root [...] and we gave it
> "tools" that were actually these claude managed agents that we were making!

(`/make-managed` shipped as `/managed-agent-deploy`, with
`/managed-agent-prototype` in front of it.)

## Problem

YC founders pick their AI platform in week one, anchored on whichever credit
offer has the biggest headline number. During the batch revenue is king and
distribution is the moat: every day counts, and it counts in customers
onboarded. But the batch's default move is to spend that week on an engineering
exercise instead — LangChain or LangGraph or the Agent SDK, where state lives,
who hosts the sandbox — and whatever gets engineered against customer one is
wrong anyway; the real product shows up around customer 10, 20, 30.

Founders can prototype an agent for a specific customer extremely fast in
Claude Code, but there is no story for turning that working session into a
deployed, repeatable, integrable agent — the transcript where it finally worked
is a dead end. Separately, Claude Managed Agents has no last-mile story: no
Slack connector, no frontend SDK, just webhooks and roll-your-own relays.

## Outcome

A starter repo + a two-skill flow — `/managed-agent-prototype` to get it
working, `/managed-agent-deploy` to ship it — that turns each customer into
forward-deployed engineering: get the agent working on *their* use case in one
Claude Code session, compile that session into a deployed Managed Agent behind
a streaming eve router, works-on-my-machine to production in ~20 minutes, then
go get the next customer. Positions Claude as the best platform to **prototype
and deploy new AI agents** — and deletes the platform-architecture week
entirely.
