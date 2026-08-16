import { defineState } from "eve/context";
import { defineDynamic, defineTool } from "eve/tools";
import { allowed } from "@/lib/access.ts";
import { loadManagedAgent, runTask } from "@/lib/claude-managed-agent.ts";
import { acl } from "@/managed/hypothesis-generator/acl.ts";
// Static import so eve's bundler sees the custom-tool handlers: the deployed
// agent parks on `requires_action` until this process runs them.
import { tools } from "@/managed/hypothesis-generator/tools.ts";

const sessionIdState = defineState<string | undefined>(
  "hypothesis-generator-session",
  () => undefined
);

export default defineDynamic({
  events: {
    "session.started": (_event, ctx) =>
      allowed(ctx, acl)
        ? defineTool({
            description:
              "Turns a literature knowledge graph into ranked, evidence-traceable hypotheses, each with its supporting quotes, its weakest link, and the follow-up search that would settle it. Provide a complete, self-contained task; the " +
              "specialist runs remotely and returns its final answer.",
            inputSchema: {
              properties: {
                task: {
                  description: "The full task for the specialist.",
                  type: "string",
                },
              },
              required: ["task"],
              type: "object",
            },
            async execute(input) {
              // skipToolImport: tools come from the static import above;
              // dynamic import() inside eve's bundled runtime is not reliable.
              const { manifest, rubric } = await loadManagedAgent(
                "hypothesis-generator",
                { skipToolImport: true }
              );
              const previous =
                manifest.session_policy === "reuse"
                  ? sessionIdState.get()
                  : undefined;
              const result = await runTask({
                manifest,
                rubric,
                sessionId: previous,
                task: String(input.task),
                tools,
              });
              if (manifest.session_policy === "reuse") {
                sessionIdState.update(() => result.sessionId);
              }
              return result.text;
            },
          })
        : null,
  },
});
