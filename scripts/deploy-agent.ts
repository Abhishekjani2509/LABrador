/**
 * Deploy a compiled agent to the Claude Managed Agents API.
 *
 *   npm run deploy-agent <name>
 *
 * Thin Anthropic SDK wrapper, idempotent by content hash:
 *   1. zip + upload each skills/<dir>/ bundle that changed  → Skills API
 *   2. create the agent, or update it (new version) if config changed
 *   3. write agent_id / versions / hashes back into manifest.json
 *
 * Re-running with nothing changed is a no-op.
 */
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { toFile } from "@anthropic-ai/sdk";
import {
  loadCompiledAgent,
  makeClient,
  repoRoot,
  type AgentManifest,
} from "../lib/managed.ts";

const name = process.argv[2];
if (!name) {
  console.error("usage: npm run deploy-agent <name>");
  process.exit(1);
}

const client = makeClient();
const compiled = await loadCompiledAgent(name);
const { dir, manifest, instructions, tools } = compiled;
const deployment: NonNullable<AgentManifest["deployment"]> = manifest.deployment ?? {
  agent_id: "",
  agent_version: 0,
  skills: {},
  system_hash: "",
  tools_hash: "",
};

const sha = (text: string | Buffer) => createHash("sha256").update(text).digest("hex");

// --- 1. skills ------------------------------------------------------------

const skillsRoot = join(dir, "skills");
const skillDirs = existsSync(skillsRoot)
  ? (await readdir(skillsRoot, { withFileTypes: true })).filter((e) => e.isDirectory()).map((e) => e.name)
  : [];

for (const skillDir of skillDirs) {
  const bundleHash = await hashDir(join(skillsRoot, skillDir));
  const existing = deployment.skills[skillDir];
  if (existing && existing.hash === bundleHash) {
    console.log(`skill ${skillDir}: unchanged (${existing.skill_id})`);
    continue;
  }
  const zipPath = await zipDir(join(skillsRoot, skillDir), skillDir);
  const file = await toFile(await readFile(zipPath), `${skillDir}.zip`, { type: "application/zip" });
  if (existing?.skill_id) {
    const version = await client.beta.skills.versions.create(existing.skill_id, { files: [file] });
    deployment.skills[skillDir] = { skill_id: existing.skill_id, version: String(version.version), hash: bundleHash };
    console.log(`skill ${skillDir}: new version ${version.version} of ${existing.skill_id}`);
  } else {
    const skill = await client.beta.skills.create({ files: [file] });
    deployment.skills[skillDir] = { skill_id: skill.id, version: String(skill.latest_version ?? "latest"), hash: bundleHash };
    console.log(`skill ${skillDir}: created ${skill.id}`);
  }
  await rm(zipPath, { force: true });
}

// drop records for skills dirs that no longer exist
for (const known of Object.keys(deployment.skills)) {
  if (!skillDirs.includes(known)) {
    console.log(`skill ${known}: removed from artifact (leaving uploaded skill in workspace)`);
    delete deployment.skills[known];
  }
}

// --- 2. agent -------------------------------------------------------------

const agentConfig = {
  name: manifest.name,
  description: manifest.description,
  model: manifest.model,
  system: instructions,
  tools: [
    { type: "agent_toolset_20260401" as const },
    ...tools.map((tool) => ({
      type: "custom" as const,
      name: tool.name,
      description: tool.description,
      input_schema: tool.input_schema as { type: "object"; [key: string]: unknown },
    })),
  ],
  skills: Object.values(deployment.skills).map((skill) => ({
    type: "custom" as const,
    skill_id: skill.skill_id,
    version: "latest",
  })),
  mcp_servers: (manifest.mcp_servers ?? []) as never[],
};

const systemHash = sha(instructions);
const toolsHash = sha(JSON.stringify(agentConfig.tools) + JSON.stringify(agentConfig.skills));

if (!deployment.agent_id) {
  const agent = await client.beta.agents.create(agentConfig);
  deployment.agent_id = agent.id;
  deployment.agent_version = agent.version;
  console.log(`agent created: ${agent.id} v${agent.version}`);
} else if (deployment.system_hash !== systemHash || deployment.tools_hash !== toolsHash) {
  const current = await client.beta.agents.retrieve(deployment.agent_id);
  const agent = await client.beta.agents.update(deployment.agent_id, {
    version: current.version,
    ...agentConfig,
  });
  deployment.agent_version = agent.version;
  console.log(`agent updated: ${agent.id} v${agent.version}`);
} else {
  console.log(`agent unchanged: ${deployment.agent_id} v${deployment.agent_version}`);
}

deployment.system_hash = systemHash;
deployment.tools_hash = toolsHash;

// --- 3. write back --------------------------------------------------------

manifest.deployment = deployment;
const manifestPath = join(dir, "manifest.json");
const nextManifest = JSON.stringify(manifest, null, 2) + "\n";
if (nextManifest === (await readFile(manifestPath, "utf8"))) {
  console.log(`manifest unchanged: agent/tools/${name}/manifest.json`);
} else {
  await writeFile(manifestPath, nextManifest);
  console.log(`manifest updated: agent/tools/${name}/manifest.json`);
}

// --- helpers --------------------------------------------------------------

async function hashDir(root: string): Promise<string> {
  const entries: string[] = [];
  async function walk(current: string, prefix: string) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await walk(join(current, entry.name), rel);
      else entries.push(`${rel}:${sha(await readFile(join(current, entry.name)))}`);
    }
  }
  await walk(root, "");
  return sha(entries.sort().join("\n"));
}

async function zipDir(root: string, dirName: string): Promise<string> {
  const staging = await mkdtemp(join(tmpdir(), "skill-"));
  const zipPath = join(staging, `${dirName}.zip`);
  // Zip so the archive contains <dirName>/SKILL.md at the top level.
  execFileSync("zip", ["-r", zipPath, dirName], { cwd: join(root, ".."), stdio: "pipe" });
  return zipPath;
}

export { repoRoot };
