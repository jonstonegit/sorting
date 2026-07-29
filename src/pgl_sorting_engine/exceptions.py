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