"""Core domain models for the PGL Sorting Engine."""

from dataclasses import dataclass
from decimal import Decimal

from pgl_sorting_engine.enums import LocationName
from pgl_sorting_engine.validation import (
    _coerce_positive_decimal,
    _normalize_label,
    _normalize_required_text,
    _normalize_two_letter_code,
)


@dataclass(frozen=True, slots=True)
class Accession:
    """
    A pathology accession awaiting assignment to a work location.

    Attributes:
        accession_number: Unique LIS accession identifier.
        prefix: Two-letter accession prefix.
        case_type: Two-letter code that maps to a subspecialty rule.
        hospital: Hospital or facility where the case originated.
        weight: Estimated workload associated with the accession.
    """

    accession_number: str
    prefix: str
    case_type: str
    hospital: str
    weight: Decimal

    def __post_init__(self) -> None:
        """Normalize and validate the accession after initialization."""
        object.__setattr__(
            self,
            "accession_number",
            _normalize_required_text(self.accession_number, "Accession number"),
        )
        object.__setattr__(
            self,
            "prefix",
            _normalize_two_letter_code(self.prefix, "Prefix"),
        )
        object.__setattr__(
            self,
            "case_type",
            _normalize_two_letter_code(self.case_type, "Case type"),
        )
        object.__setattr__(
            self,
            "hospital",
            _normalize_label(self.hospital, "Hospital"),
        )
        object.__setattr__(
            self,
            "weight",
            _coerce_positive_decimal(self.weight, "Weight"),
        )


@dataclass(frozen=True, slots=True)
class Pathologist:
    """
    A pathologist who may be assigned to a location on a particular day.

    Subspecialties belong to the pathologist rather than permanently to a
    location. A location's daily capabilities will be derived from the
    pathologists assigned there.
    """

    pathologist_id: str
    display_name: str
    subspecialties: frozenset[str]

    def __post_init__(self) -> None:
        """Normalize and validate pathologist information."""
        normalized_id = _normalize_required_text(
            self.pathologist_id,
            "Pathologist ID",
        ).upper()

        normalized_name = _normalize_required_text(
            self.display_name,
            "Pathologist name",
        )

        normalized_subspecialties = frozenset(
            _normalize_label(subspecialty, "Subspecialty")
            for subspecialty in self.subspecialties
        )

        object.__setattr__(self, "pathologist_id", normalized_id)
        object.__setattr__(self, "display_name", normalized_name)
        object.__setattr__(
            self,
            "subspecialties",
            normalized_subspecialties,
        )


@dataclass(frozen=True, slots=True)
class DailyLocationStaffing:
    """
    The pathologists assigned to one location for a particular sorting run.

    An empty pathologist list means that the location has no capacity that day.
    """

    location: LocationName
    pathologist_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Normalize IDs and reject duplicate pathologist assignments."""
        normalized_ids = tuple(
            _normalize_required_text(pathologist_id, "Pathologist ID").upper()
            for pathologist_id in self.pathologist_ids
        )

        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError(
                f"Location {self.location} contains duplicate pathologist IDs."
            )

        object.__setattr__(self, "pathologist_ids", normalized_ids)

    @property
    def number_of_pathologists(self) -> int:
        """Return the number of pathologists assigned to the location."""
        return len(self.pathologist_ids)

    @property
    def is_active(self) -> bool:
        """Return whether the location has at least one pathologist."""
        return self.number_of_pathologists > 0


@dataclass(frozen=True, slots=True)
class HospitalRoutingRule:
    """
    Define which work locations may receive cases from an originating hospital.

    A required location represents a hard routing rule. For example, Omega
    Hospital cases may always be required to go to the OMEGA location.
    """

    hospital: str
    allowed_locations: frozenset[LocationName]
    required_location: LocationName | None = None

    def __post_init__(self) -> None:
        """Normalize the hospital and validate its location rules."""
        normalized_hospital = _normalize_label(self.hospital, "Hospital")
        normalized_locations = frozenset(self.allowed_locations)

        if not normalized_locations:
            raise ValueError(
                f"Hospital {normalized_hospital} must have at least one allowed location."
            )

        if (
            self.required_location is not None
            and self.required_location not in normalized_locations
        ):
            raise ValueError(
                f"Required location {self.required_location} must also be included "
                f"in the allowed locations for {normalized_hospital}."
            )

        object.__setattr__(self, "hospital", normalized_hospital)
        object.__setattr__(self, "allowed_locations", normalized_locations)