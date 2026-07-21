#!/usr/bin/env node
// ============================================================================
// MOCK STAND-IN ONLY. This does NOT post to X or LinkedIn.
// It does not call any real social API, hold any credentials, or reach the
// network. It only appends a queued entry to data/outbox.json so the rest of
// the pipeline (and a human) can see what *would* be posted. Swap this out
// for the real X/LinkedIn publish API before this agent goes live.
// ============================================================================
//
// Usage:
//   node scripts/publish-post.mjs --platform x --text "hello world"

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTBOX_PATH = path.join(__dirname, "..", "data", "outbox.json");

function parseArgs(argv) {
  const args = { platform: null, text: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--platform") args.platform = argv[++i];
    else if (argv[i] === "--text") args.text = argv[++i];
  }
  return args;
}

async function loadOutbox() {
  try {
    const raw = await readFile(OUTBOX_PATH, "utf8");
    return JSON.parse(raw);
  } catch (err) {
    if (err.code === "ENOENT") return [];
    throw err;
  }
}

function nextId(outbox) {
  const maxN = outbox.reduce((max, entry) => {
    const match = /^mock-(\d+)$/.exec(entry.id);
    return match ? Math.max(max, Number(match[1])) : max;
  }, 0);
  return `mock-${maxN + 1}`;
}

async function main() {
  const { platform, text } = parseArgs(process.argv.slice(2));

  if (!platform || !["x", "linkedin"].includes(platform)) {
    console.error('Missing/invalid --platform. Expected "x" or "linkedin".');
    process.exit(1);
  }
  if (!text) {
    console.error("Missing --text.");
    process.exit(1);
  }

  console.warn(
    "[MOCK] publish-post.mjs is a stand-in for the real X/LinkedIn publish API. " +
      "Nothing is being posted anywhere — this only queues an entry in data/outbox.json.",
  );

  const outbox = await loadOutbox();
  const entry = {
    // Derived from the highest existing numeric id, not outbox.length — length
    // shrinks when an entry is cancelled from the middle, which would otherwise
    // let a new post collide with an id still in use.
    id: nextId(outbox),
    platform,
    text,
    status: "queued",
    queued_at: new Date().toISOString(),
  };
  outbox.push(entry);

  await writeFile(OUTBOX_PATH, JSON.stringify(outbox, null, 2) + "\n");

  console.log(JSON.stringify(entry, null, 2));
}

main();
