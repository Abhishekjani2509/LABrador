"""Markdown rendering. Inspectability is a deliverable, not a debug aid.

Every renderer here is a pure function of one ``Slate`` -- the same object that
``slate.json`` holds -- so any view can be produced, or reproduced, from a saved
run without re-running the pipeline. That is the property the modes below rest
on: a report is a *view*, and the record is the slate.

Four modes, because four different questions get asked of one slate:

``prose``  (default, ``report.md``)  What is this idea, is it any good, what
           would kill it, what do I do next. Paragraphs, for reading.
``table``  (``report-table.md``)     Which of these should I look at first.
           One row per hypothesis, for scanning and comparing.
``trace``  (``report-trace.md``)     Where did this come from. The graph walk
           node by node, each edge carrying its link id, recomputed support,
           conditions and the findings that back it.
``full``   (``report-full.md``)      Is the work correct. Claims, per-claim
           citations, gate tables and verbatim source sentences.

Order within a hypothesis is chosen so a skeptical reader hits the weakest part
first: statement, then what would kill it, then the criticism, then the
evidence, then the caveats. A report that leads with the evidence reads as
advocacy.

**A mode changes the form, never the safety.** Every signal a reader must not
miss renders in all four: the failure badges, a halted verification, an
error-level validation issue, and the absence-of-evidence warning on a
truncated graph. What a mode may drop is corroboration and detail, all of which
survives in the slate. ``test_every_mode_keeps_the_signals_a_reader_must_not_miss``
is what stops a new mode from quietly becoming a softer one.
"""

from __future__ import annotations

from collections.abc import Callable

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


def _halt_note(hypothesis: Hypothesis) -> str:
    """The one sentence a halted verification must never be read without.

    Gates below a halt did not run. A view that shows the passes and omits the
    halt turns a partial verification into a clean-looking one, so every mode
    calls this rather than formatting its own.
    """
    verification = hypothesis.verification
    if not (verification and verification.halted_at):
        return ""
    halted = verification.halted_at
    gate = verification.gate(halted)
    return (
        f"Verification stopped at **{halted}**: {gate.summary if gate else ''} "
        "Every gate below it was not run, and none of them should be read as passed."
    )


def _flags(hypothesis: Hypothesis) -> list[str]:
    """Compact flags for views with no room for a badge line, e.g. a table row."""
    flags = [b.replace("*", "").split(" — ")[0] for b in _failure_badges(hypothesis)]
    verification = hypothesis.verification
    if verification and verification.halted_at:
        flags.append(f"HALTED at {verification.halted_at}")
    return flags


_SCORE_LABELS = [
    ("support", "support"),
    ("novelty", "novelty"),
    ("testability", "testability"),
    ("contradiction_risk", "contradiction risk"),
]


def _scores_sentence(hypothesis: Hypothesis) -> str:
    """The same numbers as ``_scores_block``, but as one English sentence."""
    parts = [
        f"{label} {hypothesis.scores[key]:.2f}"
        for key, label in _SCORE_LABELS
        if key in hypothesis.scores
    ]
    if not parts:
        return ""
    listed = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    if hypothesis.rank_score is not None:
        return f"It ranks **{hypothesis.rank_score:.2f}** overall, on {listed}."
    return f"It scores {listed}."


def _an(noun: str) -> str:
    return f"an {noun}" if noun[:1] in "aeiou" else f"a {noun}"


_COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine")


def _count_word(n: int) -> str:
    return _COUNT_WORDS[n] if 0 <= n < len(_COUNT_WORDS) else str(n)


def _chain(hypothesis: Hypothesis) -> str:
    """The path as one arrow chain.

    The full renderer gives each hop its own line with link id, state and
    support, which is what an auditor needs. A reader trying to understand the
    idea needs the shape, and the shape fits on one line.
    """
    if not hypothesis.path:
        return ""
    parts = [hypothesis.subject_name]
    for step in hypothesis.path:
        arrow = f"←{step['how']}—" if step["reversed"] else f"—{step['how']}→"
        parts.append(f"{arrow} {step['to_name']}")
    return " ".join(parts)


def _dropped_detail(hypothesis: Hypothesis) -> str:
    """Name what brief mode is not showing.

    A reader who cannot tell that detail was withheld will read a brief report
    as the whole record — the same mistake as reading a truncated search as an
    exhaustive one. So the count is stated even though the content is not.
    """
    art = hypothesis.articulation
    counts: list[str] = []
    if art:
        if art.claims:
            counts.append(f"{len(art.claims)} claims")
        if art.assumptions:
            counts.append(f"{len(art.assumptions)} assumptions")
        if art.predictions:
            counts.append(f"{len(art.predictions)} predictions")
    findings = hypothesis.evidence.get("findings") or {}
    if findings:
        counts.append(f"{len(findings)} source sentences")
    if len(hypothesis.critiques) > 1:
        counts.append(f"{len(hypothesis.critiques) - 1} more critique(s)")
    if not counts:
        return ""
    return (
        f"<sub>Not shown: {', '.join(counts)}, the mechanism write-up and the "
        "gate table — all of it in `slate.json`. Recover with "
        "`hypgen --report-from slate.json --report-mode full --out .`</sub>"
    )


def _hypothesis_brief_md(hypothesis: Hypothesis, position: int) -> str:
    art = hypothesis.articulation
    out: list[str] = []
    title = art.statement if art else (
        f"{hypothesis.subject_name} → {hypothesis.object_name} "
        f"({hypothesis.motif.replace('_', ' ')})"
    )
    out.append(f"## {position}. {title}")
    out.append("")

    # A failed hypothesis leads with the failure, before any prose makes it
    # sound alive.
    badges = _failure_badges(hypothesis)
    if badges:
        out.append(" · ".join(badges))
        out.append("")

    # One paragraph that says what kind of idea this is, how it fared, and how
    # it scored — the sentence a colleague would say out loud before showing
    # you the details.
    motif = _an(hypothesis.motif.replace("_", " "))
    hops = f"{hypothesis.hops} hop{'s' if hypothesis.hops != 1 else ''}"
    intro = f"This is {motif} over {hops}"
    chain = _chain(hypothesis)
    intro += f": {chain}." if chain else "."
    judged: list[str] = []
    if hypothesis.verification:
        judged.append(
            f"Verification judged it **{hypothesis.verification.verdict.upper()}**"
        )
    if hypothesis.verdict:
        clause = f"the critics read it as {hypothesis.verdict.replace('_', ' ')}"
        judged.append(clause if judged else clause[0].upper() + clause[1:])
    if judged:
        intro += " " + ", and ".join(judged) + "."
    scores = _scores_sentence(hypothesis)
    if scores:
        intro += " " + scores
    out.append(intro)
    out.append("")

    if art:
        out.append(f"What would kill it: {art.falsifier}")
        out.append("")
        out.append(f"The experiment that would settle it: {art.decisive_experiment}")
        out.append("")

    # One objection, not all of them: the critics are ordered so the first lens
    # is the one that most nearly sank it. The rest are corroboration, and
    # corroboration is what brief mode is allowed to drop.
    if hypothesis.critiques:
        critique = hypothesis.critiques[0]
        verdict = critique.verdict.replace("_", " ")
        out.append(
            f"The strongest objection comes from the {critique.lens or 'general'} "
            f"critic, which read the hypothesis as {verdict}:"
        )
        out.append("")
        out.append(f"> {critique.strongest_objection}")
        out.append("")

    halt = _halt_note(hypothesis)
    if halt:
        out.append(f"> {halt}")
        out.append("")

    # Caveats are already full sentences written to be read; run them together
    # as a paragraph rather than bulleting them apart.
    if hypothesis.caveats:
        count = len(hypothesis.caveats)
        lead = (
            "One caveat travels with this hypothesis. "
            if count == 1
            else f"{_count_word(count).capitalize()} caveats travel with this hypothesis. "
        )
        out.append(lead + " ".join(hypothesis.caveats))
        out.append("")

    # Warnings are detail; errors mean the hypothesis is invalid, and that
    # travels at every detail level.
    errors = [i for i in hypothesis.issues if i.severity == "error"]
    if errors:
        out.append("Validation rejected it:")
        out.extend(f"- ❌ `{i.code}` {i.detail}" for i in errors)
        out.append("")

    dropped = _dropped_detail(hypothesis)
    if dropped:
        out.append(dropped)
        out.append("")
    return "\n".join(out)


# -- table mode ------------------------------------------------------------


def _cell(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _table_md(slate: Slate) -> str:
    """One row per hypothesis: the view for deciding what to read first.

    Endpoints, not statements, fill the subject column. A statement is a
    paragraph-long sentence and truncating it in a cell would misrepresent a
    hedged claim as a flat one -- the reader is pointed at prose mode instead.
    """
    out = [
        "| # | hypothesis | motif | hops | verification | critics "
        "| support | novelty | testability | rank | flags |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, h in enumerate(slate.hypotheses, start=1):
        verification = h.verification.verdict if h.verification else "—"
        flags = _flags(h)
        out.append(
            f"| {i} | {h.subject_name} → {h.object_name} "
            f"| `{h.motif}` | {h.hops} | {verification} "
            f"| {h.verdict.replace('_', ' ') if h.verdict else '—'} "
            f"| {_cell(h.scores.get('support'))} "
            f"| {_cell(h.scores.get('novelty'))} "
            f"| {_cell(h.scores.get('testability'))} "
            f"| {_cell(h.rank_score)} "
            f"| {'; '.join(flags) if flags else ''} |"
        )
    out.append("")
    out.append(
        "Ranking orders the page; it does not grade the science. Columns are "
        "separate axes on purpose — a hypothesis with high support and low "
        "novelty is a known fact, and averaging them would rank it first."
    )
    out.append("")

    # A flag in a cell is easy to skim past, so anything flagged gets restated
    # underneath at full width. A table must not be the view where a rejected
    # hypothesis looks like a slightly worse row.
    flagged = [(i, h) for i, h in enumerate(slate.hypotheses, start=1) if _flags(h)]
    if flagged:
        out.append("**Flagged rows**")
        out.append("")
        for i, h in flagged:
            for badge in _failure_badges(h):
                out.append(f"- {i}. {badge}")
            for issue in (x for x in h.issues if x.severity == "error"):
                out.append(f"  - ❌ `{issue.code}` {issue.detail}")
            halt = _halt_note(h)
            if halt:
                out.append(f"- {i}. {halt}")
        out.append("")
    return "\n".join(out)


# -- trace mode ------------------------------------------------------------


def _trace_md(hypothesis: Hypothesis, position: int) -> str:
    """The graph walk, node by node, with each edge's evidence hanging off it.

    This is the provenance view: it answers "where did this come from" without
    the reader having to trust any prose. Every hop names its link id, the
    support recomputed from findings (not the graph's stated confidence), the
    conditions the result was measured under, and the finding ids on each side
    of the question -- including `no` and `no_effect`, because an edge that
    something argues against is exactly what a trace exists to surface.
    """
    out = [f"## {position}. {hypothesis.subject_name} → {hypothesis.object_name}"]
    out.append("")
    badges = _failure_badges(hypothesis)
    if badges:
        out.append(" · ".join(badges))
        out.append("")
    out.append(
        f"`{hypothesis.motif}` · {hypothesis.hops} hop(s) · {hypothesis.provenance}"
    )
    out.append("")

    links = hypothesis.evidence.get("links") or {}
    findings = hypothesis.evidence.get("findings") or {}
    out.append("```")
    out.append(f"{hypothesis.subject_name}  ({hypothesis.subject})")
    for step in hypothesis.path:
        link = links.get(step["link"], {})
        support = step.get("support")
        support_txt = "n/a" if support is None else f"{support:.2f}"
        direction = "reversed" if step["reversed"] else "forward"
        out.append(
            f"  │  {step['link']}  {step['how']}  "
            f"[{step['state']}, {direction}, support {support_txt}]"
        )
        conditions = link.get("conditions") or []
        if conditions:
            out.append(f"  │    conditions: {', '.join(conditions)}")
        stated = link.get("stated_confidence")
        if stated is not None and support is not None:
            drift = support - stated
            if abs(drift) >= 0.005:
                direction_word = "below" if drift < 0 else "above"
                out.append(
                    f"  │    recomputed {abs(drift):.2f} {direction_word} the "
                    f"graph's stated confidence of {stated:.2f}"
                )
        for verdict_key, label in (
            ("yes", "supports"),
            ("no", "contradicts"),
            ("no_effect", "no effect"),
        ):
            for finding_id in link.get(verdict_key) or []:
                finding = findings.get(finding_id, {})
                marks = []
                if finding.get("hedged"):
                    marks.append("hedged")
                if finding.get("is_own_result") is False:
                    marks.append("citing others")
                suffix = f" [{', '.join(marks)}]" if marks else ""
                paper = finding.get("paper", "?")
                where = finding.get("where") or "conditions unstated"
                out.append(
                    f"  │    {label}: {finding_id} ({paper}, {where}){suffix}"
                )
                quote = finding.get("quote")
                if quote:
                    out.append(f'  │      "{quote}"')
        arrow = "▲" if step["reversed"] else "▼"
        out.append(f"  {arrow}")
        out.append(f"{step['to_name']}  ({step['to']})")
    out.append("```")
    out.append("")

    gap = hypothesis.evidence.get("gap")
    if gap:
        out.append(f"Closes gap `{gap.get('id', '?')}`: {gap.get('why') or gap}")
        out.append("")

    notes = hypothesis.evidence.get("scoring_notes") or []
    if notes:
        out.append("**How the scores got their values**")
        out.extend(f"- {n}" for n in notes)
        out.append("")

    halt = _halt_note(hypothesis)
    if halt:
        out.append(f"> {halt}")
        out.append("")

    errors = [i for i in hypothesis.issues if i.severity == "error"]
    if errors:
        out.append("Validation rejected it:")
        out.extend(f"- ❌ `{i.code}` {i.detail}" for i in errors)
        out.append("")

    if hypothesis.caveats:
        out.append("**Caveats**")
        out.extend(f"- {c}" for c in hypothesis.caveats)
        out.append("")
    return "\n".join(out)


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


def _header(slate: Slate, mode: str) -> list[str]:
    cov = slate.coverage
    verification = " · ".join(
        f"{slate.counts.get(f'verification_{v}', 0)} {v}"
        for v in ("verified", "qualified", "unverified", "rejected")
    )
    if mode == "prose":
        # A short narrative instead of stat lines. The truncation flag stays in
        # the same sentence as the read counts: it is the fact that decides how
        # much any novelty score below is worth.
        outcomes = ", ".join(
            f"{slate.counts.get(f'verification_{v}', 0)} {v}"
            for v in ("verified", "qualified", "unverified", "rejected")
            if slate.counts.get(f"verification_{v}", 0)
        )
        n = len(slate.hypotheses)
        produced = (
            f"This run produced {_count_word(n)} "
            f"hypothes{'is' if n == 1 else 'es'}"
            + (f" ({outcomes})" if outcomes else "")
            + f" in {slate.counts.get('model_calls', 0)} model calls, "
            f"working from a graph of {slate.counts.get('things', 0)} things, "
            f"{slate.counts.get('links', 0)} links and "
            f"{slate.counts.get('findings', 0)} findings."
        )
        read = (
            f" The underlying search read {cov.get('read')} of its "
            f"{cov.get('found')} results"
            + (
                ", so the graph is a **truncated sample** of the literature, "
                "not the literature"
                if cov.get("truncated")
                else ""
            )
            + "."
        )
        return [
            f"# Hypotheses — {slate.graph_id} (round {slate.round})",
            "",
            f"The question this slate answers: **{slate.question}**"
            if slate.question
            else "",
            "",
            produced + read,
            "",
        ]
    return [
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
        f"Verification: {verification}.",
        "",
    ]


# Every mode is a function of the slate and nothing else. Adding one means
# adding a renderer here; the CLI, the filenames and the mode validation all
# read from this map rather than repeating the list.
MODES: dict[str, Callable[[Hypothesis, int], str]] = {
    "prose": _hypothesis_brief_md,
    "trace": _trace_md,
    "full": _hypothesis_md,
}
# table renders the whole slate at once rather than per hypothesis.
MODE_NAMES: tuple[str, ...] = ("prose", "table", "trace", "full")

FILENAMES: dict[str, str] = {
    "prose": "report.md",
    "table": "report-table.md",
    "trace": "report-trace.md",
    "full": "report-full.md",
}


def to_markdown(slate: Slate, mode: str = "prose") -> str:
    """Render a slate in one of ``MODE_NAMES``.

    ``prose`` is the default because the report exists to be read, and a reader
    who gives up three screens in has got nothing from the audit trail either.
    Every mode is a pure function of the slate, so any view can be produced
    from a saved ``slate.json`` without re-running the pipeline.
    """
    if mode not in MODE_NAMES:
        raise ValueError(
            f"mode must be one of {', '.join(MODE_NAMES)}, got {mode!r}"
        )
    cov = slate.coverage
    out = _header(slate, mode)
    # This warning is the reason a novelty score means anything, so it is not a
    # mode's to drop -- including the table, where scores are most inviting to
    # read straight off the page.
    if cov.get("truncated") or cov.get("depth") == "quick":
        out += [
            "> Absence of a link in this graph is **not** evidence of absence in "
            "the literature. Every novelty score below is discounted for that, "
            "but read the per-hypothesis caveats before acting on one.",
            "",
        ]

    if mode == "table":
        out.append(_table_md(slate))
    else:
        render = MODES[mode]
        for i, hypothesis in enumerate(slate.hypotheses, start=1):
            out.append(render(hypothesis, i))

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
