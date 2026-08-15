"""Markdown rendering. Inspectability is a deliverable, not a debug aid.

The order of each section is chosen so a skeptical reader hits the weakest part
first: statement, then what would kill it, then the criticism, then the
evidence, then the caveats. A report that leads with the evidence reads as
advocacy.
"""

from __future__ import annotations

from hyp_gen.schema import Hypothesis, Slate

_BAR = "█"


def _meter(value: float, width: int = 10) -> str:
    filled = max(0, min(int(round(value * width)), width))
    return f"{_BAR * filled}{'·' * (width - filled)} {value:.2f}"


def _scores_block(hypothesis: Hypothesis) -> str:
    order = [
        ("support", "how well the graph backs it"),
        ("novelty", "how much it is not already stated"),
        ("testability", "how cheaply it can be settled"),
        ("contradiction_risk", "how much the evidence fights itself"),
        ("structure", "path specificity after hub damping"),
    ]
    lines = ["| axis | score | reading |", "|---|---|---|"]
    for key, gloss in order:
        if key in hypothesis.scores:
            lines.append(f"| {key} | `{_meter(hypothesis.scores[key])}` | {gloss} |")
    return "\n".join(lines)


# Structural errors are found against the graph, before any model call, and
# mean the candidate was never articulated. A citation error is found after the
# fact, against the evidence pack, and means the model wrote something it could
# not source. Both invalidate the hypothesis; they say completely different
# things about *what went wrong*, so the report does not call them the same.
_STRUCTURAL_CODES = {"unknown_thing", "unknown_link", "broken_path", "already_stated"}


def _failure_badges(hypothesis: Hypothesis) -> list[str]:
    errors = [i for i in hypothesis.issues if i.severity == "error"]
    badges: list[str] = []
    if any(i.code in _STRUCTURAL_CODES for i in errors):
        badges.append("**BLOCKED — not articulated**")
    if any(i.code == "illegal_citation" for i in errors):
        badges.append("**CITATION REJECTED — cites evidence it was not shown**")
    if errors and not badges:
        badges.append("**INVALID — see validation**")
    return badges


def _hypothesis_md(hypothesis: Hypothesis, position: int) -> str:
    art = hypothesis.articulation
    out: list[str] = []
    title = art.statement if art else (
        f"{hypothesis.subject_name} → {hypothesis.object_name} "
        f"({hypothesis.motif.replace('_', ' ')})"
    )
    out.append(f"## {position}. {title}")
    out.append("")

    badges = [f"`{hypothesis.motif}`", f"`{hypothesis.hops} hop(s)`"]
    badges += [f"`{t}`" for t in hypothesis.tags]
    if hypothesis.verification:
        badges.append(f"**{hypothesis.verification.verdict.upper()}**")
    if hypothesis.verdict:
        badges.append(f"**verdict: {hypothesis.verdict}**")
    if hypothesis.elo is not None:
        badges.append(f"Elo {hypothesis.elo:.0f}")
    badges.extend(_failure_badges(hypothesis))
    out.append(" · ".join(badges))
    out.append("")

    if art:
        out.append(f"**Mechanism.** {art.mechanism}")
        out.append("")
        out.append(f"**Novel because.** {art.novel_because}")
        out.append("")
        out.append(f"**Killed by.** {art.falsifier}")
        out.append("")
        out.append(f"**Decisive experiment.** {art.decisive_experiment}")
        out.append("")
        if art.predictions:
            out.append("**If true, we should also see**")
            out.extend(f"- {p}" for p in art.predictions)
            out.append("")
        if art.assumptions:
            out.append("**Assumed, not shown**")
            out.extend(f"- {a}" for a in art.assumptions)
            out.append("")
        out.append("**Claims**")
        out.append("")
        out.append("| # | claim | cites | inferred |")
        out.append("|---|---|---|---|")
        for i, claim in enumerate(art.claims):
            cites = ", ".join(f"`{c}`" for c in claim.cites) or "—"
            out.append(f"| {i} | {claim.text} | {cites} | {'yes' if claim.inferred else 'no'} |")
        out.append("")

    for critique in hypothesis.critiques:
        out.append(f"**Critique — {critique.lens or 'general'} ({critique.verdict})**")
        out.append("")
        out.append(f"> {critique.strongest_objection}")
        out.append("")
        if critique.unsupported_leaps:
            out.extend(f"- unsupported leap: {leap}" for leap in critique.unsupported_leaps)
            out.append("")
        if critique.alternative_explanation:
            out.append(f"*Duller reading:* {critique.alternative_explanation}")
            out.append("")

    if hypothesis.verification:
        out.append("**Verification**")
        out.append("")
        out.append("```")
        out.append(hypothesis.verification.table())
        out.append("```")
        out.append("")
        # A halt is the one thing in this report that a reader must not be able
        # to mistake for a clean run, so it gets prose as well as a table row.
        halted = hypothesis.verification.halted_at
        if halted:
            gate = hypothesis.verification.gate(halted)
            out.append(
                f"> Verification stopped at **{halted}**: {gate.summary if gate else ''} "
                "Every gate below it was not run, and none of them should be read as passed."
            )
            out.append("")

    out.append("**Scores**")
    out.append("")
    out.append(_scores_block(hypothesis))
    out.append("")

    if hypothesis.path:
        out.append("**Path**")
        out.append("")
        for step in hypothesis.path:
            arrow = "←" if step["reversed"] else "→"
            support = step["support"]
            support_txt = f"{support:.2f}" if support is not None else "n/a"
            out.append(
                f"- `{step['link']}` {step['from_name']} {arrow} {step['to_name']} "
                f"*({step['how']}, {step['state']}, support {support_txt})*"
            )
        out.append("")

    if hypothesis.evidence.get("findings"):
        out.append("**Source sentences**")
        out.append("")
        for fid, finding in hypothesis.evidence["findings"].items():
            marks = []
            if finding["hedged"]:
                marks.append("hedged")
            if not finding["is_own_result"]:
                marks.append("citing others")
            suffix = f" *[{', '.join(marks)}]*" if marks else ""
            where = finding["where"] or "conditions unstated"
            out.append(
                f"- `{fid}` ({finding['paper']}, {finding['says']}, {where}){suffix}\n"
                f"  > {finding['quote']}"
            )
        out.append("")

    if hypothesis.caveats:
        out.append("**Caveats**")
        out.extend(f"- {c}" for c in hypothesis.caveats)
        out.append("")

    if hypothesis.issues:
        out.append("**Validation**")
        out.extend(
            f"- {'❌' if i.severity == 'error' else '⚠️'} `{i.code}` {i.detail}"
            for i in hypothesis.issues
        )
        out.append("")

    if hypothesis.asks:
        out.append("**To move this, ask Stage 1 for**")
        out.extend(
            f"- `{a.ask}` on `{a.target}` at `{a.depth}` — {a.reason}"
            for a in hypothesis.asks
        )
        out.append("")

    out.append(f"<sub>{hypothesis.provenance}</sub>")
    out.append("")
    return "\n".join(out)


def to_markdown(slate: Slate) -> str:
    cov = slate.coverage
    out = [
        f"# Hypotheses — {slate.graph_id} (round {slate.round})",
        "",
        f"**Question.** {slate.question}" if slate.question else "",
        "",
        f"Graph: {slate.counts.get('things', 0)} things · "
        f"{slate.counts.get('links', 0)} links · "
        f"{slate.counts.get('findings', 0)} findings · "
        f"{slate.counts.get('gaps', 0)} gaps",
        "",
        f"Coverage: `{cov.get('depth')}` depth, read {cov.get('read')} of "
        f"{cov.get('found')} results"
        + (", **truncated**" if cov.get("truncated") else "")
        + ".",
        "",
        f"Shortlisted {slate.counts.get('shortlisted', 0)}, "
        f"blocked {slate.counts.get('blocked', 0)}, "
        f"model calls {slate.counts.get('model_calls', 0)}.",
        "",
        "Verification: "
        + " · ".join(
            f"{slate.counts.get(f'verification_{v}', 0)} {v}"
            for v in ("verified", "qualified", "unverified", "rejected")
        )
        + ".",
        "",
    ]
    if cov.get("truncated") or cov.get("depth") == "quick":
        out += [
            "> Absence of a link in this graph is **not** evidence of absence in "
            "the literature. Every novelty score below is discounted for that, "
            "but read the per-hypothesis caveats before acting on one.",
            "",
        ]

    for i, hypothesis in enumerate(slate.hypotheses, start=1):
        out.append(_hypothesis_md(hypothesis, i))

    if slate.asks:
        out += ["---", "", "## Next round", "", "One ask per request:", ""]
        out += [
            "```json\n"
            + "\n".join(
                f'{{"graph_id": "{a.graph_id}", "ask": "{a.ask}", '
                f'"target": "{a.target}", "depth": "{a.depth}", '
                f'"reason": "{a.reason}"}}'
                for a in slate.asks
            )
            + "\n```",
            "",
        ]
    return "\n".join(line for line in out if line is not None)
