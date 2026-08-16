/**
 * The single definition, for this repo, of what counts as a credential.
 *
 * WHY THIS EXISTS: `/managed-agent-deploy` compiles the *session transcript*
 * into CLAUDE.md, rubric.md, manifest.json and the skills. A transcript that
 * happened to contain a literal API key can therefore get that key written into
 * an artifact — and those artifacts leave this machine by two different routes:
 *
 *   deploy time (`scripts/deploy.ts`)
 *     - CLAUDE.md                        → the agent's `system` prompt
 *     - every tool's description/schema  → the agent config's `tools[]`
 *     - each .claude/skills/<dir>/       → uploaded WHOLE as a zip, file by file
 *
 *   run time (`lib/claude-managed-agent.ts` → `runTask`)
 *     - rubric.md                        → `user.define_outcome` rubric content
 *     - manifest.json fields             → session title, `vault_ids`,
 *                                          `memory.instructions` on the
 *                                          session's memory-store resource
 *
 * Those two routes do NOT share a chokepoint on the *deploy* side — rubric.md
 * never passes through deploy.ts on its way to the API. They do share one on
 * the *load* side: `loadManagedAgent()` reads every one of these artifacts, and
 * every path to the API goes through it. So the scan lives here, and both
 * `loadManagedAgent()` (the control) and `scripts/deploy.ts` (a backstop, plus
 * the skill bundles that only it can see) call into it.
 *
 * ONE DEFINITION, ON PURPOSE. A second copy of these regexes in a second file
 * drifts: the two copies disagree, the weaker one is the one that runs on the
 * path that matters, and the guard becomes decoration. Import from here.
 *
 * These functions THROW rather than warn. A warning in a long build log is not
 * a control — nobody reads a log that ends in success.
 *
 * FALSE POSITIVES ARE THE REAL RISK: a guard that blocks legitimate work gets
 * commented out, and then there is no guard. So every rule below anchors on a
 * distinctive vendor prefix, or on a keyed assignment behind an entropy gate.
 * Nothing here fires on "this string looks random". Known-benign strings that
 * must keep passing, all verified against this scanner:
 *
 *   sk-ant-[A-Za-z0-9_-]{20,}        a secret-scanning REGEX quoted in a .md —
 *                                    the next char is '[', so no 20-char run
 *   grep -r 'sk-ant-' .              a sweep example, prefix with no payload
 *   ANTHROPIC_API_KEY=               .env.example, empty value
 *   gxl_paperclip-0.7.36-...whl      a wheel filename — an 11-char run
 *   gxl_1234567890abcdef             a test placeholder — a 16-char run, which
 *                                    is exactly why the gxl_ threshold below is
 *                                    32 and not the 16 first proposed
 *   $VAR / ${VAR} / your-key-here    shell interpolation and fill-me-ins
 *   64-char sha256 hex, PDB-ID prose no vendor prefix, no keyed assignment
 */

/** Patterns anchored on a vendor prefix. Distinctive enough to need no entropy gate. */
const CREDENTIAL_PATTERNS: { rule: string; re: RegExp }[] = [
  // Real key is sk-ant- plus ~101 chars; 20 is far below that and still clears
  // the quoted-regex case above.
  { re: /sk-ant-[A-Za-z0-9_-]{20,}/g, rule: "anthropic-api-key" },
  // 32, NOT 16: the placeholder gxl_1234567890abcdef is a 16-char run and a
  // real Paperclip key is a 64-char run, so 32 separates them with margin.
  { re: /gxl_[A-Za-z0-9_-]{32,}/g, rule: "paperclip-api-key" },
  { re: /\bAKIA[0-9A-Z]{16}\b/g, rule: "aws-access-key-id" },
  { re: /-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----/g, rule: "private-key-block" },
];

/**
 * FOO_API_KEY / FOO_TOKEN / FOO_SECRET = <value>. The name alone is not enough
 * (docs mention these constantly), so the value must also be long, mixed, and
 * high-entropy. An empty value — .env.example's `ANTHROPIC_API_KEY=` — cannot
 * match at all because the value group requires 20+ characters.
 */
const KEYED_ASSIGNMENT =
  /\b[A-Z][A-Z0-9_]*_(?:API_KEY|TOKEN|SECRET)["']?\s*[:=]\s*["']?([A-Za-z0-9+/_=.~-]{20,})/g;

/** Values that are obviously prose or a fill-me-in, however long they are. */
const PLACEHOLDER_VALUE =
  /^(?:your|my|the|an?|example|sample|dummy|fake|test|todo|changeme|change_me|placeholder|redacted|insert|replace|xxx|abc|foo|bar|none|null|undefined)/i;

/** Long base64 runs get decoded once and rescanned — a key survives base64 intact. */
const BASE64_RUN = /[A-Za-z0-9+/]{24,}={0,2}/g;

const PRINTABLE_ASCII = /^[\t\n\r\x20-\x7E]*$/;

function shannonBitsPerChar(value: string): number {
  const counts = new Map<string, number>();
  for (const ch of value) {
    counts.set(ch, (counts.get(ch) ?? 0) + 1);
  }
  let bits = 0;
  for (const n of counts.values()) {
    const p = n / value.length;
    bits -= p * Math.log2(p);
  }
  return bits;
}

/**
 * Enumerated placeholders defeat an entropy gate: `1234567890abcdef` scores
 * MAXIMUM entropy because every character is distinct, yet it is obviously not
 * a secret. Shannon entropy cannot see order, so check for order separately —
 * a run of consecutive codepoints this long does not occur in a random key.
 * (This is what the `gxl_1234567890abcdef` test placeholder trips.)
 */
function hasSequentialRun(value: string, minRun = 6): boolean {
  let run = 1;
  for (let i = 1; i < value.length; i += 1) {
    run = value.charCodeAt(i) === value.charCodeAt(i - 1) + 1 ? run + 1 : 1;
    if (run >= minRun) {
      return true;
    }
  }
  return false;
}

const HAS_LOWER = /[a-z]/;
const HAS_UPPER = /[A-Z]/;
const HAS_DIGIT = /[0-9]/;

/** A credential is long, high-entropy, and mixes character classes. Prose is not. */
function looksLikeSecretValue(value: string): boolean {
  if (PLACEHOLDER_VALUE.test(value) || hasSequentialRun(value)) {
    return false;
  }
  const classes =
    (HAS_LOWER.test(value) ? 1 : 0) +
    (HAS_UPPER.test(value) ? 1 : 0) +
    (HAS_DIGIT.test(value) ? 1 : 0);
  return classes >= 2 && shannonBitsPerChar(value) >= 3;
}

export type CredentialHit = { rule: string; match: string };

/** One artifact to scan: a label for the error message, and its full text. */
export type ScannedArtifact = { label: string; text: string };

/**
 * `decodeBase64` recurses exactly one level, so a base64-wrapped key is caught
 * without the scan looping on its own output.
 */
export function findCredentials(
  text: string,
  decodeBase64 = true
): CredentialHit[] {
  const hits: CredentialHit[] = [];
  for (const { rule, re } of CREDENTIAL_PATTERNS) {
    for (const m of text.matchAll(re)) {
      hits.push({ match: m[0], rule });
    }
  }
  for (const [whole, value] of text.matchAll(KEYED_ASSIGNMENT)) {
    if (value && looksLikeSecretValue(value)) {
      hits.push({ match: whole, rule: "keyed-secret-assignment" });
    }
  }
  if (decodeBase64) {
    for (const m of text.matchAll(BASE64_RUN)) {
      let decoded: string;
      try {
        decoded = Buffer.from(m[0], "base64").toString("utf8");
      } catch {
        continue;
      }
      // Random base64 decodes to binary noise; only rescan real text.
      if (!PRINTABLE_ASCII.test(decoded)) {
        continue;
      }
      for (const hit of findCredentials(decoded, false)) {
        hits.push({ match: hit.match, rule: `${hit.rule} (base64-encoded)` });
      }
    }
  }
  return hits;
}

/**
 * Never print the secret itself — these messages go to build logs, CI output
 * and, on the runtime path, to whatever surfaces a tool error.
 */
export function redact(secret: string): string {
  return `${secret.slice(0, 6)}… (${secret.length} chars, redacted)`;
}

/**
 * Throws with every hit across every artifact, so one run fixes them all.
 *
 * `action` names what is being refused, e.g. "deploy" or
 * `load managed agent "x"` — the callers are a deploy script and a runtime
 * loader and the reader needs to know which one stopped.
 */
export function assertNoCredentials(
  artifacts: ScannedArtifact[],
  action = "upload"
): void {
  const problems = artifacts.flatMap(({ label, text }) =>
    findCredentials(text).map(
      (hit) => `  ${label}: ${hit.rule} — ${redact(hit.match)}`
    )
  );
  if (problems.length > 0) {
    throw new Error(
      [
        `refusing to ${action}: ${problems.length} credential-like string(s) in artifacts that upload.`,
        ...problems,
        "",
        "The compiler mines the session transcript, so a key pasted into the",
        "session can land in CLAUDE.md, rubric.md, manifest.json, a tool",
        "description or a skill. Remove it from the artifact AND ROTATE THE",
        "KEY — it is disclosed either way, and removing it does not",
        "un-disclose it.",
      ].join("\n")
    );
  }
}
