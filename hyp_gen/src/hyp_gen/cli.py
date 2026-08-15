"""Command line entry point.

    hypgen --graph graph.json --profile repurposing --out reports/

``--dry-run`` skips every model call and prints the structural slate: what was
enumerated, how it scored, and why. Start there. Most early failures are
traversal or parameter failures, and they are far easier to see as a table of
candidates than inside a finished report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hyp_gen import verify
from hyp_gen.evidence import build_pack
from hyp_gen.graph import GraphIndex, KnowledgeGraph
from hyp_gen.llm import Judge
from hyp_gen.params import PROFILES, Params
from hyp_gen.pipeline import Generator
from hyp_gen.report import to_markdown


def _overrides(pairs: list[str]) -> dict:
    """Parse ``--set traversal.max_hops=4`` into a nested dict.

    Values are parsed as JSON when possible so ``--set framing.mode=closed``
    and ``--set traversal.max_hops=4`` both do the obvious thing.
    """
    out: dict[str, dict] = {}
    for pair in pairs:
        if "=" not in pair or "." not in pair.split("=", 1)[0]:
            raise SystemExit(f"--set expects group.key=value, got {pair!r}")
        path, raw = pair.split("=", 1)
        group, key = path.split(".", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        out.setdefault(group, {})[key] = value
    return out


def _dry_run(generator: Generator) -> None:
    index: GraphIndex = generator.index
    shortlist = generator.shortlist()

    print(f"graph {generator.graph.graph_id} round {generator.graph.round}")
    print(
        f"  {len(generator.graph.things)} things, {len(generator.graph.links)} links, "
        f"{len(generator.graph.findings)} findings, {len(generator.graph.gaps)} gaps"
    )
    print(
        f"  coverage: {generator.graph.coverage.depth}, "
        f"read {generator.graph.coverage.read}/{generator.graph.coverage.found}"
        f"{', truncated' if generator.graph.coverage.truncated else ''}"
        f"  →  absence_reliability {index.absence_reliability()}"
    )
    print()
    header = f"{'id':<28}{'motif':<22}{'sup':>6}{'nov':>6}{'test':>6}{'risk':>6}{'str':>6}{'rank':>8}"
    print(header)
    print("-" * len(header))
    for candidate, scores in shortlist:
        print(
            f"{candidate.id[:27]:<28}{candidate.motif:<22}"
            f"{scores.support:>6.2f}{scores.novelty:>6.2f}{scores.testability:>6.2f}"
            f"{scores.contradiction_risk:>6.2f}{scores.structure:>6.2f}"
            f"{scores.rank_score:>8.3f}"
        )
        chain = " → ".join(
            [index.name(candidate.subject)]
            + [index.name(e.dst) for e in candidate.path]
        )
        print(f"    {chain}")
        for note in scores.notes:
            print(f"    · {note}")

        # The deterministic gates need no key, so a dry run can already say
        # which candidates would be rejected on structure or on resting entirely
        # on one lab. Those are the two failures worth knowing about before
        # spending a single model call.
        context = verify.GateContext(
            index=index,
            candidate=candidate,
            pack=build_pack(index, candidate, scores),
            params=generator.params,
        )
        for gate in verify.verify(context).gates:
            if gate.status in ("fail", "warn"):
                mark = "✗" if gate.status == "fail" else "!"
                print(f"    {mark} {gate.name}: {gate.summary}")
    if not shortlist:
        print("(nothing survived selection — loosen the params or check the graph)")
    print(f"\n{len(shortlist)} shortlisted. No model calls made.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hypgen")
    parser.add_argument("--graph", required=True, type=Path, help="Stage 1 graph JSON")
    parser.add_argument("--profile", default="default", choices=sorted(PROFILES))
    parser.add_argument("--params", type=Path, help="params JSON, overrides --profile")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="GROUP.KEY=VALUE",
        help="patch one parameter, e.g. --set traversal.max_hops=4",
    )
    parser.add_argument("--out", type=Path, help="directory for report.md and slate.json")
    parser.add_argument("--dry-run", action="store_true", help="no model calls")
    args = parser.parse_args(argv)

    graph = KnowledgeGraph.load(args.graph)
    overrides = _overrides(args.set)
    if args.params:
        base = Params.load(args.params).model_dump()
        for group, values in overrides.items():
            base.setdefault(group, {}).update(values)
        params = Params.model_validate(base)
    else:
        params = Params.profile(args.profile, overrides)

    judge = None
    if not args.dry_run:
        try:
            judge = Judge(max_calls=params.budget.max_model_calls)
            ready = judge.has_credentials()
        except Exception as exc:  # pragma: no cover - defensive
            judge, ready, detail = None, False, str(exc)
        else:
            detail = "no API key, auth token, or profile credential resolved"
        if not ready:
            # A stack trace forty frames deep is a terrible first experience,
            # and the useful half of this pipeline needs no credentials at all.
            print(
                f"cannot reach the Anthropic API: {detail}.\n\n"
                "Set ANTHROPIC_API_KEY (or run `ant auth login`) for the full "
                "run, or use --dry-run for the structural slate — it needs no "
                "credentials and still writes --out.",
                file=sys.stderr,
            )
            return 2

    generator = Generator(graph=graph, params=params, judge=judge)

    if args.dry_run:
        _dry_run(generator)

    slate = generator.run()

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(to_markdown(slate))
        (args.out / "slate.json").write_text(slate.model_dump_json(indent=2))
        print(f"\nwrote {args.out / 'report.md'} and {args.out / 'slate.json'}")
    elif not args.dry_run:
        print(to_markdown(slate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
