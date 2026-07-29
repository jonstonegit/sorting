"""Tests for routing-rule models and lookup services."""

import pytest

from pgl_sorting_engine import (
    CaseTypeRule,
    ConfigurationError,
    DuplicateRuleError,
    LocationName,
    PrefixRoutingRule,
    RoutingRuleSet,
    SubspecialtyRequirement,
    UnknownCaseTypeError,
    UnknownPrefixError,
)


def test_case_type_rule_normalizes_values() -> None:
    rule = CaseTypeRule(
        case_type=" gi ",
        subspecialty=" gastrointestinal ",
        requirement=SubspecialtyRequirement.REQUIRED,
    )

    assert rule.case_type == "GI"
    assert rule.subspecialty == "GASTROINTESTINAL"
    assert rule.requirement is SubspecialtyRequirement.REQUIRED


def test_required_case_type_must_have_subspecialty() -> None:
    with pytest.raises(ConfigurationError, match="must specify"):
        CaseTypeRule(
            case_type="GI",
            subspecialty=None,
            requirement=SubspecialtyRequirement.REQUIRED,
        )


def test_not_required_case_type_cannot_have_subspecialty() -> None:
    with pytest.raises(ConfigurationError, match="NOT_REQUIRED"):
        CaseTypeRule(
            case_type="GC",
            subspecialty="GENERAL",
            requirement=SubspecialtyRequirement.NOT_REQUIRED,
        )


def test_prefix_rule_normalizes_prefix() -> None:
    rule = PrefixRoutingRule(
        prefix=" ab ",
        allowed_locations=frozenset(
            {
                LocationName.OLOL,
                LocationName.BRG,
            }
        ),
        preferred_locations=(LocationName.OLOL,),
    )

    assert rule.prefix == "AB"
    assert rule.allowed_locations == frozenset(
        {
            LocationName.OLOL,
            LocationName.BRG,
        }
    )
    assert rule.preferred_locations == (LocationName.OLOL,)


def test_required_prefix_location_must_be_allowed() -> None:
    with pytest.raises(ConfigurationError, match="must be allowed"):
        PrefixRoutingRule(
            prefix="OM",
            allowed_locations=frozenset({LocationName.OLOL}),
            required_location=LocationName.OMEGA,
        )


def test_preferred_prefix_locations_must_be_allowed() -> None:
    with pytest.raises(ConfigurationError, match="must also be allowed"):
        PrefixRoutingRule(
            prefix="AB",
            allowed_locations=frozenset({LocationName.OLOL}),
            preferred_locations=(LocationName.MET,),
        )


def test_prefix_cannot_be_required_and_preferred() -> None:
    with pytest.raises(ConfigurationError, match="both a required"):
        PrefixRoutingRule(
            prefix="OM",
            allowed_locations=frozenset(
                {
                    LocationName.OMEGA,
                    LocationName.OLOL,
                }
            ),
            required_location=LocationName.OMEGA,
            preferred_locations=(LocationName.OMEGA,),
        )


def test_rule_set_rejects_duplicate_case_types() -> None:
    first = CaseTypeRule(
        case_type="GI",
        subspecialty="GI",
        requirement=SubspecialtyRequirement.REQUIRED,
    )
    second = CaseTypeRule(
        case_type="gi",
        subspecialty="GASTROINTESTINAL",
        requirement=SubspecialtyRequirement.PREFERRED,
    )

    with pytest.raises(DuplicateRuleError, match="Duplicate case-type"):
        RoutingRuleSet(
            case_type_rules=(first, second),
            prefix_rules=(),
        )


def test_rule_set_rejects_duplicate_prefixes() -> None:
    first = PrefixRoutingRule(
        prefix="AB",
        allowed_locations=frozenset({LocationName.OLOL}),
    )
    second = PrefixRoutingRule(
        prefix="ab",
        allowed_locations=frozenset({LocationName.BRG}),
    )

    with pytest.raises(DuplicateRuleError, match="Duplicate prefix"):
        RoutingRuleSet(
            case_type_rules=(),
            prefix_rules=(first, second),
        )


def test_rule_set_returns_case_type_rule() -> None:
    case_rule = CaseTypeRule(
        case_type="GI",
        subspecialty="GI",
        requirement=SubspecialtyRequirement.REQUIRED,
    )

    rule_set = RoutingRuleSet(
        case_type_rules=(case_rule,),
        prefix_rules=(),
    )

    assert rule_set.get_case_type_rule("gi") is case_rule


def test_rule_set_returns_prefix_rule() -> None:
    prefix_rule = PrefixRoutingRule(
        prefix="AB",
        allowed_locations=frozenset(
            {
                LocationName.OLOL,
                LocationName.BRG,
            }
        ),
    )

    rule_set = RoutingRuleSet(
        case_type_rules=(),
        prefix_rules=(prefix_rule,),
    )

    assert rule_set.get_prefix_rule("ab") is prefix_rule


def test_unknown_case_type_raises_specific_error() -> None:
    rule_set = RoutingRuleSet(
        case_type_rules=(),
        prefix_rules=(),
    )

    with pytest.raises(UnknownCaseTypeError, match="ZZ"):
        rule_set.get_case_type_rule("ZZ")


def test_unknown_prefix_raises_specific_error() -> None:
    rule_set = RoutingRuleSet(
        case_type_rules=(),
        prefix_rules=(),
    )

    with pytest.raises(UnknownPrefixError, match="ZZ"):
        rule_set.get_prefix_rule("ZZ")