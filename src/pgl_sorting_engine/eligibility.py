"""Determine which locations are eligible to receive an accession."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pgl_sorting_engine.enums import (
    LocationName,
    RoutingOverrideMode,
    SubspecialtyRequirement,
)
from pgl_sorting_engine.exceptions import RoutingConflictError
from pgl_sorting_engine.models import Accession, HospitalRoutingRule
from pgl_sorting_engine.rules import (
    CaseTypeRule,
    PrefixRoutingRule,
    RoutingOverrideRule,
    RoutingRuleSet,
)
from pgl_sorting_engine.staffing import DailySortingContext


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """Result of evaluating one accession against the routing rules."""

    accession: Accession
    eligible_locations: frozenset[LocationName]
    preferred_locations: tuple[LocationName, ...]
    required_location: LocationName | None
    subspecialty: str | None
    subspecialty_requirement: SubspecialtyRequirement
    exclusion_reasons: Mapping[LocationName, tuple[str, ...]]
    decision_notes: tuple[str, ...]
    override_rule: RoutingOverrideRule | None = None
    override_activated: bool = False
    preferred_until_target_location: LocationName | None = None
    preferred_until_weight_cap_location: LocationName | None = None
    override_notes: tuple[str, ...] = ()

    @property
    def is_assignable(self) -> bool:
        """Return whether at least one eligible destination exists."""
        return bool(self.eligible_locations)

    @property
    def is_mandatory(self) -> bool:
        """Return whether the accession has a mandatory destination."""
        return self.required_location is not None

    @property
    def matched_override(self) -> bool:
        """Return whether a configurable override matched the accession."""
        return self.override_rule is not None

    def reasons_for_exclusion(
        self,
        location: LocationName,
    ) -> tuple[str, ...]:
        """Return all reasons a location was excluded."""
        return self.exclusion_reasons.get(LocationName(location), ())


@dataclass(frozen=True, slots=True)
class _OverrideEvaluation:
    """Internal interpretation of a matched routing override."""

    rule: RoutingOverrideRule | None
    required_location: LocationName | None = None
    preferred_locations: tuple[LocationName, ...] = ()
    preferred_until_target_location: LocationName | None = None
    preferred_until_weight_cap_location: LocationName | None = None
    activated: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EligibilityService:
    """Evaluate accessions using routing rules and today's staffing."""

    rules: RoutingRuleSet
    staffing_context: DailySortingContext

    def evaluate(self, accession: Accession) -> EligibilityResult:
        """Calculate all eligible and preferred locations."""
        hospital_rule = self.rules.get_hospital_rule(accession.hospital)
        prefix_rule = self.rules.get_prefix_rule(accession.prefix)
        case_type_rule = self.rules.get_case_type_rule(accession.case_type)
        override_rule = self.rules.find_override_rule(
            hospital=accession.hospital,
            prefix=accession.prefix,
            case_type=accession.case_type,
        )
        override = self._evaluate_override(
            rule=override_rule,
            case_type_rule=case_type_rule,
        )

        required_location = self._resolve_required_location(
            accession=accession,
            hospital_rule=hospital_rule,
            prefix_rule=prefix_rule,
            override_required=override.required_location,
            override_rule=override.rule,
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

        override_preferences = tuple(
            location
            for location in override.preferred_locations
            if location in eligible_locations
        )
        soft_target = override.preferred_until_target_location
        soft_weight_cap = override.preferred_until_weight_cap_location
        override_notes = list(override.notes)
        override_activated = override.activated

        if soft_target is not None and soft_target not in eligible_locations:
            override_notes.append(
                f"Configured destination {soft_target.value} was not eligible; "
                "the accession will use routine distribution."
            )
            soft_target = None
            override_activated = False

        if (
            soft_weight_cap is not None
            and soft_weight_cap not in eligible_locations
        ):
            override_notes.append(
                f"Configured destination {soft_weight_cap.value} was not "
                "eligible; the accession will use routine distribution."
            )
            soft_weight_cap = None
            override_activated = False

        if (
            override.rule is not None
            and override.rule.mode is RoutingOverrideMode.PREFERRED
        ):
            override_activated = bool(override_preferences)
            if not override_preferences:
                override_notes.append(
                    "None of the configured preferred locations were eligible; "
                    "the accession will use routine distribution."
                )

        preferred_locations = self._calculate_preferences(
            eligible_locations=eligible_locations,
            prefix_rule=prefix_rule,
            case_type_rule=case_type_rule,
            required_location=required_location,
            override_preferences=override_preferences,
        )

        decision_notes = self._build_decision_notes(
            accession=accession,
            hospital_rule=hospital_rule,
            prefix_rule=prefix_rule,
            case_type_rule=case_type_rule,
            required_location=required_location,
            override_rule=override.rule,
            override_notes=tuple(override_notes),
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
            override_rule=override.rule,
            override_activated=override_activated,
            preferred_until_target_location=soft_target,
            preferred_until_weight_cap_location=soft_weight_cap,
            override_notes=tuple(override_notes),
        )

    def _evaluate_override(
        self,
        rule: RoutingOverrideRule | None,
        case_type_rule: CaseTypeRule,
    ) -> _OverrideEvaluation:
        if rule is None:
            return _OverrideEvaluation(rule=None)

        matched = (
            f"Matched routing override {rule.rule_name!r} "
            f"({rule.mode.value})."
        )

        if rule.mode is RoutingOverrideMode.IDENTIFY_ONLY:
            return _OverrideEvaluation(
                rule=rule,
                notes=(
                    matched,
                    "The rule identifies the accession but does not alter routing.",
                ),
            )

        if rule.mode is RoutingOverrideMode.ALWAYS_REQUIRED:
            destination = rule.destination_location
            if destination is None:
                raise RuntimeError(
                    "Validated required routing rule has no destination."
                )
            return _OverrideEvaluation(
                rule=rule,
                required_location=destination,
                activated=True,
                notes=(
                    matched,
                    f"The rule requires {destination.value}.",
                ),
            )

        if (
            rule.mode
            is RoutingOverrideMode.REQUIRED_IF_SUBSPECIALIST_PRESENT
        ):
            destination = rule.destination_location
            subspecialty = (
                rule.required_subspecialty
                or case_type_rule.subspecialty
            )
            if destination is None or subspecialty is None:
                raise RuntimeError(
                    "Validated conditional routing rule is incomplete."
                )

            capability = self.staffing_context.get_location_capability(
                destination
            )
            if capability.has_subspecialty(subspecialty):
                return _OverrideEvaluation(
                    rule=rule,
                    required_location=destination,
                    activated=True,
                    notes=(
                        matched,
                        f"{destination.value} has {subspecialty} coverage, "
                        "so the conditional requirement was activated.",
                    ),
                )

            return _OverrideEvaluation(
                rule=rule,
                notes=(
                    matched,
                    f"{destination.value} does not have {subspecialty} "
                    "coverage, so the conditional requirement was not "
                    "activated and routine routing applies.",
                ),
            )

        if rule.mode is RoutingOverrideMode.PREFERRED:
            return _OverrideEvaluation(
                rule=rule,
                preferred_locations=rule.preferred_locations,
                notes=(
                    matched,
                    "Eligible configured locations will be used as ordered "
                    "preferences during routine balancing.",
                ),
            )

        if rule.mode is RoutingOverrideMode.PREFERRED_UNTIL_TARGET:
            destination = rule.destination_location
            if destination is None:
                raise RuntimeError(
                    "Validated until-target routing rule has no destination."
                )
            return _OverrideEvaluation(
                rule=rule,
                preferred_until_target_location=destination,
                activated=True,
                notes=(
                    matched,
                    f"{destination.value} will receive the case while its "
                    "pre-assignment workload is below target; the final case "
                    "may cross the target.",
                ),
            )

        if rule.mode is RoutingOverrideMode.PREFERRED_UNTIL_WEIGHT_CAP:
            destination = rule.destination_location
            weight_cap = rule.weight_cap
            if destination is None or weight_cap is None:
                raise RuntimeError(
                    "Validated until-weight-cap routing rule is incomplete."
                )
            return _OverrideEvaluation(
                rule=rule,
                preferred_until_weight_cap_location=destination,
                activated=True,
                notes=(
                    matched,
                    f"{destination.value} will receive matching cases while "
                    f"their cumulative assigned weight remains at or below "
                    f"the configured cap of {weight_cap}.",
                ),
            )

        raise RuntimeError(f"Unsupported routing override mode: {rule.mode}.")

    def _resolve_required_location(
        self,
        accession: Accession,
        hospital_rule: HospitalRoutingRule,
        prefix_rule: PrefixRoutingRule,
        override_required: LocationName | None,
        override_rule: RoutingOverrideRule | None,
    ) -> LocationName | None:
        """Resolve hospital, prefix, and override mandatory destinations."""
        requirements: list[tuple[str, LocationName]] = []

        if hospital_rule.required_location is not None:
            requirements.append(
                (f"hospital {hospital_rule.hospital}", hospital_rule.required_location)
            )
        if prefix_rule.required_location is not None:
            requirements.append(
                (f"prefix {prefix_rule.prefix}", prefix_rule.required_location)
            )
        if override_required is not None:
            name = override_rule.rule_name if override_rule else "override"
            requirements.append((f"routing override {name}", override_required))

        unique_destinations = {destination for _, destination in requirements}
        if len(unique_destinations) > 1:
            description = ", while ".join(
                f"{source} requires {destination.value}"
                for source, destination in requirements
            )
            raise RoutingConflictError(
                f"Accession {accession.accession_number} has conflicting "
                f"mandatory destinations: {description}."
            )

        required_location = (
            requirements[0][1] if requirements else None
        )
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
        reasons: list[str] = []

        if required_location is not None and location != required_location:
            reasons.append(
                f"A mandatory routing rule requires {required_location.value}."
            )
        if location not in hospital_rule.allowed_locations:
            reasons.append(
                f"Hospital {hospital_rule.hospital} does not allow "
                f"{location.value}."
            )
        if location not in prefix_rule.allowed_locations:
            reasons.append(
                f"Prefix {prefix_rule.prefix} does not allow {location.value}."
            )

        capability = self.staffing_context.get_location_capability(location)
        if not capability.is_active:
            reasons.append(
                f"No pathologists are staffed at {location.value}."
            )
        if (
            case_type_rule.requirement
            is SubspecialtyRequirement.REQUIRED
            and case_type_rule.subspecialty is not None
            and not capability.has_subspecialty(case_type_rule.subspecialty)
        ):
            reasons.append(
                f"Required subspecialty {case_type_rule.subspecialty} is "
                f"unavailable at {location.value}."
            )
        return reasons

    def _calculate_preferences(
        self,
        eligible_locations: set[LocationName],
        prefix_rule: PrefixRoutingRule,
        case_type_rule: CaseTypeRule,
        required_location: LocationName | None,
        override_preferences: tuple[LocationName, ...],
    ) -> tuple[LocationName, ...]:
        if required_location is not None:
            return ()

        preferred: list[LocationName] = []
        for location in (*override_preferences, *prefix_rule.preferred_locations):
            if location in eligible_locations and location not in preferred:
                preferred.append(location)

        if (
            case_type_rule.requirement
            is SubspecialtyRequirement.PREFERRED
            and case_type_rule.subspecialty is not None
        ):
            for location in LocationName:
                if location not in eligible_locations:
                    continue
                capability = self.staffing_context.get_location_capability(
                    location
                )
                if (
                    capability.has_subspecialty(case_type_rule.subspecialty)
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
        override_rule: RoutingOverrideRule | None,
        override_notes: tuple[str, ...],
    ) -> tuple[str, ...]:
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
            f"Hospital {hospital_rule.hospital} allows: {hospital_locations}.",
            f"Prefix {prefix_rule.prefix} allows: {prefix_locations}.",
            (
                f"Case type {accession.case_type} has subspecialty "
                f"requirement {case_type_rule.requirement.value}."
            ),
        ]
        if case_type_rule.subspecialty is not None:
            notes.append(
                f"Associated subspecialty: {case_type_rule.subspecialty}."
            )
        if override_rule is not None:
            notes.extend(override_notes)
        if required_location is not None:
            notes.append(
                f"Mandatory destination: {required_location.value}."
            )
        return tuple(notes)
