#!/usr/bin/env node
// ============================================================================
// MOCK STAND-IN ONLY. This does NOT cancel anything on X or LinkedIn.
// It does not call any real social API, hold any credentials, or reach the
// network. It only removes a queued entry from data/outbox.json so a human
// can back out of a mock-queued post before the pipeline "publishes" it.
// Swap this out for the real X/LinkedIn cancel API before this agent goes live.
// ============================================================================
//
// Usage:
//   node scripts/cancel-post.mjs --id mock-3

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTBOX_PATH = path.join(__dirname, "..", "data", "outbox.json");

function parseArgs(argv) {
  const args = { id: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--id") args.id = argv[++i];
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

async function main() {
  const { id } = parseArgs(process.argv.slice(2));

  if (!id) {
    console.error("Missing --id.");
    process.exit(1);
  }

  console.warn(
    "[MOCK] cancel-post.mjs is a stand-in for the real X/LinkedIn cancel API. " +
      "Nothing is being cancelled anywhere — this only removes an entry from data/outbox.json.",
  );

  const outbox = await loadOutbox();
  const index = outbox.findIndex((entry) => entry.id === id);

  if (index === -1) {
    console.error(`No outbox entry found with id "${id}".`);
    process.exit(1);
  }

  const [removed] = outbox.splice(index, 1);

  await writeFile(OUTBOX_PATH, JSON.stringify(outbox, null, 2) + "\n");

  console.log(JSON.stringify(removed, null, 2));
}

main();
