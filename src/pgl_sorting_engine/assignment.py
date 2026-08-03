"""Weighted accession assignment and sorting-run result models."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from pgl_sorting_engine.eligibility import (
    EligibilityResult,
    EligibilityService,
)
from pgl_sorting_engine.enums import (
    AssignmentMethod,
    LocationName,
    RoutingOverrideMode,
)
from pgl_sorting_engine.exceptions import (
    DuplicateAccessionError,
    SortingEngineError,
)
from pgl_sorting_engine.models import Accession

ZERO_WEIGHT = Decimal("0")

BALANCED_LOCATIONS = (
    LocationName.OLOL,
    LocationName.BRG,
    LocationName.WH,
)
SPECIAL_ONLY_LOCATIONS = frozenset(
    {
        LocationName.TEXAS,
        LocationName.OMEGA,
    }
)
TEXAS_CASE_TYPES = frozenset({"DP", "DS"})
OMEGA_HOSPITAL = "Omega Hospital"


@dataclass(frozen=True, slots=True)
class AssignmentSettings:
    """Editable MET and WH workload parameters."""

    met_weight_per_pathologist: Decimal = Decimal("200")
    wh_starting_weight: Decimal = Decimal("400")

    def __post_init__(self) -> None:
        met_weight = Decimal(str(self.met_weight_per_pathologist))
        wh_weight = Decimal(str(self.wh_starting_weight))

        if not met_weight.is_finite():
            raise ValueError(
                "met_weight_per_pathologist must be finite."
            )

        if not wh_weight.is_finite():
            raise ValueError("wh_starting_weight must be finite.")

        if met_weight < ZERO_WEIGHT:
            raise ValueError(
                "met_weight_per_pathologist cannot be negative."
            )

        if wh_weight < ZERO_WEIGHT:
            raise ValueError("wh_starting_weight cannot be negative.")

        object.__setattr__(
            self,
            "met_weight_per_pathologist",
            met_weight,
        )
        object.__setattr__(self, "wh_starting_weight", wh_weight)


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    """
    Record the final destination and reasoning for one accession.

    A target of ``None`` means that the location is governed by a special
    routing rule rather than an ordinary workload target.
    """

    accession: Accession
    location: LocationName
    method: AssignmentMethod
    eligibility: EligibilityResult
    assigned_weight_before: Decimal
    assigned_weight_after: Decimal
    target_weight: Decimal | None
    decision_notes: tuple[str, ...]
    override_applied: bool = False
    override_application_notes: tuple[str, ...] = ()
    override_matching_weight_before: Decimal | None = None
    override_matching_weight_after: Decimal | None = None
    override_weight_cap: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UnassignedAccession:
    """Record an accession that could not be safely assigned."""

    accession: Accession
    error_code: str
    summary: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocationSortingSummary:
    """Summarize workload assigned to one location."""

    location: LocationName
    number_of_pathologists: int
    target_weight: Decimal | None
    accession_count: int
    assigned_weight: Decimal
    starting_weight: Decimal = ZERO_WEIGHT

    @property
    def is_active(self) -> bool:
        """Return whether the location has staffing capacity."""
        return self.number_of_pathologists > 0

    @property
    def effective_weight(self) -> Decimal:
        """Return assigned weight plus any configured starting load."""
        return self.starting_weight + self.assigned_weight

    @property
    def assigned_weight_per_pathologist(self) -> Decimal | None:
        """Return newly assigned weight per pathologist, when staffed."""
        if self.number_of_pathologists == 0:
            return None

        return self.assigned_weight / self.number_of_pathologists

    @property
    def weight_per_pathologist(self) -> Decimal | None:
        """Return effective weight per pathologist, when staffed."""
        if self.number_of_pathologists == 0:
            return None

        return self.effective_weight / self.number_of_pathologists

    @property
    def variance_from_target(self) -> Decimal | None:
        """Return assigned weight minus target, when a target exists."""
        if self.target_weight is None:
            return None

        return self.assigned_weight - self.target_weight


@dataclass(frozen=True, slots=True)
class SortingRunResult:
    """Complete output from one sorting run."""

    input_accession_count: int
    assignments: tuple[AssignmentResult, ...]
    unassigned_accessions: tuple[UnassignedAccession, ...]
    location_summaries: Mapping[LocationName, LocationSortingSummary]

    @property
    def assigned_accession_count(self) -> int:
        """Return the number of successfully assigned accessions."""
        return len(self.assignments)

    @property
    def unassigned_accession_count(self) -> int:
        """Return the number of accessions requiring review."""
        return len(self.unassigned_accessions)

    @property
    def total_assigned_weight(self) -> Decimal:
        """Return total weight successfully assigned."""
        return sum(
            (
                assignment.accession.weight
                for assignment in self.assignments
            ),
            start=ZERO_WEIGHT,
        )

    @property
    def total_unassigned_weight(self) -> Decimal:
        """Return total weight that could not be assigned."""
        return sum(
            (
                item.accession.weight
                for item in self.unassigned_accessions
            ),
            start=ZERO_WEIGHT,
        )

    def summary_for(
        self,
        location: LocationName,
    ) -> LocationSortingSummary:
        """Return the summary for a particular location."""
        return self.location_summaries[LocationName(location)]


@dataclass(frozen=True, slots=True)
class _EvaluatedAccession:
    """Internal pairing of an accession with its eligibility result."""

    accession: Accession
    eligibility: EligibilityResult


@dataclass(frozen=True, slots=True)
class _ForcedAccession:
    """Internal record for a special business-rule assignment."""

    item: _EvaluatedAccession
    location: LocationName
    reason: str


@dataclass(frozen=True, slots=True)
class SortingEngine:
    """
    Assign accessions according to special rules and weighted balancing.

    Assignment order:

    1. DP and DS cases go to TEXAS without a workload target.
    2. When exactly one pathologist is at OMEGA, Omega Hospital cases go
       to OMEGA. Otherwise OMEGA receives no work.
    3. Ordinary mandatory routing rules are applied.
    4. MET receives eligible work toward a fixed target equal to its
       pathologist count multiplied by ``met_weight_per_pathologist``.
    5. Remaining eligible work is balanced among OLOL, BRG, and WH.
       WH begins with the configured ``wh_starting_weight``.
    """

    eligibility_service: EligibilityService
    settings: AssignmentSettings = field(
        default_factory=AssignmentSettings
    )

    def run(
        self,
        accessions: Iterable[Accession],
    ) -> SortingRunResult:
        """Perform one complete accession sorting run."""
        accession_list = tuple(accessions)
        self._validate_unique_accessions(accession_list)

        evaluated, unassigned = self._evaluate_accessions(
            accession_list
        )

        (
            forced_cases,
            mandatory_cases,
            flexible_cases,
            policy_unassigned,
        ) = self._classify_accessions(evaluated)
        unassigned.extend(policy_unassigned)

        target_cases = [*mandatory_cases, *flexible_cases]
        targets = self._calculate_location_targets(target_cases)

        assigned_weights = {
            location: ZERO_WEIGHT
            for location in LocationName
        }
        assigned_counts = {
            location: 0
            for location in LocationName
        }
        assignments: list[AssignmentResult] = []
        override_weight_totals: dict[
            tuple[str | None, str, str, LocationName],
            Decimal,
        ] = {}

        for forced_case in sorted(
            forced_cases,
            key=lambda item: self._accession_sort_key(
                item.item
            ),
        ):
            forced_assignment = self._assign_forced(
                forced=forced_case,
                assigned_weights=assigned_weights,
            )

            assignments.append(forced_assignment)

            assigned_counts[
                forced_assignment.location
            ] += 1


        for mandatory_item in sorted(
            mandatory_cases,
            key=self._accession_sort_key,
        ):
            mandatory_assignment = self._assign_mandatory(
                item=mandatory_item,
                targets=targets,
                assigned_weights=assigned_weights,
            )

            assignments.append(mandatory_assignment)

            assigned_counts[
                mandatory_assignment.location
            ] += 1


        for flexible_item in sorted(
            flexible_cases,
            key=self._accession_sort_key,
        ):
            flexible_assignment = self._assign_flexible(
                item=flexible_item,
                targets=targets,
                assigned_weights=assigned_weights,
                override_weight_totals=override_weight_totals,
            )

            if flexible_assignment is None:
                unassigned.append(
                    self._create_policy_unassigned_result(
                        item=flexible_item,
                        error_code=(
                            "NO_AVAILABLE_LOCATION_AFTER_CAPS"
                        ),
                        summary=(
                            "Accession "
                            f"{flexible_item.accession.accession_number} "
                            "had no available destination after "
                            "workload caps were applied."
                        ),
                    )
                )
                continue

            assignments.append(flexible_assignment)

            assigned_counts[
                flexible_assignment.location
            ] += 1

        summaries = self._build_location_summaries(
            targets=targets,
            assigned_weights=assigned_weights,
            assigned_counts=assigned_counts,
        )

        return SortingRunResult(
            input_accession_count=len(accession_list),
            assignments=tuple(assignments),
            unassigned_accessions=tuple(unassigned),
            location_summaries=MappingProxyType(summaries),
        )

    def _validate_unique_accessions(
        self,
        accessions: tuple[Accession, ...],
    ) -> None:
        """Reject duplicate accession numbers within one sorting run."""
        seen: set[str] = set()
        duplicates: set[str] = set()

        for accession in accessions:
            if accession.accession_number in seen:
                duplicates.add(accession.accession_number)

            seen.add(accession.accession_number)

        if duplicates:
            duplicate_list = ", ".join(sorted(duplicates))
            raise DuplicateAccessionError(
                f"Duplicate accession numbers found: {duplicate_list}."
            )

    def _evaluate_accessions(
        self,
        accessions: tuple[Accession, ...],
    ) -> tuple[
        list[_EvaluatedAccession],
        list[UnassignedAccession],
    ]:
        """Evaluate eligibility and separate routing failures."""
        evaluated: list[_EvaluatedAccession] = []
        unassigned: list[UnassignedAccession] = []
        omega_rule_active = self._omega_pathologist_count() == 1

        for accession in accessions:
            try:
                eligibility = self.eligibility_service.evaluate(
                    accession
                )
            except SortingEngineError as exc:
                unassigned.append(
                    UnassignedAccession(
                        accession=accession,
                        error_code="ROUTING_ERROR",
                        summary=str(exc),
                        details=(type(exc).__name__,),
                    )
                )
                continue

            special_override = self._is_texas_case(accession) or (
                omega_rule_active
                and self._is_omega_hospital(accession)
            )

            if not eligibility.is_assignable and not special_override:
                unassigned.append(
                    self._create_no_eligible_location_result(
                        accession=accession,
                        eligibility=eligibility,
                    )
                )
                continue

            evaluated.append(
                _EvaluatedAccession(
                    accession=accession,
                    eligibility=eligibility,
                )
            )

        return evaluated, unassigned

    def _classify_accessions(
        self,
        evaluated: list[_EvaluatedAccession],
    ) -> tuple[
        list[_ForcedAccession],
        list[_EvaluatedAccession],
        list[_EvaluatedAccession],
        list[UnassignedAccession],
    ]:
        """Separate special, mandatory, flexible, and policy failures."""
        forced: list[_ForcedAccession] = []
        mandatory: list[_EvaluatedAccession] = []
        flexible: list[_EvaluatedAccession] = []
        unassigned: list[UnassignedAccession] = []

        texas_count = self._pathologist_count(LocationName.TEXAS)
        omega_count = self._omega_pathologist_count()
        omega_rule_active = omega_count == 1

        for item in evaluated:
            accession = item.accession

            if self._is_texas_case(accession):
                if texas_count == 0:
                    unassigned.append(
                        self._create_policy_unassigned_result(
                            item=item,
                            error_code="TEXAS_NOT_STAFFED",
                            summary=(
                                f"Accession {accession.accession_number} "
                                f"is a {accession.case_type} case and must "
                                "go to TEXAS, but TEXAS has no staffed "
                                "pathologists."
                            ),
                        )
                    )
                    continue

                forced.append(
                    _ForcedAccession(
                        item=item,
                        location=LocationName.TEXAS,
                        reason=(
                            f"Case type {accession.case_type} is routed "
                            "to TEXAS without a workload target."
                        ),
                    )
                )
                continue

            if omega_rule_active and self._is_omega_hospital(accession):
                forced.append(
                    _ForcedAccession(
                        item=item,
                        location=LocationName.OMEGA,
                        reason=(
                            "Exactly one pathologist is staffed at OMEGA, "
                            "so Omega Hospital cases are routed to OMEGA."
                        ),
                    )
                )
                continue

            if not item.eligibility.is_assignable:
                unassigned.append(
                    self._create_no_eligible_location_result(
                        accession=accession,
                        eligibility=item.eligibility,
                    )
                )
                continue

            if item.eligibility.is_mandatory:
                required_location = item.eligibility.required_location

                if required_location in SPECIAL_ONLY_LOCATIONS:
                    unassigned.append(
                        self._create_policy_unassigned_result(
                            item=item,
                            error_code="SPECIAL_LOCATION_RULE_CONFLICT",
                            summary=(
                                f"Accession {accession.accession_number} "
                                f"was routed to {required_location.value}, "
                                "but that destination is reserved for its "
                                "special assignment rule."
                            ),
                        )
                    )
                    continue

                mandatory.append(item)
                continue

            if not self._normal_eligible_locations(item):
                unassigned.append(
                    self._create_policy_unassigned_result(
                        item=item,
                        error_code="NO_POLICY_ELIGIBLE_LOCATION",
                        summary=(
                            f"Accession {accession.accession_number} has "
                            "no eligible destination after TEXAS and OMEGA "
                            "were removed from ordinary balancing."
                        ),
                    )
                )
                continue

            flexible.append(item)

        return forced, mandatory, flexible, unassigned

    def _create_no_eligible_location_result(
        self,
        accession: Accession,
        eligibility: EligibilityResult,
    ) -> UnassignedAccession:
        """Create a detailed manual-review record."""
        details: list[str] = []

        for location in LocationName:
            reasons = eligibility.reasons_for_exclusion(location)

            if not reasons:
                continue

            details.append(
                f"{location.value}: {'; '.join(reasons)}"
            )

        return UnassignedAccession(
            accession=accession,
            error_code="NO_ELIGIBLE_LOCATION",
            summary=(
                f"No eligible location was found for accession "
                f"{accession.accession_number}."
            ),
            details=tuple(details),
        )

    @staticmethod
    def _create_policy_unassigned_result(
        item: _EvaluatedAccession,
        error_code: str,
        summary: str,
    ) -> UnassignedAccession:
        """Create an unassigned record caused by a business policy."""
        eligible = ", ".join(
            location.value
            for location in item.eligibility.eligible_locations
        )
        details = (
            f"Eligibility service locations: {eligible or 'none'}.",
        )

        return UnassignedAccession(
            accession=item.accession,
            error_code=error_code,
            summary=summary,
            details=details,
        )

    def _calculate_location_targets(
        self,
        evaluated: list[_EvaluatedAccession],
    ) -> dict[LocationName, Decimal | None]:
        """Calculate MET and proportional OLOL/BRG/WH targets."""
        targets: dict[LocationName, Decimal | None] = {
            location: None
            for location in LocationName
        }

        met_count = self._pathologist_count(LocationName.MET)
        met_target = (
            Decimal(met_count)
            * self.settings.met_weight_per_pathologist
        )
        targets[LocationName.MET] = met_target

        for location in BALANCED_LOCATIONS:
            targets[location] = ZERO_WEIGHT

        total_weight = sum(
            (item.accession.weight for item in evaluated),
            start=ZERO_WEIGHT,
        )
        proportional_weight = max(
            total_weight - met_target,
            ZERO_WEIGHT,
        )

        pathologist_counts = {
            location: self._pathologist_count(location)
            for location in BALANCED_LOCATIONS
        }
        total_balanced_pathologists = sum(
            pathologist_counts.values()
        )

        if total_balanced_pathologists == 0:
            return targets

        wh_starting_weight = self._wh_starting_weight()
        effective_pool = proportional_weight + wh_starting_weight
        weight_per_pathologist = (
            effective_pool
            / Decimal(total_balanced_pathologists)
        )

        for location in BALANCED_LOCATIONS:
            target = (
                Decimal(pathologist_counts[location])
                * weight_per_pathologist
            )

            if location == LocationName.WH:
                target -= wh_starting_weight

            targets[location] = max(target, ZERO_WEIGHT)

        return targets

    @staticmethod
    def _accession_sort_key(
        item: _EvaluatedAccession,
    ) -> tuple[Decimal, str]:
        """Sort heavier cases first, then accession number."""
        return (-item.accession.weight, item.accession.accession_number)

    def _assign_forced(
        self,
        forced: _ForcedAccession,
        assigned_weights: dict[LocationName, Decimal],
    ) -> AssignmentResult:
        """Assign an accession under a special destination rule."""
        item = forced.item
        before = assigned_weights[forced.location]
        after = before + item.accession.weight
        assigned_weights[forced.location] = after

        return AssignmentResult(
            accession=item.accession,
            location=forced.location,
            method=AssignmentMethod.MANDATORY,
            eligibility=item.eligibility,
            assigned_weight_before=before,
            assigned_weight_after=after,
            target_weight=None,
            decision_notes=(
                forced.reason,
                (
                    f"Location weight changed from {before} "
                    f"to {after}."
                ),
            ),
        )

    def _assign_mandatory(
        self,
        item: _EvaluatedAccession,
        targets: Mapping[LocationName, Decimal | None],
        assigned_weights: dict[LocationName, Decimal],
    ) -> AssignmentResult:
        """Assign an accession with an ordinary mandatory destination."""
        required_location = item.eligibility.required_location

        if required_location is None:
            raise RuntimeError(
                "Mandatory assignment called without a required location."
            )

        if required_location in SPECIAL_ONLY_LOCATIONS:
            raise RuntimeError(
                "Special-only locations must be assigned before ordinary "
                "mandatory routing."
            )

        before = assigned_weights[required_location]
        after = before + item.accession.weight
        assigned_weights[required_location] = after
        target = self._required_target(targets, required_location)

        return AssignmentResult(
            accession=item.accession,
            location=required_location,
            method=AssignmentMethod.MANDATORY,
            eligibility=item.eligibility,
            assigned_weight_before=before,
            assigned_weight_after=after,
            target_weight=target,
            decision_notes=(
                (
                    f"Mandatory routing required "
                    f"{required_location.value}."
                ),
                (
                    f"Target weight was {target}; location weight "
                    f"changed from {before} to {after}."
                ),
            ),
            override_applied=(
                item.eligibility.override_rule is not None
                and item.eligibility.override_activated
            ),
            override_application_notes=(
                (
                    f"Routing override "
                    f"{item.eligibility.override_rule.rule_name!r} "
                    "created the mandatory destination."
                ),
            )
            if (
                item.eligibility.override_rule is not None
                and item.eligibility.override_activated
            )
            else (),
        )

    def _assign_flexible(
        self,
        item: _EvaluatedAccession,
        targets: Mapping[LocationName, Decimal | None],
        assigned_weights: dict[LocationName, Decimal],
        override_weight_totals: dict[
            tuple[str | None, str, str, LocationName],
            Decimal,
        ],
    ) -> AssignmentResult | None:
        """Select the best ordinary location for a flexible accession."""
        candidates = self._available_flexible_locations(
            item=item,
            targets=targets,
            assigned_weights=assigned_weights,
        )

        cap_destination = (
            item.eligibility.preferred_until_weight_cap_location
        )
        cap_rule = item.eligibility.override_rule
        cap_value: Decimal | None = None
        cap_before: Decimal | None = None
        cap_after: Decimal | None = None
        cap_key: tuple[str | None, str, str, LocationName] | None = None
        cap_override_used = False
        cap_would_be_exceeded = False

        if cap_destination is not None:
            if (
                cap_rule is None
                or cap_rule.mode
                is not RoutingOverrideMode.PREFERRED_UNTIL_WEIGHT_CAP
                or cap_rule.weight_cap is None
            ):
                raise RuntimeError(
                    "Validated preferred-until-weight-cap rule is incomplete."
                )

            cap_value = cap_rule.weight_cap
            cap_key = (*cap_rule.match_key, cap_destination)
            cap_before = override_weight_totals.get(cap_key, ZERO_WEIGHT)
            proposed_cap_weight = cap_before + item.accession.weight

            if proposed_cap_weight > cap_value:
                cap_would_be_exceeded = True
                candidates = tuple(
                    location
                    for location in candidates
                    if location != cap_destination
                )

        if not candidates:
            return None

        soft_destination = (
            item.eligibility.preferred_until_target_location
        )
        soft_override_used = False

        if (
            cap_destination is not None
            and not cap_would_be_exceeded
            and cap_destination in candidates
        ):
            selected_location = cap_destination
            cap_override_used = True
        elif soft_destination is not None and soft_destination in candidates:
            soft_target = self._required_target(
                targets,
                soft_destination,
            )
            if assigned_weights[soft_destination] < soft_target:
                selected_location = soft_destination
                soft_override_used = True
            else:
                selected_location = min(
                    candidates,
                    key=lambda location: self._candidate_sort_key(
                        location=location,
                        eligibility=item.eligibility,
                        targets=targets,
                        assigned_weights=assigned_weights,
                    ),
                )
        else:
            selected_location = min(
                candidates,
                key=lambda location: self._candidate_sort_key(
                    location=location,
                    eligibility=item.eligibility,
                    targets=targets,
                    assigned_weights=assigned_weights,
                ),
            )

        before = assigned_weights[selected_location]
        after = before + item.accession.weight
        assigned_weights[selected_location] = after

        if cap_override_used:
            if cap_key is None or cap_before is None or cap_value is None:
                raise RuntimeError(
                    "Weight-cap assignment state was not initialized."
                )
            cap_after = cap_before + item.accession.weight
            override_weight_totals[cap_key] = cap_after

        target = self._required_target(targets, selected_location)
        deficit_before = target - before

        notes = [
            (
                f"Selected {selected_location.value} from "
                f"{len(candidates)} currently available locations."
            ),
            (
                f"Target weight was {target}; assigned weight before "
                f"selection was {before}; remaining target deficit "
                f"was {deficit_before}."
            ),
            f"Location weight changed from {before} to {after}.",
        ]

        if cap_override_used:
            override_rule = item.eligibility.override_rule
            override_name = (
                override_rule.rule_name
                if override_rule is not None
                else "unnamed override"
            )
            notes.append(
                f"Routing override {override_name!r} sent the accession to "
                f"{selected_location.value}. Matching weight changed from "
                f"{cap_before} to {cap_after} under the strict cap of "
                f"{cap_value}."
            )
        elif cap_would_be_exceeded:
            override_rule = item.eligibility.override_rule
            override_name = (
                override_rule.rule_name
                if override_rule is not None
                else "unnamed override"
            )
            proposed = (
                cap_before + item.accession.weight
                if cap_before is not None
                else item.accession.weight
            )
            destination_name = (
                cap_destination.value
                if cap_destination is not None
                else "the configured destination"
            )
            notes.append(
                f"Routing override {override_name!r} did not route to "
                f"{destination_name} because matching weight would increase "
                f"from {cap_before} "
                f"to {proposed}, exceeding the strict cap of {cap_value}. "
                "The capped destination was excluded and routine distribution "
                "was used."
            )
        elif (
            cap_destination is not None
            and cap_destination not in candidates
        ):
            notes.append(
                f"The preferred-until-weight-cap destination "
                f"{cap_destination.value} was not currently available under "
                "the location workload policy; routine distribution was used."
            )

        if soft_override_used:
            override_rule = item.eligibility.override_rule
            override_name = (
                override_rule.rule_name
                if override_rule is not None
                else "unnamed override"
            )
            notes.append(
                f"Routing override {override_name!r} "
                f"sent the accession to {selected_location.value} because "
                f"its pre-assignment weight {before} was below target "
                f"{target}. The final case was allowed to cross the target."
            )
            if after >= target:
                notes.append(
                    f"{selected_location.value} is now closed to additional "
                    "target-based flexible assignments for this run."
                )
        elif (
            item.eligibility.preferred_until_target_location is not None
        ):
            destination = (
                item.eligibility.preferred_until_target_location
            )
            destination_target = self._required_target(
                targets,
                destination,
            )
            notes.append(
                f"The preferred-until-target override did not route to "
                f"{destination.value} because its assigned weight "
                f"{assigned_weights[destination]} was not below target "
                f"{destination_target}; routine distribution was used."
            )

        if selected_location == LocationName.WH:
            starting_weight = self._wh_starting_weight()
            notes.append(
                f"WH began with configured weight {starting_weight}; "
                f"its effective weight after assignment was "
                f"{starting_weight + after}."
            )

        if selected_location in item.eligibility.preferred_locations:
            notes.append(
                f"{selected_location.value} was a preferred location and "
                "preference was available as a tie-breaker."
            )

        return AssignmentResult(
            accession=item.accession,
            location=selected_location,
            method=AssignmentMethod.WEIGHT_BALANCED,
            eligibility=item.eligibility,
            assigned_weight_before=before,
            assigned_weight_after=after,
            target_weight=target,
            decision_notes=tuple(notes),
            override_applied=(
                cap_override_used
                or soft_override_used
                or (
                    item.eligibility.override_rule is not None
                    and item.eligibility.override_rule.mode
                    is RoutingOverrideMode.PREFERRED
                    and selected_location
                    in item.eligibility.override_rule.preferred_locations
                )
            ),
            override_application_notes=(
                tuple(
                    note
                    for note in notes
                    if "override" in note.lower()
                    or "strict cap" in note.lower()
                )
            ),
            override_matching_weight_before=cap_before,
            override_matching_weight_after=cap_after,
            override_weight_cap=cap_value,
        )

    def _candidate_sort_key(
        self,
        location: LocationName,
        eligibility: EligibilityResult,
        targets: Mapping[LocationName, Decimal | None],
        assigned_weights: Mapping[LocationName, Decimal],
    ) -> tuple[Decimal, bool, int, str]:
        """Rank an ordinary eligible location by target deficit."""
        target = self._required_target(targets, location)
        deficit = target - assigned_weights[location]

        try:
            preference_rank = (
                eligibility.preferred_locations.index(location)
            )
            is_not_preferred = False
        except ValueError:
            preference_rank = len(
                eligibility.preferred_locations
            )
            is_not_preferred = True

        return (
            -deficit,
            is_not_preferred,
            preference_rank,
            location.value,
        )

    def _normal_eligible_locations(
        self,
        item: _EvaluatedAccession,
    ) -> tuple[LocationName, ...]:
        """Return eligible destinations used by ordinary balancing."""
        return tuple(
            location
            for location in item.eligibility.eligible_locations
            if location not in SPECIAL_ONLY_LOCATIONS
        )

    def _available_flexible_locations(
        self,
        item: _EvaluatedAccession,
        targets: Mapping[LocationName, Decimal | None],
        assigned_weights: Mapping[LocationName, Decimal],
    ) -> tuple[LocationName, ...]:
        """Return ordinary locations still open to flexible work.

        MET uses a one-case overshoot policy: a case may be assigned while
        MET's pre-assignment weight is below target. After that case brings
        MET to or above target, MET is excluded from additional flexible work.
        Mandatory assignments are not limited by this cap.
        """
        locations: list[LocationName] = []
        for location in self._normal_eligible_locations(item):
            if location == LocationName.MET:
                target = self._required_target(targets, location)
                if assigned_weights[location] >= target:
                    continue
            locations.append(location)
        return tuple(locations)

    @staticmethod
    def _required_target(
        targets: Mapping[LocationName, Decimal | None],
        location: LocationName,
    ) -> Decimal:
        """Return a numeric target for a target-based location."""
        target = targets[location]

        if target is None:
            raise RuntimeError(
                f"{location.value} does not use a workload target."
            )

        return target

    def _pathologist_count(self, location: LocationName) -> int:
        """Return the number of pathologists staffed at a location."""
        capability = (
            self.eligibility_service.staffing_context
            .get_location_capability(location)
        )
        return capability.number_of_pathologists

    def _omega_pathologist_count(self) -> int:
        """Return the number of pathologists staffed at OMEGA."""
        return self._pathologist_count(LocationName.OMEGA)

    def _wh_starting_weight(self) -> Decimal:
        """Return WH starting weight only when WH is staffed."""
        if self._pathologist_count(LocationName.WH) == 0:
            return ZERO_WEIGHT

        return self.settings.wh_starting_weight

    def _is_texas_case(self, accession: Accession) -> bool:
        """Return whether an accession belongs to a TEXAS case type."""
        return accession.case_type.strip().upper() in TEXAS_CASE_TYPES

    def _is_omega_hospital(self, accession: Accession) -> bool:
        """Return whether an accession originated at Omega Hospital."""
        return (
            accession.hospital.strip().casefold()
            == OMEGA_HOSPITAL.casefold()
        )

    def _build_location_summaries(
        self,
        targets: Mapping[LocationName, Decimal | None],
        assigned_weights: Mapping[LocationName, Decimal],
        assigned_counts: Mapping[LocationName, int],
    ) -> dict[LocationName, LocationSortingSummary]:
        """Build final statistics for every configured location."""
        summaries: dict[
            LocationName,
            LocationSortingSummary,
        ] = {}

        for location in LocationName:
            starting_weight = (
                self._wh_starting_weight()
                if location == LocationName.WH
                else ZERO_WEIGHT
            )

            summaries[location] = LocationSortingSummary(
                location=location,
                number_of_pathologists=self._pathologist_count(location),
                target_weight=targets[location],
                accession_count=assigned_counts[location],
                assigned_weight=assigned_weights[location],
                starting_weight=starting_weight,
            )

        return summaries
