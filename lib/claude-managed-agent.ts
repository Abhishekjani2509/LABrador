/**
 * Runtime for calling deployed Claude Managed Agents.
 *
 * One loop, used by both `scripts/console.ts` (CLI) and the compiled eve
 * tool wrappers in `agent/tools/<name>/index.ts`:
 *
 *   get-or-create session → send user event → consume SSE →
 *   answer custom-tool calls in-process → return the final agent message.
 *
 * Custom tools are the interesting part: when the managed agent calls one,
 * the session parks at `status_idle` with `stop_reason: requires_action`
 * until *this process* runs the matching handler from the compiled
 * `tools.ts` and posts a `user.custom_tool_result`. The process running
 * this file is the tool executor — no extra infrastructure.
 */
import Anthropic from "@anthropic-ai/sdk";

// ---------------------------------------------------------------------------
// Types shared with compiled artifacts
// ---------------------------------------------------------------------------

/** One custom tool: declaration (sent to the agent) + local handler. */
export interface CustomToolSpec {
  description: string;
  handler: (input: Record<string, unknown>) => Promise<string> | string;
  input_schema: Record<string, unknown>;
  name: string;
}

/** Shape of `agent/tools/<name>/manifest.json`. */
export interface AgentManifest {
  /** Written by `/make-managed` at compile time; basis for Claude-merge. */
  compiled_hashes?: Record<string, string>;
  /** Written by `scripts/deploy.ts`. Absent until first deploy. */
  deployment?: {
    agent_id: string;
    agent_version: number;
    /** skills dir name → uploaded skill. */
    skills: Record<string, { skill_id: string; version: string; hash: string }>;
    system_hash: string;
    tools_hash: string;
  };
  description?: string;
  /** "message" = conversational turns; "outcome" = rubric-graded deliverable. */
  invocation: "message" | "outcome";
  /** Outcome mode only. Default 3, max 20. */
  max_iterations?: number;
  /** Remote streamable-HTTP MCP servers, passed through to the agent config. */
  mcp_servers?: unknown[];
  /** Model for the managed agent, e.g. "claude-sonnet-5". */
  model: string;
  name: string;
  /** One line per shared-runtime fix made during the compile session. */
  runtime_notes?: string[];
  /** "reuse" = one MA session per caller session; "fresh" = new session per task. */
  session_policy: "reuse" | "fresh";
  /** Vault IDs holding MCP credentials; attached to every session at create. */
  vault_ids?: string[];
}

export interface RunTaskOptions {
  client?: Anthropic;
  manifest: AgentManifest;
  /** Observe every stream event (CLI rendering, transcript capture). */
  onEvent?: (event: SessionEvent) => void;
  /** Outcome mode: rubric markdown (from the compiled rubric.md). */
  rubric?: string;
  /** Reuse an existing session (session_policy "reuse"); omit to create one. */
  sessionId?: string;
  /** The task text: a user message, or the outcome description in outcome mode. */
  task: string;
  /** Hard cap on one task, in milliseconds. Default 10 minutes. */
  timeoutMs?: number;
  tools?: CustomToolSpec[];
}

export interface RunTaskResult {
  /** Outcome mode: the grader's final result, e.g. "satisfied". */
  outcome?: { result: string; explanation?: string };
  /** Session ID — stash it to reuse the session for follow-up tasks. */
  sessionId: string;
  /** Final agent message text (or the last one before end-turn idle). */
  text: string;
}

/** Loosely-typed session stream event (the SDK streams these as unions). */
export interface SessionEvent {
  id?: string;
  type: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Client + environment
// ---------------------------------------------------------------------------

export function makeClient(): Anthropic {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("ANTHROPIC_API_KEY is not set (see .env.example)");
  }
  return new Anthropic({ apiKey });
}

const SHARED_ENVIRONMENT_NAME = "mvp-shared";
let cachedEnvironmentId: string | undefined;

/**
 * Sessions need an environment (the sandbox config). The starter uses one
 * shared cloud environment, found by name or created on first use.
 */
export async function getOrCreateEnvironment(
  client: Anthropic
): Promise<string> {
  if (cachedEnvironmentId) {
    return cachedEnvironmentId;
  }
  for await (const env of client.beta.environments.list()) {
    if (env.name === SHARED_ENVIRONMENT_NAME && env.archived_at === null) {
      cachedEnvironmentId = env.id;
      return env.id;
    }
  }
  const created = await client.beta.environments.create({
    name: SHARED_ENVIRONMENT_NAME,
  });
  cachedEnvironmentId = created.id;
  return created.id;
}

/**
 * Session titles reject Unicode control/format characters (e.g. newlines).
 * Task text is often a pasted document, so collapse all whitespace/control
 * characters before truncating rather than slicing the raw string — a raw
 * slice can land mid-document and carry a newline straight into the title.
 */
function titleSnippet(task: string, maxLen = 60): string {
  const collapsed = task
    .replace(/[\p{Cc}\p{Cf}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  return collapsed.length > maxLen
    ? `${collapsed.slice(0, maxLen - 1)}…`
    : collapsed;
}

// ---------------------------------------------------------------------------
// The loop
// ---------------------------------------------------------------------------

/**
 * Run one task against a deployed managed agent and wait for the result.
 */
export async function runTask(opts: RunTaskOptions): Promise<RunTaskResult> {
  const client = opts.client ?? makeClient();
  const { deployment } = opts.manifest;
  if (!deployment?.agent_id) {
    throw new Error(
      `"${opts.manifest.name}" has no deployment.agent_id — run: bun run deploy ${opts.manifest.name}`
    );
  }

  let { sessionId } = opts;
  if (!sessionId) {
    const environmentId = await getOrCreateEnvironment(client);
    const session = await client.beta.sessions.create({
      agent: deployment.agent_id,
      environment_id: environmentId,
      title: `${opts.manifest.name}: ${titleSnippet(opts.task)}`,
      ...(opts.manifest.vault_ids?.length
        ? { vault_ids: opts.manifest.vault_ids }
        : {}),
    });
    sessionId = session.id;
  }

  // Kick off the turn before consuming the stream.
  if (opts.manifest.invocation === "outcome") {
    if (!opts.rubric) {
      throw new Error("outcome mode requires a rubric (rubric.md)");
    }
    await client.beta.sessions.events.send(sessionId, {
      events: [
        {
          description: opts.task,
          max_iterations: opts.manifest.max_iterations ?? 3,
          rubric: { content: opts.rubric, type: "text" },
          type: "user.define_outcome",
        },
      ],
    });
  } else {
    await client.beta.sessions.events.send(sessionId, {
      events: [
        { content: [{ text: opts.task, type: "text" }], type: "user.message" },
      ],
    });
  }

  return consumeUntilEndTurn({ client, opts, sessionId });
}

interface StreamState {
  lastMessage: string;
  // Outcome mode: the grader inspects sandbox files, not the reply — so
  // agents commonly emit the real deliverable as one agent.message, then a
  // short wrap-up ("all criteria met...") as the true last message once the
  // grader reports satisfied. Taking strictly the last message clobbers the
  // deliverable with that wrap-up. Track the longest message seen instead;
  // in practice the deliverable is far longer than any status remark.
  // Message mode has no such wrap-up phase, so it keeps last-message semantics.
  longestMessage: string;
  outcome?: RunTaskResult["outcome"];
  // Built-in/MCP tool uses that evaluated to permission "ask" — these block the
  // session until a user.tool_confirmation, not a custom_tool_result. This
  // runtime is headless (no human to ask), so it denies with an explanatory
  // message rather than crashing: permission grants belong in the deployed
  // agent config (mcp_toolset permission_policy "always_allow"), set at
  // compile time by the founder.
  pendingPermissionAsks: Set<string>;
  // agent.custom_tool_use events by event ID, so requires_action can find
  // the tool name + input for each blocking event_id.
  pendingToolUses: Map<
    string,
    { name: string; input: Record<string, unknown> }
  >;
}

async function consumeUntilEndTurn(args: {
  client: Anthropic;
  sessionId: string;
  opts: RunTaskOptions;
}): Promise<RunTaskResult> {
  const { client, sessionId, opts } = args;
  const toolsByName = new Map((opts.tools ?? []).map((t) => [t.name, t]));
  const deadline = Date.now() + (opts.timeoutMs ?? 10 * 60 * 1000);
  const state: StreamState = {
    lastMessage: "",
    longestMessage: "",
    pendingPermissionAsks: new Set(),
    pendingToolUses: new Map(),
  };

  const stream = await client.beta.sessions.events.stream(sessionId);

  for await (const raw of stream) {
    if (Date.now() > deadline) {
      throw new Error(
        `runTask timed out after ${opts.timeoutMs ?? 600_000}ms (session ${sessionId})`
      );
    }
    const event = raw as unknown as SessionEvent;
    opts.onEvent?.(event);

    if (event.type === "session.status_terminated") {
      throw new Error(
        `session ${sessionId} terminated: ${JSON.stringify(event.error ?? "")}`
      );
    }
    if (event.type !== "session.status_idle") {
      trackEvent(event, state);
      continue;
    }
    const stopReason = event.stop_reason as
      | { type: string; event_ids?: string[] }
      | undefined;
    if (stopReason?.type !== "requires_action") {
      // end_turn (or anything else terminal-ish): we're done.
      return {
        outcome: state.outcome,
        sessionId,
        text: finalText(opts, state),
      };
    }
    await answerBlockingEvents({
      client,
      eventIds: stopReason.event_ids ?? [],
      sessionId,
      state,
      toolsByName,
    });
    // session resumes; keep streaming
  }

  return { outcome: state.outcome, sessionId, text: finalText(opts, state) };
}

function trackEvent(event: SessionEvent, state: StreamState): void {
  switch (event.type) {
    case "agent.message": {
      const content = event.content as
        | Array<{ type: string; text?: string }>
        | undefined;
      const text = (content ?? [])
        .filter((block) => block.type === "text" && block.text)
        .map((block) => block.text)
        .join("\n");
      if (text) {
        state.lastMessage = text;
        if (text.length > state.longestMessage.length) {
          state.longestMessage = text;
        }
      }
      break;
    }
    case "agent.custom_tool_use": {
      if (event.id) {
        state.pendingToolUses.set(event.id, {
          input: (event.input ?? {}) as Record<string, unknown>,
          name: String(event.name ?? ""),
        });
      }
      break;
    }
    case "agent.tool_use":
    case "agent.mcp_tool_use": {
      if (event.id && event.evaluated_permission === "ask") {
        state.pendingPermissionAsks.add(event.id);
      }
      break;
    }
    case "span.outcome_evaluation_end": {
      state.outcome = {
        explanation: event.explanation ? String(event.explanation) : undefined,
        result: String(event.result ?? ""),
      };
      break;
    }
    default:
      break;
  }
}

/** Answer every event blocking a requires_action idle in one batched send. */
async function answerBlockingEvents(args: {
  client: Anthropic;
  eventIds: string[];
  sessionId: string;
  state: StreamState;
  toolsByName: Map<string, CustomToolSpec>;
}): Promise<void> {
  const { client, eventIds, sessionId, state, toolsByName } = args;
  const events = await Promise.all(
    eventIds.map((eventId) => answerFor(eventId, state, toolsByName))
  );
  if (events.length > 0) {
    await client.beta.sessions.events.send(sessionId, { events });
  }
}

async function answerFor(
  eventId: string,
  state: StreamState,
  toolsByName: Map<string, CustomToolSpec>
) {
  if (state.pendingPermissionAsks.has(eventId)) {
    state.pendingPermissionAsks.delete(eventId);
    return {
      deny_message:
        "This caller is headless and cannot approve tool permissions. " +
        "Proceed without this tool; if it is essential, the agent's " +
        "toolset needs permission_policy always_allow at deploy time.",
      result: "deny" as const,
      tool_use_id: eventId,
      type: "user.tool_confirmation" as const,
    };
  }
  const use = state.pendingToolUses.get(eventId);
  state.pendingToolUses.delete(eventId);
  const result = await executeCustomTool(toolsByName, eventId, use);
  return {
    content: [{ text: result, type: "text" as const }],
    custom_tool_use_id: eventId,
    type: "user.custom_tool_result" as const,
  };
}

function finalText(opts: RunTaskOptions, state: StreamState): string {
  return opts.manifest.invocation === "outcome"
    ? state.longestMessage || state.lastMessage
    : state.lastMessage;
}

async function executeCustomTool(
  toolsByName: Map<string, CustomToolSpec>,
  eventId: string,
  use: { name: string; input: Record<string, unknown> } | undefined
): Promise<string> {
  if (!use) {
    return `Error: no agent.custom_tool_use event seen for ${eventId}`;
  }
  const tool = toolsByName.get(use.name);
  if (!tool) {
    return `Error: no local handler registered for custom tool "${use.name}"`;
  }
  try {
    return await tool.handler(use.input);
  } catch (error) {
    return `Error executing ${use.name}: ${error instanceof Error ? error.message : String(error)}`;
  }
}

// ---------------------------------------------------------------------------
// Artifact loading (used by console.ts and the eve wrappers)
// ---------------------------------------------------------------------------

import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import dotenvx from "@dotenvx/dotenvx";

/**
 * The source-tree location works when running from tsx CLIs; when eve bundles
 * this module, import.meta.url points into the build output, so fall back to
 * walking up from cwd to the repo root (the dir holding prototypes/ + package.json).
 */
function findRepoRoot(): string {
  const fromSource = join(dirname(fileURLToPath(import.meta.url)), "..");
  if (existsSync(join(fromSource, "prototypes"))) {
    return fromSource;
  }
  let dir = process.cwd();
  for (;;) {
    if (
      existsSync(join(dir, "prototypes")) &&
      existsSync(join(dir, "package.json"))
    ) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) {
      return fromSource;
    }
    dir = parent;
  }
}
export const repoRoot = findRepoRoot();

// Load the repo-root .env so the CLIs work right after `cp .env.example .env`.
dotenvx.config({
  ignore: ["MISSING_ENV_FILE"],
  path: join(repoRoot, ".env"),
  quiet: true,
});

export interface CompiledAgent {
  dir: string;
  instructions: string;
  manifest: AgentManifest;
  rubric?: string;
  tools: CustomToolSpec[];
}

/**
 * Load a compiled artifact from `agent/compiled/<name>/` (manifest,
 * instructions, rubric, skills, tools.ts — one dir per agent). The dir lives
 * outside eve's authored slots on purpose: eve requires modules under
 * `agent/tools/**` to BE tools and rejects data files under `agent/lib/**`.
 *
 * `skipToolImport`: the eve tool wrappers import their `tools.ts` statically
 * (so the bundler sees it) and pass handlers via `runTask`; they set this to
 * avoid a runtime dynamic import inside the bundled app. CLIs (tsx) leave it
 * unset and get handlers loaded dynamically.
 */
export async function loadCompiledAgent(
  name: string,
  opts?: { skipToolImport?: boolean }
): Promise<CompiledAgent> {
  const dir = join(repoRoot, "agent", "compiled", name);
  const manifestPath = join(dir, "manifest.json");
  if (!existsSync(manifestPath)) {
    throw new Error(
      `no compiled agent at agent/compiled/${name}/ (missing manifest.json)`
    );
  }
  const manifest = JSON.parse(
    await readFile(manifestPath, "utf8")
  ) as AgentManifest;
  const instructions = await readFile(join(dir, "instructions.md"), "utf8");
  const rubricPath = join(dir, "rubric.md");
  const rubric = existsSync(rubricPath)
    ? await readFile(rubricPath, "utf8")
    : undefined;
  let tools: CustomToolSpec[] = [];
  const toolsPath = join(dir, "tools.ts");
  if (!opts?.skipToolImport && existsSync(toolsPath)) {
    const mod = (await import(toolsPath)) as { tools?: CustomToolSpec[] };
    tools = mod.tools ?? [];
  }
  return { dir, instructions, manifest, rubric, tools };
}
