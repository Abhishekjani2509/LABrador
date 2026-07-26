---
name: managed-agent-setup
description: One-command setup for this starter, first run through production. Run as /managed-agent-setup — it installs dependencies, gets ANTHROPIC_API_KEY into .env, and (when you're ready) removes the agents-untracked .gitignore block and wires your auth stack (Supabase, WorkOS, Clerk, better-auth, or your own) into the router so per-agent ACLs enforce. Idempotent: it does whichever phases your repo still needs.
---

# /managed-agent-setup — from fresh clone to yours

One skill, two jobs, run it any time — it checks state and does only the
phases that apply:

- **Fresh clone?** Phase 1 gets you to a working `bun run dev` in one go.
- **Repo becoming yours?** Phases 2–5 flip the starter's two deliberately
  conservative defaults: agents are untracked (`.gitignore` ignores
  `managed/*` and `agent/tools/*` except `workflow.ts` — fixtures often
  carry real customer data), and no auth is wired (every `acl.ts` says
  `{ public: true }`; a restricted ACL would hide its tool from everyone,
  because unresolved callers fail closed).

Interview first, edit second — one question at a time, each with a
recommendation and a one-line reason; never ask what the repo already
answers.

## Phase 1 — Bootstrap (fresh clone)

Skip silently whatever is already done.

1. `bun install` (bun, not npm/node — check `bun --version` first and point
   at https://bun.sh if it's missing).
2. **`.env` with `ANTHROPIC_API_KEY`.** If absent, copy `.env.example` to
   `.env` and offer the founder both paths, recommending the first:
   - *"Edit `.env` yourself (key from platform.claude.com → API keys) and
     tell me when it's in"* — recommended, because anything pasted in chat
     lands in the session transcript, and transcripts in this repo are
     compiler input;
   - or they paste it here and you write it into `.env` — fine too, just
     say the transcript caveat out loud first. Never echo the key back.
3. Verify: `bun run typecheck && bun run check`, then prove the key works
   with one free API call:
   `bun -e 'const m = await import("@/lib/claude-managed-agent.ts"); await m.makeClient().beta.environments.list(); console.log("key ok")'`
4. Tell them the next step in one line: `/managed-agent-prototype
   <describe your customer and use case>`.

Founders kicking the tires stop here. The rest is for when the repo is
theirs.

## Phase 2 — Version your agents

1. Show the founder the agents block in `.gitignore` and confirm removal.
   Remove **the whole block** — `managed/*`, `!managed/.gitkeep`,
   `agent/tools/*`, `!agent/tools/workflow.ts` — never half of it: a tracked
   wrapper importing an untracked `managed/<name>/` is a repo that
   typechecks for you and no one else.
2. **Before staging anything, sweep `managed/*/fixtures/` for real
   personal or customer data** — names, emails, account records. That data
   is why the default exists. Anything sensitive: scrub it, or keep that
   one agent untracked by re-adding its two paths as specific ignore lines.
3. Stage the newly-visible files and show the founder `git status` so what's
   about to become repo content is a decision, not a surprise.

If the founder only wants Phases 1–2 (auth can wait), stop here — that's a
fine place to be.

## Phase 3 — Auth interview

Resolve, one at a time, with a recommendation each:

1. **What do your users authenticate with?** Supabase Auth, WorkOS, Clerk,
   better-auth, a JWT you mint yourself, or nothing yet. If nothing yet:
   recommend stopping here — wiring auth before users exist is speculative
   plumbing, and ACLs can stay `{ public: true }` until then.
2. **Where does the router meet users?** Your app over HTTP, Slack, both.
   This decides where the token arrives (Authorization header, Slack
   signing) and which eve entry points need the auth hook.
3. **What's the caller id ACLs should gate on?** A user id or an org id.
   Recommend org id for B2B (one customer = one principal), user id
   otherwise. This is the string founders will put in `acl.ts` `principals`.

## Phase 4 — Wire it

Follow eve's auth guide — https://eve.dev/docs/guides/auth-and-route-protection —
so that `ctx.session.auth.current` is populated by the time `session.started`
resolvers run. The provider decides the verification step in the auth hook:

- **Supabase** — verify the access token (JWT secret or JWKS), principal is
  `sub` (user id) or an org claim you attach.
- **Clerk / WorkOS** — verify with their SDK or JWKS endpoint; both hand you
  user and org ids directly.
- **better-auth** — validate the session from the cookie/API on each request.
- **Your own JWT** — verify signature + expiry; pick one stable claim as the
  principal and resist gating on anything mutable.

Then make `resolvePrincipal` in `lib/access.ts` return the id you chose in
Phase 3 — it reads `ctx.session.auth.current?.principalId` today; adjust it
(e.g. to an org id you stamped into the session's attributes at login) rather
than scattering claim-reads across wrappers. Keep `allowed()` fail-closed
exactly as it is.

## Phase 5 — Flip ACLs and prove it

1. Walk every `managed/*/acl.ts` with the founder: which agents stay
   `{ public: true }`, which become `{ principals: ["…"] }` with real ids
   from their auth system.
2. Verify like you mean it: `bun run typecheck && bun run check`, boot the
   router (`bun run dev`), then make **two** calls — one authenticated as an
   allowed principal (sees the restricted tool), one unauthenticated or
   wrong-principal (doesn't). One call proves nothing; the pair is the test.

## Failure modes

- **The pasted key lives in the transcript.** This repo's compile step mines
  session transcripts; a key pasted in chat is in that record. Prefer the
  self-edit path; if they paste anyway, it still must never appear in any
  file except `.env` (gitignored — verify, don't assume).
- **Committing fixtures with real customer data.** The single reason the
  untracked default exists. The Phase 2 sweep is not optional, and "it's
  just test data" from a founder deserves one follow-up question, because
  fixtures built from a real customer's rows usually are that customer's
  rows.
- **Restricting an ACL before auth is wired.** Fail-closed means the tool
  vanishes for every caller, while `bun run console` — which bypasses the
  router entirely — keeps working. If the founder wants restriction but
  Phase 4 isn't done, leave `{ public: true }` and a TODO, not a live
  restriction.
- **Testing auth through `bun run console`.** It talks to the Managed Agent
  directly and proves nothing about router gating. Phase 5's paired calls
  must go through eve.
- **Removing half the ignore block.** `managed/*` gone but `agent/tools/*`
  kept (or vice versa) recreates the asymmetry this skill exists to retire:
  clones that typecheck only on the founder's machine.
- **A principal that isn't stable.** Gating on an email or display name
  breaks the day it's edited; gate on the immutable id your provider issues.
