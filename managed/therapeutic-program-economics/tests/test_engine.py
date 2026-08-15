from __future__ import annotations

import json
from copy import deepcopy
from math import prod
from pathlib import Path

import pytest
from test_cashflow import program_inputs

from labrador_roi.comparables import ComparableSet
from labrador_roi.engine import (
    ENGINE_VERSION,
    SCHEMA_VERSION,
    Recommendation,
    analyze_program,
)
from labrador_roi.models import (
    DecisionGrade,
    EvidenceGrade,
    EvidenceMetadata,
    EvidenceType,
    ProgramInput,
)
from labrador_roi.simulation import SimulationAssumptions, TriangularRange

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"

FIXED_ASSUMPTIONS = SimulationAssumptions(
    price_multiplier=TriangularRange(low=1, mode=1, high=1),
    patient_multiplier=TriangularRange(low=1, mode=1, high=1),
    gross_to_net_shift=TriangularRange(low=0, mode=0, high=0),
    persistence_multiplier=TriangularRange(low=1, mode=1, high=1),
    development_cost_multiplier=TriangularRange(low=1, mode=1, high=1),
    launch_delay_years=TriangularRange(low=0, mode=0, high=0),
    loe_retention_multiplier=TriangularRange(low=1, mode=1, high=1),
)


def _evidence_payload(
    source_id: str = "test-source",
    *,
    evidence_type: str = "PAYER_OR_HTA",
    grade: str = "MODERATE",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "evidence_type": evidence_type,
        "grade": grade,
        "synthetic": False,
    }


def _replace_fixture_evidence(
    value,
    *,
    evidence_type: str = "PAYER_OR_HTA",
    grade: str = "MODERATE",
):
    if isinstance(value, dict):
        if {"evidence_type", "grade", "synthetic"} <= value.keys():
            return _evidence_payload(
                str(value.get("source_id") or "test-source"),
                evidence_type=evidence_type,
                grade=grade,
            )
        return {
            key: _replace_fixture_evidence(item, evidence_type=evidence_type, grade=grade)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _replace_fixture_evidence(item, evidence_type=evidence_type, grade=grade)
            for item in value
        ]
    return value


def _decision_ready_fixture(
    *,
    evidence_type: str = "PAYER_OR_HTA",
    grade: str = "MODERATE",
) -> tuple[ProgramInput, ComparableSet]:
    raw_program = json.loads((FIXTURE_ROOT / "demo_program.json").read_text())
    raw_program = _replace_fixture_evidence(raw_program, evidence_type=evidence_type, grade=grade)
    group = _evidence_payload(
        evidence_type=evidence_type,
        grade=grade,
    )
    raw_program["patent"]["evidence"]["patent_inputs"] = group
    raw_program["development"]["program_probability_of_approval"] = prod(
        raw_program["development"]["stage_success_probabilities"].values()
    )
    raw_program["expansion_indications"][0]["access"]["patient_cost_share_fraction"] = 0
    for indication in [
        raw_program["initial_indication"],
        *raw_program["expansion_indications"],
    ]:
        indication["population"]["evidence"]["population_inputs"] = group
        indication["evidence"]["commercial_inputs"] = group
        indication["evidence"]["candidate_list_price"] = group
        if indication["access"].get("patient_cost_share_fraction", 0) > 0:
            indication["access"]["annual_patient_oop"] = 2_000
            indication["access"]["evidence"]["annual_patient_oop"] = group
    raw_comparables = json.loads((FIXTURE_ROOT / "demo_comparables.json").read_text())
    raw_comparables = _replace_fixture_evidence(
        raw_comparables, evidence_type=evidence_type, grade=grade
    )
    return (
        ProgramInput.model_validate(raw_program),
        ComparableSet.model_validate({"comparables": raw_comparables["comparables"]}),
    )


def test_seeded_analysis_is_reproducible() -> None:
    first = analyze_program(
        program_inputs(), simulations=200, seed=77, simulation_assumptions=FIXED_ASSUMPTIONS
    )
    second = analyze_program(
        program_inputs(), simulations=200, seed=77, simulation_assumptions=FIXED_ASSUMPTIONS
    )

    assert first.input_digest == second.input_digest
    assert first.run_id == second.run_id
    assert first.uncertainty == second.uncertainty
    assert first.summary == second.summary


def test_analysis_has_stable_audit_contract_and_decomposition() -> None:
    result = analyze_program(
        program_inputs(), simulations=100, seed=1, simulation_assumptions=FIXED_ASSUMPTIONS
    )

    assert result.schema_version == SCHEMA_VERSION
    assert result.engine_version == ENGINE_VERSION
    assert result.run_id.startswith("run_")
    assert result.input_digest.startswith("sha256:")
    assert result.seed == 1
    assert result.simulations == 100
    assert result.simulation_assumptions == FIXED_ASSUMPTIONS
    assert result.input_snapshot["cashflow_inputs"]["program_id"] == "program-1"
    assert result.calculation_steps
    assert result.value_decomposition.protected_net_revenue > 0
    assert result.summary.value_lost_per_launch_delay_year != 0
    assert result.critical_evidence_status == {"cashflow_inputs": True}


def test_standardized_recommendation_and_decision_grade() -> None:
    result = analyze_program(
        program_inputs(), simulations=300, seed=4, simulation_assumptions=FIXED_ASSUMPTIONS
    )

    assert result.decision_grade == DecisionGrade.DECISION_GRADE
    assert result.recommendation in set(Recommendation)
    assert result.recommendation != Recommendation.NOT_DECISION_GRADE


def test_unsupported_inputs_never_receive_decision_grade() -> None:
    unsupported = program_inputs().model_copy(update={"critical_inputs_supported": False})
    result = analyze_program(
        unsupported, simulations=50, seed=2, simulation_assumptions=FIXED_ASSUMPTIONS
    )

    assert result.decision_grade == DecisionGrade.NOT_DECISION_GRADE
    assert result.recommendation == Recommendation.NOT_DECISION_GRADE


def test_result_contains_no_secret_from_evidence_reference() -> None:
    inputs = program_inputs().model_copy(
        update={"evidence_references": ("https://example.test/data?api_key=secret-value",)}
    )
    result = analyze_program(
        inputs, simulations=10, seed=5, simulation_assumptions=FIXED_ASSUMPTIONS
    )

    rendered = result.model_dump_json()
    assert "secret-value" not in rendered
    assert result.input_snapshot["cashflow_inputs"]["evidence_references"] == [
        "https://example.test/data?api_key=%5BREDACTED%5D"
    ]


def test_zero_oop_public_coverage_maps_to_full_affordability() -> None:
    program = ProgramInput.model_validate_json((FIXTURE_ROOT / "demo_program.json").read_text())
    public_access = program.initial_indication.access.model_copy(
        update={"universal_or_public_coverage": True, "patient_cost_share_fraction": 0.0}
    )
    program = program.model_copy(
        update={
            "initial_indication": program.initial_indication.model_copy(
                update={"access": public_access}
            )
        }
    )
    comparable_payload = json.loads((FIXTURE_ROOT / "demo_comparables.json").read_text())
    comparables = ComparableSet.model_validate({"comparables": comparable_payload["comparables"]})

    result = analyze_program(program, comparables, simulations=5, seed=3)

    assert result.access[0].patient_affordability_rate == 1.0


def test_mapping_order_cannot_change_results_behind_the_same_run_id() -> None:
    raw = json.loads((FIXTURE_ROOT / "demo_program.json").read_text())
    reordered = deepcopy(raw)
    reordered["development"]["stage_costs"] = dict(
        reversed(list(reordered["development"]["stage_costs"].items()))
    )
    comparables_payload = json.loads((FIXTURE_ROOT / "demo_comparables.json").read_text())
    comparables = ComparableSet.model_validate({"comparables": comparables_payload["comparables"]})

    first = analyze_program(
        ProgramInput.model_validate(raw),
        comparables,
        simulations=25,
        seed=9,
        simulation_assumptions=FIXED_ASSUMPTIONS,
    )
    second = analyze_program(
        ProgramInput.model_validate(reordered),
        comparables,
        simulations=25,
        seed=9,
        simulation_assumptions=FIXED_ASSUMPTIONS,
    )

    assert first.input_digest == second.input_digest
    assert first.run_id == second.run_id
    assert first.cash_flow == second.cash_flow
    assert first.uncertainty == second.uncertainty


def test_complete_supported_fixture_can_clear_decision_gate() -> None:
    program, comparables = _decision_ready_fixture()

    result = analyze_program(program, comparables, simulations=5, seed=1)

    assert result.decision_grade == DecisionGrade.DECISION_GRADE
    assert all(result.critical_evidence_status.values())
    assert not any(item.severity.value == "ERROR" for item in result.warnings)
    assert result.input_snapshot["program"]["program_id"] == program.program_id
    assert len(result.input_snapshot["comparables"]["comparables"]) == len(comparables.comparables)


def test_missing_commercial_rates_block_decision_grade_instead_of_issuing_stop() -> None:
    program, comparables = _decision_ready_fixture()
    indication = program.initial_indication
    assumptions = dict(indication.assumptions)
    for key in (
        "peak_adoption_rate",
        "adoption_ramp_years",
        "annual_persistence_rate",
        "dose_intensity",
    ):
        assumptions.pop(key, None)
    indication = indication.model_copy(
        update={
            "access": indication.access.model_copy(update={"adoption_by_year": {}}),
            "assumptions": assumptions,
        }
    )
    program = program.model_copy(
        update={"initial_indication": indication, "expansion_indications": []}
    )

    result = analyze_program(program, comparables, simulations=10, seed=1)

    assert result.decision_grade == DecisionGrade.NOT_DECISION_GRADE
    assert result.recommendation == Recommendation.NOT_DECISION_GRADE
    error_codes = {item.code for item in result.warnings if item.severity.value == "ERROR"}
    assert {"MISSING_ADOPTION", "MISSING_PERSISTENCE", "MISSING_DOSE_INTENSITY"} <= error_codes


def test_missing_expansion_development_path_blocks_decision_grade() -> None:
    program, comparables = _decision_ready_fixture()
    program = program.model_copy(
        update={"development": program.development.model_copy(update={"assumptions": {}})}
    )

    result = analyze_program(program, comparables, simulations=10, seed=1)

    assert result.decision_grade == DecisionGrade.NOT_DECISION_GRADE
    assert result.recommendation == Recommendation.NOT_DECISION_GRADE
    assert result.critical_evidence_status["cashflow.expansion.development_path"] is False
    assert any(item.code == "MISSING_EXPANSION_DEVELOPMENT_PATH" for item in result.warnings)


def test_missing_initial_development_probability_blocks_decision_grade() -> None:
    program, comparables = _decision_ready_fixture()
    development = program.development.model_copy(
        update={
            "stage_costs": {},
            "stage_durations_years": {},
            "stage_success_probabilities": {},
            "stage_order": [],
            "program_probability_of_approval": None,
        }
    )
    program = program.model_copy(update={"development": development, "expansion_indications": []})

    result = analyze_program(program, comparables, simulations=5, seed=1)

    assert result.decision_grade == DecisionGrade.NOT_DECISION_GRADE
    assert result.critical_evidence_status["cashflow.development_path"] is False
    assert any(item.code == "MISSING_INITIAL_DEVELOPMENT_PATH" for item in result.warnings)


def test_diagnosis_and_clinical_eligibility_reduce_stock_and_incident_flow() -> None:
    program, comparables = _decision_ready_fixture()

    def with_fractions(diagnosed: float, clinically_eligible: float) -> ProgramInput:
        population = program.initial_indication.population.model_copy(
            update={
                "diagnosed_fraction": diagnosed,
                "clinically_eligible_fraction": clinically_eligible,
            }
        )
        indication = program.initial_indication.model_copy(update={"population": population})
        return program.model_copy(
            update={"initial_indication": indication, "expansion_indications": []}
        )

    excluded = analyze_program(with_fractions(0, 0), comparables, simulations=5, seed=1)
    eligible = analyze_program(with_fractions(1, 1), comparables, simulations=5, seed=1)

    assert sum(row.initial_new_starts for row in excluded.cash_flow.annual_cash_flows) == 0
    assert sum(row.initial_new_starts for row in eligible.cash_flow.annual_cash_flows) > 0
    assert excluded.value_decomposition.gross_revenue == 0
    assert eligible.value_decomposition.gross_revenue > 0


def test_negative_monte_carlo_cost_multiplier_is_rejected() -> None:
    with pytest.raises(ValueError, match="development_cost_multiplier"):
        SimulationAssumptions(development_cost_multiplier=TriangularRange(low=-1, mode=-1, high=-1))


def test_low_grade_unsupported_evidence_cannot_clear_decision_gate() -> None:
    metadata = EvidenceMetadata(
        source_id="placeholder",
        evidence_type=EvidenceType.UNSUPPORTED,
        grade=EvidenceGrade.LOW,
    )
    assert metadata.supports_decision is False

    program, comparables = _decision_ready_fixture(
        evidence_type="UNSUPPORTED",
        grade="LOW",
    )
    result = analyze_program(program, comparables, simulations=5, seed=1)

    assert result.decision_grade == DecisionGrade.NOT_DECISION_GRADE
    assert result.recommendation == Recommendation.NOT_DECISION_GRADE


def test_inconsistent_aggregate_approval_probability_blocks_decision_grade() -> None:
    program, comparables = _decision_ready_fixture()
    program = program.model_copy(
        update={
            "development": program.development.model_copy(
                update={"program_probability_of_approval": 0.5}
            )
        }
    )

    result = analyze_program(program, comparables, simulations=5, seed=1)

    stage_product = prod(program.development.stage_success_probabilities.values())
    assert result.cash_flow.initial_approval_probability == pytest.approx(stage_product)
    assert (
        result.critical_evidence_status["cashflow.development_probability_reconciliation"] is False
    )
    assert result.decision_grade == DecisionGrade.NOT_DECISION_GRADE
    assert any(
        item.code == "INCONSISTENT_PROGRAM_APPROVAL_PROBABILITY" and item.severity.value == "ERROR"
        for item in result.warnings
    )


def test_standard_input_snapshot_redacts_credentials_but_preserves_access_inputs() -> None:
    program, comparables = _decision_ready_fixture()
    program = program.model_copy(
        update={
            "assumptions": {
                **program.assumptions,
                "authorization_header": "Bearer actual-credential-value",
            }
        }
    )

    result = analyze_program(program, comparables, simulations=2, seed=1)

    snapshot = result.input_snapshot["program"]
    assert snapshot["assumptions"]["authorization_header"] == "[REDACTED]"
    assert (
        snapshot["initial_indication"]["access"]["prior_authorization_pass_fraction"]
        == program.initial_indication.access.prior_authorization_pass_fraction
    )


def test_candidate_list_and_selected_net_reconcile_in_cash_revenue() -> None:
    program, comparables = _decision_ready_fixture()
    program = program.model_copy(update={"expansion_indications": []})

    result = analyze_program(program, comparables, simulations=2, seed=1)

    corridor = result.pricing[0].annual_net_price_corridor
    assert corridor is not None
    assert corridor.candidate_list_price is not None
    assert corridor.selected_annual_net_price <= corridor.candidate_list_price
    first_revenue = next(row for row in result.cash_flow.annual_cash_flows if row.gross_revenue > 0)
    assert first_revenue.net_revenue / first_revenue.gross_revenue == pytest.approx(
        corridor.selected_annual_net_price / corridor.candidate_list_price
    )
