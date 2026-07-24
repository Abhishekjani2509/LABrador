---
name: make-managed-agent
description: Compile the current prototyping session into a deployed Claude Managed Agent. Run as /make-managed-agent <name> from the session where the prototype in prototypes/<name>/ actually worked — the transcript is the primary compiler input.
---

# /make-managed-agent <name> — the compiler

You are about to turn a working prototype into a deployed agent. The founder
prototyped in `prototypes/<name>/` in _this_ session; the transcript above — what
was tried, what broke, what fixed it, what finally worked — is your primary
source. Files are secondary evidence. You are the compiler: the output is a
complete artifact dir at `agent/compiled/<name>/` plus a live Managed Agent.

Work through the four phases in order. **Do not emit any artifact file while
open questions remain** — mining and interviewing complete first, always.

## Phase 1 — Read the source

Explore before you ask anything. From the repo root:

- `prototypes/<name>/` — every file: fixtures, scratch outputs, scripts, notes.
- `prototypes/<name>/.mcp.json` — if present, each **remote streamable-HTTP**
  server becomes an `mcp_servers` entry (stdio servers cannot deploy — flag
  them to the founder as the one thing that won't carry over).
- `prototypes/<name>/.claude/skills/*/SKILL.md` — authored skills; these upload
  to the Skills API **unchanged**. Copy them into the artifact as-is.
- `prototypes/<name>/CLAUDE.md` — if present, treat as instructions material.
- `agent/compiled/<name>/` — if it already exists, this is a **recompile**: read
  `manifest.json` `compiled_hashes` now and follow the merge rules in Phase 4.

## Phase 2 — Mine the transcript

Reread the session and extract, with the discipline that _lessons matter more
than the task statement_:

1. **The task** — what the agent is actually for, in the founder's words.
2. **Lessons** — every snag hit and how it was resolved (wrong format, edge
   case, misread input, retried approach). These become explicit guidance in
   `instructions.md`. An instructions file that only restates the task has
   thrown away the most valuable part of the transcript.
3. **Recurring procedures** — multi-step routines the session repeated or
   refined → derived skills (a `skills/<slug>/SKILL.md` bundle), unless an
   authored skill already covers them.
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
   operating rules in `instructions.md` and no rubric file is emitted.

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
  calls only. Expect roughly 2–4 questions, not 10.
- **Simplicity first.** Recommend the smallest configuration that matches
  the session; the founder can always recompile richer later.

Always resolve (asking only where the evidence is genuinely ambiguous):

| Decision                          | Default recommendation                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent name + one-line description | dir name; description from the task                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Model                             | `claude-sonnet-5` (upgrade only if the session needed deep reasoning). Confirm it as its own one-line question — never bundled into the keep/drop list                                                                                                                                                                                                                                                                                                         |
| Invocation mode                   | **Always ask this one directly: "do you want to define an outcome — a rubric a machine grades every run against — or keep it conversational?"** Recommend `message` by default; recommend `outcome` only when the founder wants a _machine_ to grade iterations. The discriminator is **"do they want to stop hand-checking?"**, not "did they hand-check this session?" — corrections the founder wants codified into a rubric so it's enforced automatically every future run point to `outcome` (recurring, gradeable deliverable); corrections made because they want to keep eyeballing raw output each run point to `message`. The answer decides whether `rubric.md` exists at all |
| Session policy                    | `reuse` (conversational continuity); `fresh` for stateless one-shot tasks                                                                                                                                                                                                                                                                                                                                                                                      |
| Keep/drop                         | your mined list of skills + custom tools, shown as a short list for confirmation                                                                                                                                                                                                                                                                                                                                                                               |

## Phase 4 — Emit, deploy, verify

Only now touch files. The compiled artifact spans three paths (eve requires
every module under `agent/tools/**` to _be_ a tool, so handlers and the
wrapper sit exactly where eve expects them):

| File                                    | Content                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `agent/compiled/<name>/instructions.md` | The agent's system prompt: role, task, and the **lessons** from Phase 2 as operating rules. Written for a fresh agent with none of this session's context. Hard structural constraints (fixed sections, orderings) go in as a **literal fill-in template** of the output, not prose prohibitions — models follow skeletons more reliably than "don't" rules.                                                                                                                                                                                                                                                       |
| `agent/compiled/<name>/rubric.md`       | **`outcome` mode only** — emitted if and only if the founder said yes to defining an outcome in Phase 3; it is sent with `user.define_outcome` at runtime. In `message` mode do NOT emit this file: the Phase 2 quality bar goes into `instructions.md` as operating rules instead (a rubric nothing grades against is dead documentation).                                                                                                                                                                                                                                                                                                                                               |
| `agent/compiled/<name>/skills/<slug>/…` | Authored skills copied **byte-for-byte unchanged**, plus any derived skills. Each dir must contain `SKILL.md` (with `name` + `description` frontmatter).                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `agent/compiled/<name>/manifest.json`   | Schema below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `agent/compiled/<name>/tools.ts`        | Custom tool handlers (omit when there are none). Template below. When the prototype has runnable local scripts, handlers **shell out to those exact scripts** (repo-root-relative paths) — never reimplement their logic in TypeScript; a reimplementation is a second, untested copy. And when the deployed sandbox lacks an affordance the skill's prose assumes (reading a local file, running a local script, hitting the founder's network), **add a thin custom tool that provides it** and bridge the skill's language to that tool in instructions.md — don't leave the gap for the smoke test to trip on. |
| `agent/tools/<name>.ts`                 | eve tool wrapper — this file's name is the router-facing tool name. Template below; emit it verbatim with the name substituted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

Then append one dispatch entry to `agent/instructions.md` under
`## Specialists`: tool name, one line on when to dispatch to it.

**Recompile (Claude-merge).** If `agent/compiled/<name>/` existed before this
run: for every file, compare its current hash against `compiled_hashes` in
the old manifest. A mismatch means the file changed since the last compile.
**Never clobber those changes.** Three-way merge: keep them, integrate your
new derivation around them, and say in one line per merged file what you
kept from each side. Files with matching hashes are yours to regenerate
freely.

**Attribute before you claim.** Never assert provenance you can't verify.
Categorize each changed region as: (a) an edit this session directed, (b)
unchanged prior baseline, or (c) **content you did not write and this
session did not direct — a founder hand-edit**. Surface bucket (c)
explicitly ("I found a `## House style` section I didn't generate —
preserving it") instead of folding it into "your edits from this session".
Every preserved hand-edit that encodes a checkable behavior **must** get a
matching enforcement home in the same compile — a `rubric.md` criterion in
`outcome` mode, an explicit operating rule in `instructions.md` in `message`
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
the repo root (e.g. `agent/compiled/<name>/instructions.md`,
`agent/compiled/<name>/tools.ts`). This is the merge base for the next recompile.

**Deploy + verify.** Run `bun run deploy <name>` and show the founder
the output (skill IDs, agent ID + version). Then prove it works with the
**largest realistic input the session actually used** — e.g. the full fixture
file from `prototypes/<name>/`, not a hand-typed one-liner. Run the smoke test
in the **foreground (blocking)** — never as a backgrounded job. Do not end
your turn until you have read a terminal verdict from its output
(`grader: satisfied` / final reply, or a failure); a turn that ends while
the smoke test is still running has verified nothing:
`bun run console <name> -- --once "$(cat prototypes/<name>/fixtures/<file>)"`.
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
- `instructions.md` must pin **one canonical sandbox output path** (e.g.
  `/mnt/session/outputs/<name>.md`) that the agent writes and the rubric
  references — and must also tell the agent to paste the full deliverable
  into its final reply: sandbox-written files are not retrievable through
  the Files API afterward, so the reply is the only channel back.
- The outcome-mode smoke test needs event-level proof, same as custom tools:
  the trace must show `grader: satisfied` AND the final reply carrying the
  real deliverable (not a short wrap-up) — those are independent facts.

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
  "mcp_servers": [],
  "runtime_notes": ["<one line per shared-runtime fix made during this session>"],
  "compiled_hashes": { "<relative path>": "<sha256>" }
}
```

(`deployment` is added by `deploy.ts`; never write it by hand.)

### agent/tools/<name>.ts template

```ts
import { defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { loadCompiledAgent, runTask } from "@/lib/claude-managed-agent.ts";
// Only when the agent has custom tools — static import so eve's bundler sees it:
// import { tools } from "@/agent/compiled/<name>/tools.ts";

const sessionIdState = defineState<string | undefined>("<name>-session", () => undefined);

export default defineTool({
  description:
    "<agent description>. Provide a complete, self-contained task; the " +
    "specialist runs remotely and returns its final answer.",
  inputSchema: {
    type: "object",
    properties: {
      task: { type: "string", description: "The full task for the specialist." },
    },
    required: ["task"],
  },
  async execute(input) {
    // skipToolImport: tools come from the static import above (or none);
    // dynamic import() inside eve's bundled runtime is not reliable.
    const { manifest, rubric } = await loadCompiledAgent("<name>", { skipToolImport: true });
    const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
    // `tools` only for tool-bearing agents (the static import above); omit otherwise.
    const result = await runTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
    if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
    return result.text;
  },
});
```

### agent/compiled/<name>/tools.ts template

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
