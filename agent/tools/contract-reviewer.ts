import { defineTool } from "eve/tools";
import { defineState } from "eve/context";
import { loadCompiledAgent, runTask } from "../../lib/managed.ts";

const sessionIdState = defineState<string | undefined>(
  "contract-reviewer-session",
  () => undefined,
);

export default defineTool({
  description:
    "Reviews client contracts (MSAs and similar) and returns a structured " +
    "extraction of parties, key dates, obligations, and severity-ranked " +
    "red flags. Provide a complete, self-contained task; the specialist " +
    "runs remotely and returns its final answer.",
  inputSchema: {
    type: "object",
    properties: {
      task: { type: "string", description: "The full task for the specialist." },
    },
    required: ["task"],
  },
  async execute(input) {
    const { manifest, rubric, tools } = await loadCompiledAgent("contract-reviewer");
    const previous = manifest.session_policy === "reuse" ? sessionIdState.get() : undefined;
    const result = await runTask({ manifest, tools, rubric, task: String(input.task), sessionId: previous });
    if (manifest.session_policy === "reuse") sessionIdState.update(() => result.sessionId);
    return result.text;
  },
});
