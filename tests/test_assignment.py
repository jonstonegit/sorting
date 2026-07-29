"""Tests for weighted accession assignment."""

from decimal import Decimal

import pytest

from pgl_sorting_engine import (
    Accession,
    AssignmentMethod,
    CaseTypeRule,
    DailyLocationStaffing,
    DailySortingContext,
    DuplicateAccessionError,
    EligibilityService,
    HospitalRoutingRule,
    LocationName,
    Pathologist,
    PrefixRoutingRule,
    RoutingRuleSet,
    SortingEngine,
    SubspecialtyRequirement,
)


def create_engine(
    *,
    olol_pathologists: int = 1,
    brg_pathologists: int = 1,
    preferred_locations: tuple[LocationName, ...] = (),
    required_location: LocationName | None = None,
) -> SortingEngine:
    """Create a configurable assignment engine for tests."""
    pathologists: list[Pathologist] = []
    staffing: list[DailyLocationStaffing] = []

    olol_ids: list[str] = []

    for index in range(olol_pathologists):
        pathologist_id = f"O{index + 1}"
        olol_ids.append(pathologist_id)
        pathologists.append(
            Pathologist(
                pathologist_id=pathologist_id,
                display_name=f"OLOL Pathologist {index + 1}",
                subspecialties=frozenset(),
            )
        )

    brg_ids: list[str] = []

    for index in range(brg_pathologists):
        pathologist_id = f"B{index + 1}"
        brg_ids.append(pathologist_id)
        pathologists.append(
            Pathologist(
                pathologist_id=pathologist_id,
                display_name=f"BRG Pathologist {index + 1}",
                subspecialties=frozenset(),
            )
        )

    if olol_ids:
        staffing.append(
            DailyLocationStaffing(
                location=LocationName.OLOL,
                pathologist_ids=tuple(olol_ids),
            )
        )

    if brg_ids:
        staffing.append(
            DailyLocationStaffing(
                location=LocationName.BRG,
                pathologist_ids=tuple(brg_ids),
            )
        )

    case_rule = CaseTypeRule(
        case_type="GC",
        subspecialty=None,
        requirement=SubspecialtyRequirement.NOT_REQUIRED,
    )

    prefix_rule = PrefixRoutingRule(
        prefix="AB",
        allowed_locations=frozenset(
            {
                LocationName.OLOL,
                LocationName.BRG,
            }
        ),
        preferred_locations=preferred_locations,
    )

    hospital_rule = HospitalRoutingRule(
        hospital="Hospital A",
        allowed_locations=frozenset(
            {
                LocationName.OLOL,
                LocationName.BRG,
            }
        ),
        required_location=required_location,
    )

    rule_set = RoutingRuleSet(
        case_type_rules=(case_rule,),
        prefix_rules=(prefix_rule,),
        hospital_rules=(hospital_rule,),
    )

    staffing_context = DailySortingContext(
        pathologists=tuple(pathologists),
        staffing=tuple(staffing),
    )

    return SortingEngine(
        eligibility_service=EligibilityService(
            rules=rule_set,
            staffing_context=staffing_context,
        )
    )


def create_accession(
    accession_number: str,
    weight: str = "1",
    *,
    hospital: str = "Hospital A",
    prefix: str = "AB",
    case_type: str = "GC",
) -> Accession:
    """Create an accession for assignment tests."""
    return Accession(
        accession_number=accession_number,
        prefix=prefix,
        case_type=case_type,
        hospital=hospital,
        weight=Decimal(weight),
    )


def test_balances_work_proportional_to_pathologists() -> None:
    engine = create_engine(
        olol_pathologists=2,
        brg_pathologists=1,
    )

    result = engine.run(
        (
            create_accession("S26-1"),
            create_accession("S26-2"),
            create_accession("S26-3"),
        )
    )

    assert result.summary_for(
        LocationName.OLOL
    ).assigned_weight == Decimal("2")

    assert result.summary_for(
        LocationName.BRG
    ).assigned_weight == Decimal("1")


def test_mandatory_assignment_uses_required_location() -> None:
    engine = create_engine(
        required_location=LocationName.BRG,
    )

    result = engine.run(
        (create_accession("S26-1"),)
    )

    assignment = result.assignments[0]

    assert assignment.location is LocationName.BRG
    assert assignment.method is AssignmentMethod.MANDATORY


def test_heaviest_accession_is_processed_first() -> None:
    engine = create_engine(
        olol_pathologists=2,
        brg_pathologists=1,
    )

    result = engine.run(
        (
            create_accession("S26-LIGHT", "1"),
            create_accession("S26-HEAVY", "5"),
            create_accession("S26-MEDIUM", "2"),
        )
    )

    assert result.assignments[0].accession.accession_number == (
        "S26-HEAVY"
    )


def test_preference_breaks_equal_deficit_tie() -> None:
    engine = create_engine(
        preferred_locations=(LocationName.OLOL,),
    )

    result = engine.run(
        (create_accession("S26-1"),)
    )

    assert result.assignments[0].location is LocationName.OLOL


def test_unknown_hospital_becomes_unassigned() -> None:
    engine = create_engine()

    result = engine.run(
        (
            create_accession(
                "S26-1",
                hospital="Unknown Hospital",
            ),
        )
    )

    assert result.assigned_accession_count == 0
    assert result.unassigned_accession_count == 1
    assert (
        result.unassigned_accessions[0].error_code
        == "ROUTING_ERROR"
    )


def test_no_active_eligible_location_becomes_unassigned() -> None:
    engine = create_engine(
        olol_pathologists=0,
        brg_pathologists=0,
    )

    result = engine.run(
        (create_accession("S26-1"),)
    )

    assert result.assigned_accession_count == 0
    assert result.unassigned_accession_count == 1
    assert (
        result.unassigned_accessions[0].error_code
        == "NO_ELIGIBLE_LOCATION"
    )


def test_duplicate_accessions_are_rejected() -> None:
    engine = create_engine()

    accession = create_accession("S26-1")

    with pytest.raises(
        DuplicateAccessionError,
        match="S26-1",
    ):
        engine.run((accession, accession))


def test_location_summary_calculates_weight_per_pathologist() -> None:
    engine = create_engine(
        olol_pathologists=2,
        brg_pathologists=1,
    )

    result = engine.run(
        (
            create_accession("S26-1"),
            create_accession("S26-2"),
            create_accession("S26-3"),
        )
    )

    olol_summary = result.summary_for(LocationName.OLOL)

    assert olol_summary.weight_per_pathologist == Decimal("1")
    assert olol_summary.accession_count == 2


def test_run_result_reports_total_weights() -> None:
    engine = create_engine()

    result = engine.run(
        (
            create_accession("S26-1", "2.5"),
            create_accession("S26-2", "1.5"),
        )
    )

    assert result.total_assigned_weight == Decimal("4.0")
    assert result.total_unassigned_weight == Decimal("0")


def test_assignment_is_deterministic_regardless_of_input_order() -> None:
    engine = create_engine(
        olol_pathologists=2,
        brg_pathologists=1,
    )

    accessions = (
        create_accession("S26-1", "3"),
        create_accession("S26-2", "2"),
        create_accession("S26-3", "1"),
    )

    forward_result = engine.run(accessions)
    reverse_result = engine.run(reversed(accessions))

    forward_assignments = {
        item.accession.accession_number: item.location
        for item in forward_result.assignments
    }
    reverse_assignments = {
        item.accession.accession_number: item.location
        for item in reverse_result.assignments
    }

    assert forward_assignments == reverse_assignments