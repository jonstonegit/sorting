"""Shared validation and normalization helpers."""

from decimal import Decimal, InvalidOperation


def _normalize_required_text(value: str, field_name: str) -> str:
    """
    Strip surrounding whitespace and verify that required text is present.

    Args:
        value: Text to normalize.
        field_name: Human-readable name used in error messages.

    Returns:
        The normalized text.

    Raises:
        TypeError: If value is not a string.
        ValueError: If value is empty after normalization.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")

    return normalized


def _normalize_two_letter_code(value: str, field_name: str) -> str:
    """
    Normalize and validate a two-letter code.

    Codes are converted to uppercase so values such as ``gi`` and ``GI``
    are treated identically.
    """
    normalized = _normalize_required_text(value, field_name).upper()

    if len(normalized) != 2 or not normalized.isalpha():
        raise ValueError(
            f"{field_name} must contain exactly two letters; received {value!r}."
        )

    return normalized


def _normalize_label(value: str, field_name: str) -> str:
    """
    Normalize a configurable label.

    Surrounding whitespace is removed, repeated internal whitespace is
    collapsed, and the result is converted to uppercase.
    """
    normalized = _normalize_required_text(value, field_name)
    return " ".join(normalized.split()).upper()


def _coerce_positive_decimal(value: object, field_name: str) -> Decimal:
    """
    Convert a numeric value to a positive, finite Decimal.

    Decimal is used for accession weights so repeated workload additions
    remain predictable.
    """
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a valid numeric value; received {value!r}."
        ) from exc

    if not decimal_value.is_finite():
        raise ValueError(f"{field_name} must be finite.")

    if decimal_value <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")

    return decimal_value