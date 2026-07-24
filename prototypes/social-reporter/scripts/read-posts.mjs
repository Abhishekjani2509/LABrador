#!/usr/bin/env node
// Mock stand-in for a real "fetch my posts" API call (X API / LinkedIn API).
// Reads from the local data/posts.json fixture instead of any live account.
//
// Usage:
//   node scripts/read-posts.mjs [--since 2026-07-14] [--platform x|linkedin]

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const POSTS_PATH = path.join(__dirname, "..", "data", "posts.json");

function parseArgs(argv) {
  const args = { since: null, platform: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--since") args.since = argv[++i];
    else if (argv[i] === "--platform") args.platform = argv[++i];
  }
  return args;
}

async function main() {
  const { since, platform } = parseArgs(process.argv.slice(2));

  if (platform && !["x", "linkedin"].includes(platform)) {
    console.error(`Unknown --platform "${platform}". Expected "x" or "linkedin".`);
    process.exit(1);
  }

  const raw = await readFile(POSTS_PATH, "utf8");
  let posts = JSON.parse(raw);

  if (since) {
    const sinceDate = new Date(since);
    if (Number.isNaN(sinceDate.getTime())) {
      console.error(`Could not parse --since "${since}" as a date.`);
      process.exit(1);
    }
    posts = posts.filter((p) => new Date(p.timestamp) >= sinceDate);
  }

  if (platform) {
    posts = posts.filter((p) => p.platform === platform);
  }

  console.log(JSON.stringify(posts, null, 2));
}

main();
