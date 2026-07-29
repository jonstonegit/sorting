"""Custom exceptions raised by the PGL Sorting Engine."""


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