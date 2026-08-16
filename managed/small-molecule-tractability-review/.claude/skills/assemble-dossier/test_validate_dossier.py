#!/usr/bin/env python3
"""Tests for validate_dossier.py.

Two halves.

1. Every rule gets at least one deliberately broken dossier that it must catch.
   A validator that passes everything is worthless, so the assertions are on the
   rule NAME firing, not merely on "some violation happened".

2. The fixtures are run as data. `rheumatoid_arthritis.json` is the strongest
   test set available for this agent — eight targets in one disease, four drugged
   with small molecules and four with biologics only, so nothing varies except
   the modality that won.

Pure stdlib. Run with:

    python3 -m unittest discover -s . -p 'test_*.py' -v
    python3 test_validate_dossier.py
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from validate_dossier import Violation, validate_dossier

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples"
FIXTURES = HERE.parents[2] / "fixtures"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


JAK1 = _load(EXAMPLES / "jak1_P23458.json")
TNF = _load(EXAMPLES / "tnf_P01375.json")


def rules(violations: list[Violation]) -> set[str]:
    return {v.rule for v in violations}


def broken(base: dict) -> dict:
    return copy.deepcopy(base)


def with_druggability_range(base: dict) -> dict:
    """A dossier that actually reports a spread.

    SYNTHETIC, and still needed. JAK1 now carries a REAL range from the
    2026-08-15 run (volume 305.9-913.8 A^3, druggability 0.020-0.437, all four
    measurements by `ligand_site_jaccard`) — see
    `test_the_real_jak1_pool_is_accepted`, which asserts against that data
    directly. This helper stays for the shapes the real runs do not produce:
    a `site_signature_overlap` basis, a two-entry ensemble with a named
    non-existent partner, and the deliberately-broken variants below. Its
    numbers are invented and are never presented as data.
    """
    d = broken(base)
    d["_example"] = "SYNTHETIC — invented numbers, test harness only"
    d["tractability"]["pocket_volume_a3"] = {
        "min": 310.0,
        "max": 545.0,
        "spread_pct": 43.1,
        "clustering_d": [1.6, 2.4],
        # Rule 4a: the primary number is the D=1.6 figure specifically, carried
        # separately from the spread that pools both clustering values.
        "primary_d1_6_a3": 310.0,
        "site_pocket_selected_by": ["ligand_site_jaccard", "site_signature_overlap"],
    }
    d["tractability"]["pocket_druggability"] = {
        "min": 0.402,
        "max": 0.735,
        "fold_range": 1.8,
        "site_pocket_selected_by": ["ligand_site_jaccard", "site_signature_overlap"],
        # Rule 4.0: only legal value, and the rate travels with the number.
        "load_bearing": False,
        "_provenance": "shipped fpocket 3-descriptor logistic regression",
        "_false_negative_rate": (
            "15 of 37 ligand-anchored holo pockets (41%) score below 0.1; "
            "target-level AUC 0.720, 95% CI 0.44-0.94"
        ),
    }
    d["tractability"]["method"]["ensemble_pdb_ids"] = ["3EYG", "4E4N"]
    d["tractability"]["ensemble_consensus_fraction"]["n_structures"] = 2
    return d


# ---------------------------------------------------------------------------
# The positive controls
# ---------------------------------------------------------------------------


class TestValidExamples(unittest.TestCase):
    def test_jak1_passes(self):
        self.assertEqual(validate_dossier(JAK1), [])

    def test_tnf_passes(self):
        self.assertEqual(validate_dossier(TNF), [])

    def test_synthetic_range_passes(self):
        """A properly reported spread must not be flagged."""
        self.assertEqual(validate_dossier(with_druggability_range(JAK1)), [])

    def test_validator_is_not_vacuous(self):
        """An empty object must fail loudly, or nothing above means anything."""
        self.assertGreater(len(validate_dossier({})), 5)


# ---------------------------------------------------------------------------
# R1 — no number without provenance
# ---------------------------------------------------------------------------


class TestNumberProvenance(unittest.TestCase):
    def test_unsourced_identity_number(self):
        d = broken(JAK1)
        del d["target"]["sources"]
        v = validate_dossier(d)
        self.assertIn("NUMBER_WITHOUT_PROVENANCE", rules(v))
        self.assertTrue(any(x.path == "target.sequence_length" for x in v))

    def test_unsourced_actives_count(self):
        d = broken(JAK1)
        d["target_precedent"]["sources"] = []
        d["target_precedent"]["chembl_target_id"] = None
        d["target_precedent"]["best_potency_assay"] = None
        v = validate_dossier(d)
        paths = {x.path for x in v if x.rule == "NUMBER_WITHOUT_PROVENANCE"}
        self.assertIn("target_precedent.distinct_actives", paths)

    def test_provenance_is_inherited_downward_not_sideways(self):
        """A source on one block does not cover a number in another."""
        d = broken(JAK1)
        d["target_precedent"]["sources"] = []
        d["target_precedent"]["chembl_target_id"] = None
        d["target_precedent"]["best_potency_assay"] = None
        paths = {
            x.path for x in validate_dossier(d) if x.rule == "NUMBER_WITHOUT_PROVENANCE"
        }
        # structure.* still has its own sources and must stay clean.
        self.assertNotIn("structure.holo_count", paths)


# ---------------------------------------------------------------------------
# R2 — the two axes are never averaged
# ---------------------------------------------------------------------------


class TestAxesNeverAveraged(unittest.TestCase):
    def test_overall_score_field(self):
        d = broken(JAK1)
        d["overall_score"] = 0.82
        self.assertIn("AXES_AVERAGED", rules(validate_dossier(d)))

    def test_any_key_naming_an_aggregate(self):
        d = broken(JAK1)
        d["tractability"]["overall_confidence"] = 0.7
        self.assertIn("AXES_AVERAGED", rules(validate_dossier(d)))

    def test_field_combining_precedent_and_tractability(self):
        d = broken(JAK1)
        d["tractability"]["precedent_weighted_druggability"] = 0.61
        v = [x for x in validate_dossier(d) if x.rule == "AXES_AVERAGED"]
        self.assertTrue(v)
        self.assertIn("precedent", v[0].message)

    def test_composite_under_any_name(self):
        d = broken(JAK1)
        d["target_precedent"]["composite_score"] = 3
        self.assertIn("AXES_AVERAGED", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# R3 — modality separation
# ---------------------------------------------------------------------------


class TestModalitySeparation(unittest.TestCase):
    def test_biologic_in_the_small_molecule_block(self):
        d = broken(TNF)
        d["target_precedent"]["approved_small_molecules"] = [
            {"name": "adalimumab", "year": 2002, "source": "chembl_v.drugs_by_accession"}
        ]
        v = [x for x in validate_dossier(d) if x.rule == "MODALITY_LEAK"]
        self.assertTrue(v)
        self.assertTrue(any("biologic_precedent" in x.message for x in v))
        self.assertTrue(any("USAN stem" in x.message for x in v))

    def test_usan_stem_alone_is_caught(self):
        """Even when the biologic block was never filled in."""
        d = broken(JAK1)
        d["target_precedent"]["approved_small_molecules"].append(
            {"name": "secukinumab", "year": 2015, "source": "chembl_v.drugs_by_accession"}
        )
        self.assertIn("MODALITY_LEAK", rules(validate_dossier(d)))

    def test_wrong_modality_tag(self):
        d = broken(JAK1)
        d["target_precedent"]["approved_small_molecules"][0]["modality"] = "antibody"
        self.assertIn("MODALITY_LEAK", rules(validate_dossier(d)))

    def test_tractability_claimed_on_biologic_precedent(self):
        """Zero approved small molecules, verdict tractable on precedent grounds."""
        d = broken(TNF)
        d["verdict_basis"] = "retrieved_precedent"
        d["target_precedent"]["clinical_stage_small_molecules"] = []
        d["target_precedent"]["best_potency_characterised"] = False
        v = [x for x in validate_dossier(d) if x.rule == "MODALITY_LEAK"]
        self.assertTrue(any(x.path == "verdict_basis" for x in v))

    def test_biologics_plus_tractable_verdict_needs_a_stated_conflict(self):
        d = broken(TNF)
        d["axis_conflict"] = None
        v = validate_dossier(d)
        self.assertIn("MODALITY_LEAK", rules(v))
        self.assertIn("AXIS_CONFLICT_UNDECLARED", rules(v))


# ---------------------------------------------------------------------------
# R4 — insufficient_evidence is reachable and used
# ---------------------------------------------------------------------------


class TestInsufficientEvidence(unittest.TestCase):
    def test_thin_evidence_must_decline(self):
        """The IL-11 shape: 15 compounds, one assay, no holo, no drugs."""
        d = broken(JAK1)
        d["target_precedent"]["distinct_actives"] = 15
        d["target_precedent"]["approved_small_molecules"] = []
        d["target_precedent"]["approved_small_molecules_count"] = 0
        d["structure"]["holo_count"] = 0
        v = [x for x in validate_dossier(d) if x.rule == "INSUFFICIENT_EVIDENCE_AVOIDED"]
        self.assertTrue(v)
        self.assertIn("insufficient_evidence", v[0].message)

    def test_declining_is_accepted(self):
        d = broken(JAK1)
        d["target_precedent"]["distinct_actives"] = 15
        d["target_precedent"]["approved_small_molecules"] = []
        d["target_precedent"]["approved_small_molecules_count"] = 0
        d["structure"]["holo_count"] = 0
        d["verdict"] = "insufficient_evidence"
        d["verdict_basis"] = "none"
        self.assertNotIn(
            "INSUFFICIENT_EVIDENCE_AVOIDED", rules(validate_dossier(d))
        )

    def test_null_holo_count_does_not_trigger(self):
        """A failed structure query is not zero holo structures."""
        d = broken(JAK1)
        d["target_precedent"]["distinct_actives"] = 15
        d["target_precedent"]["approved_small_molecules"] = []
        d["structure"]["holo_count"] = None
        d["not_found"].append(
            {"field": "structure.holo_count", "reason": "PDB query failed"}
        )
        self.assertNotIn(
            "INSUFFICIENT_EVIDENCE_AVOIDED", rules(validate_dossier(d))
        )

    def test_declining_requires_naming_the_resolver(self):
        d = broken(JAK1)
        d["verdict"] = "insufficient_evidence"
        d["verdict_basis"] = "none"
        d["next_experiment"]["resolves"] = ""
        self.assertIn("INSUFFICIENT_EVIDENCE_AVOIDED", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# R5 — druggability is a range, never a point
# ---------------------------------------------------------------------------


class TestDruggabilityRange(unittest.TestCase):
    def test_scalar_druggability(self):
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"] = 0.735
        v = [x for x in validate_dossier(d) if x.rule == "DRUGGABILITY_POINT_ESTIMATE"]
        self.assertTrue(v)

    def test_one_sided_range_is_a_point_estimate(self):
        """The shape the EARLIER JAK1 and TNF runs delivered.

        Both relayed a maximum and no minimum, and both dossiers reported no
        druggability at all rather than publish one. The 2026-08-15 re-run gave
        JAK1 a real two-sided range, so the one-sided shape now has to be
        constructed here — but it is the failure mode that produced the rule.
        """
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"]["min"] = None
        d["tractability"]["pocket_druggability"]["max"] = 0.735
        v = [x for x in validate_dossier(d) if x.rule == "DRUGGABILITY_POINT_ESTIMATE"]
        self.assertTrue(any("one-sided" in x.message for x in v))

    def test_loose_druggability_figure_elsewhere(self):
        d = broken(JAK1)
        d["tractability"]["max_druggability"] = 0.735
        self.assertIn("DRUGGABILITY_POINT_ESTIMATE", rules(validate_dossier(d)))

    def test_range_from_a_single_clustering_value(self):
        d = with_druggability_range(JAK1)
        d["tractability"]["method"]["clustering_d_swept"] = [1.6]
        v = [x for x in validate_dossier(d) if x.rule == "DRUGGABILITY_POINT_ESTIMATE"]
        self.assertTrue(any("clustering" in x.message for x in v))

    def test_range_with_no_ensemble_named(self):
        d = with_druggability_range(JAK1)
        d["tractability"]["method"]["ensemble_pdb_ids"] = []
        d["tractability"]["ensemble_consensus_fraction"]["n_structures"] = None
        v = [x for x in validate_dossier(d) if x.rule == "DRUGGABILITY_POINT_ESTIMATE"]
        self.assertTrue(any("ensemble" in x.message for x in v))

    def test_druggability_without_volume(self):
        d = with_druggability_range(JAK1)
        d["tractability"]["pocket_volume_a3"] = {
            "min": None,
            "max": None,
            "spread_pct": None,
        }
        d["not_found"] = [
            e
            for e in d["not_found"]
            if "pocket_volume_a3" not in str(e.get("field", ""))
        ]
        v = [x for x in validate_dossier(d) if x.rule == "DRUGGABILITY_POINT_ESTIMATE"]
        self.assertTrue(any("volume" in x.message for x in v))

    def test_scalar_volume(self):
        d = broken(JAK1)
        d["tractability"]["pocket_volume_a3"] = 412.0
        self.assertIn("DRUGGABILITY_POINT_ESTIMATE", rules(validate_dossier(d)))


class TestFractionCarriesN(unittest.TestCase):
    def test_fraction_without_n(self):
        d = broken(JAK1)
        cons = d["tractability"]["ensemble_consensus_fraction"]
        # pocket_scan emits no consensus fraction, so the real dossier leaves
        # this null. Supply one, or there is no fraction to demand an N for.
        cons["fraction_with_strong_pocket"] = 0.5
        cons["n_measurements"] = None
        cons["n_structures"] = None
        self.assertIn("FRACTION_WITHOUT_N", rules(validate_dossier(d)))

    def test_n_structures_disagrees_with_the_named_ensemble(self):
        """And this fires with NO fraction reported, which is the normal case.

        `pocket_scan` returns the denominators and no consensus fraction at
        all, so gating this check behind the fraction retired it on every real
        dossier. `n_structures: 5` against two named entries is a
        self-contradiction whether or not a fraction was computed from it.
        """
        d = with_druggability_range(JAK1)
        d["tractability"]["ensemble_consensus_fraction"]["n_structures"] = 5
        self.assertIsNone(
            d["tractability"]["ensemble_consensus_fraction"][
                "fraction_with_strong_pocket"
            ]
        )
        v = [x for x in validate_dossier(d) if x.rule == "FRACTION_WITHOUT_N"]
        self.assertTrue(any("named in" in x.message for x in v))


# ---------------------------------------------------------------------------
# R6 — a pooled spread must record how the site was chosen
# ---------------------------------------------------------------------------


class TestSameSiteBasis(unittest.TestCase):
    def test_spread_with_no_basis(self):
        d = with_druggability_range(JAK1)
        del d["tractability"]["pocket_druggability"]["site_pocket_selected_by"]
        del d["tractability"]["pocket_volume_a3"]["site_pocket_selected_by"]
        v = [x for x in validate_dossier(d) if x.rule == "SAME_SITE_BASIS_MISSING"]
        self.assertEqual(len(v), 2)

    def test_max_druggability_no_ligand_site_must_not_be_pooled(self):
        """The apo default: 'the most druggable pocket anywhere in the chain'."""
        d = with_druggability_range(JAK1)
        d["tractability"]["pocket_druggability"]["site_pocket_selected_by"] = [
            "max_druggability_no_ligand_site"
        ]
        v = [x for x in validate_dossier(d) if x.rule == "SAME_SITE_BASIS_INVALID"]
        self.assertTrue(v)
        self.assertIn("must not be pooled", v[0].message)

    def test_homooligomer_signature_must_not_be_pooled(self):
        """A homotrimer triplicates residue numbers; the match is unresolvable."""
        d = with_druggability_range(TNF)
        d["tractability"]["pocket_druggability"]["site_pocket_selected_by"] = [
            "ligand_site_jaccard",
            "site_signature_unreliable_homooligomer",
        ]
        v = [x for x in validate_dossier(d) if x.rule == "SAME_SITE_BASIS_INVALID"]
        self.assertTrue(v)

    def test_the_real_tnf_pool_is_rejected(self):
        """The measured refusal, as data rather than as a hypothetical.

        These are the actual numbers from the 2026-08-15 pocket_scan run on
        2AZ5 + 1TNF + 1A8M + 2E7A + 2ZJC + 5TSW: twelve measurements, of which
        ten were selected by `site_signature_unreliable_homooligomer`. The
        dossier leaves them out. This asserts the gate would have caught them
        had it not — and note the fold_range, 651.0, which is the withdrawn
        650-fold spread regenerating from the same defect.
        """
        d = broken(TNF)
        d["tractability"]["method"]["ensemble_pdb_ids"] = [
            "2AZ5", "1TNF", "1A8M", "2E7A", "2ZJC", "5TSW",
        ]
        d["tractability"]["pocket_volume_a3"].update(
            {"min": 126.933, "max": 809.541, "spread_pct": 84.3}
        )
        d["tractability"]["pocket_druggability"].update(
            {"min": 0.001, "max": 0.651, "fold_range": 651.0}
        )
        v = [x for x in validate_dossier(d) if x.rule == "SAME_SITE_BASIS_INVALID"]
        self.assertTrue(v, "the homo-oligomer pool was accepted")
        self.assertTrue(
            any("pocket_volume_a3" in x.path for x in v)
            and any("pocket_druggability" in x.path for x in v),
            f"both blocks must be rejected, got {[x.path for x in v]}",
        )

    def test_the_real_jak1_pool_is_accepted(self):
        """The other side of the same call, also as measured data.

        All 4 of 4 JAK1 measurements came back `ligand_site_jaccard`, so the
        spread the dossier reports is a spread over one site and nothing here
        may object to it.
        """
        v = rules(validate_dossier(JAK1))
        self.assertNotIn("SAME_SITE_BASIS_INVALID", v)
        self.assertNotIn("SAME_SITE_BASIS_MISSING", v)
        self.assertNotIn("DRUGGABILITY_POINT_ESTIMATE", v)

    def test_off_site_density_geometry_is_rejected(self):
        """Quoting `site_from_density` as the ligand site — the retracted error.

        29.57 A is the real distance the 2026-08-15 TNF run measured, and the
        app raised its own `off_site_warning` on it. The dossier keeps the
        geometry null; this asserts the gate catches it if a later run does not.
        """
        d = broken(TNF)
        d["tractability"]["mdpocket_site_definition_used"] = "site_from_density"
        d["tractability"]["pocket_volume_a3"].update({"min": 141.0, "max": 198.8})
        v = [x for x in validate_dossier(d) if x.rule == "SITE_INCONSISTENT"]
        self.assertTrue(any("different pocket" in x.message for x in v), v)

    def test_on_site_density_geometry_is_fine(self):
        """JAK1's two site definitions agree at 1.86 A, well inside the threshold."""
        d = broken(JAK1)
        d["tractability"]["mdpocket_site_definition_used"] = "site_from_density"
        v = [x for x in validate_dossier(d) if x.rule == "SITE_INCONSISTENT"]
        self.assertFalse(v, f"1.86 A is not off-site: {v}")

    def test_interface_class_asserted_without_measuring_it(self):
        """The TNF temptation: the mechanism is known, so name it anyway.

        `destabiliser_candidate` is true of TNF-alpha in the literature. The
        dossier still says `no_partner_structure`, because rule 2b requires the
        classification be measured and no partner complex was analysed.
        """
        d = broken(TNF)
        d["tractability"]["pocket_vs_interface"]["classification"] = (
            "destabiliser_candidate"
        )
        v = [x for x in validate_dossier(d) if x.rule == "SITE_INCONSISTENT"]
        self.assertTrue(any("partner_pdb_id" in x.path for x in v), v)
        self.assertTrue(any("pocket_interface_overlap" in x.path for x in v), v)

    def test_measured_interface_class_is_accepted(self):
        d = broken(TNF)
        d["tractability"]["pocket_vs_interface"].update(
            {
                "classification": "destabiliser_candidate",
                "partner_pdb_id": "1TNR",
                "pocket_interface_overlap": 0.0,
                "interface_residues": ["A:57", "A:143"],
            }
        )
        v = [x for x in validate_dossier(d) if x.rule == "SITE_INCONSISTENT"]
        self.assertFalse(v, f"a measured classification was rejected: {v}")

    def test_unknown_basis_string(self):
        d = with_druggability_range(JAK1)
        d["tractability"]["pocket_druggability"]["site_pocket_selected_by"] = ["eyeball"]
        self.assertIn("SAME_SITE_BASIS_MISSING", rules(validate_dossier(d)))

    def test_single_structure_single_d_may_use_the_weak_basis(self):
        """Nothing is pooled, so nothing is being falsely compared."""
        d = with_druggability_range(JAK1)
        d["tractability"]["method"]["ensemble_pdb_ids"] = ["3EYG"]
        d["tractability"]["method"]["clustering_d_swept"] = [1.6]
        d["tractability"]["ensemble_consensus_fraction"]["n_structures"] = 1
        for block in ("pocket_druggability", "pocket_volume_a3"):
            d["tractability"][block]["site_pocket_selected_by"] = [
                "max_druggability_no_ligand_site"
            ]
        self.assertNotIn("SAME_SITE_BASIS_INVALID", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# R7 — cryptic means what the field says it means
# ---------------------------------------------------------------------------


class TestCrypticDefinition(unittest.TestCase):
    def test_site_present_in_apo_is_occluded_not_cryptic(self):
        """The TNF-alpha error a reviewer finds immediately."""
        d = broken(TNF)
        d["tractability"]["cryptic_evidence"]["is_cryptic"] = True
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(any("OCCLUDED" in x.message for x in v))

    def test_cryptic_needs_all_or_nearly_all_apo_structures(self):
        d = broken(TNF)
        d["tractability"]["cryptic_evidence"].update(
            {
                "is_cryptic": True,
                "site_present_in_apo_ensemble": False,
                "n_apo_examined": 5,
                "n_apo_site_absent": 2,
            }
        )
        d["tractability"]["cryptic_pocket_risk"] = "high"
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(any("nearly all" in x.message for x in v))

    def test_cryptic_from_a_single_apo_structure(self):
        d = broken(TNF)
        d["tractability"]["cryptic_evidence"].update(
            {
                "is_cryptic": True,
                "site_present_in_apo_ensemble": False,
                "n_apo_examined": 0,
                "n_apo_site_absent": 0,
            }
        )
        d["tractability"]["cryptic_pocket_risk"] = "high"
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(any("apo ensemble" in x.message for x in v))

    def test_cryptic_risk_flagged_from_tier_alone(self):
        d = broken(JAK1)
        d["structure"]["tier"] = "apo_experimental"
        d["tractability"]["cryptic_pocket_risk"] = "high"
        del d["tractability"]["cryptic_evidence"]
        d["tractability"]["cryptic_mechanism"] = "undetermined"
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(any("carries no information" in x.message for x in v))

    def test_mechanism_asserted_with_no_evidence_block(self):
        d = broken(JAK1)
        d["tractability"]["cryptic_mechanism"] = "loop_or_backbone_motion"
        del d["tractability"]["cryptic_evidence"]
        self.assertIn("CRYPTIC_MISCLAIM", rules(validate_dossier(d)))

    def test_occlusion_with_a_nanomolar_prognosis(self):
        d = broken(TNF)
        d["tractability"]["cryptic_potency_prior"]["expected_ceiling"] = "nanomolar"
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(any("low-micromolar" in x.message for x in v))

    def test_loop_motion_with_a_micromolar_prognosis(self):
        d = broken(TNF)
        d["tractability"]["cryptic_mechanism"] = "loop_or_backbone_motion"
        d["tractability"]["cryptic_potency_prior"]["expected_ceiling"] = (
            "micromolar_at_best"
        )
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(any("25 of 27" in x.message for x in v))

    def test_cryptic_call_with_no_basis(self):
        d = broken(JAK1)
        d["tractability"]["cryptic_evidence"]["basis"] = ""
        self.assertIn("CRYPTIC_MISCLAIM", rules(validate_dossier(d)))

    # -- the template-growth regression -------------------------------------
    #
    # The four tests below exist because the output template grew to ALWAYS ship
    # a `cryptic_evidence` block. Every guard in this rule that asked "is the
    # block absent?" became unreachable the moment that happened, and the two
    # dossiers that guard existed to reject started passing. The two tests above
    # that `del` the block still pass, and that is the trap: they kept the dead
    # guard looking alive while no dossier produced from the template could ever
    # reach it.

    def _empty_census(self) -> dict:
        """`cryptic_evidence` exactly as the CLAUDE.md template ships it."""
        return {
            "_note": (
                "The apo census the cryptic call rests on. Vajda 2018: cryptic "
                "only if the site is absent in all, or nearly all, unbound "
                "structures."
            ),
            "is_cryptic": None,
            "n_apo_examined": None,
            "n_apo_site_absent": None,
            "site_present_in_apo_ensemble": None,
            "basis": None,
            "definition": None,
            "source": None,
        }

    def test_mechanism_asserted_over_an_all_null_census(self):
        """A mechanism asserted with the census block shipped empty.

        This is the dossier the rule exists to stop: `subunit_occlusion` — a
        mechanism carrying a micromolar-at-best prognosis — asserted with every
        field of the census left null. Under the key-absence guard it returned
        ZERO `CRYPTIC_MISCLAIM` violations, because the block was present.
        """
        d = broken(TNF)
        d["tractability"]["cryptic_mechanism"] = "subunit_occlusion"
        d["tractability"]["cryptic_evidence"] = self._empty_census()
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(
            any("no cryptic census" in x.message for x in v),
            f"a mechanism asserted over an all-null census went uncaught: {v}",
        )

    def test_cryptic_risk_from_tier_alone_with_the_block_shipped_empty(self):
        """Second instance of the same dead guard, in the same rule.

        `cryptic_pocket_risk: high` on an apo tier with no displacement fires on
        every apo target equally and carries no information. The old guard
        excused it whenever a `cryptic_evidence` KEY existed — so shipping the
        template's empty block bought a free pass on exactly the claim rule 5
        forbids.
        """
        d = broken(JAK1)
        d["structure"]["tier"] = "apo_experimental"
        d["tractability"]["cryptic_pocket_risk"] = "high"
        d["tractability"]["cryptic_mechanism"] = "undetermined"
        d["tractability"]["cryptic_evidence"] = self._empty_census()
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(
            any("carries no information" in x.message for x in v),
            f"'high' from tier alone went uncaught behind an empty census: {v}",
        )

    def test_a_partial_census_still_answers_the_tier_question(self):
        """The boundary the tier check must NOT overshoot.

        A census that examined ten apo structures is a measurement even if the
        `is_cryptic` call was withheld, so `high` is no longer being read off
        the tier. Testing `is_cryptic` here instead of "does the block carry
        anything" would have made this a false positive.
        """
        d = broken(JAK1)
        d["structure"]["tier"] = "apo_experimental"
        d["tractability"]["cryptic_pocket_risk"] = "high"
        d["tractability"]["cryptic_mechanism"] = "undetermined"
        d["tractability"]["cryptic_evidence"] = self._empty_census()
        d["tractability"]["cryptic_evidence"]["n_apo_examined"] = 10
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertFalse(
            [x for x in v if "carries no information" in x.message],
            f"a real apo census was rejected as tier-alone flagging: {v}",
        )

    def test_null_evidence_block_does_not_crash_the_rule(self):
        """Why the `isinstance` disjunct survives the fix.

        The obvious repair — swapping the guard for a bare
        `ev.get("is_cryptic") is None` — raises AttributeError on
        `cryptic_evidence: null`, which the template's own "use null, never
        omit" instruction makes a legal thing to write.
        """
        d = broken(JAK1)
        d["tractability"]["cryptic_evidence"] = None
        d["tractability"]["cryptic_mechanism"] = "sidechain_occlusion"
        v = [x for x in validate_dossier(d) if x.rule == "CRYPTIC_MISCLAIM"]
        self.assertTrue(
            any("no cryptic census" in x.message for x in v),
            f"a null evidence block was not treated as a missing census: {v}",
        )

    def test_a_filled_census_is_not_flagged(self):
        """The fix must not fire on either worked example."""
        for name, d in (("JAK1", JAK1), ("TNF", TNF)):
            with self.subTest(dossier=name):
                self.assertNotIn("CRYPTIC_MISCLAIM", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# R8 — null is not zero
# ---------------------------------------------------------------------------


class TestNullIsNotZero(unittest.TestCase):
    def test_unexplained_null(self):
        d = broken(JAK1)
        d["not_found"] = [
            e for e in d["not_found"] if "disorder_fraction" not in str(e.get("field"))
        ]
        v = [x for x in validate_dossier(d) if x.rule == "NULL_IS_NOT_ZERO"]
        self.assertTrue(any(x.path == "tractability.disorder_fraction" for x in v))

    def test_measured_zero_also_declared_missing(self):
        """0.0 and 'we could not measure it' are different claims."""
        d = broken(JAK1)
        d["tractability"]["disorder_fraction"] = 0.0
        v = [x for x in validate_dossier(d) if x.rule == "NULL_IS_NOT_ZERO"]
        self.assertTrue(any(x.path == "tractability.disorder_fraction" for x in v))
        self.assertTrue(any("a measured" in x.message for x in v))

    def test_measured_zero_is_fine_when_not_also_in_not_found(self):
        d = broken(JAK1)
        d["tractability"]["disorder_fraction"] = 0.0
        d["not_found"] = [
            e for e in d["not_found"] if "disorder_fraction" not in str(e.get("field"))
        ]
        self.assertNotIn("NULL_IS_NOT_ZERO", rules(validate_dossier(d)))

    def test_sentinel_string_in_a_numeric_field(self):
        d = broken(JAK1)
        d["structure"]["holo_count"] = "N/A"
        v = [x for x in validate_dossier(d) if x.rule == "NULL_IS_NOT_ZERO"]
        self.assertTrue(any(x.path == "structure.holo_count" for x in v))

    def test_not_found_naming_the_block_does_not_excuse_every_null_in_it(self):
        """The laundering path: one vague line covering a whole block."""
        d = broken(JAK1)
        d["not_found"] = [{"field": "tractability", "reason": "we did not run it"}]
        v = [x for x in validate_dossier(d) if x.rule == "NULL_IS_NOT_ZERO"]
        self.assertGreaterEqual(len(v), 5)


# ---------------------------------------------------------------------------
# R9 — as-of integrity
# ---------------------------------------------------------------------------


def _as_of_2010_jak1() -> dict:
    """JAK1 at 2010-12-31 — before ruxolitinib. RA is biologic-only here."""
    d = broken(JAK1)
    d["as_of_date"] = "2010-12-31"
    d["target_precedent"]["approved_small_molecules"] = []
    d["target_precedent"]["approved_small_molecules_count"] = 0
    d["verdict"] = "insufficient_evidence"
    d["verdict_basis"] = "none"
    return d


class TestAsOfIntegrity(unittest.TestCase):
    def test_clinical_candidates_always_carry_the_flag(self):
        d = _as_of_2010_jak1()
        v = [x for x in validate_dossier(d) if x.rule == "AS_OF_LEAKAGE"]
        self.assertTrue(
            any(
                x.path == "target_precedent.clinical_stage_small_molecules"
                for x in v
            )
        )

    def test_undated_bioactivity_counts_carry_the_flag(self):
        d = _as_of_2010_jak1()
        paths = {x.path for x in validate_dossier(d) if x.rule == "AS_OF_LEAKAGE"}
        self.assertIn("target_precedent.distinct_actives", paths)
        self.assertIn("target_precedent.best_potency_nm", paths)

    def test_flagged_dossier_passes(self):
        d = _as_of_2010_jak1()
        d["target_precedent"]["as_of_leakage"] = [
            {
                "field": "clinical_stage_small_molecules",
                "leakage_risk": True,
                "note": "ChEMBL max_phase is current state with no phase history; "
                "no clinical candidate list is date-filterable at the source",
            },
            {
                "field": "distinct_actives",
                "leakage_risk": True,
                "note": "bioactivities_by_accession has no date column; count is "
                "current, not as-of 2010-12-31",
            },
            {
                "field": "best_potency_nm",
                "leakage_risk": True,
                "note": "same undated table as distinct_actives",
            },
        ]
        self.assertNotIn("AS_OF_LEAKAGE", rules(validate_dossier(d)))

    def test_an_approval_after_the_cutoff(self):
        d = _as_of_2010_jak1()
        d["target_precedent"]["approved_small_molecules"] = [
            {
                "name": "ruxolitinib phosphate",
                "year": 2011,
                "source": "chembl_v.drugs_by_accession",
            }
        ]
        v = [x for x in validate_dossier(d) if x.rule == "AS_OF_LEAKAGE"]
        self.assertTrue(any("after the as_of_date" in x.message for x in v))

    def test_malformed_as_of_date(self):
        d = broken(JAK1)
        d["as_of_date"] = "2010"
        v = [x for x in validate_dossier(d) if x.rule == "AS_OF_LEAKAGE"]
        self.assertTrue(any("ISO date" in x.message for x in v))

    def test_no_cutoff_means_no_leakage_rules(self):
        self.assertNotIn("AS_OF_LEAKAGE", rules(validate_dossier(JAK1)))


# ---------------------------------------------------------------------------
# R10/R11 — conflict declaration and assay provenance
# ---------------------------------------------------------------------------


class TestAxisConflictAndAssayProvenance(unittest.TestCase):
    def test_contaminated_assay_forces_a_stated_conflict(self):
        d = broken(TNF)
        d["axis_conflict"] = ""
        v = [x for x in validate_dossier(d) if x.rule == "AXIS_CONFLICT_UNDECLARED"]
        self.assertTrue(v)
        self.assertIn("different protein", v[0].message)

    def test_actives_with_no_holo_structures_forces_a_conflict(self):
        """The MYC shape: 1,079 compounds, 0 of 25 structures with a real ligand."""
        d = broken(JAK1)
        d["target_precedent"]["distinct_actives"] = 1079
        d["structure"]["holo_count"] = 0
        d["structure"]["apo_count"] = 25
        d["structure"]["total_pdb_structures"] = 25
        v = [x for x in validate_dossier(d) if x.rule == "AXIS_CONFLICT_UNDECLARED"]
        self.assertTrue(any("holo" in x.message for x in v))

    def test_actives_reported_without_assay_provenance(self):
        d = broken(JAK1)
        d["target_precedent"]["assay_concentration"]["top_assay_description"] = None
        d["target_precedent"]["assay_concentration"]["top_assay_share_pct"] = None
        d["not_found"].append(
            {"field": "top_assay_share_pct", "reason": "not queried"}
        )
        v = [x for x in validate_dossier(d) if x.rule == "ASSAY_PROVENANCE_MISSING"]
        self.assertEqual(len(v), 2)

    def test_dominant_assay_not_checked_for_target_identity(self):
        d = broken(TNF)
        d["target_precedent"]["assay_concentration"]["measures_a_different_target"] = None
        v = [x for x in validate_dossier(d) if x.rule == "ASSAY_PROVENANCE_MISSING"]
        self.assertTrue(any("even measures this protein" in x.message for x in v))

    def test_potency_without_a_characterisation_call(self):
        d = broken(JAK1)
        d["target_precedent"]["best_potency_characterised"] = None
        self.assertIn("ASSAY_PROVENANCE_MISSING", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# R0 — the template is the contract
# ---------------------------------------------------------------------------


class TestWellFormed(unittest.TestCase):
    def test_missing_key(self):
        d = broken(JAK1)
        del d["falsification"]
        self.assertIn("WELL_FORMED", rules(validate_dossier(d)))

    def test_unfilled_enum_placeholder(self):
        d = broken(JAK1)
        d["verdict"] = "small_molecule_tractable | not_tractable | insufficient_evidence"
        v = [x for x in validate_dossier(d) if x.rule == "WELL_FORMED"]
        self.assertTrue(any("placeholder" in x.message for x in v))

    def test_nameless_template_stub(self):
        d = broken(JAK1)
        d["target_precedent"]["terminated_programs"] = [
            {"program": "", "year": None, "stated_reason": "", "source": ""}
        ]
        v = [x for x in validate_dossier(d) if x.rule == "WELL_FORMED"]
        self.assertTrue(any("empty template stub" in x.message for x in v))

    def test_falsification_survived_left_null(self):
        d = broken(JAK1)
        d["falsification"]["survived"] = None
        self.assertIn("WELL_FORMED", rules(validate_dossier(d)))

    def test_no_checks_run(self):
        d = broken(JAK1)
        d["falsification"]["checks_run"] = []
        self.assertIn("WELL_FORMED", rules(validate_dossier(d)))

    def test_invalid_enum_value(self):
        d = broken(JAK1)
        d["tractability"]["cryptic_mechanism"] = "cryptic"
        self.assertIn("WELL_FORMED", rules(validate_dossier(d)))

    def test_verdict_as_a_number(self):
        d = broken(JAK1)
        d["verdict"] = 0.82
        self.assertIn("WELL_FORMED", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# The fixtures, run as data
# ---------------------------------------------------------------------------


RA = _load(FIXTURES / "rheumatoid_arthritis.json")
TARGETS = _load(FIXTURES / "targets.json")


def dossier_from_ra_row(row: dict, verdict: str, basis: str) -> dict:
    """Build a dossier skeleton from a rheumatoid_arthritis.json row."""
    d = broken(JAK1)
    d["_example"] = f"fixture-derived: {row['gene']}"
    d["target"].update(
        {
            "uniprot_accession": row["accession"],
            "gene_symbol": row["gene"],
            "protein_name": row["gene"],
            "sequence_length": None,
        }
    )
    d["target"]["sources"] = [f"fixtures/rheumatoid_arthritis.json {row['gene']}"]
    d["verdict"] = verdict
    d["verdict_basis"] = basis
    sm = [
        {
            "name": e["name"],
            "year": e["year"],
            "modality": "small_molecule",
            "source": "fixtures/rheumatoid_arthritis.json first_approval from ChEMBL",
        }
        for e in row.get("approved_small_molecules", [])
    ]
    bio = [
        {
            "name": e["name"],
            "year": e["year"],
            "modality": e["modality"].replace(" ", "_"),
            "source": "fixtures/rheumatoid_arthritis.json first_approval from ChEMBL",
        }
        for e in row.get("approved_biologics", [])
    ]
    d["target_precedent"]["approved_small_molecules"] = sm
    d["target_precedent"]["approved_small_molecules_count"] = len(sm)
    d["biologic_precedent"]["approved_biologics"] = bio
    return d


class TestRheumatoidArthritisFixture(unittest.TestCase):
    """Eight RA targets. Four won with small molecules, four with biologics.

    Nothing varies except the modality, which is the one variable this agent
    exists to measure.
    """

    def test_fixture_shape(self):
        self.assertEqual(len(RA["small_molecule_tractable"]), 4)
        self.assertEqual(len(RA["biologic_only"]), 4)

    def test_jak_family_rows_are_clean(self):
        for row in RA["small_molecule_tractable"]:
            with self.subTest(gene=row["gene"]):
                d = dossier_from_ra_row(row, "small_molecule_tractable", "retrieved_precedent")
                v = validate_dossier(d)
                self.assertNotIn("MODALITY_LEAK", rules(v), msg=str(v))
                self.assertNotIn("AXIS_CONFLICT_UNDECLARED", rules(v), msg=str(v))
                self.assertEqual(row["expected_verdict"], "small_molecule_tractable")

    def test_crediting_a_biologic_toward_tractability_is_caught(self):
        """The one failure that voids a run regardless of everything else."""
        for row in RA["biologic_only"]:
            with self.subTest(gene=row["gene"]):
                d = dossier_from_ra_row(row, "small_molecule_tractable", "retrieved_precedent")
                # The naive read: "approved drugs exist, therefore tractable."
                d["target_precedent"]["approved_small_molecules"] = [
                    {
                        "name": e["name"],
                        "year": e["year"],
                        "source": "chembl_v.drugs_by_accession",
                    }
                    for e in row["approved_biologics"]
                ]
                self.assertIn("MODALITY_LEAK", rules(validate_dossier(d)))

    def test_biologic_only_rows_may_not_claim_tractability_silently(self):
        for row in RA["biologic_only"]:
            with self.subTest(gene=row["gene"]):
                d = dossier_from_ra_row(row, "small_molecule_tractable", "computed_tractability")
                d["axis_conflict"] = None
                v = rules(validate_dossier(d))
                self.assertIn("MODALITY_LEAK", v)
                self.assertIn("AXIS_CONFLICT_UNDECLARED", v)

    def test_cd20_negative_verdict_needs_no_manufactured_conflict(self):
        """Both axes agree that there is nothing to bind. Silence is correct."""
        row = next(r for r in RA["biologic_only"] if r["accession"] == "P11836")
        d = dossier_from_ra_row(row, "not_tractable", "computed_tractability")
        d["target_precedent"]["distinct_actives"] = 0
        d["target_precedent"]["best_potency_nm"] = None
        d["target_precedent"]["best_potency_characterised"] = None
        d["target_precedent"]["assay_concentration"]["top_assay_share_pct"] = None
        d["not_found"].extend(
            [
                {"field": "target_precedent.best_potency_nm", "reason": "no actives"},
                {"field": "top_assay_share_pct", "reason": "no actives"},
            ]
        )
        v = rules(validate_dossier(d))
        self.assertNotIn("AXIS_CONFLICT_UNDECLARED", v)
        self.assertNotIn("MODALITY_LEAK", v)

    def test_tnf_expected_verdict_is_the_conflict(self):
        row = next(r for r in RA["biologic_only"] if r["accession"] == "P01375")
        self.assertEqual(row["expected_verdict"], "axis_conflict")
        self.assertTrue(TNF["axis_conflict"])
        self.assertEqual(TNF["target_precedent"]["approved_small_molecules"], [])
        self.assertEqual(len(TNF["biologic_precedent"]["approved_biologics"]), 5)

    def test_as_of_2010_flips_the_jak_rows_only(self):
        """RA at 2010-12-31 is a biologic-only disease across every row here."""
        note = RA["THE_TEST"]["as_of_variant"]["2010-12-31"]
        self.assertIn("ruxolitinib is 2011", note)
        for row in RA["small_molecule_tractable"]:
            with self.subTest(gene=row["gene"]):
                d = dossier_from_ra_row(row, "insufficient_evidence", "none")
                d["as_of_date"] = "2010-12-31"
                v = [x for x in validate_dossier(d) if x.rule == "AS_OF_LEAKAGE"]
                # Every approval in these rows postdates the cutoff.
                self.assertTrue(any("after the as_of_date" in x.message for x in v))


class TestTargetsFixture(unittest.TestCase):
    def test_il11_must_decline(self):
        """15 compounds from a single assay, 8 structures, none holo."""
        f = TARGETS["slot_6_recent_orphan"]
        self.assertEqual(f["expected_output"]["verdict"], "insufficient_evidence")
        d = broken(JAK1)
        d["target"].update(
            {
                "uniprot_accession": f["uniprot"],
                "gene_symbol": "IL11",
                "protein_name": "Interleukin-11",
                "sequence_length": None,
            }
        )
        d["target"]["sources"] = ["fixtures/targets.json slot_6_recent_orphan"]
        d["target_precedent"].update(
            {
                "chembl_target_id": f["chembl_target"],
                "distinct_actives": f["distinct_compounds"],
                "best_potency_nm": f["best_potency_nm"],
                "approved_small_molecules": [],
                "approved_small_molecules_count": 0,
            }
        )
        d["target_precedent"]["assay_concentration"].update(
            {
                "top_assay_description": f["assay_provenance"],
                "top_assay_share_pct": 100.0,
                "measures_a_different_target": False,
            }
        )
        d["structure"].update(
            {"total_pdb_structures": f["pdb_total"], "holo_count": 0, "apo_count": 8}
        )
        # A confident verdict on this evidence is the failure mode.
        d["verdict"] = "small_molecule_tractable"
        self.assertIn("INSUFFICIENT_EVIDENCE_AVOIDED", rules(validate_dossier(d)))
        # Declining clears it.
        d["verdict"] = "insufficient_evidence"
        d["verdict_basis"] = "none"
        self.assertNotIn("INSUFFICIENT_EVIDENCE_AVOIDED", rules(validate_dossier(d)))

    def test_myc_actives_without_holo_is_a_conflict(self):
        myc = next(t for t in TARGETS["method_validation"] if t["target"] == "MYC")
        self.assertEqual(myc["pdb_holo"], 0)
        d = broken(JAK1)
        d["target"]["sources"] = ["fixtures/targets.json MYC"]
        d["target_precedent"]["chembl_target_id"] = myc["chembl_target"]
        d["target_precedent"]["distinct_actives"] = myc["distinct_compounds"]
        d["target_precedent"]["best_potency_nm"] = myc["best_potency_nm"]
        d["target_precedent"]["best_potency_characterised"] = False
        d["target_precedent"]["approved_small_molecules"] = []
        d["target_precedent"]["approved_small_molecules_count"] = 0
        d["structure"]["holo_count"] = 0
        d["structure"]["total_pdb_structures"] = myc["pdb_total"]
        d["structure"]["apo_count"] = myc["pdb_total"]
        d["verdict"] = "not_tractable"
        d["verdict_basis"] = "computed_tractability"
        v = [x for x in validate_dossier(d) if x.rule == "AXIS_CONFLICT_UNDECLARED"]
        self.assertTrue(v)
        self.assertIn("uncharacterised", v[0].message)

    def test_rorgt_clinical_failure_is_not_a_tractability_penalty(self):
        """152 holo, 12,900 compounds, zero approvals, terminated on tox."""
        ror = next(t for t in TARGETS["immunology"] if t["uniprot"] == "P51449")
        d = broken(JAK1)
        d["target"]["sources"] = ["fixtures/targets.json RORgt"]
        d["target_precedent"]["chembl_target_id"] = ror["chembl_target"]
        d["target_precedent"]["distinct_actives"] = ror["distinct_compounds"]
        d["target_precedent"]["best_potency_nm"] = ror["best_potency_nm"]
        d["target_precedent"]["approved_small_molecules"] = []
        d["target_precedent"]["approved_small_molecules_count"] = 0
        d["target_precedent"]["terminated_programs"] = [
            {
                "program": p["program"],
                "year": None,
                "stated_reason": p["outcome"],
                "source": "fixtures/targets.json RORgt terminated_programs",
            }
            for p in ror["terminated_programs"]
        ]
        d["structure"]["holo_count"] = ror["pdb_holo"]
        d["structure"]["total_pdb_structures"] = ror["pdb_total"]
        d["structure"]["apo_count"] = ror["pdb_total"] - ror["pdb_holo"]
        d["verdict"] = "small_molecule_tractable"
        d["verdict_basis"] = "both"
        v = rules(validate_dossier(d))
        # Tractable with zero approvals and a full terminated_programs block is
        # a legal dossier. Nothing here may object to it.
        self.assertNotIn("MODALITY_LEAK", v)
        self.assertNotIn("AXIS_CONFLICT_UNDECLARED", v)
        self.assertNotIn("INSUFFICIENT_EVIDENCE_AVOIDED", v)



# ---------------------------------------------------------------------------
# R5b — druggability is reported and carries nothing (rule 4.0)
#
# EVERY TEST IN THIS CLASS AND THE NEXT FAILS AGAINST THE PRE-2026-08-15
# VALIDATOR. That is the point: before `check_druggability_not_load_bearing`
# and `check_volume_is_primary` existed, a dossier could reach `not_tractable`
# on a druggability of 0.013 measured at a pocket with osimertinib physically
# bound in it (EGFR 6LUD, real) and pass clean, because nothing in the file read
# the druggability value against the verdict at all — `check_druggability_is_a_
# range` only ever asked whether it was a range.
# ---------------------------------------------------------------------------


def _computed_negative(base: dict) -> dict:
    """A dossier whose negative verdict rests on the computed axis."""
    d = broken(base)
    d["verdict"] = "not_tractable"
    d["verdict_basis"] = "computed_tractability"
    return d


class TestDruggabilityNotLoadBearing(unittest.TestCase):
    def test_load_bearing_true_is_rejected(self):
        """The field is a declaration and only one value is legal."""
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"]["load_bearing"] = True
        v = [
            x
            for x in validate_dossier(d)
            if x.rule == "DRUGGABILITY_LOAD_BEARING"
            and x.path.endswith("load_bearing")
        ]
        self.assertTrue(v)
        self.assertIn("0.720", v[0].message)

    def test_load_bearing_missing_is_rejected(self):
        """Silence is not the same as declaring it non-load-bearing."""
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"].pop("load_bearing", None)
        self.assertIn(
            "DRUGGABILITY_LOAD_BEARING", rules(validate_dossier(d))
        )

    def test_the_false_negative_rate_travels_with_the_number(self):
        """A reader who meets a 0.02 later cannot discount it without the rate."""
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"]["_false_negative_rate"] = ""
        v = [
            x
            for x in validate_dossier(d)
            if x.rule == "DRUGGABILITY_LOAD_BEARING"
            and x.path.endswith("_false_negative_rate")
        ]
        self.assertTrue(v)
        self.assertIn("41%", v[0].message)

    def test_a_negative_verdict_on_druggability_alone_is_rejected(self):
        """The EGFR 6LUD shape: 0.013 with a drug in the pocket, no volume.

        This is the exact failure the rule exists for. 15 of 37 pockets with a
        drug-like ligand physically bound score below 0.1, so a low score is not
        evidence of anything on its own.
        """
        d = _computed_negative(JAK1)
        d["tractability"]["pocket_druggability"]["min"] = 0.013
        d["tractability"]["pocket_druggability"]["max"] = 0.089
        d["tractability"]["pocket_volume_a3"]["min"] = None
        d["tractability"]["pocket_volume_a3"]["max"] = None
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = None
        v = [
            x
            for x in validate_dossier(d)
            if x.rule == "DRUGGABILITY_LOAD_BEARING" and x.path == "verdict"
        ]
        self.assertTrue(v)
        self.assertIn("may not carry a negative verdict", v[0].message)

    def test_insufficient_evidence_on_druggability_alone_is_rejected_too(self):
        """Both negative verdicts, not just not_tractable."""
        d = _computed_negative(JAK1)
        d["verdict"] = "insufficient_evidence"
        d["verdict_basis"] = "both"
        d["tractability"]["pocket_druggability"]["max"] = 0.009
        for k in ("min", "max", "primary_d1_6_a3"):
            d["tractability"]["pocket_volume_a3"][k] = None
        self.assertIn("DRUGGABILITY_LOAD_BEARING", rules(validate_dossier(d)))

    def test_a_negative_verdict_WITH_volume_behind_it_is_legal(self):
        """The rule must not ban negative verdicts, only unsupported ones.

        TL1A's measured D=1.6 volume is 136.9 A^3 — the smallest in the set. A
        negative verdict resting on THAT is resting on the primary number, which
        is what the rule wants, so nothing may fire.
        """
        d = _computed_negative(JAK1)
        d["tractability"]["pocket_druggability"]["max"] = 0.173
        d["tractability"]["pocket_volume_a3"]["min"] = 136.9
        d["tractability"]["pocket_volume_a3"]["max"] = 136.9
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = 136.9
        self.assertNotIn("DRUGGABILITY_LOAD_BEARING", rules(validate_dossier(d)))

    def test_a_high_volume_beside_a_low_druggability_is_a_conflict_to_report(self):
        """The judgement call, encoded: report the disagreement, resolve neither.

        EGFR is the measured case — D=1.6 volume 290.2 A^3, and 6LUD with
        osimertinib bound scoring 0.013. A dossier carrying both and saying
        nothing about it has silently picked a side.
        """
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"]["min"] = 0.013
        d["tractability"]["pocket_druggability"]["max"] = 0.475
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = 290.2
        d["tractability"]["caveat"] = None
        v = [
            x
            for x in validate_dossier(d)
            if x.rule == "DRUGGABILITY_LOAD_BEARING"
            and x.path == "tractability.caveat"
        ]
        self.assertTrue(v)
        self.assertIn("uncalibrated proposal", v[0].message)

    def test_the_conflict_is_satisfied_by_saying_so(self):
        """And a caveat that names it clears the rule — it wants disclosure."""
        d = broken(JAK1)
        d["tractability"]["pocket_druggability"]["min"] = 0.013
        d["tractability"]["pocket_druggability"]["max"] = 0.475
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = 290.2
        d["tractability"]["caveat"] = (
            "Druggability 0.013-0.475 disagrees with a 290.2 A^3 D=1.6 volume. "
            "Reported, not resolved."
        )
        self.assertNotIn("DRUGGABILITY_LOAD_BEARING", rules(validate_dossier(d)))

    def test_the_measured_constants_are_pinned(self):
        """The thresholds are the measurement, so pin them as data.

        If someone widens the false-negative band or turns the volume guide into
        a classifier, this fails and names the number that moved.
        """
        import validate_dossier as m

        self.assertEqual(m.DRUGGABILITY_FALSE_NEGATIVE_BAND, 0.5)
        self.assertEqual(m.DRUGGABILITY_FALSE_NEGATIVE_FLOOR, 0.1)
        self.assertEqual(m.PRIMARY_VOLUME_CLUSTERING_D, 1.6)
        self.assertEqual(m.MERGED_VOLUME_A3, 1000.0)
        # Uncalibrated proposal, fitted post hoc on n=15 with a 17% margin.
        # Measured: every hard target <= 207 A^3, every druggable one >= 242.
        self.assertEqual(m.VOLUME_GUIDE_DRUGGABLE_A3, 240.0)
        self.assertEqual(m.VOLUME_GUIDE_HARD_A3, 210.0)
        self.assertLess(m.VOLUME_GUIDE_HARD_A3, m.VOLUME_GUIDE_DRUGGABLE_A3)
        self.assertEqual(
            m.NEGATIVE_VERDICTS, {"not_tractable", "insufficient_evidence"}
        )

    def test_the_volume_guide_does_not_classify(self):
        """Rule 4a: it is a proposal and gates nothing.

        A target sitting between the two guide values is UNCLASSIFIED by it, and
        a dossier calling such a target tractable must not be objected to on
        those grounds. This test exists to stop the guide being quietly promoted
        into a threshold later.
        """
        d = broken(JAK1)
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = 225.0
        d["verdict"] = "small_molecule_tractable"
        v = rules(validate_dossier(d))
        self.assertNotIn("DRUGGABILITY_LOAD_BEARING", v)
        self.assertNotIn("VOLUME_NOT_PRIMARY", v)

    def test_persistence_is_still_legal_as_a_SITE_LOCATION_basis(self):
        """Rule 4c bans persistence as a quality signal, not as a locator.

        Persistence is AUC 0.500 — the site pocket was detected in 100% of
        structures for all 15 targets — and the published consensus criterion on
        top of it ranks MYC first at 0.80. So it must never stand in for
        druggability. It is still how `site_from_density` is defined and still a
        legal answer to "how was this site located", and nothing may object.
        """
        d = broken(JAK1)
        d["tractability"]["site_hypothesis_basis"] = (
            "persistence across the ensemble — no holo ligand to anchor to"
        )
        self.assertNotIn("DRUGGABILITY_LOAD_BEARING", rules(validate_dossier(d)))


# ---------------------------------------------------------------------------
# R5c — volume at D=1.6 is the primary number (rule 4a)
# ---------------------------------------------------------------------------


class TestVolumeIsPrimary(unittest.TestCase):
    def test_geometry_without_the_d1_6_primary_is_rejected(self):
        """The shape BOTH real runs had before this rule existed."""
        d = broken(JAK1)
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = None
        d["not_found"] = [
            e
            for e in d["not_found"]
            if "primary_d1_6_a3" not in str(e.get("field", ""))
        ]
        v = [
            x
            for x in validate_dossier(d)
            if x.rule == "VOLUME_NOT_PRIMARY"
            and x.path.endswith("primary_d1_6_a3")
        ]
        self.assertTrue(v)
        self.assertIn("AUC 1.000", v[0].message)

    def test_a_not_found_line_excuses_the_missing_primary(self):
        """Same discipline as every other null: say why, and it is legal.

        This is how the shipped JAK1 example passes — it declines the D=1.6
        figure rather than inventing one from a spread that pools both D values.
        """
        d = broken(JAK1)
        self.assertIsNone(d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"])
        self.assertNotIn("VOLUME_NOT_PRIMARY", rules(validate_dossier(d)))

    def test_a_merged_volume_is_not_a_site_volume(self):
        """Above ~1000 A^3 the site has merged with its neighbours.

        1152.3 A^3 is the measured D=2.4 merge on a real fixture. Quoting it as
        a D=1.6 primary number is quoting a mega-cavity no molecule occupies.
        """
        d = broken(JAK1)
        d["tractability"]["pocket_volume_a3"]["primary_d1_6_a3"] = 1152.3
        v = [x for x in validate_dossier(d) if x.rule == "VOLUME_NOT_PRIMARY"]
        self.assertTrue(v)
        self.assertIn("merged", v[0].message)

    def test_a_spread_with_no_clustering_record_is_rejected(self):
        """D=1.6 and D=2.4 do not measure the same cavity."""
        d = broken(JAK1)
        d["tractability"]["pocket_volume_a3"]["clustering_d"] = None
        v = [
            x
            for x in validate_dossier(d)
            if x.rule == "VOLUME_NOT_PRIMARY" and x.path.endswith("clustering_d")
        ]
        self.assertTrue(v)

    def test_a_refused_block_is_not_asked_for_a_primary(self):
        """TNF reports no geometry at all, so there is nothing to be primary."""
        self.assertNotIn("VOLUME_NOT_PRIMARY", rules(validate_dossier(TNF)))

    def test_druggability_alone_still_demands_the_primary_volume(self):
        """Reporting the demoted number and not the promoted one."""
        d = broken(JAK1)
        for k in ("min", "max", "primary_d1_6_a3"):
            d["tractability"]["pocket_volume_a3"][k] = None
        d["not_found"] = [
            e
            for e in d["not_found"]
            if "pocket_volume_a3" not in str(e.get("field", ""))
        ]
        self.assertIn("VOLUME_NOT_PRIMARY", rules(validate_dossier(d)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
