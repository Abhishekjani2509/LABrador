"""Output types. These are the contract with whatever consumes the slate.

Every claim carries its own citations, so downstream stages (dataset support,
ROI, simulated preclinical) can attach to a single claim rather than to a whole
hypothesis. That granularity is the point: "the target is druggable" and "the
target matters in this disease" fail for different reasons and cost different
amounts to check.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["supported", "partly_supported", "unsupported", "contradicted"]


class Claim(BaseModel):
    """One atomic, separately checkable assertion inside a hypothesis."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="A single assertion, stated so it can be true or false on its own.")
    cites: list[str] = Field(
        default_factory=list,
        description="Ids from the evidence pack only (link, finding, paper, thing, or gap ids).",
    )
    inferred: bool = Field(
        default=False,
        description="True when the graph does not state this and it is a step of reasoning.",
    )


class Articulation(BaseModel):
    """What the model is asked to produce from one structural candidate."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(description="The hypothesis in one testable sentence.")
    mechanism: str = Field(description="The proposed causal chain, in graph terms.")
    claims: list[Claim] = Field(description="The hypothesis decomposed into checkable pieces.")
    novel_because: str = Field(description="What the graph does NOT already state.")
    predictions: list[str] = Field(
        default_factory=list, description="Observations that should hold if this is true."
    )
    falsifier: str = Field(description="The single observation that would kill this.")
    decisive_experiment: str = Field(description="The cheapest experiment that discriminates.")
    assumptions: list[str] = Field(
        default_factory=list, description="What must be true but is not in the graph."
    )


class CritiqueFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_index: int
    verdict: Verdict
    reason: str
    cites: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    """The adversarial pass. Its job is to break the hypothesis, not polish it."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    strongest_objection: str
    unsupported_leaps: list[str] = Field(default_factory=list)
    per_claim: list[CritiqueFinding] = Field(default_factory=list)
    alternative_explanation: str = Field(
        default="", description="A duller reading of the same evidence, if one exists."
    )
    lens: str = Field(
        default="",
        description="Which angle this critic was told to attack from. Set by the harness, not the model.",
    )


class Comparison(BaseModel):
    """One pairwise debate in the tournament.

    Two hypotheses, one graph, one winner. Pairwise judgements are far more
    reliable than absolute scores -- a model asked "is this an 8 or a 9" is
    guessing, a model asked "which of these two is better supported" is not.
    """

    model_config = ConfigDict(extra="forbid")

    winner: Literal["A", "B"]
    margin: Literal["clear", "narrow"]
    reason: str
    decisive_evidence: list[str] = Field(
        default_factory=list, description="Ids that decided it. Pack ids only."
    )


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    severity: Literal["error", "warning"] = "warning"


GateStatus = Literal["pass", "warn", "fail", "skip"]
VerificationVerdict = Literal["verified", "qualified", "unverified", "rejected"]

_SUMMARY_WIDTH = 68


def _clip(text: str) -> str:
    return text if len(text) <= _SUMMARY_WIDTH else f"{text[: _SUMMARY_WIDTH - 1]}…"


class GateResult(BaseModel):
    """The outcome of one verification gate.

    ``summary`` is the one line that appears in the gate table, so it must say
    what happened rather than what was checked: "L4,L2 share first author — 1
    group" is a result, "checked independence" is not.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    status: GateStatus
    summary: str = ""
    issues: list[ValidationIssue] = Field(default_factory=list)
    halting: bool = Field(
        default=False,
        description="Whether a failure here stops the process. Set from params, not by the gate.",
    )


class Verification(BaseModel):
    """The full staged verification of one hypothesis.

    Distinct from ``Hypothesis.verdict``, which is only the adversarial
    critics' consensus. This is the whole process: what ran, what it found, and
    where it stopped.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: VerificationVerdict
    gates: list[GateResult] = Field(default_factory=list)
    halted_at: str | None = Field(
        default=None, description="Name of the gate that stopped the process, if one did."
    )

    def gate(self, name: str) -> GateResult | None:
        return next((g for g in self.gates if g.name == name), None)

    @property
    def failures(self) -> list[GateResult]:
        return [g for g in self.gates if g.status == "fail"]

    def table(self) -> str:
        """The gate table, fixed width, worst news legible at a glance.

        Summaries are clipped so the table stays scannable in a terminal and in
        a markdown code block. Nothing is lost by it: the full text of every
        finding is on ``GateResult.issues`` and is rendered in full by the
        report's validation section.
        """
        rows = [
            f"gate {i} {g.name:<16}{g.status.upper():<7}{_clip(g.summary)}".rstrip()
            for i, g in enumerate(self.gates, start=1)
        ]
        tail = f" (halted: {self.halted_at})" if self.halted_at else ""
        width = max((len(r) for r in rows), default=31)
        return "\n".join(
            [*rows, "─" * max(width, 31), f"VERDICT  {self.verdict}{tail}"]
        )


class Ask(BaseModel):
    """A Stage 1 request. This is the loop closing."""

    model_config = ConfigDict(extra="forbid")

    graph_id: str
    ask: Literal["expand_node", "resolve_link", "test_gap", "new_question"]
    target: str
    depth: Literal["quick", "standard", "deep", "exhaustive"] = "standard"
    reason: str = ""
    for_hypothesis: str | None = None


class Hypothesis(BaseModel):
    """One fully assembled, inspectable hypothesis."""

    model_config = ConfigDict(extra="allow")

    id: str
    motif: str
    subject: str
    object: str
    subject_name: str
    object_name: str
    hops: int
    tags: list[str] = Field(default_factory=list)
    path: list[dict] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    rank_score: float = 0.0
    evidence: dict = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    articulation: Articulation | None = None
    critiques: list[Critique] = Field(default_factory=list)
    verdict: Verdict | None = Field(
        default=None, description="Consensus across critics, per refute_threshold."
    )
    verification: Verification | None = Field(
        default=None, description="The staged gate process. None means it never ran."
    )
    elo: float | None = Field(
        default=None, description="Set only when the tournament ran."
    )
    evolved_from: str | None = None
    evolution_operator: str | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    asks: list[Ask] = Field(default_factory=list)
    provenance: str = ""

    @property
    def blocked(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def critique(self) -> Critique | None:
        """The single harshest critique, for callers that want one."""
        order = {"contradicted": 0, "unsupported": 1, "partly_supported": 2, "supported": 3}
        return min(self.critiques, key=lambda c: order.get(c.verdict, 3), default=None)


class Slate(BaseModel):
    """Everything one run produced, plus what it ran on."""

    model_config = ConfigDict(extra="allow")

    graph_id: str
    round: int
    question: str
    generated_at: str | None = None
    params: dict = Field(default_factory=dict)
    coverage: dict = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    asks: list[Ask] = Field(default_factory=list)
