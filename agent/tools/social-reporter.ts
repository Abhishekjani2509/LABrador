import { defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { loadCompiledAgent, runTask } from "@/lib/claude-managed-agent.ts";
import { tools } from "@/agent/compiled/social-reporter/tools.ts";

const sessionIdState = defineState<string | undefined>(
  "social-reporter-session",
  () => undefined,
);

export default defineTool({
  description:
    "Produces the weekly X/LinkedIn engagement report (prototype, mock data): " +
    "per-platform top posts by engagement rate, exactly one data-backed content " +
    "recommendation, two drafted posts queued for review, and a queue status " +
    "listing of everything pending. Can also cancel a queued post on request. " +
    "Provide a complete, self-contained task; the specialist runs remotely and " +
    "returns its final answer.",
  inputSchema: {
    type: "object",
    properties: {
      task: { type: "string", description: "The full task for the specialist." },
    },
    required: ["task"],
  },
  async execute(input) {
    const { manifest, rubric } = await loadCompiledAgent("social-reporter", { skipToolImport: true });
    const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
    const result = await runTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
    if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
    return result.text;
  },
});
