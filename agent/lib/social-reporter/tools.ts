import { execFileSync } from "node:child_process";
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
      "the only valid basis for saying a draft was queued.",
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
];
