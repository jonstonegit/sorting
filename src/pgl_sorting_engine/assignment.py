"""Weighted accession assignment and sorting-run result models."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from pgl_sorting_engine.eligibility import (
    EligibilityResult,
    EligibilityService,
)
from pgl_sorting_engine.enums import AssignmentMethod, LocationName
from pgl_sorting_engine.exceptions import (
    DuplicateAccessionError,
    SortingEngineError,
)
from pgl_sorting_engine.models import Accession

ZERO_WEIGHT = Decimal("0")


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    """
    Record the final destination and reasoning for one accession.

    Attributes:
        accession: Accession that was assigned.
        location: Final work location.
        method: Mandatory routing or weighted balancing.
        eligibility: Full eligibility evaluation for audit purposes.
        assigned_weight_before: Location workload before assignment.
        assigned_weight_after: Location workload after assignment.
        target_weight: Calculated workload target for the location.
        decision_notes: Explanation of the final selection.
    """

    accession: Accession
    location: LocationName
    method: AssignmentMethod
    eligibility: EligibilityResult
    assigned_weight_before: Decimal
    assigned_weight_after: Decimal
    target_weight: Decimal
    decision_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnassignedAccession:
    """
    Record an accession that could not be safely assigned.

    Attributes:
        accession: Accession that was not assigned.
        error_code: Stable category suitable for reports and logs.
        summary: Concise explanation.
        details: Location-specific or exception-specific details.
    """

    accession: Accession
    error_code: str
    summary: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocationSortingSummary:
    """Summarize workload assigned to one location."""

    location: LocationName
    number_of_pathologists: int
    target_weight: Decimal
    accession_count: int
    assigned_weight: Decimal

    @property
    def is_active(self) -> bool:
        """Return whether the location has staffing capacity."""
        return self.number_of_pathologists > 0

    @property
    def weight_per_pathologist(self) -> Decimal | None:
        """Return assigned weight per pathologist, when staffed."""
        if self.number_of_pathologists == 0:
            return None

        return self.assigned_weight / self.number_of_pathologists

    @property
    def variance_from_target(self) -> Decimal:
        """Return assigned weight minus target weight."""
        return self.assigned_weight - self.target_weight


@dataclass(frozen=True, slots=True)
class SortingRunResult:
    """
    Complete output from one sorting run.

    This structured result will later support reports, Excel exports,
    dashboards, audit logs, and daily email summaries.
    """

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
class SortingEngine:
    """
    Assign accessions using mandatory rules and weighted balancing.

    Flexible cases are processed from highest weight to lowest. The engine
    selects the eligible location with the largest remaining target deficit.
    Preferred locations are used only to break equal-deficit ties.
    """

    eligibility_service: EligibilityService

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

        targets = self._calculate_location_targets(evaluated)
        assigned_weights = {
            location: ZERO_WEIGHT
            for location in LocationName
        }
        assigned_counts = {
            location: 0
            for location in LocationName
        }

        assignments: list[AssignmentResult] = []

        mandatory_cases = sorted(
            (
                item
                for item in evaluated
                if item.eligibility.is_mandatory
            ),
            key=self._accession_sort_key,
        )

        flexible_cases = sorted(
            (
                item
                for item in evaluated
                if not item.eligibility.is_mandatory
            ),
            key=self._accession_sort_key,
        )

        for item in mandatory_cases:
            assignment = self._assign_mandatory(
                item=item,
                targets=targets,
                assigned_weights=assigned_weights,
            )
            assignments.append(assignment)
            assigned_counts[assignment.location] += 1

        for item in flexible_cases:
            assignment = self._assign_flexible(
                item=item,
                targets=targets,
                assigned_weights=assigned_weights,
            )
            assignments.append(assignment)
            assigned_counts[assignment.location] += 1

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
        """Evaluate eligibility and separate unassignable accessions."""
        evaluated: list[_EvaluatedAccession] = []
        unassigned: list[UnassignedAccession] = []

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

            if not eligibility.is_assignable:
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

            joined_reasons = "; ".join(reasons)
            details.append(
                f"{location.value}: {joined_reasons}"
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

    def _calculate_location_targets(
        self,
        evaluated: list[_EvaluatedAccession],
    ) -> dict[LocationName, Decimal]:
        """
        Calculate target weight proportional to pathologist staffing.

        Only locations eligible for at least one accession participate in
        target allocation. This avoids assigning a theoretical workload target
        to a location that cannot receive any of the day's work.
        """
        targets = {
            location: ZERO_WEIGHT
            for location in LocationName
        }

        if not evaluated:
            return targets

        participating_locations: set[LocationName] = set()

        for item in evaluated:
            participating_locations.update(
                item.eligibility.eligible_locations
            )

        total_pathologists = sum(
            self.eligibility_service.staffing_context
            .get_location_capability(location)
            .number_of_pathologists
            for location in participating_locations
        )

        if total_pathologists == 0:
            return targets

        total_weight = sum(
            (
                item.accession.weight
                for item in evaluated
            ),
            start=ZERO_WEIGHT,
        )

        for location in participating_locations:
            capability = (
                self.eligibility_service.staffing_context
                .get_location_capability(location)
            )

            targets[location] = (
                total_weight
                * capability.number_of_pathologists
                / total_pathologists
            )

        return targets

    @staticmethod
    def _accession_sort_key(
        item: _EvaluatedAccession,
    ) -> tuple[Decimal, str]:
        """Sort heavier cases first, then accession number."""
        return (-item.accession.weight, item.accession.accession_number)

    def _assign_mandatory(
        self,
        item: _EvaluatedAccession,
        targets: Mapping[LocationName, Decimal],
        assigned_weights: dict[LocationName, Decimal],
    ) -> AssignmentResult:
        """Assign an accession with a mandatory destination."""
        required_location = item.eligibility.required_location

        if required_location is None:
            raise RuntimeError(
                "Mandatory assignment called without a required location."
            )

        before = assigned_weights[required_location]
        after = before + item.accession.weight
        assigned_weights[required_location] = after

        return AssignmentResult(
            accession=item.accession,
            location=required_location,
            method=AssignmentMethod.MANDATORY,
            eligibility=item.eligibility,
            assigned_weight_before=before,
            assigned_weight_after=after,
            target_weight=targets[required_location],
            decision_notes=(
                (
                    f"Mandatory routing required "
                    f"{required_location.value}."
                ),
                (
                    f"Location weight changed from {before} "
                    f"to {after}."
                ),
            ),
        )

    def _assign_flexible(
        self,
        item: _EvaluatedAccession,
        targets: Mapping[LocationName, Decimal],
        assigned_weights: dict[LocationName, Decimal],
    ) -> AssignmentResult:
        """Select the best eligible location for a flexible accession."""
        selected_location = min(
            item.eligibility.eligible_locations,
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

        target = targets[selected_location]
        deficit_before = target - before

        notes = [
            (
                f"Selected {selected_location.value} from "
                f"{len(item.eligibility.eligible_locations)} "
                "eligible locations."
            ),
            (
                f"Target weight was {target}; assigned weight before "
                f"selection was {before}; remaining target deficit "
                f"was {deficit_before}."
            ),
            (
                f"Location weight changed from {before} "
                f"to {after}."
            ),
        ]

        if selected_location in item.eligibility.preferred_locations:
            notes.append(
                
                    f"{selected_location.value} was also a preferred "
                    "location and preference was available as a "
                    "tie-breaker."
                
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
        )

    @staticmethod
    def _candidate_sort_key(
        location: LocationName,
        eligibility: EligibilityResult,
        targets: Mapping[LocationName, Decimal],
        assigned_weights: Mapping[LocationName, Decimal],
    ) -> tuple[Decimal, bool, int, str]:
        """
        Rank an eligible location.

        Lower tuple values win. Negating the deficit causes the location
        furthest below its target to sort first.
        """
        deficit = targets[location] - assigned_weights[location]

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

    def _build_location_summaries(
        self,
        targets: Mapping[LocationName, Decimal],
        assigned_weights: Mapping[LocationName, Decimal],
        assigned_counts: Mapping[LocationName, int],
    ) -> dict[LocationName, LocationSortingSummary]:
        """Build final statistics for all five locations."""
        summaries: dict[
            LocationName,
            LocationSortingSummary,
        ] = {}

        for location in LocationName:
            capability = (
                self.eligibility_service.staffing_context
                .get_location_capability(location)
            )

            summaries[location] = LocationSortingSummary(
                location=location,
                number_of_pathologists=(
                    capability.number_of_pathologists
                ),
                target_weight=targets[location],
                accession_count=assigned_counts[location],
                assigned_weight=assigned_weights[location],
            )

        return summaries