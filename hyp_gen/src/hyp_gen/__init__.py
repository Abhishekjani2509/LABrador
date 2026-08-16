"""Hypothesis generation from a knowledge graph, for the Track A Co-Scientist.

Stage 2 of the pipeline. It receives one JSON knowledge graph and is blind to
everything about how that graph was built. Its output is a slate of hypotheses
that are functions of (graph, params) -- every claim traceable to a link id, a
finding id, and a verbatim source sentence.
"""

from hyp_gen.candidates import Candidate, enumerate_candidates
from hyp_gen.evidence import EvidencePack, build_pack
from hyp_gen.graph import GraphIndex, KnowledgeGraph
from hyp_gen.llm import BudgetExceeded, Judge, RefusalError
from hyp_gen.params import PROFILES, Params
from hyp_gen.pipeline import Generator
from hyp_gen.report import to_markdown
from hyp_gen.schema import (
    Articulation,
    Ask,
    Claim,
    Comparison,
    Critique,
    GateResult,
    Hypothesis,
    Slate,
    ValidationIssue,
    Verification,
)
from hyp_gen.scoring import LinkSupport, Scores, score_all, score_candidate, score_link
from hyp_gen.select import pareto_front, select
from hyp_gen.verify import GateContext

# `verify` is deliberately not re-exported as a name here: binding the function
# would shadow the `hyp_gen.verify` submodule, and `from hyp_gen import verify`
# would then hand callers a function where they asked for a module.

__all__ = [
    "Articulation",
    "Ask",
    "BudgetExceeded",
    "Candidate",
    "Claim",
    "Comparison",
    "Critique",
    "EvidencePack",
    "GateContext",
    "GateResult",
    "Generator",
    "GraphIndex",
    "Hypothesis",
    "Judge",
    "KnowledgeGraph",
    "LinkSupport",
    "PROFILES",
    "Params",
    "RefusalError",
    "Scores",
    "Slate",
    "ValidationIssue",
    "Verification",
    "build_pack",
    "enumerate_candidates",
    "pareto_front",
    "score_all",
    "score_candidate",
    "score_link",
    "select",
    "to_markdown",
]
