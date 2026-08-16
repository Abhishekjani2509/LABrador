import { defineState } from "eve/context";
import { defineDynamic, defineTool } from "eve/tools";
import { allowed } from "@/lib/access.ts";
import { loadManagedAgent, runTask } from "@/lib/claude-managed-agent.ts";
import { acl } from "@/managed/druggability-dossier/acl.ts";
// Static import so eve's bundler sees the custom-tool handlers.
import { preflight, tools } from "@/managed/druggability-dossier/tools.ts";

const sessionIdState = defineState<string | undefined>(
  "druggability-dossier-session",
  () => undefined
);

// One dossier run fans out to a Modal pocket scan (up to 30 minutes) plus
// several Paperclip queries, all answered by local handlers. The runtime's
// 10-minute default would abort mid-scan.
const TASK_TIMEOUT_MS = 45 * 60 * 1000;

export default defineDynamic({
  events: {
    "session.started": (_event, ctx) =>
      allowed(ctx, acl)
        ? defineTool({
            description:
              "Assembles small-molecule druggability evidence for one protein target — retrieved precedent and computed tractability as two separate, non-averaged axes — and returns a single JSON dossier. Provide a complete, self-contained task; the specialist runs remotely and returns its final answer.",
            async execute(input) {
              // Every credential and binary is checked here, before the
              // session is created — a missing one costs seconds instead of
              // surfacing forty minutes in as an axis that silently went null.
              await preflight();
              // skipToolImport: tools come from the static import above;
              // dynamic import() inside eve's bundled runtime is not reliable.
              const { manifest, rubric } = await loadManagedAgent(
                "druggability-dossier",
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
                timeoutMs: TASK_TIMEOUT_MS,
                tools,
              });
              if (manifest.session_policy === "reuse") {
                sessionIdState.update(() => result.sessionId);
              }
              return result.text;
            },
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
          })
        : null,
  },
});
