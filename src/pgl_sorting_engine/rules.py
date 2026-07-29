"""Routing-rule definitions and rule lookup services."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pgl_sorting_engine.enums import (
    LocationName,
    SubspecialtyRequirement,
)
from pgl_sorting_engine.exceptions import (
    ConfigurationError,
    DuplicateRuleError,
    UnknownCaseTypeError,
    UnknownHospitalError,
    UnknownPrefixError,
)
from pgl_sorting_engine.models import HospitalRoutingRule
from pgl_sorting_engine.validation import (
    _normalize_label,
    _normalize_two_letter_code,
)


@dataclass(frozen=True, slots=True)
class CaseTypeRule:
    """
    Define the subspecialty behavior associated with a case type.

    Attributes:
        case_type: Two-letter case-type code from the LIS.
        subspecialty: Subspecialty needed or preferred for the case.
        requirement: Whether coverage is required, preferred, or unnecessary.
    """

    case_type: str
    subspecialty: str | None
    requirement: SubspecialtyRequirement

    def __post_init__(self) -> None:
        """Normalize and validate the case-type rule."""
        normalized_case_type = _normalize_two_letter_code(
            self.case_type,
            "Case type",
        )

        try:
            normalized_requirement = SubspecialtyRequirement(self.requirement)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid subspecialty requirement: {self.requirement!r}."
            ) from exc

        normalized_subspecialty: str | None

        if self.subspecialty is None:
            normalized_subspecialty = None
        else:
            normalized_subspecialty = _normalize_label(
                self.subspecialty,
                "Subspecialty",
            )

        if (
            normalized_requirement is SubspecialtyRequirement.NOT_REQUIRED
            and normalized_subspecialty is not None
        ):
            raise ConfigurationError(
                f"Case type {normalized_case_type} is marked NOT_REQUIRED "
                "but also specifies a subspecialty."
            )

        if (
            normalized_requirement is not SubspecialtyRequirement.NOT_REQUIRED
            and normalized_subspecialty is None
        ):
            raise ConfigurationError(
                f"Case type {normalized_case_type} must specify a subspecialty "
                f"when its requirement is {normalized_requirement.value!r}."
            )

        object.__setattr__(self, "case_type", normalized_case_type)
        object.__setattr__(self, "subspecialty", normalized_subspecialty)
        object.__setattr__(self, "requirement", normalized_requirement)


@dataclass(frozen=True, slots=True)
class PrefixRoutingRule:
    """
    Define which locations may receive accessions with a particular prefix.

    Attributes:
        prefix: Two-letter accession prefix.
        allowed_locations: Locations permitted to receive the prefix.
        required_location: Optional mandatory destination.
        preferred_locations: Optional ordered list of preferred destinations.
    """

    prefix: str
    allowed_locations: frozenset[LocationName]
    required_location: LocationName | None = None
    preferred_locations: tuple[LocationName, ...] = ()

    def __post_init__(self) -> None:
        """Normalize and validate the prefix-routing rule."""
        normalized_prefix = _normalize_two_letter_code(
            self.prefix,
            "Prefix",
        )

        try:
            normalized_allowed = frozenset(
                LocationName(location) for location in self.allowed_locations
            )
            normalized_required = (
                None
                if self.required_location is None
                else LocationName(self.required_location)
            )
            normalized_preferred = tuple(
                LocationName(location) for location in self.preferred_locations
            )
        except ValueError as exc:
            raise ConfigurationError(
                f"Prefix {normalized_prefix} contains an invalid location."
            ) from exc

        if not normalized_allowed:
            raise ConfigurationError(
                f"Prefix {normalized_prefix} must allow at least one location."
            )

        if (
            normalized_required is not None
            and normalized_required not in normalized_allowed
        ):
            raise ConfigurationError(
                f"Required location {normalized_required} must be allowed "
                f"for prefix {normalized_prefix}."
            )

        if len(normalized_preferred) != len(set(normalized_preferred)):
            raise ConfigurationError(
                f"Prefix {normalized_prefix} contains duplicate preferred locations."
            )

        invalid_preferences = set(normalized_preferred) - normalized_allowed

        if invalid_preferences:
            invalid_names = ", ".join(
                sorted(location.value for location in invalid_preferences)
            )
            raise ConfigurationError(
                f"Preferred locations must also be allowed for prefix "
                f"{normalized_prefix}: {invalid_names}."
            )

        if normalized_required is not None and normalized_preferred:
            raise ConfigurationError(
                f"Prefix {normalized_prefix} cannot have both a required "
                "location and preferred locations."
            )

        object.__setattr__(self, "prefix", normalized_prefix)
        object.__setattr__(self, "allowed_locations", normalized_allowed)
        object.__setattr__(self, "required_location", normalized_required)
        object.__setattr__(self, "preferred_locations", normalized_preferred)


@dataclass(frozen=True, slots=True)
class RoutingRuleSet:
    """
    Immutable collection of case-type, prefix, and hospital routing rules.

    Duplicate codes and hospital names are rejected rather than silently
    replacing an earlier rule.
    """

    case_type_rules: tuple[CaseTypeRule, ...]
    prefix_rules: tuple[PrefixRoutingRule, ...]
    hospital_rules: tuple[HospitalRoutingRule, ...] = ()

    _case_type_index: Mapping[str, CaseTypeRule] = field(
        init=False,
        repr=False,
    )
    _prefix_index: Mapping[str, PrefixRoutingRule] = field(
        init=False,
        repr=False,
    )
    _hospital_index: Mapping[str, HospitalRoutingRule] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Build immutable lookup indexes and reject duplicate rules."""
        case_type_index: dict[str, CaseTypeRule] = {}

        for case_type_rule in self.case_type_rules:
            if case_type_rule.case_type in case_type_index:
                raise DuplicateRuleError(
                    f"Duplicate case-type rule found for "
                    f"{case_type_rule.case_type}."
                )

            case_type_index[case_type_rule.case_type] = case_type_rule

        prefix_index: dict[str, PrefixRoutingRule] = {}

        for prefix_rule in self.prefix_rules:
            if prefix_rule.prefix in prefix_index:
                raise DuplicateRuleError(
                    f"Duplicate prefix rule found for {prefix_rule.prefix}."
                )

            prefix_index[prefix_rule.prefix] = prefix_rule

        hospital_index: dict[str, HospitalRoutingRule] = {}

        for hospital_rule in self.hospital_rules:
            if hospital_rule.hospital in hospital_index:
                raise DuplicateRuleError(
                    f"Duplicate hospital rule found for "
                    f"{hospital_rule.hospital}."
                )

            hospital_index[hospital_rule.hospital] = hospital_rule

        object.__setattr__(
            self,
            "_case_type_index",
            MappingProxyType(case_type_index),
        )
        object.__setattr__(
            self,
            "_prefix_index",
            MappingProxyType(prefix_index),
        )
        object.__setattr__(
            self,
            "_hospital_index",
            MappingProxyType(hospital_index),
        )

    def get_case_type_rule(self, case_type: str) -> CaseTypeRule:
        """
        Return the rule for a case type.

        Raises:
            UnknownCaseTypeError: If the code has no configured rule.
        """
        normalized_case_type = _normalize_two_letter_code(
            case_type,
            "Case type",
        )

        try:
            return self._case_type_index[normalized_case_type]
        except KeyError as exc:
            raise UnknownCaseTypeError(
                f"No routing rule is configured for case type "
                f"{normalized_case_type}."
            ) from exc

    def get_prefix_rule(self, prefix: str) -> PrefixRoutingRule:
        """
        Return the rule for an accession prefix.

        Raises:
            UnknownPrefixError: If the prefix has no configured rule.
        """
        normalized_prefix = _normalize_two_letter_code(
            prefix,
            "Prefix",
        )

        try:
            return self._prefix_index[normalized_prefix]
        except KeyError as exc:
            raise UnknownPrefixError(
                f"No routing rule is configured for prefix "
                f"{normalized_prefix}."
            ) from exc

    def get_hospital_rule(self, hospital: str) -> HospitalRoutingRule:
        """
        Return the routing rule for an originating hospital.

        Raises:
            UnknownHospitalError: If no rule exists for the hospital.
        """
        normalized_hospital = _normalize_label(
            hospital,
            "Hospital",
        )

        try:
            return self._hospital_index[normalized_hospital]
        except KeyError as exc:
            raise UnknownHospitalError(
                f"No routing rule is configured for hospital "
                f"{normalized_hospital}."
            ) from exc