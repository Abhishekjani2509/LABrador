import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { repoRoot, type CustomToolSpec } from "../../../lib/managed.ts";

/**
 * These handlers shell out to the founder's real prototype scripts under
 * managed/social-reporter/scripts/ — same fixture data, same mock publish
 * queue, not a reimplementation. They run in this process (the tool
 * executor), which has repo access; the deployed agent's remote sandbox
 * does not.
 */
const SCRIPTS_DIR = join(repoRoot, "managed", "social-reporter", "scripts");
const OUTBOX_PATH = join(repoRoot, "managed", "social-reporter", "data", "outbox.json");

export const tools: CustomToolSpec[] = [
  {
    name: "read_posts",
    description:
      "Reads the founder's mock X/LinkedIn post history by running the real " +
      "read-posts.mjs script against managed/social-reporter/data/posts.json. " +
      "This is a prototype: no live X/LinkedIn account is connected, so results " +
      "are always the mock fixture data, never a live feed. Optionally filter " +
      "with `since` (YYYY-MM-DD, inclusive) and/or `platform` (\"x\" or " +
      "\"linkedin\"). Returns the posts as a JSON array (id, platform, text, " +
      "timestamp, impressions, likes, comments, reposts).",
    input_schema: {
      type: "object",
      properties: {
        since: {
          type: "string",
          description: "Only include posts at or after this date, YYYY-MM-DD.",
        },
        platform: {
          type: "string",
          enum: ["x", "linkedin"],
          description: "Restrict results to one platform.",
        },
      },
    },
    async handler(input) {
      const args = [join(SCRIPTS_DIR, "read-posts.mjs")];
      if (input.since) args.push("--since", String(input.since));
      if (input.platform) args.push("--platform", String(input.platform));
      return execFileSync(process.execPath, args, { encoding: "utf8" });
    },
  },
  {
    name: "queue_post",
    description:
      "MOCK STAND-IN for publishing to X/LinkedIn — this does NOT post " +
      "anywhere and does NOT call any real social API. It runs the founder's " +
      "real publish-post.mjs script, which appends the draft to " +
      "managed/social-reporter/data/outbox.json with status \"queued\" and a " +
      "queued_at timestamp, so the founder can review it before anything real " +
      "gets built. Returns the appended entry as JSON — that return value is " +
      "the only valid basis for saying a draft was queued. X posts are hard-capped " +
      "at 280 characters — the tool rejects longer text instead of queueing it.",
    input_schema: {
      type: "object",
      properties: {
        platform: {
          type: "string",
          enum: ["x", "linkedin"],
          description: "Which platform the draft is written for.",
        },
        text: { type: "string", description: "The full post text to queue." },
      },
      required: ["platform", "text"],
    },
    async handler(input) {
      if (input.platform === "x" && String(input.text).length > 280) return JSON.stringify({ error: "post exceeds 280 chars for X", length: String(input.text).length });
      const args = [
        join(SCRIPTS_DIR, "publish-post.mjs"),
        "--platform",
        String(input.platform),
        "--text",
        String(input.text),
      ];
      return execFileSync(process.execPath, args, { encoding: "utf8" });
    },
  },
  {
    name: "cancel_post",
    description:
      "MOCK STAND-IN for cancelling a queued X/LinkedIn post — this does NOT " +
      "cancel anything on a real platform and does NOT call any real social API. " +
      "It runs the founder's real cancel-post.mjs script, which removes the " +
      "matching entry from managed/social-reporter/data/outbox.json outright " +
      "(not a soft-delete/status flag) so it no longer appears anywhere, " +
      "including in Queue status. Returns the removed entry as JSON — that " +
      "return value is the only valid basis for saying a post was cancelled. " +
      "If no entry matches the given id, the script exits with an error instead " +
      "of removing anything; surface that error rather than claiming success.",
    input_schema: {
      type: "object",
      properties: {
        id: { type: "string", description: "The outbox entry id to cancel, e.g. \"mock-3\"." },
      },
      required: ["id"],
    },
    async handler(input) {
      const args = [join(SCRIPTS_DIR, "cancel-post.mjs"), "--id", String(input.id)];
      try {
        return execFileSync(process.execPath, args, { encoding: "utf8" });
      } catch (err) {
        return JSON.stringify({ error: (err as { stderr: string }).stderr.trim() });
      }
    },
  },
  {
    name: "list_queue",
    description:
      "Returns the current contents of the mock outbox " +
      "(managed/social-reporter/data/outbox.json) exactly as stored — every " +
      "entry `queue_post` has appended, in outbox order, each with id, " +
      "platform, text, status, and queued_at. Cancelled posts are removed " +
      "outright by `cancel_post`, so they are simply absent here, not marked " +
      "cancelled. Call this fresh before writing a Queue status section rather " +
      "than relying on individual queue_post/cancel_post return values, which " +
      "only describe the single entry each call touched.",
    input_schema: { type: "object", properties: {} },
    async handler() {
      return readFile(OUTBOX_PATH, "utf8");
    },
  },
];
