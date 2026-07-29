"""Determine which locations are eligible to receive an accession."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pgl_sorting_engine.enums import (
    LocationName,
    SubspecialtyRequirement,
)
from pgl_sorting_engine.exceptions import RoutingConflictError
from pgl_sorting_engine.models import (
    Accession,
    HospitalRoutingRule,
)
from pgl_sorting_engine.rules import (
    CaseTypeRule,
    PrefixRoutingRule,
    RoutingRuleSet,
)
from pgl_sorting_engine.staffing import DailySortingContext


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """
    Result of evaluating one accession against the routing rules.

    Attributes:
        accession: Accession being evaluated.
        eligible_locations: Locations that may receive the accession.
        preferred_locations: Eligible locations that should be considered
            first during workload balancing.
        required_location: Mandatory destination, when one exists.
        subspecialty: Subspecialty associated with the case type.
        subspecialty_requirement: Whether coverage is required or preferred.
        exclusion_reasons: Reasons each ineligible location was excluded.
        decision_notes: General notes describing the evaluation.
    """

    accession: Accession
    eligible_locations: frozenset[LocationName]
    preferred_locations: tuple[LocationName, ...]
    required_location: LocationName | None
    subspecialty: str | None
    subspecialty_requirement: SubspecialtyRequirement
    exclusion_reasons: Mapping[LocationName, tuple[str, ...]]
    decision_notes: tuple[str, ...]

    @property
    def is_assignable(self) -> bool:
        """Return whether at least one eligible destination exists."""
        return bool(self.eligible_locations)

    @property
    def is_mandatory(self) -> bool:
        """Return whether the accession has a mandatory destination."""
        return self.required_location is not None

    def reasons_for_exclusion(
        self,
        location: LocationName,
    ) -> tuple[str, ...]:
        """Return all reasons a location was excluded."""
        return self.exclusion_reasons.get(LocationName(location), ())


@dataclass(frozen=True, slots=True)
class EligibilityService:
    """
    Evaluate accessions using routing rules and today's staffing context.

    This service determines valid destinations only. It does not perform
    workload balancing or make the final assignment among multiple eligible
    locations.
    """

    rules: RoutingRuleSet
    staffing_context: DailySortingContext

    def evaluate(self, accession: Accession) -> EligibilityResult:
        """Calculate all eligible and preferred locations for an accession."""
        hospital_rule = self.rules.get_hospital_rule(accession.hospital)
        prefix_rule = self.rules.get_prefix_rule(accession.prefix)
        case_type_rule = self.rules.get_case_type_rule(
            accession.case_type
        )

        required_location = self._resolve_required_location(
            accession=accession,
            hospital_rule=hospital_rule,
            prefix_rule=prefix_rule,
        )

        exclusion_reasons: dict[LocationName, tuple[str, ...]] = {}
        eligible_locations: set[LocationName] = set()

        for location in LocationName:
            reasons = self._evaluate_location(
                location=location,
                hospital_rule=hospital_rule,
                prefix_rule=prefix_rule,
                case_type_rule=case_type_rule,
                required_location=required_location,
            )

            if reasons:
                exclusion_reasons[location] = tuple(reasons)
            else:
                eligible_locations.add(location)

        preferred_locations = self._calculate_preferences(
            eligible_locations=eligible_locations,
            prefix_rule=prefix_rule,
            case_type_rule=case_type_rule,
            required_location=required_location,
        )

        decision_notes = self._build_decision_notes(
            accession=accession,
            hospital_rule=hospital_rule,
            prefix_rule=prefix_rule,
            case_type_rule=case_type_rule,
            required_location=required_location,
        )

        return EligibilityResult(
            accession=accession,
            eligible_locations=frozenset(eligible_locations),
            preferred_locations=preferred_locations,
            required_location=required_location,
            subspecialty=case_type_rule.subspecialty,
            subspecialty_requirement=case_type_rule.requirement,
            exclusion_reasons=MappingProxyType(exclusion_reasons),
            decision_notes=decision_notes,
        )

    def _resolve_required_location(
        self,
        accession: Accession,
        hospital_rule: HospitalRoutingRule,
        prefix_rule: PrefixRoutingRule,
    ) -> LocationName | None:
        """
        Resolve mandatory hospital and prefix destinations.

        Raises:
            RoutingConflictError: If the hospital and prefix require
                different locations, or if a mandatory destination is
                prohibited by another applicable rule.
        """
        hospital_required = hospital_rule.required_location
        prefix_required = prefix_rule.required_location

        if (
            hospital_required is not None
            and prefix_required is not None
            and hospital_required != prefix_required
        ):
            raise RoutingConflictError(
                f"Accession {accession.accession_number} has conflicting "
                f"mandatory destinations: hospital "
                f"{hospital_rule.hospital} requires "
                f"{hospital_required.value}, while prefix "
                f"{prefix_rule.prefix} requires {prefix_required.value}."
            )

        required_location = hospital_required or prefix_required

        if required_location is None:
            return None

        if required_location not in hospital_rule.allowed_locations:
            raise RoutingConflictError(
                f"Accession {accession.accession_number} is required to go "
                f"to {required_location.value}, but hospital "
                f"{hospital_rule.hospital} does not allow that location."
            )

        if required_location not in prefix_rule.allowed_locations:
            raise RoutingConflictError(
                f"Accession {accession.accession_number} is required to go "
                f"to {required_location.value}, but prefix "
                f"{prefix_rule.prefix} does not allow that location."
            )

        return required_location

    def _evaluate_location(
        self,
        location: LocationName,
        hospital_rule: HospitalRoutingRule,
        prefix_rule: PrefixRoutingRule,
        case_type_rule: CaseTypeRule,
        required_location: LocationName | None,
    ) -> list[str]:
        """Return all reasons a location cannot receive the accession."""
        reasons: list[str] = []

        if (
            required_location is not None
            and location != required_location
        ):
            reasons.append(
                f"A mandatory routing rule requires "
                f"{required_location.value}."
            )

        if location not in hospital_rule.allowed_locations:
            reasons.append(
                f"Hospital {hospital_rule.hospital} does not allow "
                f"{location.value}."
            )

        if location not in prefix_rule.allowed_locations:
            reasons.append(
                f"Prefix {prefix_rule.prefix} does not allow "
                f"{location.value}."
            )

        capability = self.staffing_context.get_location_capability(
            location
        )

        if not capability.is_active:
            reasons.append(
                f"No pathologists are staffed at {location.value}."
            )

        if (
            case_type_rule.requirement
            is SubspecialtyRequirement.REQUIRED
            and case_type_rule.subspecialty is not None
            and not capability.has_subspecialty(
                case_type_rule.subspecialty
            )
        ):
            reasons.append(
                f"Required subspecialty "
                f"{case_type_rule.subspecialty} is unavailable at "
                f"{location.value}."
            )

        return reasons

    def _calculate_preferences(
        self,
        eligible_locations: set[LocationName],
        prefix_rule: PrefixRoutingRule,
        case_type_rule: CaseTypeRule,
        required_location: LocationName | None,
    ) -> tuple[LocationName, ...]:
        """Calculate an ordered list of preferred eligible locations."""
        if required_location is not None:
            return ()

        preferred: list[LocationName] = []

        for location in prefix_rule.preferred_locations:
            if (
                location in eligible_locations
                and location not in preferred
            ):
                preferred.append(location)

        if (
            case_type_rule.requirement
            is SubspecialtyRequirement.PREFERRED
            and case_type_rule.subspecialty is not None
        ):
            for location in LocationName:
                if location not in eligible_locations:
                    continue

                capability = (
                    self.staffing_context.get_location_capability(
                        location
                    )
                )

                if (
                    capability.has_subspecialty(
                        case_type_rule.subspecialty
                    )
                    and location not in preferred
                ):
                    preferred.append(location)

        return tuple(preferred)

    def _build_decision_notes(
        self,
        accession: Accession,
        hospital_rule: HospitalRoutingRule,
        prefix_rule: PrefixRoutingRule,
        case_type_rule: CaseTypeRule,
        required_location: LocationName | None,
    ) -> tuple[str, ...]:
        """Create general audit notes for the eligibility evaluation."""
        hospital_locations = ", ".join(
            location.value
            for location in sorted(
                hospital_rule.allowed_locations,
                key=lambda item: item.value,
            )
        )

        prefix_locations = ", ".join(
            location.value
            for location in sorted(
                prefix_rule.allowed_locations,
                key=lambda item: item.value,
            )
        )

        notes = [
            (
                f"Hospital {hospital_rule.hospital} allows: "
                f"{hospital_locations}."
            ),
            (
                f"Prefix {prefix_rule.prefix} allows: "
                f"{prefix_locations}."
            ),
            (
                f"Case type {accession.case_type} has subspecialty "
                f"requirement {case_type_rule.requirement.value}."
            ),
        ]

        if case_type_rule.subspecialty is not None:
            notes.append(
                f"Associated subspecialty: "
                f"{case_type_rule.subspecialty}."
            )

        if required_location is not None:
            notes.append(
                f"Mandatory destination: {required_location.value}."
            )

        return tuple(notes)