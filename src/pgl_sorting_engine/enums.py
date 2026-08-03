"""Enumerated values used by the PGL Sorting Engine."""

from enum import StrEnum


class LocationName(StrEnum):
    """A location to which pathology accessions may be assigned."""

    OLOL = "OLOL"
    BRG = "BRG"
    WH = "WH"
    MET = "MET"
    TEXAS = "TEXAS"
    OMEGA = "OMEGA"


class SubspecialtyRequirement(StrEnum):
    """Describe how subspecialty coverage affects case routing."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    NOT_REQUIRED = "not_required"


class AssignmentMethod(StrEnum):
    """Describe how an accession received its final location."""

    MANDATORY = "mandatory"
    WEIGHT_BALANCED = "weight_balanced"


class RoutingOverrideMode(StrEnum):
    """Describe how a configurable routing override affects a match."""

    IDENTIFY_ONLY = "identify_only"
    ALWAYS_REQUIRED = "always_required"
    REQUIRED_IF_SUBSPECIALIST_PRESENT = (
        "required_if_subspecialist_present"
    )
    PREFERRED = "preferred"
    PREFERRED_UNTIL_TARGET = "preferred_until_target"
