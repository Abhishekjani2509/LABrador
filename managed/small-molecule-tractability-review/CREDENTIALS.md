# Credentials: where they live, what breaks, how to rotate

Short answer to the question that prompted this file: **the deployed agent holds
no API key, and it cannot be given one by this deployment.** Credentials stay on
the operator's machine. What follows is why that is structurally true rather
than merely currently true, and what to do when a key changes.

## 1. Why the deployed agent holds no key

Every one of this agent's nine custom tools is answered by a handler that runs in
the **local process** — the laptop or server that called `runTask` — not in the
cloud sandbox. `lib/claude-managed-agent.ts` parks the session at
`status_idle` / `stop_reason: requires_action`, this process runs the matching
handler, and posts the result back as `user.custom_tool_result`.

What actually uploads is a short list, and no credential is on it:

| Artifact | Uploaded as | Contains a key? |
| --- | --- | --- |
| `CLAUDE.md` | the agent's `system` prompt | no |
| `rubric.md` | runtime rubric, outcome mode (`claude-managed-agent.ts:294`) | no |
| `.claude/skills/<dir>/**` | zipped whole, Skills API | no |
| each tool's `name`, `description`, `input_schema` | agent `tools[]` (`scripts/deploy.ts:166-174`) | no |
| `manifest.json` `name`, `description`, `model` | agent config | no |

**Handler bodies never leave the machine.** `deploy.ts` reads `tool.handler` only
to *call* it locally; it is never serialised into `agentConfig`. `.env` is loaded
by dotenvx into this process and is uploaded by nothing. `acl.ts`, `fixtures/`
and `pipeline.html` do not upload at all.

So the sandbox could not use a Paperclip key if it had one — it has no
`paperclip` binary to use it with. The credential and the binary are on the same
machine, and that machine is not the sandbox.

### No vault is needed, and none should be provisioned

`manifest.json` sets `"mcp_servers": []`. The vault mechanism in the starter
(credentials of type `static_bearer`, keyed by MCP server URL, attached via
`vault_ids`) exists **only** to let a deployed agent authenticate to a remote MCP
server. This agent talks to no MCP server.

**Do not provision a vault credential for this agent.** Doing so would place a
real key in cloud-side storage to serve a code path that does not execute, which
is strictly worse than the current position. If this agent ever gains an
`mcp_servers` entry, revisit this section — until then the correct number of
vault credentials is zero.

## 2. Credential and binary inventory

Two of these are `.env` variables. The third is not, and that catches people out:
**Modal does not authenticate from `.env`.**

| What | Where it lives | What breaks without it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | repo-root `.env` | Nothing runs. No session is created at all. |
| `PAPERCLIP_API_KEY` | repo-root `.env` | The entire retrieved-precedent axis: `paperclip_sql`, `_search`, `_grep`, `_read`, and the Paperclip half of `neighbour_precedent`. |
| Modal token (`token_id` / `token_secret`) | `~/.modal.toml`, under `[rafwiewiora]` | The entire computed-tractability axis — `pocket_scan`, which is the only route to fpocket/mdpocket. |
| `MODAL_BIN` | env var (see §3) | Same as above; there is no local fallback. |
| `MICROMAMBA_BIN` | env var, defaults to `~/.local/bin/micromamba` | `cryptic_analysis`, `interface_analysis`, `disorder_scan`, `neighbour_precedent`. |
| `PAPERCLIP_BIN` | env var, defaults to `~/.local/bin/paperclip` | Same as `PAPERCLIP_API_KEY`. |
| `DRUGGABILITY_ENV` | env var, defaults to `druggability` | The gemmi/numpy scripts. |
| `MODAL_PROFILE` | env var, defaults to `rafwiewiora` | Wrong workspace, or none. |

## 3. Making the Modal binary durable

**This is currently fragile and should be fixed.** The only `modal` on this
machine is:

    /private/tmp/foldarium-modal-test-venv/bin/modal

`/private/tmp` does not survive a reboot, and `modal` is **not on PATH**. As
things stand, the next reboot turns every `pocket_scan` call into a hard failure.
That failure is at least loud — `resolveBin` now throws naming `MODAL_BIN` — but
loud is not the same as working.

Pick one:

- **Durable install (preferred).** Put Modal in a permanent env and put it on
  PATH:

      /Users/bb/.local/bin/micromamba run -n druggability pip install modal
      # then, in your shell profile:
      export MODAL_BIN="$HOME/micromamba/envs/druggability/bin/modal"

- **Pin the existing venv.** Recreate it somewhere permanent (not `/private/tmp`)
  and export `MODAL_BIN` to the new absolute path.

`MODAL_BIN` is honoured ahead of PATH, so setting it is always sufficient.

### The profile is enforced, not merely defaulted

`~/.modal.toml` contains three profiles: `foldariumtest`,
`molspace-production` and `rafwiewiora` (the active one). Only `rafwiewiora` may
be used by this pipeline.

Two guards now enforce that, because defaulting alone was not enough:

1. A blank `MODAL_PROFILE` is treated as unset. The previous
   `process.env.MODAL_PROFILE ?? "rafwiewiora"` would have let `MODAL_PROFILE=""`
   through — empty string is not nullish — and Modal would then have silently
   selected its own active profile, which is whatever `modal profile activate`
   last set. That is a wrong-workspace bug with no error message.
2. A profile that is not `rafwiewiora` is **rejected by name**, not merely
   checked for existence. Existence was the wrong test: the forbidden workspaces
   are in the same file, so "is it a real profile" waves
   `molspace-production` straight through. If you ever genuinely need another
   workspace, set `MODAL_PROFILE_OVERRIDE` to the same value to acknowledge it.

## 4. Rotation procedure

### Why this is mandatory, not ceremony

Both the Anthropic key and the Paperclip key were **pasted into the session
transcript**. That transcript is the primary input to `/managed-agent-deploy`,
which mines it for lessons and writes `CLAUDE.md`, `rubric.md`, skills and
`manifest.json` from it. So the keys exist in at least one place that is read by
a program whose job is to copy things out of it and upload them.

Nothing in the current artifacts contains a key — that was swept and is clean
(§6). The exposure is the transcript itself, not the output. But a key that has
been pasted into a document processed by a compiler is a key that must be
treated as disclosed, regardless of whether this particular compile happened to
copy it. Rotate both.

### Anthropic key

1. Revoke and re-issue at <https://platform.claude.com/settings/keys>.
2. Update `ANTHROPIC_API_KEY` in the repo-root `.env`. Nowhere else — the
   `.claude/get-api-key.sh` helper reads that same file, so there is exactly one
   copy.
3. Verify:

       bun run console druggability-dossier -- --once "reply with OK"

   A stale key fails immediately with `401` from the Agents API.

### Paperclip key

1. Re-issue through Paperclip.
2. Update `PAPERCLIP_API_KEY` in the repo-root `.env`.
3. Verify — and verify with a query whose answer you already know, not one that
   could legitimately be empty:

       paperclip sql -s proteins "SELECT COUNT(*) FROM chembl_v.drugs_by_accession WHERE accession = 'P23458'"

   JAK1 has 11 approved rows. A zero or an error means the key did not take.

### Modal token

1. `modal token new --profile rafwiewiora` — this rewrites `~/.modal.toml`.
2. Confirm `active = true` still sits under `[rafwiewiora]` and that you have not
   been switched to another workspace.
3. Verify: `"$MODAL_BIN" profile current` should print `rafwiewiora`.

### After any rotation

Run the preflight. It checks all three credential sources and all four binaries
in one pass:

    bun -e 'import {preflight} from "@/managed/druggability-dossier/tools.ts"; await preflight(); console.log("preflight OK")'

## 5. Preflight: failing at second zero

`preflight()` is exported from `tools.ts` and is called by
`agent/tools/druggability-dossier.ts` **before the session is created**. It
verifies `ANTHROPIC_API_KEY`, `PAPERCLIP_API_KEY`, the `paperclip`,
`micromamba` and `modal` binaries, the Modal profile, and that the
`DRUGGABILITY_ENV` conda env actually imports gemmi and numpy.

Two design points that are the whole reason it exists:

- **It aggregates.** Every problem is reported in one throw, not just the first.
  Failing one at a time turns setup into a guess-and-recheck loop.
- **It runs before the run, not at first use.** `pocket_scan` is typically
  reached tens of minutes into a dossier, after the precedent queries. A missing
  `MODAL_BIN` discovered there costs the entire run.

`DOSSIER_SKIP_PREFLIGHT=1` exists for driving the Paperclip tools by hand on a
machine with no Modal. Never set it for a real dossier.

### The failure mode this is all defending against

A missing credential must never look like a negative result. A `paperclip` call
with no valid key returning zero rows is indistinguishable from *a target with no
precedent* — and telling those two apart is this agent's entire job. Every
credential path therefore raises with a named variable rather than returning an
empty set.

That includes a key that is **present but dead**: `requireEnv` cannot catch an
expired key, so failed `paperclip` runs are additionally checked for auth
signatures (401/403/unauthorized/invalid key) and converted into a throw that
says, in words, "this is an authentication failure, NOT an empty result". The
check is scoped to non-zero exits on purpose — a successful literature search can
legitimately return document text containing the word "unauthorized", and turning
retrieved evidence into a hard failure would be the same bug wearing a different
hat.

## 6. Pre-upload artifact scan (proposed — belongs in shared `scripts/`)

**There is currently no guard.** `/managed-agent-deploy` reads a transcript that
may contain literal keys and writes `CLAUDE.md`, `rubric.md`, skills and
`manifest.json` from it; `scripts/deploy.ts` then uploads those without ever
inspecting them for credential patterns. A compiler mistake would ship a key and
nothing would stop it.

This belongs in shared `scripts/deploy.ts`, not here — it must cover *every*
managed agent, not just this one, and a per-agent copy is a guard that the next
agent silently lacks. It is not ours to edit, so the patch is written out rather
than applied.

Scan every artifact that leaves the machine — the skill zips, `instructions`
(CLAUDE.md), `rubric.md`, and the serialised tool descriptions — and **fail the
deploy**, not warn. A warning in a deploy log is a warning nobody reads.

Suggested patch to `scripts/deploy.ts`, before the `agents.create` /
`agents.update` calls:

```ts
const CREDENTIAL_PATTERNS = [
  /sk-ant-[A-Za-z0-9_-]{20,}/,       // Anthropic
  /gxl_[A-Za-z0-9_-]{16,}/,          // Paperclip
  /AKIA[0-9A-Z]{16}/,                // AWS
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
];

function scanArtifact(label: string, text: string): void {
  for (const pattern of CREDENTIAL_PATTERNS) {
    if (pattern.test(text)) {
      throw new Error(
        `refusing to deploy: ${label} matches a credential pattern ` +
          `(${pattern}). The compiler mined a transcript containing a live ` +
          "key. Remove it from the artifact AND rotate the key — it is " +
          "disclosed either way."
      );
    }
  }
}

scanArtifact("CLAUDE.md (system prompt)", instructions);
scanArtifact("rubric.md", rubric ?? "");
scanArtifact("tool definitions", JSON.stringify(agentConfig.tools));
// and, per skill bundle, over the zip's text members before upload
```

Two notes for whoever applies it:

- Scan the **zip contents**, not the zip bytes — compression hides the pattern.
  The same pass should exclude `__pycache__`/`*.pyc`, which currently upload and
  carry absolute local paths (already routed in `manifest.json`; this agent's
  `.gitignore` stops them being committed but does not stop the zip).
- A match means rotate, not just edit. Removing the key from the artifact does
  not un-disclose it.

## 7. A trap for anyone re-running the credential sweep

`grep` in this shell is **not** `/usr/bin/grep`. It is a function wrapping
`ugrep` with `--ignore-files`, which honours `.gitignore`. So:

    grep -r 'sk-ant-' .        # silently skips .env, *.pyc, and everything gitignored

That will report clean on a repo whose `.env` is full of live keys, because
`.env` is gitignored. Any credential sweep must use `/usr/bin/grep` directly, or
pass `--no-ignore-files`, and should include `-a` so compiled bytecode is
searched too. A scan that cannot find a key you know is there is not evidence of
absence — verify the scanner against a known positive before trusting a negative.
