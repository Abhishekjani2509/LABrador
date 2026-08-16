/**
 * Auto-integrator: merge every updated team branch into main, verified.
 *
 *   bun scripts/integrate.ts             # one sweep: fetch, merge, verify, push
 *   bun scripts/integrate.ts --dry-run   # everything except the final push
 *
 * What it does, in order, inside a THROWAWAY clone under /tmp (your working
 * checkout is never touched — pull after it runs):
 *
 *   1. clone the team remote, check out main
 *   2. for each refs/heads/* except main: skip if already an ancestor of
 *      main, else `git merge --no-ff`
 *   3. safety net for the 2026-08-15 rename: if a merge resurrects a dead
 *      node dir (e.g. managed/druggability-dossier), move its contents into
 *      the renamed dir — unless that would overwrite files, which escalates
 *   4. run `bun install --frozen-lockfile`, `bun run typecheck`,
 *      `bun run check` — a red check aborts the push, nothing lands
 *   5. append a merge-log entry to COORDINATION.md (§9)
 *   6. push main (one retry with rebase if someone pushed concurrently)
 *
 * What it deliberately does NOT do: resolve merge conflicts. A conflicted
 * branch is skipped, reported with `CONFLICT`, and left for a human (or the
 * watching Claude session) to merge with judgment. Auto-resolving semantic
 * conflicts unattended is how a shared main gets quietly broken.
 */
import { execSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const REMOTE = "https://github.com/Abhishekjani2509/LABrador.git";
/** 2026-08-15 rename map: dead dir → live dir (see COORDINATION.md §2). */
const RENAMES: Record<string, string> = {
  "druggability-dossier": "small-molecule-tractability-review",
  "literature-graph": "research-evidence-mapper",
  "program-strategy-valuation": "therapeutic-program-economics",
  "simulated-clinical": "trial-recruitment-forecaster",
  spike: "sandbox-capability-probe",
};

const TRAILING_NEWLINES = /\n+$/;
const TOUCHED_NODE_RE = /^managed\/([^/]+)\//;
const dryRun = process.argv.includes("--dry-run");
const log = (line: string) => process.stdout.write(`${line}\n`);

function sh(cmd: string, cwd: string): string {
  return execSync(cmd, {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function trySh(cmd: string, cwd: string): { ok: boolean; out: string } {
  try {
    return { ok: true, out: sh(cmd, cwd) };
  } catch (error) {
    const e = error as { stderr?: string; stdout?: string; message?: string };
    return {
      ok: false,
      out: `${e.stdout ?? ""}${e.stderr ?? ""}` || (e.message ?? "failed"),
    };
  }
}

function listBranches(cwd: string): { name: string; sha: string }[] {
  return sh('git ls-remote origin "refs/heads/*"', cwd)
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const [sha, ref] = line.split("\t");
      return { name: (ref ?? "").replace("refs/heads/", ""), sha: sha ?? "" };
    })
    .filter((b) => b.name && b.name !== "main");
}

function isAncestor(sha: string, cwd: string): boolean {
  return trySh(`git merge-base --is-ancestor ${sha} HEAD`, cwd).ok;
}

/**
 * If a merge resurrected a dead node dir, move its contents into the live
 * dir. Returns "clean" | "moved" | "collision" — collision means a moved
 * file already exists at the destination, which needs human judgment.
 */
function fixDeadPaths(cwd: string): "clean" | "moved" | "collision" {
  let moved = false;
  for (const [dead, live] of Object.entries(RENAMES)) {
    const deadDir = join(cwd, "managed", dead);
    if (!existsSync(deadDir)) {
      continue;
    }
    for (const entry of readdirSync(deadDir)) {
      if (existsSync(join(cwd, "managed", live, entry))) {
        return "collision";
      }
      sh(`git mv "managed/${dead}/${entry}" "managed/${live}/${entry}"`, cwd);
      moved = true;
    }
    rmSync(deadDir, { force: true, recursive: true });
  }
  if (moved) {
    sh(
      'git commit -am "auto-integrate: move resurrected pre-rename paths to renamed dirs"',
      cwd
    );
  }
  return moved ? "moved" : "clean";
}

/** Subjects of the commits a branch brings in — for the §9 merge log. */
function incomingSubjects(
  b: { name: string; sha: string },
  cwd: string
): string {
  const subjects = trySh(`git log --format=%s HEAD..origin/${b.name} -5`, cwd);
  return subjects.ok && subjects.out
    ? subjects.out.split("\n").join(" · ")
    : "";
}

function mergeBranch(b: { name: string; sha: string }, cwd: string): string {
  const merge = trySh(
    `git merge --no-ff origin/${b.name} -m "auto-integrate: merge ${b.name} (${b.sha.slice(0, 7)})"`,
    cwd
  );
  if (!merge.ok) {
    trySh("git merge --abort", cwd);
    return "CONFLICT";
  }
  const paths = fixDeadPaths(cwd);
  if (paths === "collision") {
    sh("git reset --hard ORIG_HEAD", cwd);
    return "COLLISION";
  }
  return paths === "moved" ? "MERGED+path-fix" : "MERGED";
}

/**
 * Python nodes gate on their own suites, but only when the merge touched
 * them: any managed/<node>/ with a pyproject.toml AND a uv.lock (no lock =
 * not reproducibly testable; logged, not blocking).
 */
function touchedPythonNodes(cwd: string, baseSha: string): string[] {
  const touched = trySh(
    `git diff --name-only ${baseSha}..HEAD -- "managed/*/pyproject.toml" "managed/*/**"`,
    cwd
  );
  if (!touched.ok) {
    return [];
  }
  const dirs = new Set<string>();
  for (const file of touched.out.split("\n")) {
    const m = file.match(TOUCHED_NODE_RE);
    if (m?.[1]) {
      dirs.add(`managed/${m[1]}`);
    }
  }
  return [...dirs].filter(
    (d) =>
      existsSync(join(cwd, d, "pyproject.toml")) &&
      existsSync(join(cwd, d, "uv.lock"))
  );
}

function verify(cwd: string, baseSha: string): { ok: boolean; out: string } {
  const install = trySh("bun install --frozen-lockfile", cwd);
  if (!install.ok) {
    return { ok: false, out: `bun install failed:\n${install.out}` };
  }
  const typecheck = trySh("bun run typecheck", cwd);
  if (!typecheck.ok) {
    return { ok: false, out: `typecheck failed:\n${typecheck.out}` };
  }
  const check = trySh("bun run check", cwd);
  if (!check.ok) {
    return { ok: false, out: `check failed:\n${check.out}` };
  }
  for (const node of touchedPythonNodes(cwd, baseSha)) {
    const pyDir = join(cwd, node);
    // --extra dev where declared; plain sync otherwise.
    const sync = trySh("uv sync --frozen --extra dev", pyDir).ok
      ? { ok: true, out: "" }
      : trySh("uv sync --frozen", pyDir);
    if (!sync.ok) {
      return { ok: false, out: `uv sync failed (${node}):\n${sync.out}` };
    }
    const pytest = trySh("uv run pytest -q", pyDir);
    if (!pytest.ok) {
      return { ok: false, out: `pytest failed (${node}):\n${pytest.out}` };
    }
    log(`pytest green: ${node}`);
  }
  return { ok: true, out: "" };
}

function appendMergeLog(cwd: string, entries: string[]): void {
  const path = join(cwd, "COORDINATION.md");
  let text = readFileSync(path, "utf8");
  const header = "## 9. Merge log (automated)";
  if (!text.includes(header)) {
    text += `\n${header}\n\nAppended by \`scripts/integrate.ts\` on every verified auto-merge.\n`;
  }
  const stamp = sh("date -u '+%Y-%m-%d %H:%M UTC'", cwd);
  text += `\n- **${stamp}** — ${entries.join("; ")} — typecheck+check green.`;
  writeFileSync(path, `${text}\n`.replace(TRAILING_NEWLINES, "\n"));
  sh("git add COORDINATION.md", cwd);
  sh('git commit -m "COORDINATION.md: merge log (auto-integrate)"', cwd);
}

function push(cwd: string): boolean {
  if (trySh("git push origin main", cwd).ok) {
    return true;
  }
  // Someone pushed concurrently: replay our merge commits on the new tip once.
  const rebase = trySh("git pull --rebase origin main", cwd);
  return rebase.ok && trySh("git push origin main", cwd).ok;
}

const work = mkdtempSync(join(tmpdir(), "labrador-integrate-"));
try {
  log(`workspace: ${work}`);
  sh(`git clone --quiet ${REMOTE} repo`, work);
  const repo = join(work, "repo");
  sh("git checkout --quiet main", repo);

  const baseSha = sh("git rev-parse HEAD", repo);
  const pending = listBranches(repo).filter((b) => !isAncestor(b.sha, repo));
  if (pending.length === 0) {
    log("NOTHING-TO-MERGE: every branch is already in main");
    process.exit(0);
  }

  const results = pending.map((b) => {
    const subjects = incomingSubjects(b, repo);
    const status = mergeBranch(b, repo);
    log(`${status}: ${b.name} (${b.sha.slice(0, 7)})`);
    return { branch: b.name, status, subjects };
  });
  const merged = results.filter((r) => r.status.startsWith("MERGED"));
  const escalate = results.filter((r) => !r.status.startsWith("MERGED"));

  if (merged.length === 0) {
    log("NO-CLEAN-MERGES: everything pending needs human judgment");
    process.exit(2);
  }

  const checks = verify(repo, baseSha);
  if (!checks.ok) {
    log(
      `VERIFY-FAILED — nothing pushed. Details:\n${checks.out.slice(0, 4000)}`
    );
    log(`inspect: ${repo}`);
    process.exit(2);
  }

  appendMergeLog(
    repo,
    merged.map(
      (r) =>
        `merged \`${r.branch}\` (${r.status})${r.subjects ? ` — ${r.subjects}` : ""}`
    )
  );

  if (dryRun) {
    log(`DRY-RUN: would push ${merged.length} merge(s); inspect ${repo}`);
    process.exit(0);
  }
  if (!push(repo)) {
    log("PUSH-FAILED after retry — inspect and push manually");
    log(`inspect: ${repo}`);
    process.exit(2);
  }
  log(`PUSHED: ${merged.map((r) => r.branch).join(", ")}`);
  if (escalate.length > 0) {
    log(
      `NEEDS-HUMAN: ${escalate.map((r) => `${r.branch} (${r.status})`).join(", ")}`
    );
    process.exit(3);
  }
} finally {
  if (!process.exitCode || process.exitCode === 0) {
    rmSync(work, { force: true, recursive: true });
  }
}
