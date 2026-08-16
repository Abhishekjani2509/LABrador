"""End to end, including the model stages driven by a scripted fake judge.

The fake judge is not a mock of convenience -- it is how the harness's own
failure handling gets tested. A judge that refuses, that runs out of budget, or
that cites something it was never shown are all things the real one will
eventually do, and all three must degrade into a visible warning rather than a
crash or a silent pass.
"""

from __future__ import annotations

import json

import pytest

from hyp_gen.evidence import build_pack
from hyp_gen.graph import GraphIndex, KnowledgeGraph
from hyp_gen.llm import BudgetExceeded, RefusalError
from hyp_gen.params import (
    BudgetParams,
    EvidenceParams,
    LoopParams,
    MotifParams,
    Params,
    RankingParams,
    SelectionParams,
)
from hyp_gen.pipeline import Generator
from hyp_gen import report
from hyp_gen.report import to_markdown
from hyp_gen.schema import Articulation, Claim, Comparison, Critique, Slate
from hyp_gen.scoring import score_candidate


class FakeJudge:
    """Returns schema-valid answers without touching the network."""

    def __init__(self, *, cite: str | None = None, verdict: str = "partly_supported",
                 raises: Exception | None = None, max_calls: int = 40,
                 prefers: str | None = None) -> None:
        self.cite = cite
        self.verdict = verdict
        self.raises = raises
        self.max_calls = max_calls
        # `prefers` makes comparisons content-based rather than positional:
        # whichever side's evidence pack mentions this id wins, wherever it is
        # shown. Without it the fake always answers "A", which is the position
        # bias the tournament is supposed to detect.
        self.prefers = prefers
        self.calls = 0
        self.systems: list[str] = []

    def parse(self, *, system, prompt, schema, effort="high", max_tokens=8000):
        self.calls += 1
        if self.calls > self.max_calls:
            raise BudgetExceeded("out of budget")
        if self.raises is not None:
            raise self.raises
        self.systems.append(system)
        if schema is Articulation:
            cites = [self.cite] if self.cite else []
            return Articulation(
                statement="A causes B under condition C.",
                mechanism="A -> X -> B",
                claims=[Claim(text="A binds X", cites=cites, inferred=not cites)],
                novel_because="the graph never states A to B",
                predictions=["X rises before B"],
                falsifier="B occurs with X knocked out",
                decisive_experiment="knock out X and measure B",
                assumptions=["X is measurable in this system"],
            )
        if schema is Critique:
            return Critique(
                verdict=self.verdict,
                strongest_objection="the middle link is single-source",
                unsupported_leaps=["A to B is not stated"],
            )
        if schema is Comparison:
            winner = "A"
            if self.prefers:
                first, _, second = prompt.partition("=" * 60)
                if self.prefers not in first and self.prefers in second:
                    winner = "B"
            return Comparison(winner=winner, margin="clear", reason="better evidence")
        raise AssertionError(f"unexpected schema {schema}")


def _params(**ranking) -> Params:
    return Params(
        selection=SelectionParams(top_k=3),
        ranking=RankingParams(**ranking),
    )


def test_runs_without_a_judge(graph: KnowledgeGraph, params: Params) -> None:
    """The deterministic half must stand alone -- this is what --dry-run and a
    keyless demo depend on."""
    slate = Generator(graph=graph, params=params).run()
    assert isinstance(slate, Slate)
    assert slate.hypotheses
    assert slate.counts["model_calls"] == 0
    assert all(h.articulation is None for h in slate.hypotheses)


def test_every_hypothesis_is_traceable(graph: KnowledgeGraph, params: Params) -> None:
    """Each one has to carry its own audit trail: links, findings, quotes."""
    slate = Generator(graph=graph, params=params).run()
    index = GraphIndex(graph)
    for hypothesis in slate.hypotheses:
        assert hypothesis.provenance
        for step in hypothesis.path:
            assert step["link"] in index.links
        for fid, finding in hypothesis.evidence["findings"].items():
            assert fid in index.findings
            assert finding["quote"], "a finding with no verbatim sentence is unciteable"


def test_articulates_and_critiques_with_lenses(graph: KnowledgeGraph) -> None:
    judge = FakeJudge()
    params = _params(critics_per_hypothesis=2)
    slate = Generator(graph=graph, params=params, judge=judge).run()
    live = [h for h in slate.hypotheses if not h.blocked]
    assert live
    for hypothesis in live:
        assert hypothesis.articulation is not None
        assert [c.lens for c in hypothesis.critiques] == ["mechanism", "evidence"]
        assert hypothesis.verdict is not None


def test_critic_count_drives_the_call_budget(graph: KnowledgeGraph) -> None:
    one = FakeJudge()
    three = FakeJudge()
    Generator(graph=graph, params=_params(critics_per_hypothesis=1), judge=one).run()
    Generator(graph=graph, params=_params(critics_per_hypothesis=3), judge=three).run()
    assert three.calls > one.calls


def test_consensus_needs_a_majority_to_refute(graph: KnowledgeGraph) -> None:
    """One lens calling it unsupported is information, not a ruling."""
    params = _params(critics_per_hypothesis=3, refute_threshold=0.9)
    slate = Generator(graph=graph, params=params, judge=FakeJudge(verdict="unsupported")).run()
    live = [h for h in slate.hypotheses if not h.blocked]
    assert all(h.verdict == "unsupported" for h in live)

    lenient = _params(critics_per_hypothesis=3, refute_threshold=0.34)
    slate2 = Generator(
        graph=graph, params=lenient, judge=FakeJudge(verdict="supported")
    ).run()
    assert all(h.verdict == "supported" for h in slate2.hypotheses if not h.blocked)


def test_illegal_citations_surface_as_errors(graph: KnowledgeGraph) -> None:
    judge = FakeJudge(cite="L-does-not-exist")
    slate = Generator(graph=graph, params=_params(), judge=judge).run()
    codes = {i.code for h in slate.hypotheses for i in h.issues}
    assert "illegal_citation" in codes


def test_a_refusal_degrades_to_a_warning(graph: KnowledgeGraph) -> None:
    judge = FakeJudge(raises=RefusalError("classifier declined"))
    slate = Generator(graph=graph, params=_params(), judge=judge).run()
    assert slate.hypotheses  # the run survives
    codes = {i.code for h in slate.hypotheses for i in h.issues}
    assert "articulate_failed" in codes


def test_budget_stops_the_run_not_just_one_hypothesis(graph: KnowledgeGraph) -> None:
    """The ceiling is a stop. Retrying it once per survivor would burn the rest
    of the run rediscovering the same thing."""
    judge = FakeJudge(max_calls=1)
    params = Params(
        selection=SelectionParams(top_k=3),
        ranking=RankingParams(critics_per_hypothesis=2),
        budget=BudgetParams(max_model_calls=1),
    )
    slate = Generator(graph=graph, params=params, judge=judge).run()
    assert judge.calls == 2  # the call that trips it, and no more
    codes = {i.code for h in slate.hypotheses for i in h.issues}
    assert "skipped_no_budget" in codes


def test_stale_gaps_are_dropped_before_selection(graph: KnowledgeGraph) -> None:
    """A gap whose pair now has a link was promoted (or is wrong). Proposing it
    is a restatement, and it must not take a slot from a real candidate."""
    clone = graph.model_copy(deep=True)
    clone.gaps[0].missing = ["t1", "t3"]  # g1 now names a pair L1 already links
    wide = Params(selection=SelectionParams(top_k=12))
    slate = Generator(graph=clone, params=wide).run()
    assert "H-g1" not in {h.id for h in slate.hypotheses}
    assert "H-g2" in {h.id for h in slate.hypotheses}  # the untouched gap survives
    assert all(not h.blocked for h in slate.hypotheses)


def test_structurally_invalid_candidates_never_reach_the_model(
    graph: KnowledgeGraph,
) -> None:
    """Belt and braces: if a bad candidate does reach assembly, it is blocked
    before a model call is spent on it."""
    clone = graph.model_copy(deep=True)
    clone.gaps[0].missing = ["t1", "t3"]
    lenient = Params(
        selection=SelectionParams(top_k=12),
        motifs=MotifParams(require_unstated=False),
        ranking=RankingParams(critics_per_hypothesis=1),
    )
    judge = FakeJudge()
    slate = Generator(graph=clone, params=lenient, judge=judge).run()

    stale = next(h for h in slate.hypotheses if h.id == "H-g1")
    assert stale.blocked
    assert stale.articulation is None
    assert "already_stated" in {i.code for i in stale.issues}


def test_tournament_ranks_on_content(graph: KnowledgeGraph) -> None:
    params = _params(tournament=True, critics_per_hypothesis=1)
    judge = FakeJudge(prefers="L8")  # decides by evidence, not by position
    slate = Generator(graph=graph, params=params, judge=judge).run()

    rated = [h for h in slate.hypotheses if h.elo is not None]
    assert len(rated) >= 2
    assert rated == sorted(rated, key=lambda h: -h.elo)
    assert len({h.elo for h in rated}) > 1  # the debates moved something
    # The winner is the one whose pack actually contains the preferred link.
    assert "L8" in rated[0].evidence["links"]


def test_tournament_refuses_to_rank_a_position_biased_judge(graph: KnowledgeGraph) -> None:
    """A judge that always says "A" is exactly what swapped passes exist to
    catch: the verdict flips with the order, so nothing separates."""
    params = _params(tournament=True, critics_per_hypothesis=1, debate_turns=2)
    slate = Generator(graph=graph, params=params, judge=FakeJudge()).run()
    rated = [h for h in slate.hypotheses if h.elo is not None]
    assert len(rated) >= 2
    assert len({h.elo for h in rated}) == 1  # split verdicts, no movement


def test_single_debate_turn_takes_the_judge_at_its_word(graph: KnowledgeGraph) -> None:
    """With one pass there is no swap to disagree with, so even a biased judge
    produces a ranking -- which is the argument for debate_turns >= 2."""
    params = _params(tournament=True, critics_per_hypothesis=1, debate_turns=1)
    slate = Generator(graph=graph, params=params, judge=FakeJudge()).run()
    rated = [h for h in slate.hypotheses if h.elo is not None]
    assert len({h.elo for h in rated}) > 1


def test_evolution_revises_and_rechecks(graph: KnowledgeGraph) -> None:
    params = _params(critics_per_hypothesis=1, evolution_rounds=1, evolve_top_n=1)
    slate = Generator(graph=graph, params=params, judge=FakeJudge()).run()
    evolved = [h for h in slate.hypotheses if h.evolved_from]
    assert evolved
    assert evolved[0].evolution_operator in params.ranking.evolve_operators


def test_asks_are_off_until_the_loop_is_enabled(graph: KnowledgeGraph) -> None:
    assert Generator(graph=graph, params=Params()).run().asks == []

    looped = Params(loop=LoopParams(enabled=True, max_requests=5))
    slate = Generator(graph=graph, params=looped).run()
    assert slate.asks
    for ask in slate.asks:
        assert ask.graph_id == graph.graph_id
        assert ask.ask in {"expand_node", "resolve_link", "test_gap", "new_question"}
        assert ask.reason


def test_asks_only_target_unsearched_gaps(graph: KnowledgeGraph) -> None:
    """g2 was already searched; asking Stage 1 to look again wastes a round."""
    looped = Params(loop=LoopParams(enabled=True, max_requests=10))
    slate = Generator(graph=graph, params=looped).run()
    gap_targets = {a.target for a in slate.asks if a.ask == "test_gap"}
    assert "g2" not in gap_targets


def test_asks_are_deduped_and_capped(graph: KnowledgeGraph) -> None:
    looped = Params(loop=LoopParams(enabled=True, max_requests=2))
    slate = Generator(graph=graph, params=looped).run()
    assert len(slate.asks) <= 2
    keys = [(a.ask, a.target) for a in slate.asks]
    assert len(keys) == len(set(keys))


def test_slate_serialises_and_round_trips(graph: KnowledgeGraph) -> None:
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    payload = json.loads(slate.model_dump_json())
    assert Slate.model_validate(payload).graph_id == slate.graph_id
    # The params that produced it travel with it, or the run is not reproducible.
    assert payload["params"]["traversal"]["max_hops"]


def test_report_renders_the_audit_trail(graph: KnowledgeGraph) -> None:
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    markdown = to_markdown(slate, mode="full")
    assert "# Hypotheses" in markdown
    assert "Killed by" in markdown
    assert "Source sentences" in markdown
    # The coverage warning is not optional on a truncated graph.
    assert "not** evidence of absence" in markdown


def test_the_brief_report_is_the_default_and_is_much_shorter(
    graph: KnowledgeGraph,
) -> None:
    """report.md is read by humans; the audit trail is read by auditors.

    Brief being the *default* is the point -- a reader who has to know about a
    flag to get a readable report does not get one.
    """
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    brief = to_markdown(slate)
    assert brief == to_markdown(slate, mode="prose")
    assert len(brief) < len(to_markdown(slate, mode="full")) / 2
    # The corroboration is what got dropped, not the idea or its refutation.
    assert "What would kill it" in brief
    assert "The experiment that would settle it" in brief
    assert "Source sentences" not in brief
    # ...and a reader is told detail was withheld, rather than left to assume
    # the short report is the whole record.
    assert "slate.json" in brief


def test_the_brief_report_keeps_every_warning_the_full_one_has(
    graph: KnowledgeGraph,
) -> None:
    """Brief is a shorter view, not a softer one."""
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    brief = to_markdown(slate)
    # Truncated coverage: the absence-of-evidence warning is not optional.
    assert "not** evidence of absence" in brief
    # Per-hypothesis caveats survive too -- they carry the same warning down to
    # the individual claim.
    assert "caveat" in brief.lower()


def test_every_mode_keeps_the_signals_a_reader_must_not_miss(
    graph: KnowledgeGraph,
) -> None:
    """A mode changes the form, never the safety.

    This is the test that stops a new view from quietly becoming a softer one:
    whatever shape it renders in, it carries the absence-of-evidence warning
    and it names a rejected hypothesis as rejected.
    """
    judge = FakeJudge(cite="L-does-not-exist")  # every hypothesis fails citations
    slate = Generator(graph=graph, params=_params(), judge=judge).run()
    assert any(
        i.code == "illegal_citation" for h in slate.hypotheses for i in h.issues
    ), "fixture must actually produce a rejected hypothesis"

    for mode in report.MODE_NAMES:
        rendered = to_markdown(slate, mode=mode)
        assert "not** evidence of absence" in rendered, mode
        assert "CITATION REJECTED" in rendered, mode


def test_every_mode_renders_every_hypothesis(graph: KnowledgeGraph) -> None:
    """A view that silently drops rows is worse than no view."""
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    assert len(slate.hypotheses) > 1
    for mode in report.MODE_NAMES:
        rendered = to_markdown(slate, mode=mode)
        for hypothesis in slate.hypotheses:
            assert hypothesis.subject_name in rendered, (mode, hypothesis.id)


def test_trace_mode_names_every_link_and_its_evidence(graph: KnowledgeGraph) -> None:
    """Trace answers 'where did this come from', so the ids have to be in it."""
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    trace = to_markdown(slate, mode="trace")
    for hypothesis in slate.hypotheses:
        for step in hypothesis.path:
            assert step["link"] in trace
        for finding_id, finding in hypothesis.evidence["findings"].items():
            assert finding_id in trace
            # The verbatim sentence, not a paraphrase of it.
            assert finding["quote"] in trace


def test_table_mode_is_one_row_per_hypothesis(graph: KnowledgeGraph) -> None:
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    table = to_markdown(slate, mode="table")
    # The `|---|` separator does not match this filter, so it is the header row
    # plus exactly one row per hypothesis.
    rows = [line for line in table.splitlines() if line.startswith("| ")]
    assert len(rows) == len(slate.hypotheses) + 1


def test_an_unknown_mode_is_an_error(graph: KnowledgeGraph) -> None:
    """Silently falling back to prose would hand an auditor a partial record
    that looks complete."""
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    with pytest.raises(ValueError, match="mode must be"):
        to_markdown(slate, mode="verbose")


def test_run_is_reproducible(graph: KnowledgeGraph, params: Params) -> None:
    first = Generator(graph=graph, params=params).run()
    second = Generator(graph=graph, params=params).run()
    assert [h.id for h in first.hypotheses] == [h.id for h in second.hypotheses]
    assert [h.rank_score for h in first.hypotheses] == [
        h.rank_score for h in second.hypotheses
    ]


def test_output_cap_is_enforced(graph: KnowledgeGraph) -> None:
    params = Params(
        selection=SelectionParams(top_k=8), budget=BudgetParams(max_output_hypotheses=2)
    )
    assert len(Generator(graph=graph, params=params).run().hypotheses) == 2


def test_evidence_pack_bounds_the_model_world(graph: KnowledgeGraph, params: Params) -> None:
    """Whatever is not in the pack cannot be cited, so the pack must contain
    every id the candidate rests on and nothing else."""
    index = GraphIndex(graph)
    generator = Generator(graph=graph, params=params)
    candidate, scores = generator.shortlist()[0]
    pack = build_pack(index, candidate, score_candidate(index, candidate, params))
    legal = pack.legal_ids()
    for link_id in candidate.link_ids:
        assert link_id in legal
    rendered = pack.to_prompt()
    assert "FINDINGS" in rendered and "PAPERS" in rendered
    unrelated = set(index.links) - set(candidate.link_ids)
    assert not (unrelated & legal)


@pytest.mark.parametrize("profile", ["default", "conservative", "speculative", "repurposing"])
def test_profiles_all_produce_something(graph: KnowledgeGraph, profile: str) -> None:
    from hyp_gen.params import PROFILES

    slate = Generator(graph=graph, params=PROFILES[profile]).run()
    assert slate.hypotheses, f"{profile} produced an empty slate"


def test_conservative_is_stricter_than_speculative(graph: KnowledgeGraph) -> None:
    from hyp_gen.params import PROFILES

    conservative = Generator(graph=graph, params=PROFILES["conservative"]).run()
    speculative = Generator(graph=graph, params=PROFILES["speculative"]).run()
    assert len(conservative.hypotheses) <= len(speculative.hypotheses)
    assert max(h.scores["novelty"] for h in speculative.hypotheses) >= max(
        h.scores["novelty"] for h in conservative.hypotheses
    )


def test_report_names_the_failure_it_found(graph: KnowledgeGraph) -> None:
    """"Blocked before we spent a call" and "the model cited what it was never
    shown" are different diagnoses, and the badge has to say which."""
    from hyp_gen.report import _failure_badges
    from hyp_gen.schema import Hypothesis, ValidationIssue

    def badge(*codes: str) -> str:
        h = Hypothesis(
            id="h", motif="m", subject="a", object="b",
            subject_name="a", object_name="b", hops=1,
            issues=[ValidationIssue(code=c, detail="", severity="error") for c in codes],
        )
        return " ".join(_failure_badges(h))

    assert "BLOCKED" in badge("already_stated")
    assert "CITATION REJECTED" in badge("illegal_citation")
    both = badge("broken_path", "illegal_citation")
    assert "BLOCKED" in both and "CITATION REJECTED" in both
    assert badge() == ""

    # And a run whose model cites out of pack is labelled that way end to end.
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge(cite="L-nope")).run()
    assert "CITATION REJECTED" in to_markdown(slate)


def test_every_hypothesis_carries_a_verification(
    graph: KnowledgeGraph, params: Params
) -> None:
    """Including the ones the model half never reached. A hypothesis with no
    gate table is one a reader cannot tell was checked."""
    slate = Generator(graph=graph, params=params).run()
    assert slate.hypotheses
    for hypothesis in slate.hypotheses:
        assert hypothesis.verification is not None
        assert hypothesis.verification.gates


def test_verification_counts_reach_the_slate(graph: KnowledgeGraph) -> None:
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    tallied = sum(
        slate.counts[f"verification_{v}"]
        for v in ("verified", "qualified", "unverified", "rejected")
    )
    assert tallied == len(slate.hypotheses)


def test_a_failed_gate_is_published_not_deleted(graph: KnowledgeGraph) -> None:
    """The gates added by the staged process express themselves through the
    verdict, never by making a hypothesis vanish from the slate -- a check
    whose failures are invisible reads as assurance."""
    strict = Params(
        selection=SelectionParams(top_k=3),
        ranking=RankingParams(critics_per_hypothesis=1),
        evidence=EvidenceParams(min_independent_groups=99),
    )
    slate = Generator(graph=graph, params=strict, judge=FakeJudge()).run()

    assert slate.hypotheses
    for hypothesis in slate.hypotheses:
        assert hypothesis.verification.halted_at == "independence"
        assert hypothesis.verification.verdict == "unverified"
        assert not hypothesis.blocked, "a gate failure must not block the slate"


def test_halting_stops_the_model_gate_from_spending_calls(
    graph: KnowledgeGraph,
) -> None:
    """The reason the deterministic gates run first: critics are the expensive
    part, and a hypothesis already rejected must not pay for them."""
    strict = Params(
        selection=SelectionParams(top_k=3),
        ranking=RankingParams(critics_per_hypothesis=3),
        evidence=EvidenceParams(min_independent_groups=99),
    )
    judge = FakeJudge()
    slate = Generator(graph=graph, params=strict, judge=judge).run()

    articulated = sum(1 for h in slate.hypotheses if h.articulation is not None)
    # Articulation happens before verification, so exactly one call each and
    # not one critic call more.
    assert judge.calls == articulated
    assert all(h.critiques == [] for h in slate.hypotheses)


def test_the_report_shows_the_gate_table(graph: KnowledgeGraph) -> None:
    slate = Generator(graph=graph, params=_params(), judge=FakeJudge()).run()
    markdown = to_markdown(slate, mode="full")
    assert "**Verification**" in markdown
    assert "gate 1 structure" in markdown
    assert "VERDICT" in markdown


def test_a_halt_is_stated_in_prose_as_well_as_the_table(
    graph: KnowledgeGraph,
) -> None:
    """A halt is the one thing in the report a reader must not be able to
    mistake for a clean run."""
    strict = Params(
        selection=SelectionParams(top_k=2),
        evidence=EvidenceParams(min_independent_groups=99),
    )
    markdown = to_markdown(Generator(graph=graph, params=strict).run())
    assert "Verification stopped at **independence**" in markdown
    assert "none of them should be read as passed" in markdown
