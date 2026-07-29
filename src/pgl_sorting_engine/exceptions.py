"""Custom exceptions raised by the PGL Sorting Engine."""

from dataclasses import dataclass


class SortingEngineError(Exception):
    """Base exception for expected sorting-engine errors."""


class ConfigurationError(SortingEngineError):
    """Raised when routing configuration is invalid."""


class DuplicateRuleError(ConfigurationError):
    """Raised when multiple rules exist for the same code."""


class UnknownCaseTypeError(SortingEngineError):
    """Raised when an accession contains an unrecognized case type."""


class UnknownPrefixError(SortingEngineError):
    """Raised when an accession contains an unrecognized prefix."""


class DuplicatePathologistError(ConfigurationError):
    """Raised when a pathologist ID appears more than once in the roster."""


class DuplicateStaffingLocationError(ConfigurationError):
    """Raised when a location has multiple staffing records for one day."""


class MultipleLocationAssignmentError(ConfigurationError):
    """Raised when one pathologist is assigned to multiple locations."""


class UnknownPathologistError(ConfigurationError):
    """Raised when staffing references an unknown pathologist."""


class UnknownHospitalError(SortingEngineError):
    """Raised when an accession references an unconfigured hospital."""


class RoutingConflictError(ConfigurationError):
    """Raised when mandatory routing rules conflict with one another."""


class DuplicateAccessionError(SortingEngineError):
    """Raised when a sorting run contains duplicate accession numbers."""


@dataclass(frozen=True, slots=True)
class SpreadsheetIssue:
    """One validation problem found in an Excel workbook."""

    workbook: str
    sheet: str | None
    row_number: int | None
    message: str

    def __str__(self) -> str:
        """Return a human-readable workbook location and message."""
        location = self.workbook

        if self.sheet is not None:
            location = f"{location} / {self.sheet}"

        if self.row_number is not None:
            location = f"{location} row {self.row_number}"

        return f"{location}: {self.message}"


class SpreadsheetValidationError(ConfigurationError):
    """Raised when one or both input workbooks contain problems."""

    def __init__(
        self,
        issues: tuple[SpreadsheetIssue, ...],
    ) -> None:
        self.issues = issues

        issue_text = "\n".join(
            f"- {issue}"
            for issue in issues
        )

        super().__init__(
            f"Spreadsheet validation failed:\n{issue_text}"
        )