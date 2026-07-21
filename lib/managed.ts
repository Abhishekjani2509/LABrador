/**
 * Runtime for calling deployed Claude Managed Agents.
 *
 * One loop, used by both `scripts/run-agent.ts` (CLI) and the compiled eve
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
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  handler: (input: Record<string, unknown>) => Promise<string> | string;
}

/** Shape of `agent/tools/<name>/manifest.json`. */
export interface AgentManifest {
  name: string;
  description?: string;
  /** Model for the managed agent, e.g. "claude-sonnet-5". */
  model: string;
  /** "message" = conversational turns; "outcome" = rubric-graded deliverable. */
  invocation: "message" | "outcome";
  /** "reuse" = one MA session per caller session; "fresh" = new session per task. */
  session_policy: "reuse" | "fresh";
  /** Outcome mode only. Default 3, max 20. */
  max_iterations?: number;
  /** Remote streamable-HTTP MCP servers, passed through to the agent config. */
  mcp_servers?: unknown[];
  /** One line per shared-runtime fix made during the compile session. */
  runtime_notes?: string[];
  /** Written by `scripts/deploy-agent.ts`. Absent until first deploy. */
  deployment?: {
    agent_id: string;
    agent_version: number;
    /** skills dir name → uploaded skill. */
    skills: Record<string, { skill_id: string; version: string; hash: string }>;
    system_hash: string;
    tools_hash: string;
  };
  /** Written by `/make-managed` at compile time; basis for Claude-merge. */
  compiled_hashes?: Record<string, string>;
}

export interface RunTaskOptions {
  manifest: AgentManifest;
  tools?: CustomToolSpec[];
  /** The task text: a user message, or the outcome description in outcome mode. */
  task: string;
  /** Outcome mode: rubric markdown (from the compiled rubric.md). */
  rubric?: string;
  /** Reuse an existing session (session_policy "reuse"); omit to create one. */
  sessionId?: string;
  /** Observe every stream event (CLI rendering, transcript capture). */
  onEvent?: (event: SessionEvent) => void;
  /** Hard cap on one task, in milliseconds. Default 10 minutes. */
  timeoutMs?: number;
  client?: Anthropic;
}

export interface RunTaskResult {
  /** Final agent message text (or the last one before end-turn idle). */
  text: string;
  /** Session ID — stash it to reuse the session for follow-up tasks. */
  sessionId: string;
  /** Outcome mode: the grader's final result, e.g. "satisfied". */
  outcome?: { result: string; explanation?: string };
}

/** Loosely-typed session stream event (the SDK streams these as unions). */
export type SessionEvent = {
  type: string;
  id?: string;
  [key: string]: unknown;
};

// ---------------------------------------------------------------------------
// Client + environment
// ---------------------------------------------------------------------------

export function makeClient(): Anthropic {
  const apiKey = process.env.ANTHROPIC_API_KEY ?? readEnvFile("ANTHROPIC_API_KEY");
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY is not set (see .env.example)");
  return new Anthropic({ apiKey });
}

/** Minimal .env reader so the CLIs work right after `cp .env.example .env`. */
function readEnvFile(key: string): string | undefined {
  const envPath = join(repoRoot, ".env");
  if (!existsSync(envPath)) return undefined;
  const line = readFileSync(envPath, "utf8")
    .split("\n")
    .find((l) => l.startsWith(`${key}=`));
  return line?.slice(key.length + 1).trim().replace(/^["']|["']$/g, "") || undefined;
}

const SHARED_ENVIRONMENT_NAME = "mvp-shared";
let cachedEnvironmentId: string | undefined;

/**
 * Sessions need an environment (the sandbox config). The starter uses one
 * shared cloud environment, found by name or created on first use.
 */
export async function getOrCreateEnvironment(client: Anthropic): Promise<string> {
  if (cachedEnvironmentId) return cachedEnvironmentId;
  for await (const env of client.beta.environments.list()) {
    if (env.name === SHARED_ENVIRONMENT_NAME && env.archived_at === null) {
      cachedEnvironmentId = env.id;
      return env.id;
    }
  }
  const created = await client.beta.environments.create({ name: SHARED_ENVIRONMENT_NAME });
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
  const collapsed = task.replace(/[\p{Cc}\p{Cf}]+/gu, " ").replace(/\s+/g, " ").trim();
  return collapsed.length > maxLen ? `${collapsed.slice(0, maxLen - 1)}…` : collapsed;
}

// ---------------------------------------------------------------------------
// The loop
// ---------------------------------------------------------------------------

/**
 * Run one task against a deployed managed agent and wait for the result.
 */
export async function runTask(opts: RunTaskOptions): Promise<RunTaskResult> {
  const client = opts.client ?? makeClient();
  const deployment = opts.manifest.deployment;
  if (!deployment?.agent_id) {
    throw new Error(
      `"${opts.manifest.name}" has no deployment.agent_id — run: npm run deploy-agent ${opts.manifest.name}`,
    );
  }

  let sessionId = opts.sessionId;
  if (!sessionId) {
    const environmentId = await getOrCreateEnvironment(client);
    const session = await client.beta.sessions.create({
      agent: deployment.agent_id,
      environment_id: environmentId,
      title: `${opts.manifest.name}: ${titleSnippet(opts.task)}`,
    });
    sessionId = session.id;
  }

  // Kick off the turn before consuming the stream.
  if (opts.manifest.invocation === "outcome") {
    if (!opts.rubric) throw new Error(`outcome mode requires a rubric (rubric.md)`);
    await client.beta.sessions.events.send(sessionId, {
      events: [
        {
          type: "user.define_outcome",
          description: opts.task,
          rubric: { type: "text", content: opts.rubric },
          max_iterations: opts.manifest.max_iterations ?? 3,
        },
      ],
    });
  } else {
    await client.beta.sessions.events.send(sessionId, {
      events: [{ type: "user.message", content: [{ type: "text", text: opts.task }] }],
    });
  }

  return consumeUntilEndTurn({ client, sessionId, opts });
}

async function consumeUntilEndTurn(args: {
  client: Anthropic;
  sessionId: string;
  opts: RunTaskOptions;
}): Promise<RunTaskResult> {
  const { client, sessionId, opts } = args;
  const toolsByName = new Map((opts.tools ?? []).map((t) => [t.name, t]));
  const deadline = Date.now() + (opts.timeoutMs ?? 10 * 60 * 1000);

  let lastMessage = "";
  // Outcome mode: the grader inspects sandbox files, not the reply — so
  // agents commonly emit the real deliverable as one agent.message, then a
  // short wrap-up ("all criteria met...") as the true last message once the
  // grader reports satisfied. Taking strictly the last message clobbers the
  // deliverable with that wrap-up. Track the longest message seen instead;
  // in practice the deliverable is far longer than any status remark.
  // Message mode has no such wrap-up phase, so it keeps last-message semantics.
  let longestMessage = "";
  let outcome: RunTaskResult["outcome"];
  // agent.custom_tool_use events by event ID, so requires_action can find
  // the tool name + input for each blocking event_id.
  const pendingToolUses = new Map<string, { name: string; input: Record<string, unknown> }>();

  const stream = await client.beta.sessions.events.stream(sessionId);

  for await (const raw of stream) {
    if (Date.now() > deadline) {
      throw new Error(`runTask timed out after ${opts.timeoutMs ?? 600000}ms (session ${sessionId})`);
    }
    const event = raw as unknown as SessionEvent;
    opts.onEvent?.(event);

    switch (event.type) {
      case "agent.message": {
        const content = event.content as Array<{ type: string; text?: string }> | undefined;
        const text = (content ?? [])
          .filter((block) => block.type === "text" && block.text)
          .map((block) => block.text)
          .join("\n");
        if (text) {
          lastMessage = text;
          if (text.length > longestMessage.length) longestMessage = text;
        }
        break;
      }
      case "agent.custom_tool_use": {
        if (event.id) {
          pendingToolUses.set(event.id, {
            name: String(event.name ?? ""),
            input: (event.input ?? {}) as Record<string, unknown>,
          });
        }
        break;
      }
      case "span.outcome_evaluation_end": {
        outcome = {
          result: String(event.result ?? ""),
          explanation: event.explanation ? String(event.explanation) : undefined,
        };
        break;
      }
      case "session.status_idle": {
        const stopReason = event.stop_reason as
          | { type: string; event_ids?: string[] }
          | undefined;
        if (stopReason?.type === "requires_action") {
          for (const eventId of stopReason.event_ids ?? []) {
            const use = pendingToolUses.get(eventId);
            const result = await executeCustomTool(toolsByName, eventId, use);
            await client.beta.sessions.events.send(sessionId, {
              events: [
                {
                  type: "user.custom_tool_result",
                  custom_tool_use_id: eventId,
                  content: [{ type: "text", text: result }],
                },
              ],
            });
            pendingToolUses.delete(eventId);
          }
          break; // session resumes; keep streaming
        }
        // end_turn (or anything else terminal-ish): we're done.
        return { text: finalText(opts, lastMessage, longestMessage), sessionId, outcome };
      }
      case "session.status_terminated":
        throw new Error(`session ${sessionId} terminated: ${JSON.stringify(event.error ?? "")}`);
      default:
        break;
    }
  }

  return { text: finalText(opts, lastMessage, longestMessage), sessionId, outcome };
}

function finalText(opts: RunTaskOptions, lastMessage: string, longestMessage: string): string {
  return opts.manifest.invocation === "outcome" ? longestMessage || lastMessage : lastMessage;
}

async function executeCustomTool(
  toolsByName: Map<string, CustomToolSpec>,
  eventId: string,
  use: { name: string; input: Record<string, unknown> } | undefined,
): Promise<string> {
  if (!use) return `Error: no agent.custom_tool_use event seen for ${eventId}`;
  const tool = toolsByName.get(use.name);
  if (!tool) return `Error: no local handler registered for custom tool "${use.name}"`;
  try {
    return await tool.handler(use.input);
  } catch (error) {
    return `Error executing ${use.name}: ${error instanceof Error ? error.message : String(error)}`;
  }
}

// ---------------------------------------------------------------------------
// Artifact loading (used by run-agent.ts and the eve wrappers)
// ---------------------------------------------------------------------------

import { readFile } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The source-tree location works when running from tsx CLIs; when eve bundles
 * this module, import.meta.url points into the build output, so fall back to
 * walking up from cwd to the repo root (the dir holding managed/ + package.json).
 */
function findRepoRoot(): string {
  const fromSource = join(dirname(fileURLToPath(import.meta.url)), "..");
  if (existsSync(join(fromSource, "managed"))) return fromSource;
  let dir = process.cwd();
  for (;;) {
    if (existsSync(join(dir, "managed")) && existsSync(join(dir, "package.json"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return fromSource;
    dir = parent;
  }
}
export const repoRoot = findRepoRoot();

export interface CompiledAgent {
  dir: string;
  manifest: AgentManifest;
  instructions: string;
  rubric?: string;
  tools: CustomToolSpec[];
}

/**
 * Load a compiled artifact: data files from `agent/tools/<name>/`, custom-tool
 * handlers from `agent/lib/<name>/tools.ts`. (Handlers live under `agent/lib/`
 * because eve requires every module under `agent/tools/**` to *be* a tool.)
 */
export async function loadCompiledAgent(name: string): Promise<CompiledAgent> {
  const dir = join(repoRoot, "agent", "tools", name);
  const manifestPath = join(dir, "manifest.json");
  if (!existsSync(manifestPath)) {
    throw new Error(`no compiled agent at agent/tools/${name}/ (missing manifest.json)`);
  }
  const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as AgentManifest;
  const instructions = await readFile(join(dir, "instructions.md"), "utf8");
  const rubricPath = join(dir, "rubric.md");
  const rubric = existsSync(rubricPath) ? await readFile(rubricPath, "utf8") : undefined;
  let tools: CustomToolSpec[] = [];
  const toolsPath = join(repoRoot, "agent", "lib", name, "tools.ts");
  if (existsSync(toolsPath)) {
    const mod = (await import(toolsPath)) as { tools?: CustomToolSpec[] };
    tools = mod.tools ?? [];
  }
  return { dir, manifest, instructions, rubric, tools };
}
