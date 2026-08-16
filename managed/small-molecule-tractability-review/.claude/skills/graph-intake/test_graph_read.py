#!/usr/bin/env python3
"""Tests for graph_read.py. Stdlib only, no dependencies.

    python3 test_graph_read.py

Two of these were written to FAIL against the code as it stood on 2026-08-15 and
are the reason the ask machinery was touched at all:

- `AlreadyAskedTargetless` -- `already_asked()` matched on (verb, target), and
  `new_question` carries `target: null` by design. The first new_question ever
  issued against a graph therefore retired the verb for the life of that graph.
- `PostResolutionGate2` -- the post-resolution contradiction ask was exempted
  from gate 3 and not from gate 2, so the one ask type that has demonstrably
  worked could not fire against the `primary` row it corrects.

Fixtures built here carry `_fixture: true`, and `FixtureGuard` checks that
graph_read.py still refuses them without --allow-fixture.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "graph_read.py"

sys.path.insert(0, str(HERE))
import graph_read  # noqa: E402

# Fixtures owned by other directories. Read-only, and skipped rather than failed
# if this skill is unbundled from them.
DOSSIER = HERE.parent.parent.parent
ASKBACK = DOSSIER / "fixtures" / "upstream_graph_askback.json"
WORKED_ASK = HERE.parent / "ppi-hypothesis" / "fixtures" / "worked_ask.json"


def minimal_graph(rounds, stop_reason="max_papers"):
    """The smallest graph the reader accepts, plus whatever `rounds` we need."""
    return {
        "_fixture": True,
        "_fixture_note": "SYNTHETIC. Built in-process by test_graph_read.py.",
        "schema_version": "1.1",
        "graph_id": "g_test",
        "round": 1,
        "status": "ok",
        "things": [{"id": "t1", "name": "TL1A", "kind": "protein"}],
        "papers": [],
        "findings": [],
        "links": [],
        "gaps": [],
        "rounds": rounds,
        "coverage": {"depth": "deep", "truncated": True, "stop_reason": stop_reason},
    }


def gate(gates, name):
    return next(g for g in gates if g["gate"] == name)


def check(graph, ask):
    """check_ask(), tolerant of the pre-fix 2-tuple return.

    So that running this file against the code as it stood before the fix fails
    on the BEHAVIOUR under test rather than on the changed arity.
    """
    result = graph_read.check_ask(graph, ask)
    if len(result) == 2:
        return result[0], result[1], []
    return result


# Two DISTINCT new_question asks. Distinct in the only sense that matters to a
# routing team: they name different sources and would be answered by different
# searches.
Q1 = ("Does any primary report measure a direct binding constant for a small "
      "molecule against TL1A? PMC10762860 asserts it only as background and "
      "CHEMBL25 holds no such assay.")
Q2 = ("Is there a deposited co-structure of the TL1A ectodomain with any "
      "receptor other than DcR3? 3K51 and 3MI8 are the only ones we find, and "
      "PMC11642585 implies a third.")


class AlreadyAskedTargetless(unittest.TestCase):
    """FAILS BEFORE THE FIX. One new_question retired the verb permanently."""

    def test_second_distinct_new_question_is_not_already_asked(self):
        graph = minimal_graph([
            {"n": 1, "ask": "new_question", "target": None, "depth": "standard",
             "question": Q1, "outcome": "new_evidence"},
        ])
        gates, _, _ = check(
            graph, {"ask": "new_question", "target": None, "question": Q2})
        g = gate(gates, "NOT_ALREADY_ASKED")
        self.assertTrue(
            g["ok"],
            "a second, unrelated new_question was reported as already asked "
            "purely because an earlier one existed: " + g["detail"])

    def test_the_same_new_question_is_still_caught(self):
        """The gate must still do its job -- the fix is not 'always pass'."""
        graph = minimal_graph([
            {"n": 1, "ask": "new_question", "target": None, "question": Q1},
        ])
        gates, _, _ = check(
            graph, {"ask": "new_question", "target": None, "question": Q1})
        self.assertFalse(gate(gates, "NOT_ALREADY_ASKED")["ok"])

    def test_a_rephrased_question_still_counts_as_asked(self):
        """Upstream rewords a question when it services it. Identity is the set
        of source identifiers, not the wording -- a text hash would let this
        through as a new ask."""
        graph = minimal_graph([
            {"n": 1, "ask": "new_question", "target": None, "question": Q1},
        ])
        reworded = ("Has anyone measured a Kd or IC50 for any small molecule on "
                    "TL1A in a primary paper? We have CHEMBL25 (silent) and "
                    "PMC10762860 (background only).")
        self.assertNotEqual(reworded, Q1)
        gates, _, _ = check(
            graph, {"ask": "new_question", "target": None, "question": reworded})
        self.assertFalse(
            gate(gates, "NOT_ALREADY_ASKED")["ok"],
            "a rephrasing of an already-issued question was treated as new")

    def test_a_round_with_no_question_text_is_reported_not_ignored(self):
        """`rounds` is not required to record the question, and the real
        ask-back fixture's round 1 does not. That prior ask cannot be compared
        against, so the gate must SAY so rather than return a silent all-clear."""
        graph = minimal_graph([
            {"n": 1, "ask": "new_question", "target": None, "outcome": "new_evidence"},
        ])
        gates, _, _ = check(
            graph, {"ask": "new_question", "target": None, "question": Q2})
        g = gate(gates, "NOT_ALREADY_ASKED")
        self.assertTrue(g["ok"])
        self.assertIn("no `question` text", g["detail"])
        self.assertIn("[1]", g["detail"])

    def test_targeted_verbs_still_match_on_target(self):
        graph = minimal_graph([
            {"n": 1, "ask": "expand_node", "target": "t1", "depth": "deep"},
        ])
        hits, unmatchable = graph_read.already_asked(graph, "expand_node", "t1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(unmatchable, [])
        hits, _ = graph_read.already_asked(graph, "expand_node", "t9")
        self.assertEqual(hits, [])


class PostResolutionGate2(unittest.TestCase):
    """FAILS BEFORE THE FIX. Gate 2 blocked the correction ask.

    Uses the worked TL1A case: `resolve_link` on L4, whose basis is `primary`,
    carrying a PDB census that contradicts the row.
    """

    @classmethod
    def setUpClass(cls):
        if not (ASKBACK.exists() and WORKED_ASK.exists()):
            raise unittest.SkipTest(f"need {ASKBACK} and {WORKED_ASK}")
        cls.graph = json.loads(ASKBACK.read_text())
        cls.ask = json.loads(WORKED_ASK.read_text())["ask"]

    def test_worked_ask_still_passes_all_five_mechanical_gates(self):
        gates, _, _ = check(self.graph, self.ask)
        self.assertEqual([g["gate"] for g in gates if not g["ok"]], [])
        self.assertEqual(len(gates), 5)

    def test_gate_2_is_exempted_for_the_post_resolution_ask(self):
        gates, unchecked, exempt = check(self.graph, self.ask)
        del gates
        joined_unchecked = " ".join(unchecked)
        joined_exempt = " ".join(exempt)
        self.assertIn("SUPPORT_IS_SECONDARY_ONLY", joined_exempt)
        self.assertIn("WE_TRIED_AND_FAILED", joined_exempt)
        self.assertNotIn(
            "SUPPORT_IS_SECONDARY_ONLY", joined_unchecked,
            "gate 2 is still reported as required for an ask that carries our "
            "own answer; that is what blocks the correction")
        self.assertIn("AFFECTS_THE_DOSSIER", joined_unchecked)

    def test_an_ordinary_ask_is_not_exempted(self):
        """The exemption must not leak. An ask that does not declare itself
        post-resolution still faces both judgment gates."""
        ordinary = dict(self.ask, question=self.ask["question"].replace(
            "THIS ASK IS POST-RESOLUTION AND NOT BLOCKING", "WE WOULD LIKE TO KNOW"))
        gates, unchecked, exempt = check(self.graph, ordinary)
        del gates
        self.assertEqual(exempt, [])
        self.assertIn("SUPPORT_IS_SECONDARY_ONLY", " ".join(unchecked))

    def test_ask_context_separates_L4_from_L2(self):
        """Both are `basis: primary` and both were `mechanical_gates_clear:
        false`. L2 is the ask that must never fire; L4 is the one that worked.
        The output has to tell them apart."""
        ctx = graph_read.ask_context(self.graph)
        rows = {r["link"]: r for r in ctx["links"]}
        self.assertFalse(rows["L4"]["mechanical_gates_clear"])
        self.assertTrue(rows["L4"]["clear_if_post_resolution_contradiction"])
        # L2 is primary too, so it is also correctable-in-principle; what keeps
        # it out is that we have not contradicted it. L7 is the useful contrast:
        # already asked in round 3, so nothing about it is clear.
        self.assertFalse(rows["L7"]["mechanical_gates_clear"])
        self.assertFalse(rows["L7"]["clear_if_post_resolution_contradiction"])
        # L1/L3 are the ordinary secondary-only asks and are unaffected.
        self.assertTrue(rows["L1"]["mechanical_gates_clear"])
        self.assertTrue(rows["L3"]["mechanical_gates_clear"])
        self.assertFalse(rows["L1"]["clear_if_post_resolution_contradiction"])


class FixtureGuard(unittest.TestCase):
    """`_fixture: true` must keep being refused without --allow-fixture."""

    def run_cli(self, graph, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(graph, fh)
            path = fh.name
        try:
            return subprocess.run([sys.executable, str(SCRIPT), path, *args],
                                  capture_output=True, text=True)
        finally:
            Path(path).unlink()

    def test_fixture_is_refused_without_the_flag(self):
        r = self.run_cli(minimal_graph([]))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("_fixture: true", r.stderr)

    def test_fixture_is_accepted_with_the_flag(self):
        r = self.run_cli(minimal_graph([]), "--allow-fixture")
        self.assertEqual(r.returncode, 0, r.stderr)
        json.loads(r.stdout)

    def test_guard_fires_before_check_ask(self):
        """--check-ask must not be a way around the guard."""
        ask = json.dumps({"ask": "new_question", "target": None, "question": Q2})
        r = self.run_cli(minimal_graph([]), "--check-ask", ask)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("_fixture: true", r.stderr)

    def test_a_real_graph_carrying_no_fixture_key_passes(self):
        graph = minimal_graph([])
        del graph["_fixture"]
        r = self.run_cli(graph)
        self.assertEqual(r.returncode, 0, r.stderr)


class CliShape(unittest.TestCase):
    """The CLI contract the ppi-hypothesis skill calls."""

    @classmethod
    def setUpClass(cls):
        if not (ASKBACK.exists() and WORKED_ASK.exists()):
            raise unittest.SkipTest("need the ask-back fixtures")

    def check_ask_cli(self, ask):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(ASKBACK), "--allow-fixture",
             "--check-ask", json.dumps(ask)],
            capture_output=True, text=True)

    def test_worked_ask_exits_zero(self):
        ask = json.loads(WORKED_ASK.read_text())["ask"]
        r = self.check_ask_cli(ask)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(all(g["ok"] for g in out["gates"]))
        self.assertTrue(out.get("exempt_for_this_ask"))

    def test_unrelated_new_question_exits_zero(self):
        """The regression, end to end: round 1 of this fixture is a
        new_question, and it used to fail every later one."""
        r = self.check_ask_cli({"ask": "new_question", "target": None,
                                "depth": "deep", "question": Q2})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_fifth_verb_is_still_refused(self):
        r = self.check_ask_cli({"ask": "ask_nicely", "target": None,
                                "depth": "deep", "question": Q2})
        self.assertNotEqual(r.returncode, 0)


class BuildStillWorks(unittest.TestCase):
    """The non-ask half of the file, unchanged by this work but exercised so a
    regression in it is not silent."""

    def test_build_on_the_askback_fixture(self):
        if not ASKBACK.exists():
            self.skipTest("fixture absent")
        out = graph_read.build(json.loads(ASKBACK.read_text()))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["integrity"]["dangling_ids"], [])
        self.assertEqual(out["coverage"]["literature_exhausted"], False)

    def test_absent_list_is_refused(self):
        graph = minimal_graph([])
        del graph["links"]
        with self.assertRaises(graph_read.GraphShapeError):
            graph_read.build(graph)

    def test_null_list_is_refused(self):
        graph = minimal_graph([])
        graph["gaps"] = None
        with self.assertRaises(graph_read.GraphShapeError):
            graph_read.build(graph)


if __name__ == "__main__":
    unittest.main(verbosity=2)
