"""Daily staffing and location-capability calculations."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pgl_sorting_engine.enums import LocationName
from pgl_sorting_engine.exceptions import (
    DuplicatePathologistError,
    DuplicateStaffingLocationError,
    MultipleLocationAssignmentError,
    UnknownPathologistError,
)
from pgl_sorting_engine.models import DailyLocationStaffing, Pathologist
from pgl_sorting_engine.validation import (
    _normalize_label,
    _normalize_required_text,
)


@dataclass(frozen=True, slots=True)
class LocationCapability:
    """
    Describe what a location can handle during one sorting run.

    A location's capabilities are derived from the pathologists assigned
    there that day. They are not permanent properties of the location.

    Attributes:
        location: Work location being described.
        pathologist_ids: Pathologists assigned to the location.
        subspecialties: Combined subspecialties available at the location.
        providers_by_subspecialty: Pathologists providing each subspecialty.
    """

    location: LocationName
    pathologist_ids: tuple[str, ...]
    subspecialties: frozenset[str]
    providers_by_subspecialty: Mapping[str, tuple[str, ...]]

    @property
    def number_of_pathologists(self) -> int:
        """Return the number of pathologists working at this location."""
        return len(self.pathologist_ids)

    @property
    def is_active(self) -> bool:
        """Return whether the location has at least one pathologist."""
        return self.number_of_pathologists > 0

    def has_subspecialty(self, subspecialty: str) -> bool:
        """Return whether the location has the requested subspecialty."""
        normalized = _normalize_label(subspecialty, "Subspecialty")
        return normalized in self.subspecialties

    def providers_for_subspecialty(
        self,
        subspecialty: str,
    ) -> tuple[str, ...]:
        """Return pathologist IDs providing a requested subspecialty."""
        normalized = _normalize_label(subspecialty, "Subspecialty")
        return self.providers_by_subspecialty.get(normalized, ())


@dataclass(frozen=True, slots=True)
class DailySortingContext:
    """
    Validated pathologist roster and staffing configuration for one day.

    The context verifies that:

    * Every pathologist ID is unique.
    * Every location has at most one staffing record.
    * Every staffed pathologist exists in the roster.
    * A pathologist is not assigned to multiple locations.
    * Every location has a calculated daily capability.
    """

    pathologists: tuple[Pathologist, ...]
    staffing: tuple[DailyLocationStaffing, ...]

    _pathologist_index: Mapping[str, Pathologist] = field(
        init=False,
        repr=False,
    )
    _staffing_index: Mapping[LocationName, DailyLocationStaffing] = field(
        init=False,
        repr=False,
    )
    _location_capabilities: Mapping[LocationName, LocationCapability] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate staffing and calculate each location's capabilities."""
        pathologist_index = self._build_pathologist_index()
        staffing_index = self._build_staffing_index(pathologist_index)
        capabilities = self._build_location_capabilities(
            pathologist_index,
            staffing_index,
        )

        object.__setattr__(
            self,
            "_pathologist_index",
            MappingProxyType(pathologist_index),
        )
        object.__setattr__(
            self,
            "_staffing_index",
            MappingProxyType(staffing_index),
        )
        object.__setattr__(
            self,
            "_location_capabilities",
            MappingProxyType(capabilities),
        )

    def _build_pathologist_index(self) -> dict[str, Pathologist]:
        """Build a pathologist lookup and reject duplicate IDs."""
        index: dict[str, Pathologist] = {}

        for pathologist in self.pathologists:
            if pathologist.pathologist_id in index:
                raise DuplicatePathologistError(
                    f"Duplicate pathologist ID found: "
                    f"{pathologist.pathologist_id}."
                )

            index[pathologist.pathologist_id] = pathologist

        return index

    def _build_staffing_index(
        self,
        pathologist_index: Mapping[str, Pathologist],
    ) -> dict[LocationName, DailyLocationStaffing]:
        """Validate the daily schedule and build a location lookup."""
        staffing_index: dict[LocationName, DailyLocationStaffing] = {}
        pathologist_locations: dict[str, LocationName] = {}

        for staffing_record in self.staffing:
            location = staffing_record.location

            if location in staffing_index:
                raise DuplicateStaffingLocationError(
                    f"Multiple staffing records were provided for "
                    f"{location.value}."
                )

            for pathologist_id in staffing_record.pathologist_ids:
                if pathologist_id not in pathologist_index:
                    raise UnknownPathologistError(
                        f"Location {location.value} references unknown "
                        f"pathologist ID {pathologist_id}."
                    )

                previous_location = pathologist_locations.get(pathologist_id)

                if previous_location is not None:
                    raise MultipleLocationAssignmentError(
                        f"Pathologist {pathologist_id} is assigned to both "
                        f"{previous_location.value} and {location.value}."
                    )

                pathologist_locations[pathologist_id] = location

            staffing_index[location] = staffing_record

        return staffing_index

    def _build_location_capabilities(
        self,
        pathologist_index: Mapping[str, Pathologist],
        staffing_index: Mapping[LocationName, DailyLocationStaffing],
    ) -> dict[LocationName, LocationCapability]:
        """Calculate capabilities for all five locations."""
        capabilities: dict[LocationName, LocationCapability] = {}

        for location in LocationName:
            staffing_record = staffing_index.get(location)

            if staffing_record is None:
                pathologist_ids: tuple[str, ...] = ()
            else:
                pathologist_ids = staffing_record.pathologist_ids

            providers: dict[str, list[str]] = {}

            for pathologist_id in pathologist_ids:
                pathologist = pathologist_index[pathologist_id]

                for subspecialty in pathologist.subspecialties:
                    providers.setdefault(subspecialty, []).append(
                        pathologist_id
                    )

            provider_index = {
                subspecialty: tuple(pathologist_ids_for_specialty)
                for subspecialty, pathologist_ids_for_specialty
                in sorted(providers.items())
            }

            capabilities[location] = LocationCapability(
                location=location,
                pathologist_ids=pathologist_ids,
                subspecialties=frozenset(provider_index),
                providers_by_subspecialty=MappingProxyType(provider_index),
            )

        return capabilities

    def get_pathologist(self, pathologist_id: str) -> Pathologist:
        """
        Return a pathologist from the daily roster.

        Raises:
            UnknownPathologistError: If the ID is not in the roster.
        """
        normalized_id = _normalize_required_text(
            pathologist_id,
            "Pathologist ID",
        ).upper()

        try:
            return self._pathologist_index[normalized_id]
        except KeyError as exc:
            raise UnknownPathologistError(
                f"Unknown pathologist ID: {normalized_id}."
            ) from exc

    def get_location_capability(
        self,
        location: LocationName,
    ) -> LocationCapability:
        """Return the calculated capability for a location."""
        return self._location_capabilities[LocationName(location)]

    def active_locations(self) -> tuple[LocationCapability, ...]:
        """Return all locations with at least one pathologist."""
        return tuple(
            capability
            for capability in self._location_capabilities.values()
            if capability.is_active
        )

    def locations_with_subspecialty(
        self,
        subspecialty: str,
    ) -> tuple[LocationCapability, ...]:
        """Return active locations with the requested subspecialty."""
        normalized = _normalize_label(subspecialty, "Subspecialty")

        return tuple(
            capability
            for capability in self._location_capabilities.values()
            if capability.is_active
            and normalized in capability.subspecialties
        )