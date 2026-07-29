"""Enumerated values used by the PGL Sorting Engine."""

from enum import StrEnum


class LocationName(StrEnum):
    """A location to which pathology accessions may be assigned."""

    OLOL = "OLOL"
    BRG = "BRG"
    MET = "MET"
    TEX = "TEX"
    OMEGA = "OMEGA"

class SubspecialtyRequirement(StrEnum):
    """Describe how subspecialty coverage affects case routing."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    NOT_REQUIRED = "not_required"