"""Command-line runner for the PGL Sorting Engine."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from pgl_sorting_engine.assignment import SortingRunResult
from pgl_sorting_engine.excel_loader import load_sorting_workbooks
from pgl_sorting_engine.exceptions import SortingEngineError
from pgl_sorting_engine.reporting import create_sorting_report


def run_sorting(
    configuration_path: str | Path,
    daily_path: str | Path,
    output_path: str | Path,
    *,
    force: bool = False,
) -> SortingRunResult:
    """Load, sort, and write one daily Excel results workbook."""
    destination = Path(output_path)

    if destination.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {destination}. "
            "Use --force to replace it."
        )

    data = load_sorting_workbooks(
        configuration_path=configuration_path,
        daily_path=daily_path,
    )
    result = data.build_engine().run(data.accessions)
    create_sorting_report(result, destination)
    return result


def add_date_to_output_path(
    output_path: str | Path,
    *,
    run_date: date | None = None,
) -> Path:
    """Append the sorting date to an output workbook filename."""
    path = Path(output_path)
    sorting_date = run_date or date.today()

    return path.with_name(
        f"{path.stem}_{sorting_date:%Y-%m-%d}{path.suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the pgl-sort command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="pgl-sort",
        description=(
            "Sort pathology accessions and create an Excel results report."
        ),
    )
    parser.add_argument(
        "--configuration",
        required=True,
        type=Path,
        help="Path to sorting_configuration.xlsx.",
    )
    parser.add_argument(
        "--daily",
        required=True,
        type=Path,
        help="Path to daily_sorting.xlsx.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help=(
            "Base output path. The sorting date will be appended "
            "to the filename."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the output workbook if it already exists.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line sorting workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)

    dated_output_path = add_date_to_output_path(
        args.output
    )

    try:
        result = run_sorting(
            configuration_path=args.configuration,
            daily_path=args.daily,
            output_path=dated_output_path,
            force=args.force,
        )

    except (FileExistsError, OSError, SortingEngineError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created: {dated_output_path}")
    print(f"Assigned accessions: {result.assigned_accession_count}")
    print(f"Unassigned accessions: {result.unassigned_accession_count}")
    print(f"Assigned weight: {result.total_assigned_weight}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
