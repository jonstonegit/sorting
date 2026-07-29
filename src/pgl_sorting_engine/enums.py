"""Enumerated values used by the PGL Sorting Engine."""

from enum import StrEnum


class LocationName(StrEnum):
    """A location to which pathology accessions may be assigned."""

    OLOL = "OLOL"
    BRG = "BRG"
    MET = "MET"
    TEX = "TEX"
    OMEGA = "OMEGA"