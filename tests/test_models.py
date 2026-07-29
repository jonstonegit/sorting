"""Tests for the PGL Sorting Engine domain models."""

from decimal import Decimal

import pytest

from pgl_sorting_engine import (
    Accession,
    DailyLocationStaffing,
    HospitalRoutingRule,
    LocationName,
    Pathologist,
)


def test_accession_normalizes_codes_and_hospital() -> None:
    accession = Accession(
        accession_number=" S26-12345 ",
        prefix=" ab ",
        case_type="gi",
        hospital=" Omega Hospital ",
        weight=Decimal("2.5"),
    )

    assert accession.accession_number == "S26-12345"
    assert accession.prefix == "AB"
    assert accession.case_type == "GI"
    assert accession.hospital == "OMEGA HOSPITAL"
    assert accession.weight == Decimal("2.5")


@pytest.mark.parametrize(
    "invalid_code",
    [
        "",
        "G",
        "G12",
        "G-I",
        "123",
    ],
)
def test_accession_rejects_invalid_case_type(invalid_code: str) -> None:
    with pytest.raises(ValueError, match="Case type"):
        Accession(
            accession_number="S26-12345",
            prefix="AB",
            case_type=invalid_code,
            hospital="Hospital A",
            weight=Decimal("1"),
        )


@pytest.mark.parametrize(
    "invalid_weight",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_accession_rejects_invalid_weight(invalid_weight: Decimal) -> None:
    with pytest.raises(ValueError, match="Weight"):
        Accession(
            accession_number="S26-12345",
            prefix="AB",
            case_type="GI",
            hospital="Hospital A",
            weight=invalid_weight,
        )


def test_pathologist_normalizes_subspecialties() -> None:
    pathologist = Pathologist(
        pathologist_id=" js ",
        display_name="Dr. Smith",
        subspecialties=frozenset({"gi", " breast pathology "}),
    )

    assert pathologist.pathologist_id == "JS"
    assert pathologist.subspecialties == frozenset(
        {
            "GI",
            "BREAST PATHOLOGY",
        }
    )


def test_daily_staffing_calculates_pathologist_count() -> None:
    staffing = DailyLocationStaffing(
        location=LocationName.OLOL,
        pathologist_ids=("JS", "AB"),
    )

    assert staffing.number_of_pathologists == 2
    assert staffing.is_active is True


def test_daily_staffing_rejects_duplicate_pathologists() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DailyLocationStaffing(
            location=LocationName.OLOL,
            pathologist_ids=("JS", "js"),
        )


def test_required_location_must_be_allowed() -> None:
    with pytest.raises(ValueError, match="must also be included"):
        HospitalRoutingRule(
            hospital="Omega Hospital",
            allowed_locations=frozenset({LocationName.OLOL}),
            required_location=LocationName.OMEGA,
        )


def test_omega_hospital_can_be_required_to_omega() -> None:
    rule = HospitalRoutingRule(
        hospital="Omega Hospital",
        allowed_locations=frozenset({LocationName.OMEGA}),
        required_location=LocationName.OMEGA,
    )

    assert rule.required_location == LocationName.OMEGA