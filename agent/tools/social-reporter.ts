import { defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { loadCompiledAgent, runTask } from "../../lib/managed.ts";

const sessionIdState = defineState<string | undefined>(
  "social-reporter-session",
  () => undefined,
);

export default defineTool({
  description:
    "Produces the weekly X/LinkedIn engagement report (prototype, mock data): " +
    "per-platform top posts by engagement rate, exactly one data-backed content " +
    "recommendation, and two drafted posts queued for review. Provide a " +
    "complete, self-contained task; the specialist runs remotely and returns " +
    "its final answer.",
  inputSchema: {
    type: "object",
    properties: {
      task: { type: "string", description: "The full task for the specialist." },
    },
    required: ["task"],
  },
  async execute(input) {
    const { manifest, rubric, tools } = await loadCompiledAgent("social-reporter");
    const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
    const result = await runTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
    if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
    return result.text;
  },
});
