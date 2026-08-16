/**
 * Custom tools for the hypothesis-generator agent.
 *
 * These run in *this* process, not in the agent's cloud sandbox. That is the
 * whole reason they exist: the generator is a Python package (`src/hyp_gen/`,
 * beside this file) that lives on this machine, and the deployed agent cannot
 * run it. When the agent calls one of these, its session parks at
 * `requires_action`, the handler here shells out to the real CLI, and the
 * result is posted back.
 *
 * Every handler shells out to `hyp_gen`'s own entry point. Nothing about
 * traversal, scoring, or validation is reimplemented here — a second copy in
 * TypeScript would be an untested one, and the Python side has 212 tests.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { CustomToolSpec } from "@/lib/claude-managed-agent.ts";
import { repoRoot } from "@/lib/claude-managed-agent.ts";

const HYP_GEN = join(repoRoot, "managed", "hypothesis-generator");
const RUNS = join(HYP_GEN, "runs");
const FIXTURES = join(HYP_GEN, "fixtures");

/** Where a graph may be read from. Keeps the agent off the rest of the disk. */
const GRAPH_ROOTS = [FIXTURES];

/**
 * The interpreter to run the CLI with.
 *
 * Prefers the package's own venv, because that is where `pip install -e` put
 * the dependencies. Falls back to `python3` with `PYTHONPATH=src`, which works
 * for the deterministic half — it needs only pydantic — and fails loudly
 * rather than silently if that is missing too.
 */
function interpreter(): { cmd: string; env: Record<string, string> } {
  const venv = join(HYP_GEN, ".venv", "bin", "python");
  if (existsSync(venv)) {
    return { cmd: venv, env: {} };
  }
  return { cmd: "python3", env: { PYTHONPATH: join(HYP_GEN, "src") } };
}

type RunResult = { code: number; stderr: string; stdout: string };

function runCli(args: string[], timeoutMs = 600_000): Promise<RunResult> {
  const { cmd, env } = interpreter();
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, ["-m", "hyp_gen.cli", ...args], {
      cwd: HYP_GEN,
      env: { ...process.env, ...env },
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`hyp_gen timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on("data", (d) => {
      stdout += d;
    });
    child.stderr.on("data", (d) => {
      stderr += d;
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code: code ?? -1, stderr, stdout });
    });
  });
}

/** Resolve a caller-supplied graph reference to a path inside GRAPH_ROOTS. */
function resolveGraph(ref: string): string {
  // Reject traversal outright rather than normalising it: the agent has no
  // legitimate reason to reach outside the two graph directories, and a
  // knowledge graph is exactly the kind of input an injection would ride in on.
  if (ref.includes("..") || ref.startsWith("/")) {
    throw new Error(
      `graph must be a bare filename under fixtures/, got "${ref}"`
    );
  }
  for (const root of GRAPH_ROOTS) {
    const candidate = join(root, ref);
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error(
    `no graph named "${ref}". Call list_graphs to see what is available.`
  );
}

/** A slate trimmed to what fits usefully in an agent's context window. */
function summarise(slate: Record<string, any>, runDir: string) {
  return {
    asks: (slate.asks ?? []).map((a: any) => ({
      ask: a.ask,
      depth: a.depth,
      reason: a.reason,
      target: a.target,
    })),
    counts: slate.counts,
    coverage: slate.coverage,
    graph_id: slate.graph_id,
    hypotheses: (slate.hypotheses ?? []).map((h: any) => ({
      caveat_count: (h.caveats ?? []).length,
      hops: h.hops,
      id: h.id,
      issues: (h.issues ?? []).map((i: any) => `${i.severity}:${i.code}`),
      motif: h.motif,
      object: h.object_name,
      rank_score: h.rank_score,
      scores: h.scores,
      statement: h.articulation?.statement ?? null,
      subject: h.subject_name,
      verdict: h.verdict ?? null,
    })),
    question: slate.question,
    report_path: join(runDir, "report.md"),
    round: slate.round,
    slate_path: join(runDir, "slate.json"),
    // What the run's appetite actually resolved to. The scores below are
    // meaningless without it: support 0.5 off a craziness-0.1 slate and off a
    // craziness-0.9 one are not the same claim about the world.
    stance: slate.params?.stance,
  };
}

export const tools: CustomToolSpec[] = [
  {
    name: "list_graphs",
    description:
      "List the knowledge-graph JSON files this machine can generate hypotheses from, with a one-line summary of each (question, round, node/link counts, search coverage). Call this first when the user has not named a specific graph, or when you need to know whether a graph exists before running on it. Returns filenames to pass as the `graph` argument of generate_hypotheses.",
    input_schema: { properties: {}, type: "object" },
    async handler() {
      const found: Record<string, unknown>[] = [];
      for (const root of GRAPH_ROOTS) {
        if (!existsSync(root)) {
          continue;
        }
        for (const file of await readdir(root)) {
          if (!file.endsWith(".json")) {
            continue;
          }
          try {
            const raw = JSON.parse(await readFile(join(root, file), "utf8"));
            found.push({
              coverage: raw.coverage?.depth,
              file,
              gaps: (raw.gaps ?? []).length,
              links: (raw.links ?? []).length,
              question: raw.question,
              round: raw.round,
              things: (raw.things ?? []).length,
              truncated: raw.coverage?.truncated ?? false,
            });
          } catch {
            found.push({ error: "not valid JSON", file });
          }
        }
      }
      return JSON.stringify({ graphs: found });
    },
  },
  {
    name: "generate_hypotheses",
    description:
      "Run the hypothesis generator over one knowledge graph and return the ranked slate: per hypothesis its motif, endpoints, score vector, and validation issues, plus the Stage 1 requests that would move it. Use `profile` to set what question is asked of the graph (conservative | default | speculative | repurposing | mechanism | valuation), `craziness` to set how far out to reach for an answer, and `overrides` to patch single parameters like traversal.max_hops. Leave `articulate` false (the default) for the fast deterministic slate, which needs no model calls; set it true only when the user wants written-up hypotheses with mechanism, falsifier and adversarial critique, which costs model calls and a minute or two. The full report and slate JSON are written to disk and their paths returned — call get_hypothesis to read the evidence behind any one of them.",
    input_schema: {
      properties: {
        articulate: {
          description:
            "Run the model stages (articulation + critique). Costs API calls. Default false.",
          type: "boolean",
        },
        craziness: {
          description:
            "How ambitious the slate should be, 0 to 1. 0 is super safe: short paths, strongly-supported links, two independent research groups, nearly boring. 1 is very ambitious: long paths, weak links, and cross-field analogy — the 'I read this one thing in a slightly different field, maybe it works here' kind of idea. Composes with `profile`. Omit to use the profile's own setting.",
          type: "number",
        },
        graph: {
          description:
            "Graph filename from list_graphs, e.g. example_graph.json",
          type: "string",
        },
        overrides: {
          description:
            'Parameter patches as "group.key=value", e.g. ["traversal.max_hops=4", "selection.top_k=5"]. JSON values are parsed.',
          items: { type: "string" },
          type: "array",
        },
        profile: {
          description:
            "conservative | default | speculative | repurposing | mechanism",
          type: "string",
        },
      },
      required: ["graph"],
      type: "object",
    },
    async handler(input) {
      const graph = resolveGraph(String(input.graph ?? ""));
      const profile = String(input.profile ?? "default");
      const overrides = Array.isArray(input.overrides)
        ? (input.overrides as string[])
        : [];
      const articulate = input.articulate === true;

      const craziness =
        input.craziness === undefined ? null : Number(input.craziness);
      if (craziness !== null && !(craziness >= 0 && craziness <= 1)) {
        return JSON.stringify({
          error: `craziness must be a number between 0 and 1, got ${input.craziness}`,
        });
      }

      // One directory per run, named for the inputs, so repeated runs are
      // comparable and nothing is silently overwritten by a different stance.
      const dial = craziness === null ? "" : `-c${craziness}`;
      const stamp = `${profile}${dial}-${articulate ? "full" : "structural"}`;
      const runDir = join(RUNS, `${String(input.graph).replace(/\.json$/, "")}-${stamp}`);
      await mkdir(runDir, { recursive: true });

      const args = ["--graph", graph, "--profile", profile, "--out", runDir];
      if (craziness !== null) {
        args.push("--craziness", String(craziness));
      }
      for (const o of overrides) {
        args.push("--set", o);
      }
      if (!articulate) {
        args.push("--dry-run");
      }

      const { code, stderr } = await runCli(args);
      if (code !== 0) {
        // Exit 2 is the credential guard; say so plainly rather than making
        // the agent guess from a stack trace.
        const hint =
          code === 2
            ? " Set ANTHROPIC_API_KEY in the repo .env, or call again with articulate=false for the deterministic slate."
            : "";
        return JSON.stringify({
          error: `hyp_gen exited ${code}: ${stderr.trim()}${hint}`,
        });
      }

      const slate = JSON.parse(await readFile(join(runDir, "slate.json"), "utf8"));
      return JSON.stringify(summarise(slate, runDir));
    },
  },
  {
    name: "emit_programs",
    description:
      "Turn a slate from a previous generate_hypotheses run into LABrador ProgramInput briefs for the valuation stage — one per molecule, with the initial indication and at most one label expansion sharing the asset's patent clock. Requires an analyst `frame`: currency, geography, route, line of therapy, and the valuation, launch and patent filing years are human decisions the knowledge graph does not contain. Call with no frame to get a template to show the user; the four year fields are null and must be filled in before anything is emitted. The emitted briefs are NOT_DECISION_GRADE by construction — a literature graph has no epidemiology, access or price data — and LABrador's itemised list of missing inputs is the useful output, not the rNPV, which is zero whenever no comparable prices were supplied.",
    input_schema: {
      properties: {
        frame: {
          description:
            "Analyst frame object. Omit to receive a template to show the user. Required keys once supplied: base_year, valuation_year, launch_year, filing_year.",
          type: "object",
        },
        slate_path: {
          description: "The `slate_path` returned by generate_hypotheses.",
          type: "string",
        },
      },
      required: ["slate_path"],
      type: "object",
    },
    async handler(input) {
      const frame = input.frame as Record<string, unknown> | undefined;
      if (!frame) {
        const { code, stderr, stdout } = await runCli([
          "--emit-frame-template",
          "/dev/stdout",
        ]);
        return JSON.stringify({
          frame_template: code === 0 ? stdout : null,
          error: code === 0 ? undefined : stderr.trim(),
          next: "Show this to the user. The four null year fields are their decision, not yours — a guessed filing_year silently moves the protected window LABrador reports.",
        });
      }

      const slatePath = String(input.slate_path ?? "");
      if (!slatePath.startsWith(RUNS)) {
        throw new Error("slate_path must be a path returned by generate_hypotheses");
      }
      // The slate already exists, so re-running the generator would be both
      // wasteful and non-reproducible against it. Emit straight off the file.
      const runDir = dirname(slatePath);
      const framePath = join(runDir, "frame.json");
      const outDir = join(runDir, "programs");
      await writeFile(framePath, JSON.stringify(frame, null, 2));

      const { code, stderr } = await runCli([
        "--emit-programs-from",
        slatePath,
        "--frame",
        framePath,
        "--emit-programs",
        outDir,
      ]);
      if (code !== 0) {
        return JSON.stringify({ error: `hyp_gen exited ${code}: ${stderr.trim()}` });
      }
      const emission = JSON.parse(
        await readFile(join(outDir, "emission.json"), "utf8")
      );
      return JSON.stringify({
        comparables_path: join(outDir, "comparables.json"),
        decision_grade_warning:
          "Every emitted brief is NOT_DECISION_GRADE: the graph supplies no population, access or price. Report LABrador's gap list, not its rNPV.",
        graph_id: emission.graph_id,
        notes: emission.notes,
        programs: emission.programs.map((p: any) => ({
          expansion: p.expansion_indications.map((e: any) => e.name),
          indication: p.initial_indication.name,
          molecule: p.molecule_identifier,
          path: join(outDir, `${p.program_id}.program.json`),
          program_id: p.program_id,
          target: p.target,
        })),
        skipped: emission.skipped,
      });
    },
  },
  {
    name: "get_hypothesis",
    description:
      "Read the full evidence behind one hypothesis from a previous generate_hypotheses run: the path with per-link support, every source finding with its verbatim sentence and paper, the coverage caveats, validation issues, any adversarial critiques, and the Stage 1 asks. Call this before presenting a hypothesis to a user — the summary from generate_hypotheses carries scores but not the quotes, and a hypothesis stated without its evidence is not checkable.",
    input_schema: {
      properties: {
        hypothesis_id: {
          description: "The `id` field from the generate_hypotheses summary.",
          type: "string",
        },
        slate_path: {
          description: "The `slate_path` returned by generate_hypotheses.",
          type: "string",
        },
      },
      required: ["slate_path", "hypothesis_id"],
      type: "object",
    },
    async handler(input) {
      const slatePath = String(input.slate_path ?? "");
      if (!slatePath.startsWith(RUNS)) {
        throw new Error(`slate_path must be a path returned by generate_hypotheses`);
      }
      const slate = JSON.parse(await readFile(slatePath, "utf8"));
      const wanted = String(input.hypothesis_id ?? "");
      const h = (slate.hypotheses ?? []).find((x: any) => x.id === wanted);
      if (!h) {
        return JSON.stringify({
          error: `no hypothesis "${wanted}" in that slate`,
          available: (slate.hypotheses ?? []).map((x: any) => x.id),
        });
      }
      return JSON.stringify({
        articulation: h.articulation,
        asks: h.asks,
        caveats: h.caveats,
        critiques: h.critiques,
        evidence: {
          findings: h.evidence?.findings,
          gap: h.evidence?.gap,
          links: h.evidence?.links,
          papers: h.evidence?.papers,
          per_link_support: h.evidence?.per_link_support,
        },
        id: h.id,
        issues: h.issues,
        motif: h.motif,
        path: h.path,
        provenance: h.provenance,
        scores: h.scores,
      });
    },
  },
];
