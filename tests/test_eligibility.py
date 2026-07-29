"""Tests for accession-location eligibility calculations."""

from decimal import Decimal

import pytest

from pgl_sorting_engine import (
    Accession,
    CaseTypeRule,
    DailyLocationStaffing,
    DailySortingContext,
    EligibilityService,
    HospitalRoutingRule,
    LocationName,
    Pathologist,
    PrefixRoutingRule,
    RoutingConflictError,
    RoutingRuleSet,
    SubspecialtyRequirement,
)


def build_staffing_context() -> DailySortingContext:
    """Create a representative daily staffing context."""
    pathologists = (
        Pathologist(
            pathologist_id="JS",
            display_name="Dr. Smith",
            subspecialties=frozenset({"GI"}),
        ),
        Pathologist(
            pathologist_id="AB",
            display_name="Dr. Brown",
            subspecialties=frozenset({"BREAST"}),
        ),
        Pathologist(
            pathologist_id="CD",
            display_name="Dr. Davis",
            subspecialties=frozenset({"GU"}),
        ),
        Pathologist(
            pathologist_id="EF",
            display_name="Dr. Evans",
            subspecialties=frozenset(),
        ),
    )

    staffing = (
        DailyLocationStaffing(
            location=LocationName.OLOL,
            pathologist_ids=("JS",),
        ),
        DailyLocationStaffing(
            location=LocationName.BRG,
            pathologist_ids=("AB",),
        ),
        DailyLocationStaffing(
            location=LocationName.MET,
            pathologist_ids=("EF",),
        ),
        DailyLocationStaffing(
            location=LocationName.OMEGA,
            pathologist_ids=("CD",),
        ),
    )

    return DailySortingContext(
        pathologists=pathologists,
        staffing=staffing,
    )


def build_service(
    *,
    case_rule: CaseTypeRule | None = None,
    prefix_rule: PrefixRoutingRule | None = None,
    hospital_rule: HospitalRoutingRule | None = None,
) -> EligibilityService:
    """Create an eligibility service with representative rules."""
    selected_case_rule = case_rule or CaseTypeRule(
        case_type="GI",
        subspecialty="GI",
        requirement=SubspecialtyRequirement.REQUIRED,
    )

    selected_prefix_rule = prefix_rule or PrefixRoutingRule(
        prefix="AB",
        allowed_locations=frozenset(
            {
                LocationName.OLOL,
                LocationName.BRG,
                LocationName.MET,
            }
        ),
    )

    selected_hospital_rule = hospital_rule or HospitalRoutingRule(
        hospital="Hospital A",
        allowed_locations=frozenset(
            {
                LocationName.OLOL,
                LocationName.BRG,
                LocationName.MET,
            }
        ),
    )

    rule_set = RoutingRuleSet(
        case_type_rules=(selected_case_rule,),
        prefix_rules=(selected_prefix_rule,),
        hospital_rules=(selected_hospital_rule,),
    )

    return EligibilityService(
        rules=rule_set,
        staffing_context=build_staffing_context(),
    )


def build_accession(
    *,
    hospital: str = "Hospital A",
    prefix: str = "AB",
    case_type: str = "GI",
) -> Accession:
    """Create an accession for eligibility tests."""
    return Accession(
        accession_number="S26-12345",
        prefix=prefix,
        case_type=case_type,
        hospital=hospital,
        weight=Decimal("2.5"),
    )


def test_required_subspecialty_filters_locations() -> None:
    service = build_service()

    result = service.evaluate(build_accession())

    assert result.eligible_locations == frozenset(
        {
            LocationName.OLOL,
        }
    )
    assert result.is_assignable is True
    assert result.subspecialty == "GI"


def test_inactive_location_is_excluded() -> None:
    service = build_service(
        case_rule=CaseTypeRule(
            case_type="GC",
            subspecialty=None,
            requirement=SubspecialtyRequirement.NOT_REQUIRED,
        )
    )

    accession = build_accession(case_type="GC")
    result = service.evaluate(accession)

    assert LocationName.TEX not in result.eligible_locations
    assert result.reasons_for_exclusion(LocationName.TEX) == (
        "Hospital HOSPITAL A does not allow TEX.",
        "Prefix AB does not allow TEX.",
        "No pathologists are staffed at TEX.",
    )


def test_preferred_subspecialty_does_not_exclude_locations() -> None:
    service = build_service(
        case_rule=CaseTypeRule(
            case_type="GI",
            subspecialty="GI",
            requirement=SubspecialtyRequirement.PREFERRED,
        )
    )

    result = service.evaluate(build_accession())

    assert result.eligible_locations == frozenset(
        {
            LocationName.OLOL,
            LocationName.BRG,
            LocationName.MET,
        }
    )
    assert result.preferred_locations == (LocationName.OLOL,)


def test_prefix_preference_is_preserved() -> None:
    service = build_service(
        case_rule=CaseTypeRule(
            case_type="GC",
            subspecialty=None,
            requirement=SubspecialtyRequirement.NOT_REQUIRED,
        ),
        prefix_rule=PrefixRoutingRule(
            prefix="AB",
            allowed_locations=frozenset(
                {
                    LocationName.OLOL,
                    LocationName.BRG,
                    LocationName.MET,
                }
            ),
            preferred_locations=(
                LocationName.MET,
                LocationName.BRG,
            ),
        ),
    )

    result = service.evaluate(
        build_accession(case_type="GC")
    )

    assert result.preferred_locations == (
        LocationName.MET,
        LocationName.BRG,
    )


def test_omega_hospital_is_mandatory_to_omega() -> None:
    service = build_service(
        hospital_rule=HospitalRoutingRule(
            hospital="Omega Hospital",
            allowed_locations=frozenset({LocationName.OMEGA}),
            required_location=LocationName.OMEGA,
        ),
        prefix_rule=PrefixRoutingRule(
            prefix="AB",
            allowed_locations=frozenset(
                {
                    LocationName.OLOL,
                    LocationName.OMEGA,
                }
            ),
        ),
        case_rule=CaseTypeRule(
            case_type="GC",
            subspecialty=None,
            requirement=SubspecialtyRequirement.NOT_REQUIRED,
        ),
    )

    result = service.evaluate(
        build_accession(
            hospital="Omega Hospital",
            case_type="GC",
        )
    )

    assert result.eligible_locations == frozenset(
        {LocationName.OMEGA}
    )
    assert result.required_location is LocationName.OMEGA
    assert result.is_mandatory is True


def test_mandatory_location_may_be_operationally_unavailable() -> None:
    service = build_service(
        hospital_rule=HospitalRoutingRule(
            hospital="Hospital A",
            allowed_locations=frozenset({LocationName.TEX}),
            required_location=LocationName.TEX,
        ),
        prefix_rule=PrefixRoutingRule(
            prefix="AB",
            allowed_locations=frozenset({LocationName.TEX}),
        ),
        case_rule=CaseTypeRule(
            case_type="GC",
            subspecialty=None,
            requirement=SubspecialtyRequirement.NOT_REQUIRED,
        ),
    )

    result = service.evaluate(
        build_accession(case_type="GC")
    )

    assert result.eligible_locations == frozenset()
    assert result.is_assignable is False
    assert result.reasons_for_exclusion(LocationName.TEX) == (
        "No pathologists are staffed at TEX.",
    )


def test_conflicting_required_locations_raise_error() -> None:
    service = build_service(
        hospital_rule=HospitalRoutingRule(
            hospital="Hospital A",
            allowed_locations=frozenset(
                {
                    LocationName.OLOL,
                    LocationName.BRG,
                }
            ),
            required_location=LocationName.OLOL,
        ),
        prefix_rule=PrefixRoutingRule(
            prefix="AB",
            allowed_locations=frozenset(
                {
                    LocationName.OLOL,
                    LocationName.BRG,
                }
            ),
            required_location=LocationName.BRG,
        ),
    )

    with pytest.raises(
        RoutingConflictError,
        match="conflicting mandatory destinations",
    ):
        service.evaluate(build_accession())


def test_required_location_must_be_allowed_by_both_rules() -> None:
    service = build_service(
        hospital_rule=HospitalRoutingRule(
            hospital="Hospital A",
            allowed_locations=frozenset({LocationName.OMEGA}),
            required_location=LocationName.OMEGA,
        ),
        prefix_rule=PrefixRoutingRule(
            prefix="AB",
            allowed_locations=frozenset({LocationName.OLOL}),
        ),
    )

    with pytest.raises(
        RoutingConflictError,
        match="prefix AB does not allow",
    ):
        service.evaluate(build_accession())


def test_result_preserves_audit_notes() -> None:
    service = build_service()

    result = service.evaluate(build_accession())

    assert any(
        "Hospital HOSPITAL A allows" in note
        for note in result.decision_notes
    )
    assert any(
        "Associated subspecialty: GI" in note
        for note in result.decision_notes
    )