---
name: make-managed
description: Compile the current prototyping session into a deployed Claude Managed Agent. Run as /make-managed <name> from the session where the prototype in managed/<name>/ actually worked — the transcript is the primary compiler input.
---

# /make-managed <name> — the compiler

You are about to turn a working prototype into a deployed agent. The founder
prototyped in `managed/<name>/` in *this* session; the transcript above — what
was tried, what broke, what fixed it, what finally worked — is your primary
source. Files are secondary evidence. You are the compiler: the output is a
complete artifact dir at `agent/tools/<name>/` plus a live Managed Agent.

Work through the four phases in order. **Do not emit any artifact file while
open questions remain** — mining and interviewing complete first, always.

## Phase 1 — Read the source

Explore before you ask anything. From the repo root:

- `managed/<name>/` — every file: fixtures, scratch outputs, scripts, notes.
- `managed/<name>/.mcp.json` — if present, each **remote streamable-HTTP**
  server becomes an `mcp_servers` entry (stdio servers cannot deploy — flag
  them to the founder as the one thing that won't carry over).
- `managed/<name>/.claude/skills/*/SKILL.md` — authored skills; these upload
  to the Skills API **unchanged**. Copy them into the artifact as-is.
- `managed/<name>/CLAUDE.md` — if present, treat as instructions material.
- `agent/tools/<name>/` — if it already exists, this is a **recompile**: read
  `manifest.json` `compiled_hashes` now and follow the merge rules in Phase 4.

## Phase 2 — Mine the transcript

Reread the session and extract, with the discipline that *lessons matter more
than the task statement*:

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
   corrections are the best evidence) → `rubric.md` as concrete, gradeable
   criteria ("the summary lists every payment deadline with its date", not
   "the output is thorough").

Draft all five privately. Where the transcript is ambiguous, note the open
question for Phase 3 instead of guessing.

## Phase 3 — Interview the founder

Interview until **all** ambiguity is resolved; while any open question
remains, building is not allowed. Rules:

- **One question at a time.** Never a batch, never a form.
- **Every question ships with a recommendation** and a one-line reason, so
  the founder can just say "yes". Example: *"Invocation mode: I recommend
  `message` — your session was conversational Q&A, not a graded deliverable.
  OK?"*
- **Never ask what you can find out yourself.** If the transcript or files
  answer it, don't ask it. Interview questions are for genuine judgment
  calls only. Expect roughly 2–4 questions, not 10.
- **Simplicity first.** Recommend the smallest configuration that matches
  the session; the founder can always recompile richer later.

Always resolve (asking only where the evidence is genuinely ambiguous):

| Decision | Default recommendation |
| --- | --- |
| Agent name + one-line description | dir name; description from the task |
| Model | `claude-sonnet-5` (upgrade only if the session needed deep reasoning) |
| Invocation mode | `message`; recommend `outcome` when the session produced a graded deliverable/file |
| Session policy | `reuse` (conversational continuity); `fresh` for stateless one-shot tasks |
| Keep/drop | your mined list of skills + custom tools, shown as a short list for confirmation |

## Phase 4 — Emit, deploy, verify

Only now touch files. The compiled artifact spans three paths (eve requires
every module under `agent/tools/**` to *be* a tool, so handlers and the
wrapper sit exactly where eve expects them):

| File | Content |
| --- | --- |
| `agent/tools/<name>/instructions.md` | The agent's system prompt: role, task, and the **lessons** from Phase 2 as operating rules. Written for a fresh agent with none of this session's context. |
| `agent/tools/<name>/rubric.md` | The Phase 2 quality criteria as gradeable markdown. Emitted in both modes (in `outcome` mode it is sent with `user.define_outcome`; otherwise it documents the bar). |
| `agent/tools/<name>/skills/<slug>/…` | Authored skills copied **byte-for-byte unchanged**, plus any derived skills. Each dir must contain `SKILL.md` (with `name` + `description` frontmatter). |
| `agent/tools/<name>/manifest.json` | Schema below. |
| `agent/lib/<name>/tools.ts` | Custom tool handlers (omit when there are none). Template below — mocks and fixtures faithful to what the session used. |
| `agent/tools/<name>.ts` | eve tool wrapper — this file's name is the router-facing tool name. Template below; emit it verbatim with the name substituted. |

Then append one dispatch entry to `agent/instructions.md` under
`## Specialists`: tool name, one line on when to dispatch to it.

**Recompile (Claude-merge).** If `agent/tools/<name>/` existed before this
run: for every file, compare its current hash against `compiled_hashes` in
the old manifest. A mismatch means the founder hand-edited the file since the
last compile. **Never clobber a hand-edit.** Three-way merge: keep the
founder's edits, integrate your new derivation around them, and say in one
line per merged file what you kept from each side. Files with matching
hashes are yours to regenerate freely.

**Hashes.** After writing, record in `manifest.json.compiled_hashes` the
sha256 of every emitted file (`shasum -a 256`), keyed by path relative to
the repo root (e.g. `agent/tools/<name>/instructions.md`,
`agent/lib/<name>/tools.ts`). This is the merge base for the next recompile.

**Deploy + verify.** Run `npm run deploy-agent <name>` and show the founder
the output (skill IDs, agent ID + version). Then prove it works:
`npm run run-agent <name> -- --once "<a representative task from the session>"`
and confirm the reply meets the rubric. A compile that never ran is a guess.

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
  "compiled_hashes": { "<relative path>": "<sha256>" }
}
```

(`deployment` is added by `deploy-agent.ts`; never write it by hand.)

### agent/tools/<name>.ts template

```ts
import { defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { loadCompiledAgent, runTask } from "../../lib/managed.ts";

const sessionIdState = defineState<string | undefined>(
  "<name>-session",
  () => undefined,
);

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
    const { manifest, rubric, tools } = await loadCompiledAgent("<name>");
    const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
    const result = await runTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
    if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
    return result.text;
  },
});
```

### agent/lib/<name>/tools.ts template

```ts
import type { CustomToolSpec } from "../../../lib/managed.ts";

export const tools: CustomToolSpec[] = [
  {
    name: "<verb_noun>",
    description: "<3–4 sentences: what it does, when to use it, caveats>",
    input_schema: {
      type: "object",
      properties: { /* … */ },
      required: [/* … */],
    },
    async handler(input) {
      // Runs in *this* process when the deployed agent calls the tool.
      return JSON.stringify({ /* … */ });
    },
  },
];
```
