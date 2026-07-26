---
name: managed-agent-prototype
description: Prototype a Claude Managed Agent in managed/<name>/ from a founder's description of the customer, their use case, and the expected inputs/outputs. Run as /managed-agent-prototype <braindump> — freeform, voice-dictation friendly. Done when the agent's job works in this session against real fixtures; then /managed-agent-deploy <name> ships it.
---

# /managed-agent-prototype <braindump> — the prototyper

A founder just described an agent they want — probably out loud, probably
messy. Your job is to turn that into a working prototype in `managed/<name>/`:
fixtures that define done, a `CLAUDE.md` that will become the deployed agent's
system prompt, and skills for the procedures the agent will repeat.

Everything you do here is compiler input: `/managed-agent-deploy <name>` mines
**this session's transcript** for lessons. So keep failures visible (a snag hit
and fixed is worth more than a clean final answer), and when an artifact or
decision is superseded, say so plainly in user-visible text — the compiler
cannot tell stale from current.

## Phase 0 — Parse the braindump

The argument is freeform: customer, use case, inputs, outputs, quality bar,
fixture material, systems involved — in whatever order it came out. Extract:

1. **Who the customer is** and what job the agent does for them.
2. **Inputs** — shape, source, and a real example if one was given.
3. **Outputs** — what a good result looks like, to whom it's delivered.
4. **Fixture material** — any concrete data in the braindump (paste it into
   `fixtures/` verbatim later; never retype from memory).
5. **External systems** — sites, APIs, data stores the agent must touch.

Restate what you understood in a few lines before building anything — voice
input garbles names, formats, and numbers, and a wrong premise here poisons
every artifact downstream. Derive a kebab-case `<name>` and include it in the
restatement for confirmation.

## Phase 1 — Interview

Interview until you are confident, not until you are exhaustive. Rules:

- **One question at a time.** Never a batch, never a form.
- **Every question ships with a recommendation** and a one-line reason, so
  the founder can just say "yes".
- **Never ask what the braindump or the repo already answers.** Questions are
  for genuine judgment calls only. Expect 2–4, not 10.
- **Simplicity first.** Recommend the smallest agent that does the job; the
  founder can always extend after it works.
- **State assumptions explicitly.** If two interpretations exist, present
  both — don't pick silently.
- **Don't ask about behavior that may fall out of scope.** A recorded answer
  is indistinguishable from a requirement to the compiler, and you can't
  retract it.

Before scaffolding, lock the goal: **"done" means a full run against the
fixtures meets the founder's bar.** If you can't state that check concretely
("the report lists every payment deadline with its date", not "the output is
good"), you have another question to ask.

## Phase 2 — Scaffold managed/<name>/

Build in this order — fixtures define the target before anything aims at it:

1. **`fixtures/`** — real data from the founder, verbatim. If you must
   synthesize, label rows synthetic. One row per distinct failure mode, with
   a column saying why that case is in the set — fixtures are how a future
   recompile knows the edge cases were real.
2. **`CLAUDE.md`** — the future deployed agent's instructions, written for a
   fresh agent with none of this session's context: role, contract (including
   what it does *not* do), operating rules, and a **literal fill-in template**
   of the output — models follow skeletons more reliably than prose rules.
   This file deploys verbatim as the system prompt; keep notes-to-self out.
3. **`.claude/skills/<slug>/SKILL.md`** — one per recurring procedure, with
   any scripts the procedure needs inside the skill dir. House rules apply
   (see `.claude/CLAUDE.md`): the failure-modes section is the longest one,
   and skills are named for what they do, not what they decide.

Anything the agent must do that a deployed sandbox can't (call the founder's
systems, read their data stores) — prototype it as a **runnable local script**
and note it as a future custom tool. Deploy's `tools.ts` handlers shell out to
those exact scripts; a script that ran here is a handler that works there.

## Phase 3 — Exercise until it works

Run the agent's actual job in this session against the fixtures: read
`managed/<name>/CLAUDE.md` and its SKILL.mds and follow them literally, as the
deployed agent would. (Your cwd is the repo root, so the Skill tool won't
discover the prototype's skills — reading them is the correct move, and the
deploy smoke test covers real skill loading.)

Iterate: when a run misses the bar, fix the artifact that caused it —
instructions, skill, script, or fixture — and run again. Lessons live in two
places: distilled into the artifacts, and raw in the transcript for the
compiler. Prefer the **largest realistic fixture** for the final pass; a
one-liner proves nothing.

## Hand-off

When a full fixture run meets the bar, close with:

- what works, in one or two lines;
- edges you know are untested;
- the next step, verbatim: **run `/managed-agent-deploy <name>` in this same
  session** — the transcript is the compiler's primary input, so don't start
  a fresh session for it.
