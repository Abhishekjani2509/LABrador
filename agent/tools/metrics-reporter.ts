import { defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { loadCompiledAgent, runTask } from "@/lib/claude-managed-agent.ts";

const sessionIdState = defineState<string | undefined>(
  "metrics-reporter-session",
  () => undefined,
);

export default defineTool({
  description:
    "Turns a weekly SaaS metrics CSV into a week-over-week growth report " +
    "with activation rate, churn trend, and dollar-quantified incident " +
    "callouts. Provide a complete, self-contained task; the specialist " +
    "runs remotely and returns its final answer.",
  inputSchema: {
    type: "object",
    properties: {
      task: { type: "string", description: "The full task for the specialist." },
    },
    required: ["task"],
  },
  async execute(input) {
    const { manifest, rubric, tools } = await loadCompiledAgent("metrics-reporter", { skipToolImport: true });
    const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
    const result = await runTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
    if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
    return result.text;
  },
});
