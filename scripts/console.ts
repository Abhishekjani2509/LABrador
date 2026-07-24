/**
 * Test a deployed managed agent in the Claude Console — the visual session
 * runner at platform.claude.com — or run a single headless task.
 *
 *   bun run console <name>                 # print deployment info + open Console
 *   bun run console <name> -- --once "…"   # headless single task (smoke tests,
 *                                          #   custom-tool round-trips), print reply, exit
 *
 * The web Console can't answer custom tools (this process executes those), so
 * agents with custom tools park at requires_action there — use --once instead.
 * Outcome-mode agents (manifest.invocation === "outcome") treat the --once input
 * as an outcome description and run it against the compiled rubric.md.
 */
import { spawn } from "node:child_process";
import { loadCompiledAgent, runTask, type SessionEvent } from "@/lib/claude-managed-agent.ts";

const CONSOLE_URL = "https://platform.claude.com/workspaces/default/agent-quickstart/";

const args = process.argv.slice(2);
const name = args[0];
if (!name) {
  console.error('usage: bun run console <name> [-- --once "task"] [--quiet]');
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

if (!once) {
  if (!manifest.deployment?.agent_id) {
    console.error(`not deployed yet — run: bun run deploy ${name}`);
    process.exit(1);
  }
  if (tools.length > 0) {
    console.error(
      `note: ${tools.length} custom tool(s) run in-process — Console sessions will park on them; ` +
        `use \`bun run console ${name} -- --once "…"\` for those paths.`,
    );
  }
  console.error(`opening Console — pick agent ${manifest.deployment.agent_id} in the session runner`);
  spawn("open", [CONSOLE_URL], { stdio: "ignore", detached: true }).unref();
  process.exit(0);
}

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

const result = await runTask({ manifest, tools, task: once, rubric, onEvent: renderEvent });
if (result.outcome) console.error(`  · outcome: ${result.outcome.result}`);
console.error(`  · trace: https://platform.claude.com/workspaces/default/sessions/${result.sessionId}`);
console.log(result.text);
