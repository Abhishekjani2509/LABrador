/**
 * Chat with a deployed managed agent from your terminal — the callable
 * endpoint, before any router exists.
 *
 *   bun run run-agent <name>                 # interactive chat (session reused)
 *   bun run run-agent <name> -- --once "…"   # single task, print reply, exit
 *
 * Outcome-mode agents (manifest.invocation === "outcome") treat each input
 * as an outcome description and run it against the compiled rubric.md.
 */
import { createInterface } from "node:readline/promises";
import { loadCompiledAgent, runTask, type SessionEvent } from "@/lib/claude-managed-agent.ts";

const args = process.argv.slice(2);
const name = args[0];
if (!name) {
  console.error('usage: bun run run-agent <name> [-- --once "task"] [--quiet]');
  process.exit(1);
}
const onceIndex = args.indexOf("--once");
const once = onceIndex !== -1 ? args[onceIndex + 1] : undefined;
const quiet = args.includes("--quiet");

const compiled = await loadCompiledAgent(name);
const { manifest, rubric, tools } = compiled;

console.error(
  `[${manifest.name}] agent ${manifest.deployment?.agent_id ?? "(not deployed)"} · ` +
    `${manifest.invocation} mode · ${tools.length} custom tool(s)`,
);

function renderEvent(event: SessionEvent) {
  if (quiet) return;
  switch (event.type) {
    case "session.status_running":
      console.error("  · running…");
      break;
    case "agent.tool_use":
      console.error(`  · tool: ${String(event.name ?? "?")}`);
      break;
    case "agent.custom_tool_use":
      console.error(`  · custom tool: ${String(event.name ?? "?")} ${JSON.stringify(event.input ?? {})}`);
      break;
    case "span.outcome_evaluation_start":
      console.error(`  · grader: iteration ${String(event.iteration)}`);
      break;
    case "span.outcome_evaluation_end":
      console.error(`  · grader: ${String(event.result)}`);
      break;
    default:
      break;
  }
}

let sessionId: string | undefined;

async function ask(task: string) {
  const result = await runTask({
    manifest,
    tools,
    task,
    rubric,
    sessionId: manifest.session_policy === "reuse" ? sessionId : undefined,
    onEvent: renderEvent,
  });
  sessionId = result.sessionId;
  if (result.outcome) console.error(`  · outcome: ${result.outcome.result}`);
  console.log(result.text);
}

if (once) {
  await ask(once);
} else {
  const readline = createInterface({ input: process.stdin, output: process.stdout });
  console.error("(interactive — ctrl-d to exit)");
  for (;;) {
    const line = (await readline.question("> ")).trim();
    if (!line) continue;
    await ask(line);
  }
}
