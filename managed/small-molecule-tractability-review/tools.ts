/**
 * Custom tools for the `druggability-dossier` managed agent.
 *
 * Every handler here runs in *this* process — the laptop/server that called
 * `runTask` — not in the deployed agent's sandbox. `lib/claude-managed-agent.ts`
 * parks the session on `requires_action`, runs the matching handler locally,
 * and posts a `user.custom_tool_result` back. So these handlers get the local
 * PATH, the local micromamba envs, the local Modal credentials, and the `.env`
 * dotenvx already loaded into `process.env`.
 *
 * That is the *only* reason these tools exist. The sandbox has unrestricted
 * outbound network (verified on the `mvp-shared` environment:
 * `config.networking.type === "unrestricted"`), so nothing here bridges
 * connectivity. What it bridges is **binaries and conda packages the sandbox
 * cannot install**: `paperclip` is a private binary in none of the six
 * declarable registries (apt/cargo/gem/go/npm/pip), and `fpocket`/`mdpocket`
 * are conda-forge only with no conda member in the schema.
 *
 * Handlers shell out to the exact scripts under `.claude/skills/`. None of the
 * Python logic is reimplemented here — a reimplementation would be a second,
 * untested copy of a calibrated measurement.
 *
 * Credentials come from `process.env` and every miss is a hard failure with a
 * named variable. A silent fallback would produce a run with no data that reads
 * exactly like a run with no results, which is the worst possible output for
 * this agent.
 */
import { execFile } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type { CustomToolSpec } from "@/lib/claude-managed-agent.ts";
import { repoRoot } from "@/lib/claude-managed-agent.ts";

const execFileAsync = promisify(execFile);

const SKILLS_DIR = join(
  repoRoot,
  "managed",
  "druggability-dossier",
  ".claude",
  "skills"
);

/** Truncate handler output so one wide result cannot blow the session budget. */
const MAX_OUTPUT_CHARS = 180_000;
const MS_PER_SECOND = 1000;
const DEFAULT_TIMEOUT_S = 300;
const POCKET_SCAN_TIMEOUT_S = 1800;
const NEIGHBOUR_TIMEOUT_S = 900;
const EXEC_MAX_BUFFER = 64 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Environment resolution — loud on every miss, never a silent fallback
// ---------------------------------------------------------------------------

function requireEnv(name: string, why: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set in this process's environment. ${why} ` +
        "Add it to the repo-root .env (dotenvx loads that file into the " +
        "process that answers custom tools) and re-run the task."
    );
  }
  return value;
}

/** Find `name` on PATH, or undefined. Used so resolveBin can keep its promise. */
function onPath(name: string): string | undefined {
  const parts = (process.env.PATH ?? "").split(":").filter(Boolean);
  return parts
    .map((part) => join(part, name))
    .find((candidate) => existsSync(candidate));
}

/**
 * Resolve an executable: explicit env override first, then a known install
 * location, then PATH. Never returns a name that does not exist — a bare name
 * that is not actually on PATH is thrown here, naming the variable that would
 * fix it, rather than deferring to an ENOENT that names no variable.
 */
function resolveBin(args: {
  candidates: string[];
  envVar: string;
  fallbackOnPath: string;
  why: string;
}): string {
  const override = process.env[args.envVar];
  if (override) {
    if (!existsSync(override)) {
      throw new Error(
        `${args.envVar} points at ${override}, which does not exist. ${args.why}`
      );
    }
    return override;
  }
  const found = args.candidates.find((candidate) => existsSync(candidate));
  if (found) {
    return found;
  }
  const fromPath = onPath(args.fallbackOnPath);
  if (fromPath) {
    return fromPath;
  }
  throw new Error(
    `${args.fallbackOnPath} was not found: not at any known install location ` +
      `and not on this process's PATH. ${args.why} ` +
      `Set ${args.envVar} to its absolute path and re-run the task.`
  );
}

function micromamba(): string {
  return resolveBin({
    candidates: [join(homeDir(), ".local", "bin", "micromamba")],
    envVar: "MICROMAMBA_BIN",
    fallbackOnPath: "micromamba",
    why: "It runs the gemmi/numpy analysis scripts (cryptic_analysis, interface_analysis, disorder, neighbour_precedent) inside their conda env.",
  });
}

function homeDir(): string {
  return process.env.HOME ?? process.env.USERPROFILE ?? "";
}

/** The env carrying gemmi + numpy for the local structure-analysis scripts. */
function analysisEnvName(): string {
  return process.env.DRUGGABILITY_ENV ?? "druggability";
}

// ---------------------------------------------------------------------------
// Process runner
// ---------------------------------------------------------------------------

type RunResult = { code: number; stderr: string; stdout: string };

async function run(
  file: string,
  argv: string[],
  opts: { env?: NodeJS.ProcessEnv; timeoutSeconds?: number } = {}
): Promise<RunResult> {
  try {
    const { stdout, stderr } = await execFileAsync(file, argv, {
      env: opts.env ?? process.env,
      maxBuffer: EXEC_MAX_BUFFER,
      timeout: (opts.timeoutSeconds ?? DEFAULT_TIMEOUT_S) * MS_PER_SECOND,
    });
    return { code: 0, stderr, stdout };
  } catch (error) {
    const err = error as {
      code?: number | string;
      stderr?: string;
      stdout?: string;
    };
    if (err.code === "ENOENT") {
      throw new Error(
        `executable not found: ${file}. Install it, or point the matching ` +
          "*_BIN environment variable at it.",
        { cause: error }
      );
    }
    return {
      code: typeof err.code === "number" ? err.code : 1,
      stderr: err.stderr ?? String(error),
      stdout: err.stdout ?? "",
    };
  }
}

function clip(text: string): string {
  return text.length > MAX_OUTPUT_CHARS
    ? `${text.slice(0, MAX_OUTPUT_CHARS)}\n…[truncated by the local tool handler at ${MAX_OUTPUT_CHARS} characters — narrow the query]`
    : text;
}

/** Render a completed run for the agent: stdout on success, both on failure. */
function report(label: string, result: RunResult): string {
  if (result.code === 0) {
    return clip(result.stdout || result.stderr || "(no output)");
  }
  return clip(
    `${label} exited ${result.code}.\n\n--- stdout ---\n${result.stdout}\n\n--- stderr ---\n${result.stderr}`
  );
}

// ---------------------------------------------------------------------------
// Input coercion (the model sends JSON; keep every read explicit)
// ---------------------------------------------------------------------------

function str(input: Record<string, unknown>, key: string): string | undefined {
  const value = input[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function requiredStr(input: Record<string, unknown>, key: string): string {
  const value = str(input, key);
  if (!value) {
    throw new Error(`"${key}" is required and must be a non-empty string`);
  }
  return value;
}

function num(input: Record<string, unknown>, key: string): number | undefined {
  const value = input[key];
  return typeof value === "number" ? value : undefined;
}

function bool(input: Record<string, unknown>, key: string): boolean {
  return input[key] === true;
}

function list(input: Record<string, unknown>, key: string): string[] {
  const value = input[key];
  if (Array.isArray(value)) {
    return value.map(String).filter((item) => item.length > 0);
  }
  return typeof value === "string" && value.length > 0
    ? value
        .split(",")
        .map((item) => item.trim())
        .filter((item) => item.length > 0)
    : [];
}

// ---------------------------------------------------------------------------
// paperclip
// ---------------------------------------------------------------------------

function paperclipBin(): string {
  return resolveBin({
    candidates: [join(homeDir(), ".local", "bin", "paperclip")],
    envVar: "PAPERCLIP_BIN",
    fallbackOnPath: "paperclip",
    why: "It is the only route to the Paperclip corpus, which carries the entire retrieved-precedent axis.",
  });
}

/**
 * Signatures of an auth failure rather than an empty answer. This is the
 * distinction the whole agent exists to protect: "no rows" and "your key was
 * rejected" render almost identically once they reach the model, and one of
 * them is a finding about the target while the other is a finding about the
 * laptop. A present-but-dead key passes `requireEnv` and would otherwise sail
 * straight through as evidence of absence.
 */
const AUTH_FAILURE = new RegExp(
  [
    "\\b401\\b",
    "\\b403\\b",
    "unauthori[sz]ed",
    "forbidden",
    "invalid api key",
    "invalid token",
    "authentication failed",
    "not authenticated",
    "expired (api )?(key|token)",
    "missing api key",
  ].join("|"),
  "i"
);

async function paperclip(
  argv: string[],
  timeoutSeconds = DEFAULT_TIMEOUT_S
): Promise<RunResult> {
  requireEnv(
    "PAPERCLIP_API_KEY",
    "The Paperclip CLI authenticates non-interactively with it, and without " +
      "it every query would return an auth error that reads like an empty result."
  );
  const result = await run(paperclipBin(), argv, { timeoutSeconds });
  // Only inspect *failed* runs. A successful grep over the literature can
  // legitimately return lines containing "unauthorized" or "403" as document
  // text, and turning retrieved evidence into a hard failure would be its own
  // version of the bug this guard exists to prevent.
  if (
    result.code !== 0 &&
    AUTH_FAILURE.test(`${result.stderr}\n${result.stdout}`)
  ) {
    throw new Error(
      "PAPERCLIP_API_KEY was present but Paperclip rejected it " +
        `(exit ${result.code}). This is an authentication failure, NOT an ` +
        "empty result — do not record it as 'no precedent found'. Rotate or " +
        "re-issue the key, put it in the repo-root .env, and re-run.\n\n" +
        `--- paperclip said ---\n${clip(result.stderr || result.stdout)}`
    );
  }
  return result;
}

const paperclipSql: CustomToolSpec = {
  description:
    "Run one read-only SELECT against a Paperclip database and return the rendered table. " +
    "Use it for every structured precedent lookup — `-s proteins` reaches chembl_v/pdb_v/uniprot_v (drugs by accession, bioactivities, structures, Pfam), `-s trials` reaches the AACT-style ctgov schema, and omitting the source hits the paper corpus (documents, content_blocks, figures). " +
    "Three caveats are measured, not guessed: results are hard-capped at 200 rows, a server-side statement timeout kills long queries, and wide cells are truncated with a literal `...` at roughly 880 characters — which silently destroys json_agg output, so aggregate into separate columns instead of one JSON blob. " +
    "Usually inline literals beat subqueries, but not always: a Pfam cross-reference join timed out at 85.1 s with inline literals while the identical predicate expressed as a subquery ran in 2.2 s, so when a query times out, try the other form before concluding the data is not there.",
  async handler(input) {
    const query = requiredStr(input, "query");
    const source = str(input, "source");
    const argv = source ? ["sql", "-s", source, query] : ["sql", query];
    return report("paperclip sql", await paperclip(argv));
  },
  input_schema: {
    properties: {
      query: {
        description:
          "A single SELECT statement. Only SELECT is accepted; no DDL or DML.",
        type: "string",
      },
      source: {
        description:
          "Database to query, e.g. `proteins` (chembl_v/pdb_v/uniprot_v) or `trials` (ctgov). Omit for the paper corpus.",
        type: "string",
      },
    },
    required: ["query"],
    type: "object",
  },
  name: "paperclip_sql",
};

const paperclipGrep: CustomToolSpec = {
  description:
    "Full-text regex search over the Paperclip document corpus — `/papers/` for the literature and `/trials/` for registry records — returning matching lines with their document IDs. " +
    "Use it to find what a database column cannot express: a compound code, a termination reason, a stated adverse event. " +
    "The flags are short-form only and this is measured: `-C NUM` and `-m NUM` work, while the long forms `--context` and `--limit` are not parsed as flags and produce the misleading error `Cannot read path: /papers` — which reads like a missing corpus rather than a bad flag. " +
    "Two more measured traps: a hyphenated compound code collides with document UUIDs (3 of 20 hits for `DC-806` were substrings inside UUIDs, not mentions — always read the surrounding line before counting), and `/trials/` result paths are frequently not readable afterwards while the tool still labels its output as 'matching papers', so treat a trials hit as a pointer to check in `paperclip_sql -s trials`, not as a retrievable document.",
  async handler(input) {
    const pattern = requiredStr(input, "pattern");
    const path = str(input, "path") ?? "/papers/";
    const argv = ["grep"];
    if (bool(input, "ignore_case")) {
      argv.push("-i");
    }
    if (bool(input, "line_numbers")) {
      argv.push("-n");
    }
    if (bool(input, "count")) {
      argv.push("-c");
    }
    if (bool(input, "list_files")) {
      argv.push("-l");
    }
    if (bool(input, "fixed_string")) {
      argv.push("-F");
    }
    if (bool(input, "whole_word")) {
      argv.push("-w");
    }
    if (bool(input, "bool_mode")) {
      argv.push("--bool");
    }
    const context = num(input, "context");
    if (context !== undefined) {
      argv.push("-C", String(context));
    }
    const maxMatches = num(input, "max_matches");
    if (maxMatches !== undefined) {
      argv.push("-m", String(maxMatches));
    }
    const section = str(input, "section");
    if (section) {
      argv.push("--section", section);
    }
    const blockType = str(input, "block_type");
    if (blockType) {
      argv.push("--block-type", blockType);
    }
    argv.push(pattern, path);
    return report("paperclip grep", await paperclip(argv));
  },
  input_schema: {
    properties: {
      block_type: {
        description: "Restrict matches to a block type.",
        type: "string",
      },
      bool_mode: {
        description: "Whole-document Boolean regex (`--bool`).",
        type: "boolean",
      },
      context: {
        description:
          "Lines of context around each match. Sent as `-C NUM`; the long form does not work.",
        type: "number",
      },
      count: { description: "Count matches (`-c`).", type: "boolean" },
      fixed_string: {
        description: "Literal match, no regex (`-F`).",
        type: "boolean",
      },
      ignore_case: { description: "Case-insensitive (`-i`).", type: "boolean" },
      line_numbers: {
        description: "Show line numbers (`-n`).",
        type: "boolean",
      },
      list_files: {
        description: "List only matching document paths (`-l`).",
        type: "boolean",
      },
      max_matches: {
        description:
          "Stop after N matches per corpus. Sent as `-m NUM`; the long form does not work.",
        type: "number",
      },
      path: {
        description:
          "Corpus path: `/papers/`, `/trials/`, or a specific document such as `/papers/PMC8080595/content.lines`. Defaults to `/papers/`.",
        type: "string",
      },
      pattern: {
        description: "Regex (or literal, with fixed_string) to search for.",
        type: "string",
      },
      section: {
        description: "Restrict matches to a named section, e.g. `Methods`.",
        type: "string",
      },
      whole_word: { description: "Whole words only (`-w`).", type: "boolean" },
    },
    required: ["pattern"],
    type: "object",
  },
  name: "paperclip_grep",
};

const paperclipRead: CustomToolSpec = {
  description:
    "Read one file out of the Paperclip virtual filesystem — a document body (`/papers/<id>/content.lines`), its metadata (`/papers/<id>/meta.json`, giving doi, journal and pub_date), or a trial record (`/trials/us/<NCT>/meta.json`). " +
    "Use it after `paperclip_grep` returns a document ID, to read the passage in context and pull the citation you will put in a `source` field. " +
    "Pass `numbered: true` to get line numbers so a claim can be pinned to a line, which is what the dossier's provenance rule asks for. " +
    'Caveat, measured: `/trials/` paths that appear in grep output are frequently not readable here and return `Cannot read path`, so treat a failed trials read as expected and go to `paperclip_sql` with `source: "trials"` instead of retrying.',
  async handler(input) {
    const path = requiredStr(input, "path");
    const argv = ["cat"];
    if (bool(input, "numbered")) {
      argv.push("-n");
    }
    argv.push(path);
    return report("paperclip cat", await paperclip(argv));
  },
  input_schema: {
    properties: {
      numbered: {
        description: "Number the output lines (`-n`).",
        type: "boolean",
      },
      path: {
        description:
          "Path in the Paperclip VFS, e.g. `/papers/PMC8080595/meta.json`.",
        type: "string",
      },
    },
    required: ["path"],
    type: "object",
  },
  name: "paperclip_read",
};

const paperclipSearch: CustomToolSpec = {
  description:
    "Semantic + BM25 search over a named Paperclip source, returning ranked documents with their IDs. " +
    "Use it when you do not know the exact string to grep for — a mechanism, an indication, a programme description — and then follow up with `paperclip_grep` or `paperclip_read` on the IDs it returns. " +
    "`source` is mandatory on every search (unlike grep) and accepts comma-separated values such as `pmc`, `biorxiv`, `medrxiv`, `fda`, `trials/us` or `proteins`. " +
    "Caveat: `patents` is advertised but not provisioned and returns `Patents sources are not available.` for search, sql and ls alike, so patent counts must be reported as `null` with the reason in `not_found` rather than guessed.",
  async handler(input) {
    const query = requiredStr(input, "query");
    const source = requiredStr(input, "source");
    const argv = ["search", "-s", source];
    const limit = num(input, "limit");
    if (limit !== undefined) {
      argv.push("-n", String(limit));
    }
    argv.push(query);
    return report("paperclip search", await paperclip(argv));
  },
  input_schema: {
    properties: {
      limit: { description: "Maximum results (`-n`).", type: "number" },
      query: {
        description: "Natural-language or keyword query.",
        type: "string",
      },
      source: {
        description:
          "Required. One or more comma-separated sources, e.g. `pmc,biorxiv` or `trials/us`.",
        type: "string",
      },
    },
    required: ["query", "source"],
    type: "object",
  },
  name: "paperclip_search",
};

// ---------------------------------------------------------------------------
// pocket_scan — the Modal app
// ---------------------------------------------------------------------------

/**
 * The only Modal workspace this agent may bill or read. The founder was
 * explicit that the other workspaces in ~/.modal.toml — `molspace-production`
 * and `foldariumtest` — cannot be used, so this is a hard default with no
 * fallback, not a preference.
 */
const EXPECTED_MODAL_PROFILE = "rafwiewiora";

/**
 * There is no durable `modal` on this machine — the only one lives in a
 * throwaway venv under /private/tmp, which does not survive a reboot. So there
 * is deliberately no candidate path here: MODAL_BIN or PATH, and a loud throw
 * otherwise. See CREDENTIALS.md for making this durable.
 */
function modalBin(): string {
  return resolveBin({
    candidates: [],
    envVar: "MODAL_BIN",
    fallbackOnPath: "modal",
    why: "It runs the fpocket/mdpocket image, which is the entire computed-tractability axis; there is no local fallback for it.",
  });
}

/**
 * Modal does not authenticate from `.env`; its token_id/token_secret live in
 * `~/.modal.toml`, one block per profile. So the credential check here is
 * "does the named profile exist in that file", not a `requireEnv`.
 *
 * Resolving the profile with `??` would have been a silent-fallback bug:
 * `MODAL_PROFILE=""` is not nullish, so an empty value would have passed
 * through and let Modal pick its own active profile — which is a different
 * workspace whenever someone has run `modal profile activate` elsewhere.
 * Treat blank as unset, and refuse an unknown profile by name.
 */
function modalProfile(): string {
  const raw = process.env.MODAL_PROFILE?.trim();
  const profile = raw && raw.length > 0 ? raw : EXPECTED_MODAL_PROFILE;
  const configPath = join(homeDir(), ".modal.toml");
  if (!existsSync(configPath)) {
    throw new Error(
      `no Modal config at ${configPath}, so profile "${profile}" cannot be ` +
        "authenticated. Run `modal token new --profile " +
        `${EXPECTED_MODAL_PROFILE}` +
        "`, or point MODAL_BIN at a Modal install whose config has it."
    );
  }
  // Existence is the wrong test: the forbidden workspaces are *also* in this
  // file, so "is it a real profile" would wave `molspace-production` straight
  // through. The test is identity.
  if (
    profile !== EXPECTED_MODAL_PROFILE &&
    process.env.MODAL_PROFILE_OVERRIDE !== profile
  ) {
    throw new Error(
      `MODAL_PROFILE is "${profile}", but this agent runs only in the ` +
        `"${EXPECTED_MODAL_PROFILE}" Modal workspace. The other profiles in ` +
        `${configPath} belong to different workspaces and must not be ` +
        "billed or read by this pipeline. Unset MODAL_PROFILE to use the " +
        "correct one. If you genuinely mean to switch, set " +
        "MODAL_PROFILE_OVERRIDE to the same value to acknowledge it."
    );
  }
  const config = readFileSync(configPath, "utf8");
  if (!new RegExp(`^\\[${profile}\\]`, "m").test(config)) {
    throw new Error(
      `MODAL_PROFILE is "${profile}", which is not a profile in ${configPath}. ` +
        "Run `modal token new --profile " +
        `${profile}` +
        "` to create it."
    );
  }
  return profile;
}

const pocketScan: CustomToolSpec = {
  description:
    "Run the whole computed-tractability half of the dossier in one Modal invocation: fpocket + PRANK at every clustering value, plus the disorder, cryptic, interface and mdpocket stages. " +
    "Use it for every pocket measurement — fpocket and mdpocket are conda-forge binaries that exist only inside this Modal image, so there is no other way to get a volume, a druggability range, or a site fixed by construction. " +
    "Pass the full ensemble at once (`pdb_ids`) rather than one structure per call: one invocation pays one cold start, and same-site tracking only works when a holo structure sits in the same run as the apo ones it anchors. " +
    "Caveats that decide how you read the result: `ligand_codes` is an override and not a requirement (naming one code across four structures left three falling back to the weaker signature path and moved 7JRA from 0.000/306.9 A^3 to 0.926/1542.9 A^3), `mdpocket.sites` returns up to two definitions of which only `site_from_ligand` is the ligand site — read `distance_to_donor_ligand_centroid_a` on every entry before quoting a number — and every stage after fpocket is non-fatal and reports its own `<stage>_status`, so check those before treating a missing block as a null result. A run takes minutes and costs real credits; do not re-run it to retry a formatting question.",
  async handler(input) {
    const pdbIds = list(input, "pdb_ids");
    if (pdbIds.length === 0) {
      throw new Error(
        "pdb_ids is required and must name at least one PDB entry"
      );
    }
    const modal = modalBin();
    const profile = modalProfile();
    const argv = [
      "run",
      join(SKILLS_DIR, "pocket-scan", "modal_app.py"),
      "--pdb-ids",
      pdbIds.join(","),
    ];
    const ligandCodes = list(input, "ligand_codes");
    if (ligandCodes.length > 0) {
      argv.push("--ligand-codes", ligandCodes.join(","));
    }
    const accession = str(input, "uniprot_accession");
    if (accession) {
      argv.push("--uniprot-accession", accession);
    }
    const partners = list(input, "partner_structures");
    if (partners.length > 0) {
      argv.push("--partner-structures", partners.join(","));
    }
    const donor = str(input, "mdpocket_site_donor");
    if (donor) {
      argv.push("--mdpocket-site-donor", donor);
    }
    const result = await run(modal, argv, {
      env: { ...process.env, MODAL_PROFILE: profile },
      timeoutSeconds: POCKET_SCAN_TIMEOUT_S,
    });
    return report("modal run modal_app.py", result);
  },
  input_schema: {
    properties: {
      ligand_codes: {
        description:
          'Optional chemical component IDs used to anchor the site, e.g. `["MOV"]`. An override, not a requirement: a structure carrying its own drug-like ligand anchors itself when no supplied code matches.',
        items: { type: "string" },
        type: "array",
      },
      mdpocket_site_donor: {
        description:
          "A holo PDB ID used ONLY to define the mdpocket site, not added to the ensemble. This is how a pure-apo ensemble gets a ligand-anchored site.",
        type: "string",
      },
      partner_structures: {
        description:
          'PDB IDs of complexes containing the binding partner, e.g. `["3ALQ"]`. Turns the orthosteric/allosteric question into a measurement.',
        items: { type: "string" },
        type: "array",
      },
      pdb_ids: {
        description:
          'The ensemble, e.g. `["6OIM","4OBE"]`. Send every structure in one call.',
        items: { type: "string" },
        type: "array",
      },
      uniprot_accession: {
        description:
          "Drives the disorder stage. Strongly preferred over the structure-derived fallback, because a deposited construct is the ordered part of the protein by selection.",
        type: "string",
      },
    },
    required: ["pdb_ids"],
    type: "object",
  },
  name: "pocket_scan",
};

// ---------------------------------------------------------------------------
// Local structure-analysis scripts (gemmi + numpy)
// ---------------------------------------------------------------------------

function pythonArgv(script: string, scriptArgs: string[]): string[] {
  return ["run", "-n", analysisEnvName(), "python", script, ...scriptArgs];
}

const PDB_ID = /^[0-9][A-Za-z0-9]{3}$/;
const STRUCTURE_CACHE = join(tmpdir(), "druggability-dossier-structures");

/**
 * These handlers run locally, so a structure the *sandbox* downloaded is not
 * reachable here. Accept a 4-character PDB ID and materialise the biological
 * assembly locally; anything else is passed through as a path untouched. This
 * is not a general fetch tool — the sandbox has open egress and can curl RCSB
 * itself; it is the local half of a local-only script's input.
 */
async function resolveStructure(value: string): Promise<string> {
  if (!PDB_ID.test(value)) {
    return value;
  }
  const id = value.toUpperCase();
  mkdirSync(STRUCTURE_CACHE, { recursive: true });
  const target = join(STRUCTURE_CACHE, `${id}-assembly1.cif`);
  if (existsSync(target)) {
    return target;
  }
  const url = `https://files.rcsb.org/download/${id}-assembly1.cif`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `could not download ${url} (HTTP ${response.status}). Pass an explicit ` +
        "file path instead, or check the entry has a deposited assembly 1."
    );
  }
  writeFileSync(target, Buffer.from(await response.arrayBuffer()));
  return target;
}

const crypticAnalysis: CustomToolSpec = {
  description:
    "Classify the cryptic-pocket mechanism from one apo/holo structure pair: core C-alpha superposition excluding the mobile region, max backbone displacement at the site, clash attribution split into backbone / side-chain / displaced-subunit, a self-control against the holo structure itself, and the ligand's free-volume fraction in the apo frame. " +
    "Run it whenever both an apo and a holo structure exist, because `cryptic_pocket_risk` must be measured rather than set from structure tier. " +
    "Classify on C-alpha displacement and NOT on which atoms clash: KRAS switch-II moves 8.8 A yet zero of its 12 clashing atoms at 2.0 A are backbone, so keying on clash composition labels the canonical nanomolar target as side-chain occlusion and hands it a micromolar prognosis. " +
    "Read the self-control first — it must come back near zero, and if it does not, the superposition or the ligand placement is broken and every other number in the result is meaningless. `apo` and `holo` are paths to structure files (PDB or mmCIF) that this process can read; download the biological assembly you want before calling.",
  async handler(input) {
    const argv = [
      await resolveStructure(requiredStr(input, "apo")),
      await resolveStructure(requiredStr(input, "holo")),
      requiredStr(input, "ligand_comp_id"),
    ];
    const holoChains = list(input, "holo_chains");
    if (holoChains.length > 0) {
      argv.push("--holo-chains", ...holoChains);
    }
    const apoChains = list(input, "apo_chains");
    if (apoChains.length > 0) {
      argv.push("--apo-chains", ...apoChains);
    }
    const ligandChain = str(input, "ligand_chain");
    if (ligandChain) {
      argv.push("--ligand-chain", ligandChain);
    }
    const excludeRadius = num(input, "exclude_radius");
    if (excludeRadius !== undefined) {
      argv.push("--exclude-radius", String(excludeRadius));
    }
    if (bool(input, "no_trim")) {
      argv.push("--no-trim");
    }
    if (bool(input, "no_free_volume")) {
      argv.push("--no-free-volume");
    }
    const result = await run(
      micromamba(),
      pythonArgv(join(SKILLS_DIR, "pocket-scan", "cryptic_analysis.py"), argv),
      { timeoutSeconds: DEFAULT_TIMEOUT_S }
    );
    return report("cryptic_analysis.py", result);
  },
  input_schema: {
    properties: {
      apo: {
        description:
          "Apo structure: a 4-character PDB ID (biological assembly 1 is fetched automatically) or a path to a PDB/mmCIF file this process can read.",
        type: "string",
      },
      apo_chains: {
        description: "Chain IDs to keep from the apo structure.",
        items: { type: "string" },
        type: "array",
      },
      exclude_radius: {
        description:
          "Radius around the site used to exclude mobile residues from the superposition fit.",
        type: "number",
      },
      holo: {
        description:
          "Holo structure: a 4-character PDB ID (biological assembly 1 is fetched automatically) or a path to a PDB/mmCIF file this process can read.",
        type: "string",
      },
      holo_chains: {
        description: "Chain IDs to keep from the holo structure.",
        items: { type: "string" },
        type: "array",
      },
      ligand_chain: {
        description: "Chain the reference ligand sits in.",
        type: "string",
      },
      ligand_comp_id: {
        description:
          "Chemical component ID of the holo ligand, e.g. `MOV` or `307`. Use the component ID, not the paper's name for the compound.",
        type: "string",
      },
      no_free_volume: {
        description: "Skip the free-volume calculation.",
        type: "boolean",
      },
      no_trim: {
        description:
          "Disable auto-trim. The hand-calibration protocol used this; the deployed default does not, and the two differ by 0.1-0.2 A.",
        type: "boolean",
      },
    },
    required: ["apo", "holo", "ligand_comp_id"],
    type: "object",
  },
  name: "cryptic_analysis",
};

const interfaceAnalysis: CustomToolSpec = {
  description:
    "PPI-interface support for `tractability.pocket_vs_interface`: with `partners_accession` it lists the deposited complex structures that contain a binding partner for that UniProt accession, which is the input `pocket_scan`'s `partner_structures` argument needs. " +
    "Call it before `pocket_scan` whenever the mechanism hypothesis is orthosteric or oligomer-destabilisation, so the pocket-versus-interface label is measured rather than assumed. " +
    "With `selftest_dir` it instead runs the bundled fixture harness (IL-17A, TNF-alpha, KRAS) and caches CIFs there — use that only to check the module still behaves, never as evidence about a target. " +
    "Caveat: an asymmetric unit is not a biological assembly, and this module's own docstring records the case — 2AZ5's `assembly1` is a crystallographic tetramer of two independent TNF-alpha dimers, and scoring all four chains fuses sites across a packing contact, so always state which chains you meant.",
  async handler(input) {
    const partners = str(input, "partners_accession");
    const selftest = str(input, "selftest_dir");
    if (!(partners || selftest)) {
      throw new Error(
        "supply either partners_accession (to list partner complexes) or selftest_dir (to run the fixture harness)"
      );
    }
    const argv = partners
      ? ["--partners", partners]
      : ["--selftest", selftest ?? ""];
    const result = await run(
      micromamba(),
      pythonArgv(
        join(SKILLS_DIR, "pocket-scan", "interface_analysis.py"),
        argv
      ),
      { timeoutSeconds: DEFAULT_TIMEOUT_S }
    );
    return report("interface_analysis.py", result);
  },
  input_schema: {
    properties: {
      partners_accession: {
        description:
          "UniProt accession whose partner-containing complex structures should be listed, e.g. `P01375`.",
        type: "string",
      },
      selftest_dir: {
        description:
          "Directory to cache CIFs in while running the fixture harness. Diagnostic only.",
        type: "string",
      },
    },
    required: [],
    type: "object",
  },
  name: "interface_analysis",
};

const disorderScan: CustomToolSpec = {
  description:
    "Predict the intrinsic-disorder fraction for one or more UniProt accessions and report, per target, the fraction, the method that produced it, a confidence flag and the disordered regions. " +
    "Use it to fill `tractability.disorder_fraction` when you are not already running `pocket_scan` (whose disorder stage is the preferred source, because the Modal image carries metapredict). " +
    "A disorder fraction is not comparable to any other disorder fraction unless you carry `method` beside it: the Modal image returned 0.3419 on a target where a local environment without metapredict fell back to MobiDB and returned 0.277 — a 23% difference from the method alone. " +
    "The cardinal rule of this module is that a folded protein and a failed prediction must never look identical: 0.000 is a real answer (CDK2 and KRAS both score it) and failure is reported as FAILED, so never read a missing number as zero.",
  async handler(input) {
    const accessions = list(input, "accessions");
    if (accessions.length === 0) {
      throw new Error(
        "accessions is required and must name at least one UniProt accession"
      );
    }
    const envName = process.env.DISORDER_ENV ?? analysisEnvName();
    const result = await run(
      micromamba(),
      [
        "run",
        "-n",
        envName,
        "python",
        join(SKILLS_DIR, "pocket-scan", "disorder.py"),
        ...accessions,
      ],
      { timeoutSeconds: DEFAULT_TIMEOUT_S }
    );
    return report("disorder.py", result);
  },
  input_schema: {
    properties: {
      accessions: {
        description: 'UniProt accessions to score, e.g. `["P01116","P01375"]`.',
        items: { type: "string" },
        type: "array",
      },
    },
    required: ["accessions"],
    type: "object",
  },
  name: "disorder_scan",
};

// ---------------------------------------------------------------------------
// structure-select: Foldseek neighbour precedent
// ---------------------------------------------------------------------------

/**
 * `neighbour_precedent.py` merges a `.env` into the child environment and
 * raises FileNotFoundError when the path is absent — and its argparse default
 * is one contributor's absolute laptop path. Derive the repo's own `.env`
 * instead, and hand it an empty file rather than that default when there is
 * none, since PAPERCLIP_API_KEY already reaches the child through process.env.
 */
function envFileArg(): string {
  const repoEnv = join(repoRoot, ".env");
  if (existsSync(repoEnv)) {
    return repoEnv;
  }
  const staging = mkdtempSync(join(tmpdir(), "dossier-env-"));
  const empty = join(staging, "empty.env");
  writeFileSync(empty, "");
  return empty;
}

const neighbourPrecedent: CustomToolSpec = {
  description:
    "Structural-neighbour precedent: Foldseek the query structure, then ask Paperclip whether any neighbour fold has ever had a drug-like small molecule put into it, filling the dossier's `structural_neighbour_precedent` axis. " +
    "Use it to answer 'what other folds look like mine and has anyone drugged one', which is a different and much stronger question than Pfam family membership — TNF-alpha and IL-17A are both cytokines and share nothing mechanically. " +
    "`structure` must be a path to a PDB/CIF file this process can read, never a PDB ID or a URL, and `accession` is excluded from its own results. " +
    "Three Foldseek column caveats are already handled inside the script and you should not re-correct them: remote mode mislabels columns so `evalue` is really the probability and `bit_score` is really the E-value, a TM-score only exists via tmalign mode, and `target_id` is a filename-plus-title blob rather than an ID. The load-bearing caveat is in the output: ligands are attributed at entry level, so every holo count comes back twice — an entry-level upper bound and a single-protein-entry lower bound — and you must report the gap rather than picking one.",
  async handler(input) {
    const argv = [
      requiredStr(input, "structure"),
      requiredStr(input, "accession"),
      "--env-file",
      envFileArg(),
    ];
    const maxNeighbours = num(input, "max_neighbours");
    if (maxNeighbours !== undefined) {
      argv.push("--max-neighbours", String(maxNeighbours));
    }
    const minAlignmentLength = num(input, "min_alignment_length");
    if (minAlignmentLength !== undefined) {
      argv.push("--min-alignment-length", String(minAlignmentLength));
    }
    const cache = str(input, "cache");
    if (cache) {
      argv.push("--cache", cache);
    }
    if (bool(input, "no_tm")) {
      argv.push("--no-tm");
    }
    requireEnv(
      "PAPERCLIP_API_KEY",
      "The neighbour lookup shells out to the Paperclip CLI for each neighbour's holo counts."
    );
    const result = await run(
      micromamba(),
      pythonArgv(
        join(SKILLS_DIR, "structure-select", "neighbour_precedent.py"),
        argv
      ),
      { timeoutSeconds: NEIGHBOUR_TIMEOUT_S }
    );
    return report("neighbour_precedent.py", result);
  },
  input_schema: {
    properties: {
      accession: {
        description:
          "The query's UniProt accession. Excluded from its own results.",
        type: "string",
      },
      cache: {
        description: "Path to cache Foldseek results in across calls.",
        type: "string",
      },
      max_neighbours: {
        description: "Cap on distinct neighbour PDB entries carried forward.",
        type: "number",
      },
      min_alignment_length: {
        description:
          "Override the alignment-length floor. Leave unset for the verified default of 120 with automatic relaxation on short queries.",
        type: "number",
      },
      no_tm: {
        description:
          "Skip the tmalign pass. Faster, but then no TM-score is available at all.",
        type: "boolean",
      },
      structure: {
        description:
          "Path to the query chain or assembly as a PDB/CIF file. Never a PDB ID or a URL.",
        type: "string",
      },
    },
    required: ["structure", "accession"],
    type: "object",
  },
  name: "neighbour_precedent",
};

// ---------------------------------------------------------------------------
// Preflight
// ---------------------------------------------------------------------------

/**
 * Verify every credential and binary this agent needs, before the run starts.
 *
 * The per-handler checks above are already loud, but they fire at *use* time —
 * and `pocket_scan` is typically reached tens of minutes into a dossier, after
 * the precedent queries. A missing MODAL_BIN discovered there costs the whole
 * run. This runs at second zero instead.
 *
 * It deliberately collects *every* problem before throwing. Failing on the
 * first one turns "fix your setup" into a guess-and-recheck loop; one run
 * should tell you everything that is wrong.
 *
 * Set `DOSSIER_SKIP_PREFLIGHT=1` only to drive the Paperclip tools by hand on a
 * machine with no Modal — never for a real dossier, because the run will then
 * lose the computed-tractability axis at the point of use instead of here.
 */
export async function preflight(): Promise<void> {
  if (process.env.DOSSIER_SKIP_PREFLIGHT === "1") {
    return;
  }
  const problems: string[] = [];
  const check = (label: string, probe: () => unknown) => {
    try {
      probe();
    } catch (error) {
      problems.push(`  - ${label}: ${(error as Error).message}`);
    }
  };

  check("ANTHROPIC_API_KEY", () =>
    requireEnv(
      "ANTHROPIC_API_KEY",
      "It authenticates this process to the Agents API; without it there is no session at all."
    )
  );
  check("PAPERCLIP_API_KEY", () =>
    requireEnv(
      "PAPERCLIP_API_KEY",
      "It carries the entire retrieved-precedent axis."
    )
  );
  check("paperclip binary", paperclipBin);
  check("micromamba binary", micromamba);
  check("modal binary", modalBin);
  check("modal profile", modalProfile);

  // The conda env is the one thing that cannot be checked without running it:
  // micromamba resolving is not the same as the env existing with gemmi+numpy.
  let micromambaPath: string | undefined;
  try {
    micromambaPath = micromamba();
  } catch {
    micromambaPath = undefined;
  }
  if (micromambaPath) {
    const env = analysisEnvName();
    const probe = await run(
      micromambaPath,
      ["run", "-n", env, "python", "-c", "import gemmi, numpy"],
      { timeoutSeconds: 120 }
    );
    if (probe.code !== 0) {
      problems.push(
        `  - DRUGGABILITY_ENV: micromamba env "${env}" is missing or lacks gemmi/numpy, ` +
          "so cryptic_analysis, interface_analysis and neighbour_precedent cannot run. " +
          "Create it, or set DRUGGABILITY_ENV to the env that has them. " +
          `(${clip(probe.stderr).split("\n").slice(-3).join(" ").trim()})`
      );
    }
  }

  if (problems.length > 0) {
    throw new Error(
      `druggability-dossier preflight failed — ${problems.length} problem(s) ` +
        "must be fixed before a run can produce a complete dossier. Each one " +
        "below would otherwise surface as a missing axis mid-run, which is " +
        "indistinguishable from a target with no data:\n" +
        `${problems.join("\n")}\n\n` +
        "See managed/druggability-dossier/CREDENTIALS.md."
    );
  }
}

export const tools: CustomToolSpec[] = [
  paperclipSql,
  paperclipSearch,
  paperclipGrep,
  paperclipRead,
  pocketScan,
  crypticAnalysis,
  interfaceAnalysis,
  disorderScan,
  neighbourPrecedent,
];
