"""Routing-rule definitions and rule lookup services."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pgl_sorting_engine.enums import (
    LocationName,
    RoutingOverrideMode,
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

SPECIAL_ONLY_LOCATIONS = frozenset(
    {LocationName.TEXAS, LocationName.OMEGA}
)


@dataclass(frozen=True, slots=True)
class CaseTypeRule:
    """Define the subspecialty behavior associated with a case type."""

    case_type: str
    subspecialty: str | None
    requirement: SubspecialtyRequirement

    def __post_init__(self) -> None:
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

        normalized_subspecialty = (
            None
            if self.subspecialty is None
            else _normalize_label(self.subspecialty, "Subspecialty")
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
    """Define which locations may receive a particular prefix."""

    prefix: str
    allowed_locations: frozenset[LocationName]
    required_location: LocationName | None = None
    preferred_locations: tuple[LocationName, ...] = ()

    def __post_init__(self) -> None:
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
                f"Prefix {normalized_prefix} contains duplicate preferred "
                "locations."
            )

        invalid_preferences = set(normalized_preferred) - normalized_allowed
        if invalid_preferences:
            invalid_names = ", ".join(
                sorted(location.value for location in invalid_preferences)
            )
            raise ConfigurationError(
                "Preferred locations must also be allowed for prefix "
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
class RoutingOverrideRule:
    """Configure a prefix/case-type routing override.

    ``hospital`` is optional. A hospital-specific rule takes precedence over a
    general rule for the same prefix/case-type pair.
    """

    rule_name: str
    prefix: str
    case_type: str
    mode: RoutingOverrideMode
    hospital: str | None = None
    destination_location: LocationName | None = None
    preferred_locations: tuple[LocationName, ...] = ()
    required_subspecialty: str | None = None

    def __post_init__(self) -> None:
        name = str(self.rule_name).strip()
        if not name:
            raise ConfigurationError("Routing override rule name cannot be blank.")

        prefix = _normalize_two_letter_code(self.prefix, "Prefix")
        case_type = _normalize_two_letter_code(self.case_type, "Case type")
        hospital = (
            None
            if self.hospital is None or not str(self.hospital).strip()
            else _normalize_label(self.hospital, "Hospital")
        )

        try:
            mode = RoutingOverrideMode(self.mode)
            destination = (
                None
                if self.destination_location is None
                else LocationName(self.destination_location)
            )
            preferred = tuple(
                LocationName(location) for location in self.preferred_locations
            )
        except ValueError as exc:
            raise ConfigurationError(
                f"Routing override {name!r} contains an invalid value."
            ) from exc

        subspecialty = (
            None
            if self.required_subspecialty is None
            or not str(self.required_subspecialty).strip()
            else _normalize_label(
                self.required_subspecialty,
                "Required subspecialty",
            )
        )

        if len(preferred) != len(set(preferred)):
            raise ConfigurationError(
                f"Routing override {name!r} contains duplicate preferred "
                "locations."
            )

        if destination in SPECIAL_ONLY_LOCATIONS:
            raise ConfigurationError(
                f"Routing override {name!r} cannot route to "
                f"{destination.value}; TEXAS and OMEGA are controlled by "
                "fixed application rules."
            )

        invalid_preferred = set(preferred) & SPECIAL_ONLY_LOCATIONS
        if invalid_preferred:
            names = ", ".join(
                sorted(location.value for location in invalid_preferred)
            )
            raise ConfigurationError(
                f"Routing override {name!r} cannot prefer special-only "
                f"locations: {names}."
            )

        destination_modes = {
            RoutingOverrideMode.ALWAYS_REQUIRED,
            RoutingOverrideMode.REQUIRED_IF_SUBSPECIALIST_PRESENT,
            RoutingOverrideMode.PREFERRED_UNTIL_TARGET,
        }

        if mode in destination_modes and destination is None:
            raise ConfigurationError(
                f"Routing override {name!r} requires a destination_location."
            )

        if mode not in destination_modes and destination is not None:
            raise ConfigurationError(
                f"Routing override {name!r} must leave destination_location "
                f"blank for mode {mode.value}."
            )

        if mode is RoutingOverrideMode.PREFERRED and not preferred:
            raise ConfigurationError(
                f"Routing override {name!r} requires at least one "
                "preferred location."
            )

        if mode is not RoutingOverrideMode.PREFERRED and preferred:
            raise ConfigurationError(
                f"Routing override {name!r} must leave preferred_locations "
                f"blank for mode {mode.value}."
            )

        if (
            mode is not RoutingOverrideMode.REQUIRED_IF_SUBSPECIALIST_PRESENT
            and subspecialty is not None
        ):
            raise ConfigurationError(
                f"Routing override {name!r} may specify "
                "required_subspecialty only for "
                "required_if_subspecialist_present."
            )

        object.__setattr__(self, "rule_name", name)
        object.__setattr__(self, "prefix", prefix)
        object.__setattr__(self, "case_type", case_type)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "hospital", hospital)
        object.__setattr__(self, "destination_location", destination)
        object.__setattr__(self, "preferred_locations", preferred)
        object.__setattr__(self, "required_subspecialty", subspecialty)

    @property
    def match_key(self) -> tuple[str | None, str, str]:
        """Return the normalized rule-match key."""
        return (self.hospital, self.prefix, self.case_type)


@dataclass(frozen=True, slots=True)
class RoutingRuleSet:
    """Immutable collection of all routing rules."""

    case_type_rules: tuple[CaseTypeRule, ...]
    prefix_rules: tuple[PrefixRoutingRule, ...]
    hospital_rules: tuple[HospitalRoutingRule, ...] = ()
    override_rules: tuple[RoutingOverrideRule, ...] = ()

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
    _override_index: Mapping[
        tuple[str | None, str, str],
        RoutingOverrideRule,
    ] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        case_type_index: dict[str, CaseTypeRule] = {}

        for case_type_rule in self.case_type_rules:
            if case_type_rule.case_type in case_type_index:
                raise DuplicateRuleError(
                    "Duplicate case-type rule found for "
                    f"{case_type_rule.case_type}."
                )

            case_type_index[
                case_type_rule.case_type
            ] = case_type_rule


        prefix_index: dict[str, PrefixRoutingRule] = {}

        for prefix_rule in self.prefix_rules:
            if prefix_rule.prefix in prefix_index:
                raise DuplicateRuleError(
                    "Duplicate prefix rule found for "
                    f"{prefix_rule.prefix}."
                )

            prefix_index[
                prefix_rule.prefix
            ] = prefix_rule


        hospital_index: dict[str, HospitalRoutingRule] = {}

        for hospital_rule in self.hospital_rules:
            if hospital_rule.hospital in hospital_index:
                raise DuplicateRuleError(
                    "Duplicate hospital rule found for "
                    f"{hospital_rule.hospital}."
                )

            hospital_index[
                hospital_rule.hospital
            ] = hospital_rule


        override_index: dict[
            tuple[str | None, str, str],
            RoutingOverrideRule,
        ] = {}

        for override_rule in self.override_rules:
            if override_rule.match_key in override_index:
                previous = override_index[
                    override_rule.match_key
                ]

                scope = (
                    override_rule.hospital
                    or "all hospitals"
                )

                raise DuplicateRuleError(
                    "Duplicate routing override for "
                    f"{scope}, "
                    f"{override_rule.prefix}-"
                    f"{override_rule.case_type}: "
                    f"{previous.rule_name!r} and "
                    f"{override_rule.rule_name!r}."
                )

            if override_rule.prefix not in prefix_index:
                raise ConfigurationError(
                    f"Routing override "
                    f"{override_rule.rule_name!r} "
                    "references unknown prefix "
                    f"{override_rule.prefix}."
                )

            if (
                override_rule.case_type
                not in case_type_index
            ):
                raise ConfigurationError(
                    f"Routing override "
                    f"{override_rule.rule_name!r} "
                    "references unknown case type "
                    f"{override_rule.case_type}."
                )

            if (
                override_rule.hospital is not None
                and override_rule.hospital
                not in hospital_index
            ):
                raise ConfigurationError(
                    f"Routing override "
                    f"{override_rule.rule_name!r} "
                    "references unknown hospital "
                    f"{override_rule.hospital}."
                )

            if (
                override_rule.mode
                is RoutingOverrideMode.REQUIRED_IF_SUBSPECIALIST_PRESENT
                and override_rule.required_subspecialty
                is None
                and case_type_index[
                    override_rule.case_type
                ].subspecialty
                is None
            ):
                raise ConfigurationError(
                    f"Routing override "
                    f"{override_rule.rule_name!r} "
                    "must specify a required_subspecialty "
                    "because case type "
                    f"{override_rule.case_type} "
                    "has no associated subspecialty."
                )

            override_index[
                override_rule.match_key
            ] = override_rule

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
        object.__setattr__(
            self,
            "_override_index",
            MappingProxyType(override_index),
        )

    def get_case_type_rule(self, case_type: str) -> CaseTypeRule:
        normalized = _normalize_two_letter_code(case_type, "Case type")
        try:
            return self._case_type_index[normalized]
        except KeyError as exc:
            raise UnknownCaseTypeError(
                f"No routing rule is configured for case type {normalized}."
            ) from exc

    def get_prefix_rule(self, prefix: str) -> PrefixRoutingRule:
        normalized = _normalize_two_letter_code(prefix, "Prefix")
        try:
            return self._prefix_index[normalized]
        except KeyError as exc:
            raise UnknownPrefixError(
                f"No routing rule is configured for prefix {normalized}."
            ) from exc

    def get_hospital_rule(self, hospital: str) -> HospitalRoutingRule:
        normalized = _normalize_label(hospital, "Hospital")
        try:
            return self._hospital_index[normalized]
        except KeyError as exc:
            raise UnknownHospitalError(
                f"No routing rule is configured for hospital {normalized}."
            ) from exc

    def find_override_rule(
        self,
        hospital: str,
        prefix: str,
        case_type: str,
    ) -> RoutingOverrideRule | None:
        """Return the most specific matching override rule."""
        normalized_hospital = _normalize_label(hospital, "Hospital")
        normalized_prefix = _normalize_two_letter_code(prefix, "Prefix")
        normalized_case_type = _normalize_two_letter_code(
            case_type,
            "Case type",
        )

        exact_key = (
            normalized_hospital,
            normalized_prefix,
            normalized_case_type,
        )
        general_key = (
            None,
            normalized_prefix,
            normalized_case_type,
        )
        return self._override_index.get(exact_key) or self._override_index.get(
            general_key
        )
