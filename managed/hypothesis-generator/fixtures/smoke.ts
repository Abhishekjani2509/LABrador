/**
 * Exercises the custom-tool handlers exactly as the deployed agent does:
 * same handler functions, same JSON in and out, no session in between.
 *
 * This is the fixture that answers "does the bridge work" without spending a
 * deployment. If this passes, the only thing left between it and the real
 * agent is the SSE round-trip.
 *
 *   bun managed/hypothesis-generator/fixtures/smoke.ts
 */
import { tools } from "../tools.ts";

const byName = Object.fromEntries(tools.map((t) => [t.name, t]));

async function call(name: string, input: Record<string, unknown>) {
  const tool = byName[name];
  if (!tool) {
    throw new Error(`no tool ${name}`);
  }
  const raw = await tool.handler(input);
  return JSON.parse(raw as string);
}

/**
 * What the agent actually sees when a handler throws. `executeCustomTool` in
 * lib/claude-managed-agent.ts catches and posts the message back as the tool
 * result, so a rejected input is a readable sentence to the agent, not a
 * crashed session. Mirrored here so this fixture tests the real behaviour.
 */
async function callAsAgent(name: string, input: Record<string, unknown>) {
  try {
    return await byName[name].handler(input);
  } catch (error) {
    return `Error executing ${name}: ${
      error instanceof Error ? error.message : String(error)
    }`;
  }
}

console.log("1. list_graphs");
const graphs = await call("list_graphs", {});
console.log(`   ${graphs.graphs.length} graph(s):`);
for (const g of graphs.graphs) {
  console.log(
    `   - ${g.file}: ${g.things} things, ${g.links} links, ${g.gaps} gaps, ` +
      `${g.coverage} depth${g.truncated ? " (truncated)" : ""}`
  );
}

console.log("\n2. generate_hypotheses (structural, repurposing profile)");
const slate = await call("generate_hypotheses", {
  graph: "example_graph.json",
  profile: "repurposing",
});
if (slate.error) {
  throw new Error(slate.error);
}
console.log(`   graph ${slate.graph_id} round ${slate.round}`);
console.log(`   ${slate.hypotheses.length} hypotheses, counts:`, slate.counts);
for (const h of slate.hypotheses) {
  console.log(
    `   - ${h.id} [${h.motif}] ${h.subject} -> ${h.object}  ` +
      `sup ${h.scores.support} nov ${h.scores.novelty} rank ${h.rank_score}`
  );
}
console.log(`   report: ${slate.report_path}`);

console.log("\n3. get_hypothesis (evidence behind the top one)");
const top = slate.hypotheses[0];
const detail = await call("get_hypothesis", {
  hypothesis_id: top.id,
  slate_path: slate.slate_path,
});
console.log(`   ${detail.id}: ${detail.path.length} step(s)`);
for (const step of detail.path) {
  console.log(
    `   - ${step.link} ${step.from_name} ${step.reversed ? "<-" : "->"} ${step.to_name} ` +
      `(${step.how}, ${step.state}, support ${step.support})`
  );
}
const findings = Object.entries(detail.evidence.findings ?? {});
console.log(`   ${findings.length} source sentence(s), first:`);
if (findings.length) {
  const [fid, f] = findings[0] as [string, any];
  console.log(`   - ${fid} (${f.paper}): "${f.quote.slice(0, 90)}…"`);
}
console.log(`   ${detail.caveats.length} caveat(s), ${detail.asks.length} ask(s)`);

console.log("\n4. guardrails (as the agent would see them)");
for (const bad of ["../../../etc/passwd", "/etc/passwd", "nope.json"]) {
  const answer = await callAsAgent("generate_hypotheses", { graph: bad });
  const rejected = answer.startsWith("Error executing");
  console.log(`   ${rejected ? "rejected" : "ALLOWED"}: ${bad}`);
  if (!rejected) {
    throw new Error(`guardrail failed to reject ${bad}`);
  }
}
const outside = await callAsAgent("get_hypothesis", {
  hypothesis_id: "x",
  slate_path: "/etc/passwd",
});
console.log(
  `   ${outside.startsWith("Error executing") ? "rejected" : "ALLOWED"}: slate outside runs/`
);

console.log("\nbridge OK");
