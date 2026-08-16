---
name: managed-agent-deploy
description: Compile the current prototyping session into a deployed Claude Managed Agent. Run as /managed-agent-deploy <name> from the session where the prototype in managed/<name>/ actually worked — the transcript is the primary compiler input.
---

# /managed-agent-deploy <name> — the compiler

You are about to turn a working prototype into a deployed agent. The founder
prototyped in `managed/<name>/` in _this_ session (usually via
`/managed-agent-prototype`); the transcript above — what was tried, what broke,
what fixed it, what finally worked — is your primary source. Files are
secondary evidence. You are the compiler: the output is the wrapper
`agent/tools/<name>.ts` plus the build artifacts written back into
`managed/<name>/` (manifest.json, tools.ts, acl.ts, rubric.md), and a live
Managed Agent.

Work through the four phases in order. **Do not emit any artifact file while
open questions remain** — mining and interviewing complete first, always.

## Phase 1 — Read the source

Explore before you ask anything. From the repo root:

- `managed/<name>/` — every file: fixtures, scratch outputs, scripts, notes.
- MCP servers — `managed/<name>/.mcp.json` if present; otherwise whichever
  servers from the root `.mcp.json` this session actually used for the
  prototype. Each **remote streamable-HTTP** server becomes an `mcp_servers`
  entry (stdio servers cannot deploy — flag them to the founder as the one
  thing that won't carry over). A server the session reached via interactive
  OAuth needs a headless credential to deploy: provision an API key, store it
  as a vault credential keyed by the MCP URL (`static_bearer`), and put the
  vault ID in the manifest's `vault_ids`. Vault provisioning is a manual step
  (Console or API) — nothing in `scripts/` automates it; the runtime only
  attaches `vault_ids` at session create. Each carried-over server also needs
  a permission mode — asked in Phase 3.
- `managed/<name>/.claude/skills/*/SKILL.md` — authored skills; these upload
  to the Skills API **unchanged, straight from where they sit**. No copying.
- `managed/<name>/CLAUDE.md` — the agent's instructions file; it deploys
  verbatim as the system prompt. On a recompile, a hash mismatch against
  `compiled_hashes` means hand-edits since the last compile: treat the
  on-disk file as the new baseline and integrate this session's lessons
  around it (merge rules in Phase 4).
- `managed/<name>/manifest.json` — if it already exists, this is a
  **recompile**: read `compiled_hashes` now and follow the merge rules in
  Phase 4.

## Phase 2 — Mine the transcript

Reread the session and extract, with the discipline that _lessons matter more
than the task statement_:

1. **The task** — what the agent is actually for, in the founder's words.
2. **Lessons** — every snag hit and how it was resolved (wrong format, edge
   case, misread input, retried approach). These become explicit guidance in
   `CLAUDE.md`. An instructions file that only restates the task has thrown
   away the most valuable part of the transcript.
3. **Recurring procedures** — multi-step routines the session repeated or
   refined → derived skills (a `.claude/skills/<slug>/SKILL.md` bundle),
   unless an authored skill already covers them.
4. **External actions** — anything the prototype did via local scripts, shell
   commands, or ad-hoc code that a deployed agent cannot do in its sandbox
   (calling the founder's systems, reading their data stores, posting to
   their services) → custom tool specs for `tools.ts`: name, description,
   JSON schema input, and a handler faithful to what the session actually ran.
5. **Quality bar** — what "good output" meant in this session (the founder's
   corrections are the best evidence), as concrete, gradeable criteria ("the
   summary lists every payment deadline with its date", not "the output is
   thorough"). Include the founder's _interpretive_ bar too — if they wanted
   a "should I panic?" verdict, an output that only quantifies without
   concluding fails their real standard. Where it lands depends on Phase 3:
   founders who define an outcome get it as `rubric.md`; otherwise it becomes
   operating rules in `CLAUDE.md` and no rubric file is emitted.

Draft all five privately. Where the transcript is ambiguous, note the open
question for Phase 3 instead of guessing.

## Phase 3 — Interview the founder

Interview until **all** ambiguity is resolved; while any open question
remains, building is not allowed. Rules:

- **One question at a time.** Never a batch, never a form.
- **Every question ships with a recommendation** and a one-line reason, so
  the founder can just say "yes". Example: _"Invocation mode: I recommend
  `message` — your session was conversational Q&A, not a graded deliverable.
  OK?"_
- **Never ask what you can find out yourself.** If the transcript or files
  answer it, don't ask it. Interview questions are for genuine judgment
  calls only. Expect roughly 3–5 questions, not 10.
- **Simplicity first.** Recommend the smallest configuration that matches
  the session; the founder can always recompile richer later.

Always resolve (asking only where the evidence is genuinely ambiguous):

| Decision                          | Default recommendation                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent name + one-line description | dir name; description from the task                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Model                             | `claude-sonnet-5` (upgrade only if the session needed deep reasoning). Confirm it as its own one-line question — never bundled into the keep/drop list                                                                                                                                                                                                                                                                                                         |
| Invocation mode                   | **Always ask this one directly: "do you want to define an outcome — a rubric a machine grades every run against — or keep it conversational?"** Recommend `message` by default; recommend `outcome` only when the founder wants a _machine_ to grade iterations. The discriminator is **"do they want to stop hand-checking?"**, not "did they hand-check this session?" — corrections the founder wants codified into a rubric so it's enforced automatically every future run point to `outcome` (recurring, gradeable deliverable); corrections made because they want to keep eyeballing raw output each run point to `message`. The answer decides whether `rubric.md` exists at all |
| Session policy                    | `reuse` (conversational continuity); `fresh` for stateless one-shot tasks                                                                                                                                                                                                                                                                                                                                                                                      |
| Memory                            | **Always ask on a first deploy: "should this agent remember across sessions — a persistent memory store it reads and writes between runs?"** Recommend yes when the agent serves an ongoing relationship (a customer's preferences, corrections, and running context compound run over run — in this starter's one-agent-per-customer model that means **one store per customer**); recommend no for stateless one-shot jobs. Yes becomes a `memory` block in the manifest: deploy provisions the store once (`deployment.memory_store_id`), every session attaches it, and the agent reads/writes it under `/mnt/memory/<name>/` with its ordinary file tools — no new API for the agent to learn. Write `description` for the agent (it lands in the system prompt as what the store holds). Access defaults `read_write`; recommend `read_only` when the agent processes untrusted input (fetched web pages, third-party text) — a prompt injection can write itself into a `read_write` store and be read back as trusted memory next session. When yes, also add a short "Memory" section to `CLAUDE.md`: what's worth recording (stable facts about the customer, corrections, preferences) and what isn't (one-off task data — a store caps at 2,000 memories of ≤100 kB, many small files beat few big ones). On a recompile, keep the existing store unless the founder raises it |
| **Access**                        | **Always ask on a first deploy: "who should be able to call this agent through the router — everyone, a specific org id, or specific user ids?"** Recommend everyone (`{ public: true }`) until the founder has wired auth. The answer becomes `managed/<name>/acl.ts`. When they restrict, say plainly what the code does today: principals resolve from `ctx.session.auth`, nothing populates that until auth is wired into the eve router, and unresolved callers **fail closed** — so a restricted acl.ts hides the tool from *every* caller (HTTP, Slack, all of them) until auth exists. Restricting before wiring auth means shipping an agent nobody can reach through the router; `bun run console` still works, which makes the gap easy to miss. Wiring auth is `/managed-agent-setup`'s job — point the founder there when they want restriction for real. On a recompile, keep the existing acl.ts unless the founder raises it |
| MCP permission mode               | **Ask per carried-over MCP server: `always_allow` or `always_ask`?** MCP tool calls default to a permission "ask" that parks the session on a human confirmation — which a headless caller can never answer (the runtime denies it with an explanatory message rather than deadlocking). So `always_ask` effectively disables the server for deployed runs; recommend `always_allow` when the founder kept the server on purpose, and say plainly what that means (the agent uses that service unattended, on the founder's account/credits). The answer goes on the server's manifest entry as `"permission"` |
| Keep/drop                         | your mined list of skills + custom tools, shown as a short list for confirmation                                                                                                                                                                                                                                                                                                                                                                               |

## Phase 4 — Emit, deploy, verify

Only now touch files. Everything the compile produces lands in
`managed/<name>/` next to the source it came from, plus one thin wrapper
module. `managed/` sits outside `agent/` on purpose: eve's discovery requires
every `.ts`/`.js`-family module under `agent/tools/**` to _be_ a tool (a
non-tool module fails the build), so `tools.ts`, `acl.ts`, and skill-bundled
scripts live beyond eve's reach, and only the wrapper `agent/tools/<name>.ts`
is authored where eve looks.

| File                                          | Content                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `managed/<name>/CLAUDE.md`                    | **Edited in place** — this one file is both the prototype's instructions and the deployed system prompt; there is no copy to sync. Integrate the Phase 2 **lessons** as operating rules around what's already there: role, task, rules, written for a fresh agent with none of this session's context. Hard structural constraints (fixed sections, orderings) go in as a **literal fill-in template** of the output, not prose prohibitions — models follow skeletons more reliably than "don't" rules.                                                                                                          |
| `managed/<name>/rubric.md`                    | **`outcome` mode only** — emitted if and only if the founder said yes to defining an outcome in Phase 3; it is sent with `user.define_outcome` at runtime. In `message` mode do NOT emit this file: the Phase 2 quality bar goes into `CLAUDE.md` as operating rules instead (a rubric nothing grades against is dead documentation).                                                                                                                                                                                                                                                                              |
| `managed/<name>/.claude/skills/<slug>/…`      | Authored skills **stay exactly where they are** — deploy uploads them from here unchanged. Derived skills (Phase 2 #3) are written here too. Each dir must contain `SKILL.md` (with `name` + `description` frontmatter), and nothing but skill dirs may live under `.claude/skills/` — deploy zips every subdirectory.                                                                                                                                                                                                                                                                                             |
| `managed/<name>/manifest.json`                | Schema below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `managed/<name>/tools.ts`                     | Custom tool handlers (omit when there are none). Template below. When the prototype has runnable local scripts, handlers **shell out to those exact scripts** (repo-root-relative paths) — never reimplement their logic in TypeScript; a reimplementation is a second, untested copy. And when the deployed sandbox lacks an affordance the skill's prose assumes (reading a local file, running a local script, hitting the founder's network), **add a thin custom tool that provides it** and bridge the skill's language to that tool in `CLAUDE.md` — don't leave the gap for the smoke test to trip on. |
| `managed/<name>/acl.ts`                       | The Phase 3 access answer. Template below; the wrapper imports it and `lib/access.ts` enforces it once auth is wired.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `agent/tools/<name>.ts`                       | eve tool wrapper — this file's name is the router-facing tool name. Template below; substitute the name, and include the `tools` import and its `streamTask` argument **only when the agent has custom tools** — omit both otherwise (a bare `tools` reference with no import fails typecheck).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

Then append one dispatch entry to `agent/instructions.md` under
`## Specialists`: tool name, one line on when to dispatch to it.

**Recompile (Claude-merge).** If `managed/<name>/manifest.json` existed
before this run: for every file, compare its current hash against
`compiled_hashes` in the old manifest. A mismatch means the file changed
since the last compile. **Never clobber those changes.** Three-way merge:
keep them, integrate your new derivation around them, and say in one line
per merged file what you kept from each side. Files with matching hashes
are yours to regenerate freely.

**Attribute before you claim.** Never assert provenance you can't verify.
Categorize each changed region as: (a) an edit this session directed, (b)
unchanged prior baseline, or (c) **content you did not write and this
session did not direct — a founder hand-edit**. Surface bucket (c)
explicitly ("I found a `## House style` section I didn't generate —
preserving it") instead of folding it into "your edits from this session".
Every preserved hand-edit that encodes a checkable behavior **must** get a
matching enforcement home in the same compile — a `rubric.md` criterion in
`outcome` mode, an explicit operating rule in `CLAUDE.md` in `message`
mode. A silently preserved guard with nothing restating it is a rule the
deployed agent can drop unnoticed. And any rubric criterion asserting a concrete format or precision
(decimal places, string shape, rounding) must be **checked against the
bundled script's actual fixture output before deploy** — if they diverge,
fix one side; never ship a rubric whose letter the deployed script can't
meet. For a hand-edited item in an ordered list, the item's TEXT is what
must survive byte-for-byte; repositioning/renumbering for coherence is fine,
but call the move out in the per-file merge line ("kept the founder's
Health-verdict criterion verbatim, moved #9 → #4").

**Hashes.** After writing, record in `manifest.json.compiled_hashes` the
sha256 of every emitted file (`shasum -a 256`), keyed by path relative to
the repo root (e.g. `managed/<name>/CLAUDE.md`, `managed/<name>/tools.ts`,
`agent/tools/<name>.ts`). This is the merge base for the next recompile.

**Deploy + verify.** Run `bun run deploy <name>` and show the founder
the output (skill IDs, agent ID + version). Then prove it works with the
**largest realistic input the session actually used** — e.g. the full fixture
file from `managed/<name>/fixtures/`, not a hand-typed one-liner. Run the
smoke test in the **foreground (blocking)** — never as a backgrounded job.
Do not end your turn until you have read a terminal verdict from its output
(`grader: satisfied` / final reply, or a failure); a turn that ends while
the smoke test is still running has verified nothing:
`bun run console <name> -- --once "$(cat managed/<name>/fixtures/<file>)"`.
A smoke test that can't reproduce the founder's real input shape has not
proven anything. Prefer the _same_ fixture and parameters as the session's
best output, so the founder can A/B the deployed reply against what they
already approved. Confirm the reply meets the rubric, and re-run the smoke
test after any post-verify change to config or runtime code. When the
output has hard structural invariants (fixed section count/order, mandated
first heading), **assert them mechanically** on the smoke output (a grep is
enough) — don't rely on noticing violations by eye.

On a **recompile**, design the smoke test to cover both sides in one run:
exercise the new capability AND re-confirm the pre-existing best-output path
still holds (e.g. one request that triggers the new tool _and_ produces the
full report the founder already approved). An update that only tests the new
thing can regress the old thing silently.

When the agent has custom tools, the smoke test must show the round-trip at
the event level — the `· custom tool: <name> {…}` trace lines from
`console`, plus the tool's observable side effect (e.g. the queued row in
the outbox file) — not a prose claim that tools "were used".

**Outcome mode (design contract — violating either invariant wastes a full
debugging cycle at runtime):**

- The grader inspects **only sandbox files, never the reply text**. Every
  `rubric.md` criterion must be verifiable from the deliverable file (plus
  anything the grader can recompute in the sandbox, e.g. by re-running a
  bundled skill script). A criterion like "the full report appears in the
  reply" is unfalsifiable and dooms every run to `max_iterations_reached`.
- `CLAUDE.md` must pin **one canonical sandbox output path** (e.g.
  `/mnt/session/outputs/<name>.md`) that the agent writes and the rubric
  references — and must also tell the agent to paste the full deliverable
  into its final reply: sandbox-written files are not retrievable through
  the Files API afterward, so the reply is the only channel back.
- The outcome-mode smoke test needs event-level proof, same as custom tools:
  the trace must show `grader: satisfied` AND the final reply carrying the
  real deliverable (not a short wrap-up) — those are independent facts.
- **The input side has no separate channel.** The task string (what `--once`
  sends) becomes the *outcome description* in `user.define_outcome` — so the
  agent's input must arrive inline in that description or through a custom
  tool it can call. Design `CLAUDE.md`, the rubric, and the smoke test around
  wherever the real input actually lives; piping a fixture file into `--once`
  makes the fixture the outcome description, which is only right when you
  mean it to be.

**Runtime fixes.** If this session fixed shared runtime code (`lib/`,
`scripts/`) along the way, record each fix as a one-line entry in
`manifest.json.runtime_notes` — the artifact dir alone won't show a future
reader that the bug class was hit and solved.

### manifest.json schema

```json
{
  "name": "<name>",
  "description": "<one line>",
  "model": "claude-sonnet-5",
  "invocation": "message | outcome",
  "session_policy": "reuse | fresh",
  "max_iterations": 3,
  "mcp_servers": [{ "type": "url", "name": "<name>", "url": "<https url>", "permission": "always_allow | always_ask" }],
  "memory": { "description": "<what the store holds — shown to the agent>", "instructions": "<optional per-session guidance>", "access": "read_write | read_only" },
  "vault_ids": ["<vault id — only when an MCP credential lives in a vault>"],
  "runtime_notes": ["<one line per shared-runtime fix made during this session>"],
  "compiled_hashes": { "<relative path>": "<sha256>" }
}
```

(`deployment` is added by `deploy.ts`; never write it by hand — including
`deployment.memory_store_id`, which deploy fills when `memory` is present.
`memory` is optional: omit the whole block when the founder declined memory.
`max_iterations` applies to `outcome` mode only, max 20; omit it in `message`
mode.)

### managed/<name>/acl.ts template

```ts
import type { ACL } from "@/lib/access.ts";

// Who may call this agent through the router. Enforcement starts once auth
// is wired into the eve router (see lib/access.ts).
export const acl: ACL = { public: true };
// Restricted instead:
// export const acl: ACL = { principals: ["org_acme"] };
```

### agent/tools/<name>.ts template

The default export is a `defineDynamic` resolver, not a bare `defineTool`, so
the per-caller visibility gating in `lib/access.ts` applies, driven by this
agent's own `acl.ts`. Keep `execute` inline inside `defineTool`;
`execute: importedFn` breaks on durable replay.

`execute` is an async *generator*: eve publishes every non-final `yield` as an
`action.partial` stream event (last-write-wins snapshot, visible to channels
and clients but never to the model), and only the final yield becomes the tool
result. `streamTask` yields `TaskProgress` snapshots as the managed agent
works and returns the `RunTaskResult`, so the wrapper forwards progress and
finishes by yielding the final text.

```ts
import { defineDynamic, defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { allowed } from "@/lib/access.ts";
import { acl } from "@/managed/<name>/acl.ts";
import { loadManagedAgent, streamTask } from "@/lib/claude-managed-agent.ts";
// Only when the agent has custom tools — static import so eve's bundler sees it:
// import { tools } from "@/managed/<name>/tools.ts";

const sessionIdState = defineState<string | undefined>("<name>-session", () => undefined);

export default defineDynamic({
  events: {
    "session.started": (_event, ctx) =>
      allowed(ctx, acl)
        ? defineTool({
            description:
              "<agent description>. Provide a complete, self-contained task; the " +
              "specialist runs remotely, streams progress, and returns its final answer.",
            inputSchema: {
              type: "object",
              properties: {
                task: { type: "string", description: "The full task for the specialist." },
              },
              required: ["task"],
            },
            async *execute(input) {
              // skipToolImport: tools come from the static import above (or none);
              // dynamic import() inside eve's bundled runtime is not reliable.
              const { manifest, rubric } = await loadManagedAgent("<name>", { skipToolImport: true });
              const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
              // `tools` only for tool-bearing agents (the static import above); omit otherwise.
              const run = streamTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
              let result;
              for (;;) {
                // biome-ignore lint/performance/noAwaitInLoops: draining a generator is inherently sequential
                const next = await run.next();
                if (next.done) {
                  result = next.value;
                  break;
                }
                // Preliminary snapshot: replaced by each later yield, never sent to the model.
                yield { status: "running", ...next.value };
              }
              if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
              // Final yield = the tool result the model sees.
              yield result.text;
            },
          })
        : null,
  },
});
```

### managed/<name>/tools.ts template

```ts
import type { CustomToolSpec } from "@/lib/claude-managed-agent.ts";

export const tools: CustomToolSpec[] = [
  {
    name: "<verb_noun>",
    description: "<3–4 sentences: what it does, when to use it, caveats>",
    input_schema: {
      type: "object",
      properties: {
        /* … */
      },
      required: [
        /* … */
      ],
    },
    async handler(input) {
      // Runs in *this* process when the deployed agent calls the tool.
      return JSON.stringify({
        /* … */
      });
    },
  },
];
```
