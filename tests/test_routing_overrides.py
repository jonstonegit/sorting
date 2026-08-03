"""Tests for configurable prefix/case-type routing overrides."""

from decimal import Decimal

from pgl_sorting_engine import (
    Accession,
    AssignmentSettings,
    CaseTypeRule,
    DailyLocationStaffing,
    DailySortingContext,
    EligibilityService,
    HospitalRoutingRule,
    LocationName,
    Pathologist,
    PrefixRoutingRule,
    RoutingOverrideMode,
    RoutingOverrideRule,
    RoutingRuleSet,
    SortingEngine,
    SubspecialtyRequirement,
)


def _pathologist(
    identifier: str,
    subspecialties: frozenset[str] = frozenset(),
) -> Pathologist:
    return Pathologist(
        pathologist_id=identifier,
        display_name=identifier,
        subspecialties=subspecialties,
    )


def _service(
    override_rules: tuple[RoutingOverrideRule, ...],
    *,
    met_subspecialties: frozenset[str] = frozenset(),
) -> EligibilityService:
    pathologists = (
        _pathologist("O1"),
        _pathologist("M1", met_subspecialties),
    )
    context = DailySortingContext(
        pathologists=pathologists,
        staffing=(
            DailyLocationStaffing(
                location=LocationName.OLOL,
                pathologist_ids=("O1",),
            ),
            DailyLocationStaffing(
                location=LocationName.MET,
                pathologist_ids=("M1",),
            ),
        ),
    )
    rules = RoutingRuleSet(
        case_type_rules=(
            CaseTypeRule(
                case_type="GI",
                subspecialty="GI",
                requirement=SubspecialtyRequirement.PREFERRED,
            ),
        ),
        prefix_rules=(
            PrefixRoutingRule(
                prefix="PG",
                allowed_locations=frozenset(
                    {LocationName.OLOL, LocationName.MET}
                ),
            ),
        ),
        hospital_rules=(
            HospitalRoutingRule(
                hospital="Lane",
                allowed_locations=frozenset(
                    {LocationName.OLOL, LocationName.MET}
                ),
            ),
            HospitalRoutingRule(
                hospital="Other Hospital",
                allowed_locations=frozenset(
                    {LocationName.OLOL, LocationName.MET}
                ),
            ),
        ),
        override_rules=override_rules,
    )
    return EligibilityService(rules=rules, staffing_context=context)


def _accession(
    number: str,
    weight: str = "1",
    hospital: str = "Lane",
) -> Accession:
    return Accession(
        accession_number=number,
        prefix="PG",
        case_type="GI",
        hospital=hospital,
        weight=Decimal(weight),
    )


def test_hospital_specific_override_precedes_general_pair_rule() -> None:
    general = RoutingOverrideRule(
        rule_name="General PG-GI",
        prefix="PG",
        case_type="GI",
        mode=RoutingOverrideMode.IDENTIFY_ONLY,
    )
    lane = RoutingOverrideRule(
        rule_name="Lane PG-GI",
        hospital="Lane",
        prefix="PG",
        case_type="GI",
        mode=RoutingOverrideMode.ALWAYS_REQUIRED,
        destination_location=LocationName.MET,
    )
    service = _service((general, lane))

    lane_result = service.evaluate(_accession("S1"))
    other_result = service.evaluate(
        _accession("S2", hospital="Other Hospital")
    )

    assert lane_result.override_rule is lane
    assert lane_result.required_location is LocationName.MET
    assert other_result.override_rule is general
    assert other_result.required_location is None


def test_conditional_requirement_activates_only_with_specialist() -> None:
    rule = RoutingOverrideRule(
        rule_name="PG-GI to MET with GI",
        prefix="PG",
        case_type="GI",
        mode=RoutingOverrideMode.REQUIRED_IF_SUBSPECIALIST_PRESENT,
        destination_location=LocationName.MET,
        required_subspecialty="GI",
    )

    with_specialist = _service(
        (rule,),
        met_subspecialties=frozenset({"GI"}),
    ).evaluate(_accession("S1"))
    without_specialist = _service((rule,)).evaluate(_accession("S2"))

    assert with_specialist.required_location is LocationName.MET
    assert with_specialist.override_activated is True
    assert without_specialist.required_location is None
    assert without_specialist.override_activated is False


def test_preferred_rule_adds_ordered_eligible_preferences() -> None:
    rule = RoutingOverrideRule(
        rule_name="Prefer MET then OLOL",
        prefix="PG",
        case_type="GI",
        mode=RoutingOverrideMode.PREFERRED,
        preferred_locations=(LocationName.MET, LocationName.OLOL),
    )
    result = _service((rule,)).evaluate(_accession("S1"))

    assert result.preferred_locations[:2] == (
        LocationName.MET,
        LocationName.OLOL,
    )
    assert result.override_activated is True


def test_preferred_until_target_allows_one_case_overshoot_then_stops() -> None:
    rule = RoutingOverrideRule(
        rule_name="Lane PG-GI to MET",
        hospital="Lane",
        prefix="PG",
        case_type="GI",
        mode=RoutingOverrideMode.PREFERRED_UNTIL_TARGET,
        destination_location=LocationName.MET,
    )
    service = _service((rule,))
    engine = SortingEngine(
        eligibility_service=service,
        settings=AssignmentSettings(
            met_weight_per_pathologist=Decimal("10"),
            wh_starting_weight=Decimal("0"),
        ),
    )

    result = engine.run(
        (
            _accession("S1", "8"),
            _accession("S2", "5"),
            _accession("S3", "1"),
        )
    )
    locations = {
        assignment.accession.accession_number: assignment.location
        for assignment in result.assignments
    }

    assert locations["S1"] is LocationName.MET
    assert locations["S2"] is LocationName.MET
    assert locations["S3"] is LocationName.OLOL
    assert result.summary_for(LocationName.MET).assigned_weight == Decimal("13")
