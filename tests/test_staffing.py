"""Tests for daily staffing and location capabilities."""

import pytest

from pgl_sorting_engine import (
    DailyLocationStaffing,
    DailySortingContext,
    DuplicatePathologistError,
    DuplicateStaffingLocationError,
    LocationName,
    MultipleLocationAssignmentError,
    Pathologist,
    UnknownPathologistError,
)


def create_pathologists() -> tuple[Pathologist, ...]:
    """Return a small pathologist roster for staffing tests."""
    return (
        Pathologist(
            pathologist_id="JS",
            display_name="Dr. Smith",
            subspecialties=frozenset({"GI", "LIVER"}),
        ),
        Pathologist(
            pathologist_id="AB",
            display_name="Dr. Brown",
            subspecialties=frozenset({"BREAST", "GYN"}),
        ),
        Pathologist(
            pathologist_id="CD",
            display_name="Dr. Davis",
            subspecialties=frozenset({"GI", "GU"}),
        ),
    )


def test_context_derives_location_capabilities() -> None:
    context = DailySortingContext(
        pathologists=create_pathologists(),
        staffing=(
            DailyLocationStaffing(
                location=LocationName.OLOL,
                pathologist_ids=("JS", "AB"),
            ),
        ),
    )

    capability = context.get_location_capability(LocationName.OLOL)

    assert capability.pathologist_ids == ("JS", "AB")
    assert capability.number_of_pathologists == 2
    assert capability.is_active is True
    assert capability.subspecialties == frozenset(
        {
            "GI",
            "LIVER",
            "BREAST",
            "GYN",
        }
    )


def test_unstaffed_location_is_inactive() -> None:
    context = DailySortingContext(
        pathologists=create_pathologists(),
        staffing=(),
    )

    capability = context.get_location_capability(LocationName.MET)

    assert capability.pathologist_ids == ()
    assert capability.number_of_pathologists == 0
    assert capability.is_active is False
    assert capability.subspecialties == frozenset()


def test_capability_lists_providers_by_subspecialty() -> None:
    context = DailySortingContext(
        pathologists=create_pathologists(),
        staffing=(
            DailyLocationStaffing(
                location=LocationName.OLOL,
                pathologist_ids=("JS", "CD"),
            ),
        ),
    )

    capability = context.get_location_capability(LocationName.OLOL)

    assert capability.providers_for_subspecialty("gi") == ("JS", "CD")
    assert capability.providers_for_subspecialty("breast") == ()


def test_active_locations_returns_only_staffed_locations() -> None:
    context = DailySortingContext(
        pathologists=create_pathologists(),
        staffing=(
            DailyLocationStaffing(
                location=LocationName.OLOL,
                pathologist_ids=("JS",),
            ),
            DailyLocationStaffing(
                location=LocationName.MET,
                pathologist_ids=("AB",),
            ),
        ),
    )

    active_location_names = {
        capability.location
        for capability in context.active_locations()
    }

    assert active_location_names == {
        LocationName.OLOL,
        LocationName.MET,
    }


def test_locations_with_subspecialty_filters_locations() -> None:
    context = DailySortingContext(
        pathologists=create_pathologists(),
        staffing=(
            DailyLocationStaffing(
                location=LocationName.OLOL,
                pathologist_ids=("JS",),
            ),
            DailyLocationStaffing(
                location=LocationName.MET,
                pathologist_ids=("AB",),
            ),
            DailyLocationStaffing(
                location=LocationName.TEX,
                pathologist_ids=("CD",),
            ),
        ),
    )

    gi_locations = {
        capability.location
        for capability in context.locations_with_subspecialty("GI")
    }

    assert gi_locations == {
        LocationName.OLOL,
        LocationName.TEX,
    }


def test_duplicate_pathologist_ids_are_rejected() -> None:
    pathologists = (
        Pathologist(
            pathologist_id="JS",
            display_name="Dr. Smith",
            subspecialties=frozenset({"GI"}),
        ),
        Pathologist(
            pathologist_id="js",
            display_name="Dr. Smith Duplicate",
            subspecialties=frozenset({"BREAST"}),
        ),
    )

    with pytest.raises(DuplicatePathologistError, match="JS"):
        DailySortingContext(
            pathologists=pathologists,
            staffing=(),
        )


def test_duplicate_location_staffing_is_rejected() -> None:
    with pytest.raises(
        DuplicateStaffingLocationError,
        match="OLOL",
    ):
        DailySortingContext(
            pathologists=create_pathologists(),
            staffing=(
                DailyLocationStaffing(
                    location=LocationName.OLOL,
                    pathologist_ids=("JS",),
                ),
                DailyLocationStaffing(
                    location=LocationName.OLOL,
                    pathologist_ids=("AB",),
                ),
            ),
        )


def test_unknown_staffed_pathologist_is_rejected() -> None:
    with pytest.raises(UnknownPathologistError, match="ZZ"):
        DailySortingContext(
            pathologists=create_pathologists(),
            staffing=(
                DailyLocationStaffing(
                    location=LocationName.OLOL,
                    pathologist_ids=("ZZ",),
                ),
            ),
        )


def test_pathologist_cannot_work_at_multiple_locations() -> None:
    with pytest.raises(
        MultipleLocationAssignmentError,
        match="JS",
    ):
        DailySortingContext(
            pathologists=create_pathologists(),
            staffing=(
                DailyLocationStaffing(
                    location=LocationName.OLOL,
                    pathologist_ids=("JS",),
                ),
                DailyLocationStaffing(
                    location=LocationName.BRG,
                    pathologist_ids=("JS",),
                ),
            ),
        )


def test_get_pathologist_rejects_unknown_id() -> None:
    context = DailySortingContext(
        pathologists=create_pathologists(),
        staffing=(),
    )

    with pytest.raises(UnknownPathologistError, match="ZZ"):
        context.get_pathologist("ZZ")