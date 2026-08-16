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

from hyp_gen import report, valuation, verify
from hyp_gen.evidence import build_pack
from hyp_gen.graph import GraphIndex, KnowledgeGraph
from hyp_gen.llm import Judge
from hyp_gen.params import PROFILES, Params
from hyp_gen.pipeline import Generator
from hyp_gen.report import to_markdown
from hyp_gen.schema import Slate


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
    # The stance is the single most consequential choice a caller makes, and it
    # is invisible in the table below. Print what it actually resolved to, so a
    # surprising slate is traceable to the dial rather than to the graph.
    stance, traversal = generator.params.stance, generator.params.traversal
    dial = "—" if stance.craziness is None else f"{stance.craziness:.2f}"
    print(
        f"  stance: profile {stance.profile}, craziness {dial}"
        f"  →  {traversal.max_hops} hops, links ≥ {traversal.min_link_confidence}, "
        f"{generator.params.evidence.min_independent_groups} independent group(s)"
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


def _emit_programs(slate: Slate, frame_path: Path | None, out: Path) -> int:
    """Write one LABrador ``ProgramInput`` per molecule in the slate.

    The frame is mandatory. ``--emit-frame-template`` writes a starter with the
    four year fields left null, and pydantic rejects it until a human fills them
    in -- which is the point. A default filing year would be indistinguishable
    from a sourced one once it is in the JSON, and it moves the protected window
    LABrador reports.
    """
    if frame_path is None:
        print(
            "--emit-programs needs --frame. Currency, geography, route, the launch year "
            "and the patent filing year are analyst decisions, not graph findings, and "
            "this stage will not guess them.\n\n"
            "  hypgen --graph G --emit-frame-template frame.json   # then edit it",
            file=sys.stderr,
        )
        return 2
    try:
        frame = valuation.ProgramFrame.load(json.loads(frame_path.read_text()))
    except Exception as exc:
        print(f"invalid frame {frame_path}: {exc}", file=sys.stderr)
        return 2

    emission = valuation.emit(slate, frame)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for program in emission.programs:
        path = out / f"{program['program_id']}.program.json"
        path.write_text(json.dumps(program, indent=2))
        written.append(path)

    # LABrador's `analyze` requires a comparable catalogue, and the graph has no
    # price of any basis. An empty one is the honest catalogue: it makes the
    # missing-anchor warning fire instead of hiding the absence.
    comparables = out / "comparables.json"
    comparables.write_text("[]\n")
    (out / "emission.json").write_text(emission.model_dump_json(indent=2))

    for path in written:
        print(f"wrote {path}")
    print(f"wrote {comparables} (empty: the graph contains no price evidence)")
    for skipped in emission.skipped:
        print(f"skipped {skipped.hypothesis_id}: {skipped.reason} — {skipped.detail}")
    for note in emission.notes:
        print(f"note: {note}")
    if written:
        print(
            f"\nnext:  labrador analyze {written[0]} --comparables {comparables} "
            "--simulations 200 --seed 42"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hypgen")
    parser.add_argument("--graph", type=Path, help="Stage 1 graph JSON")
    parser.add_argument("--profile", default="default", choices=sorted(PROFILES))
    parser.add_argument(
        "--craziness",
        type=float,
        metavar="0.0-1.0",
        help=(
            "how far out to reach: 0 is super safe (short paths, strong links, two "
            "independent groups), 1 is very ambitious (long paths, weak links, "
            "cross-kind analogy). Composes with --profile, which sets the question "
            "rather than the appetite."
        ),
    )
    parser.add_argument("--params", type=Path, help="params JSON, overrides --profile")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="GROUP.KEY=VALUE",
        help="patch one parameter, e.g. --set traversal.max_hops=4",
    )
    parser.add_argument("--out", type=Path, help="directory for report.md and slate.json")
    parser.add_argument(
        "--report-mode",
        action="append",
        choices=report.MODE_NAMES,
        metavar="MODE",
        help=(
            "which view(s) to write, repeatable: prose (report.md, the default) "
            "| table (report-table.md, one row per hypothesis) | trace "
            "(report-trace.md, the graph walk with each edge's evidence) | full "
            "(report-full.md, claims, gate tables and verbatim sources)"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="no model calls")
    parser.add_argument(
        "--emit-programs",
        type=Path,
        metavar="DIR",
        help="also write LABrador ProgramInput JSON for each molecule in the slate",
    )
    parser.add_argument(
        "--frame",
        type=Path,
        help="analyst frame JSON required by --emit-programs",
    )
    parser.add_argument(
        "--emit-frame-template",
        type=Path,
        metavar="FILE",
        help="write a starter frame and exit",
    )
    parser.add_argument(
        "--emit-programs-from",
        type=Path,
        metavar="SLATE",
        help="emit programs from an existing slate.json instead of generating one",
    )
    parser.add_argument(
        "--report-from",
        type=Path,
        metavar="SLATE",
        help=(
            "re-render from an existing slate.json and exit, in whichever "
            "--report-mode(s) you ask for. Rendering is a pure function of the "
            "slate, so this costs no model calls"
        ),
    )
    args = parser.parse_args(argv)

    if args.report_from:
        # Every view is recoverable from the slate at any time, which is what
        # makes a short report.md safe as the default: nothing is lost by not
        # printing a view, only by not keeping slate.json.
        slate = Slate.model_validate(json.loads(args.report_from.read_text()))
        modes = args.report_mode or ["prose"]
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            for mode in modes:
                path = args.out / report.FILENAMES[mode]
                path.write_text(to_markdown(slate, mode=mode))
                print(f"wrote {path} ({mode})")
        else:
            print("\n\n".join(to_markdown(slate, mode=m) for m in modes))
        return 0

    if args.emit_programs_from:
        # Emitting off the slate a caller already has, rather than regenerating,
        # is the difference between a brief that matches the report they read and
        # one that merely resembles it. Re-running would also re-pay for the
        # model stages to arrive at the same place.
        if not args.emit_programs:
            parser.error("--emit-programs-from needs --emit-programs DIR")
        slate = Slate.model_validate(json.loads(args.emit_programs_from.read_text()))
        return _emit_programs(slate, args.frame, args.emit_programs)

    if args.emit_frame_template:
        args.emit_frame_template.parent.mkdir(parents=True, exist_ok=True)
        args.emit_frame_template.write_text(
            json.dumps(valuation.ProgramFrame.template(), indent=2) + "\n"
        )
        print(f"wrote {args.emit_frame_template} — fill in the four null year fields")
        return 0
    if args.graph is None:
        parser.error("--graph is required")

    graph = KnowledgeGraph.load(args.graph)
    overrides = _overrides(args.set)
    if args.params:
        if args.craziness is not None:
            parser.error("--params is a complete parameter set; --craziness derives one")
        base = Params.load(args.params).model_dump()
        for group, values in overrides.items():
            base.setdefault(group, {}).update(values)
        params = Params.model_validate(base)
    elif args.craziness is not None:
        try:
            params = Params.at_craziness(args.craziness, args.profile, overrides)
        except ValueError as exc:
            parser.error(str(exc))
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
        # The slate is the record; the reports are views of it. Write the slate
        # whatever was asked for, so any view missed here is recoverable later
        # with --report-from.
        (args.out / "slate.json").write_text(slate.model_dump_json(indent=2))
        for mode in args.report_mode or ["prose"]:
            path = args.out / report.FILENAMES[mode]
            path.write_text(to_markdown(slate, mode=mode))
            print(f"\nwrote {path} ({mode})")
        print(f"wrote {args.out / 'slate.json'}")
    elif not args.dry_run:
        print(to_markdown(slate))

    if args.emit_programs:
        return _emit_programs(slate, args.frame, args.emit_programs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
