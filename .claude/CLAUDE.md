# Building in this repo

Read `README.md` first for the four-step pipeline (prototype → compile+deploy →
call → ship) and the source/build-output boundary. This file is the part that
isn't obvious from the layout.

## The transcript is a build input — work accordingly

`/managed-agent-deploy` compiles **this session** into a deployed agent, and
Phase 2 mines the transcript for lessons, not just the task. That makes the
following true of any session you build in, `/managed-agent-prototype` runs
included. Two consequences that change how you work:

**Keep your failures in the transcript.** A snag you hit and fixed is worth more
to the compiler than a clean final answer. Don't quietly redo a broken approach —
show the break and the fix.

**Void superseded things out loud.** The compiler cannot tell stale from current,
and it reads everything. From the session that produced this repo's first agent:

- an early SKILL.md was rewritten, but the Skill tool re-injected the *superseded*
  copy verbatim into the transcript, where it read as current design;
- an `AskUserQuestion` answer ("escalate to human") survived a later scope
  correction that removed decision-making from the agent entirely — a recorded
  answer to a question that no longer applied, indistinguishable from a
  requirement.

So: when you replace an artifact or the user changes scope, say plainly in
user-visible text that the prior version is void and why. And **don't ask the
user a question about behavior that may be out of scope** — you can't retract
the answer, and the compiler will treat it as a decision.

## Where things go

`managed/<name>/` is one directory doing both jobs: it's where you prototype
*and* what gets deployed. You author `CLAUDE.md`, `.claude/skills/` and
`fixtures/`; `manifest.json`, `tools.ts`, `acl.ts`, `rubric.md` and the thin
wrapper `agent/tools/<name>.ts` are build output (hand-editable — recompiling
three-way-merges). `managed/` lives outside `agent/` on purpose: eve claims
every JS-family module under `agent/tools/**` as a tool, so `tools.ts` and
skill-bundled scripts must sit beyond eve's discovery.

**`managed/<name>/CLAUDE.md` IS the deployed agent's instructions** — uploaded
verbatim as the system prompt, edited in place by `/managed-agent-prototype` and
`/managed-agent-deploy`. There is no second copy and no write-back step; what you
read there is what runs in the cloud. Notes about *building here*
belong in this file (`.claude/CLAUDE.md`); notes about how the *deployed agent*
should behave belong in `managed/<name>/CLAUDE.md` or a SKILL.md.

## Writing skills

Authored skills upload to the Skills API unchanged, so `managed/<name>/.claude/skills/<slug>/SKILL.md`
is the deliverable, not a scratch note. Two things make one good:

- **A failure-modes section, and make it the longest one.** Procedure is cheap;
  knowing that page 1 of a search lies, or that a document's stated legal name
  won't match the registry, is what the next run actually needs.
- **Name the skill for what it does, not what it decides.** `verify-*` reads as a
  decision mandate to the compiler; `lookup-*` doesn't. Keep the agent's contract
  in the frontmatter description, including what it explicitly does *not* do.

Pair a skill with `fixtures/` — one row per distinct failure mode, with a column
saying why that case is in the set. Fixtures are how a recompile knows the edge
cases were real.

## Discipline for agents that read the web

Learned the hard way in an early prototype here; applies to any agent you
prototype that scrapes or researches.

- **Sub-model extractors infer and present it as fact.** A WebFetch of a privacy
  policy reported "incorporated in Delaware, as indicated by the address" — an
  inference dressed as a finding. Demand verbatim `field: value` output and
  reject claims not traceable to a labeled field or a literal quote.
- **Never conclude "not found" from page 1.** A record that looked absent —
  and got written up as a coverage gap — was on page 3 of the same paginated
  search. Sweep, then report totals.
- **Corroborate identity before trusting a fuzzy match.** Search will hand you a
  plausible stranger with a near-miss name.

## Commands

```
/managed-agent-prototype <braindump>   # interview + scaffold managed/<name>/, then
                                       #   exercise the agent's job on the fixtures
/managed-agent-deploy <name>           # compile this session, deploy, smoke-test
```

```bash
bun install
bun run deploy <name>      # upload skills, create/version the Managed Agent
bun run console <name>     # open in Console; -- --once "…" runs headless
bun run typecheck          # tsc --noEmit
bun run check              # ultracite (biome) — bun run fix to autofix
```

Bun, not npm/node. `ANTHROPIC_API_KEY` in `.env` (see `.env.example`). There is
no test suite — typecheck + check is the verification story. `biome.jsonc`
prefers `type` over `interface` and waives `noUnnecessaryConditions` because
Biome can't resolve zod's `z.infer` mapped types.

## Gotchas

**The agent's own skills aren't loadable while you prototype.** The session's cwd
is the repo root, so skills under `managed/<name>/.claude/skills/` are outside
what the Skill tool discovers — you can't invoke one to test it. Read the
SKILL.md and follow it by hand instead; `/managed-agent-deploy`'s smoke test is
what proves real skill loading against the deployed agent. Same split for MCP:
the root `.mcp.json` is the live one in-session, while
`managed/<name>/.mcp.json` is an optional per-agent record that deploy reads.

**Re-read a SKILL.md after editing it.** The skill listing and the Skill tool's
loaded copy can lag the file on disk, and this session saw on-disk content
regress once between a successful edit and the next read — cause never
established. Verify content before building on it.

**Assume parallel sessions in this checkout.** Stage only hunks you authored;
don't run destructive git on paths you don't own.
