"""Generate Excel templates for the PGL Sorting Engine."""

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.comments import Comment  # type: ignore[import-untyped]
from openpyxl.styles import (  # type: ignore[import-untyped]
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import (  # type: ignore[import-untyped]
    get_column_letter,
    quote_sheetname,
)
from openpyxl.worksheet.datavalidation import (  # type: ignore[import-untyped]
    DataValidation,
)
from openpyxl.worksheet.table import (  # type: ignore[import-untyped]
    Table,
    TableStyleInfo,
)

CONFIGURATION_FILENAME = "sorting_configuration.xlsx"
DAILY_FILENAME = "daily_sorting.xlsx"

MAX_INPUT_ROW = 1000

LOCATIONS = (
    "OLOL",
    "BRG",
    "WH",
    "MET",
    "TEXAS",
    "OMEGA",
)

REQUIREMENTS = (
    "required",
    "preferred",
    "not_required",
)

HEADER_FILL = PatternFill(
    fill_type="solid",
    fgColor="1F4E78",
)

SUBHEADER_FILL = PatternFill(
    fill_type="solid",
    fgColor="D9EAF7",
)

NOTE_FILL = PatternFill(
    fill_type="solid",
    fgColor="FFF2CC",
)

WHITE_FONT = Font(
    color="FFFFFF",
    bold=True,
)

TITLE_FONT = Font(
    size=18,
    bold=True,
    color="1F4E78",
)

SECTION_FONT = Font(
    size=12,
    bold=True,
    color="1F4E78",
)

THIN_GRAY_BORDER = Border(
    bottom=Side(
        style="thin",
        color="B7B7B7",
    )
)


def create_sorting_templates(
    output_directory: str | Path,
) -> tuple[Path, Path]:
    """
    Create configuration and daily sorting workbook templates.

    Args:
        output_directory: Directory where both workbooks will be saved.

    Returns:
        Paths to the configuration and daily workbooks.
    """
    output_path = Path(output_directory).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    configuration_path = output_path / CONFIGURATION_FILENAME
    daily_path = output_path / DAILY_FILENAME

    create_configuration_template(configuration_path)
    create_daily_template(daily_path)

    return configuration_path, daily_path


def create_configuration_template(
    output_path: str | Path,
) -> Path:
    """
    Create the stable sorting-configuration workbook.

    The workbook contains:

    * Pathologists
    * CaseTypes
    * Prefixes
    * Hospitals
    """
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()

    instructions = workbook.active
    instructions.title = "Instructions"

    pathologists = workbook.create_sheet("Pathologists")
    case_types = workbook.create_sheet("CaseTypes")
    prefixes = workbook.create_sheet("Prefixes")
    hospitals = workbook.create_sheet("Hospitals")
    lists = workbook.create_sheet("Lists")

    _build_configuration_instructions(instructions)
    _build_configuration_lists(lists)

    _configure_input_sheet(
        worksheet=pathologists,
        headers=(
            "pathologist_id",
            "display_name",
            "subspecialties",
        ),
        widths=(18, 28, 36),
        table_name="PathologistsTable",
        tab_color="5B9BD5",
    )

    _configure_input_sheet(
        worksheet=case_types,
        headers=(
            "case_type",
            "subspecialty",
            "requirement",
        ),
        widths=(16, 28, 20),
        table_name="CaseTypesTable",
        tab_color="70AD47",
    )

    _configure_input_sheet(
        worksheet=prefixes,
        headers=(
            "prefix",
            "allowed_locations",
            "required_location",
            "preferred_locations",
        ),
        widths=(14, 34, 22, 34),
        table_name="PrefixesTable",
        tab_color="ED7D31",
    )

    _configure_input_sheet(
        worksheet=hospitals,
        headers=(
            "hospital",
            "allowed_locations",
            "required_location",
        ),
        widths=(34, 34, 22),
        table_name="HospitalsTable",
        tab_color="A5A5A5",
    )

    _add_two_letter_validation(
        worksheet=case_types,
        cell_range=f"A2:A{MAX_INPUT_ROW}",
        field_name="case type",
    )

    _add_two_letter_validation(
        worksheet=prefixes,
        cell_range=f"A2:A{MAX_INPUT_ROW}",
        field_name="prefix",
    )

    location_formula = (
        f"{quote_sheetname('Lists')}!"
        f"$A$2:$A${len(LOCATIONS) + 1}"
    )
    requirement_formula = (
        f"{quote_sheetname('Lists')}!$B$2:$B$4"
    )

    _add_list_validation(
        worksheet=case_types,
        cell_range=f"C2:C{MAX_INPUT_ROW}",
        formula=requirement_formula,
        prompt="Select required, preferred, or not_required.",
        error="Select a valid subspecialty requirement.",
    )

    _add_list_validation(
        worksheet=prefixes,
        cell_range=f"C2:C{MAX_INPUT_ROW}",
        formula=location_formula,
        prompt="Select a required location or leave blank.",
        error="Select a valid location.",
    )

    _add_list_validation(
        worksheet=hospitals,
        cell_range=f"C2:C{MAX_INPUT_ROW}",
        formula=location_formula,
        prompt="Select a required location or leave blank.",
        error="Select a valid location.",
    )

    _add_configuration_comments(
        pathologists=pathologists,
        case_types=case_types,
        prefixes=prefixes,
        hospitals=hospitals,
    )

    lists.sheet_state = "hidden"

    workbook.save(path)
    return path


def create_daily_template(
    output_path: str | Path,
) -> Path:
    """
    Create the workbook used for one morning's sorting run.

    The workbook contains:

    * Accessions
    * Staffing
    """
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()

    instructions = workbook.active
    instructions.title = "Instructions"

    accessions = workbook.create_sheet("Accessions")
    staffing = workbook.create_sheet("Staffing")
    lists = workbook.create_sheet("Lists")

    _build_daily_instructions(instructions)
    _build_daily_lists(lists)

    _configure_input_sheet(
        worksheet=accessions,
        headers=(
            "accession_number",
            "prefix",
            "case_type",
            "hospital",
            "weight",
        ),
        widths=(24, 14, 14, 34, 14),
        table_name="AccessionsTable",
        tab_color="4472C4",
    )

    _configure_input_sheet(
        worksheet=staffing,
        headers=(
            "location",
            "pathologist_id",
        ),
        widths=(18, 22),
        table_name="StaffingTable",
        tab_color="70AD47",
    )

    _add_two_letter_validation(
        worksheet=accessions,
        cell_range=f"B2:B{MAX_INPUT_ROW}",
        field_name="prefix",
    )

    _add_two_letter_validation(
        worksheet=accessions,
        cell_range=f"C2:C{MAX_INPUT_ROW}",
        field_name="case type",
    )

    _add_positive_decimal_validation(
        worksheet=accessions,
        cell_range=f"E2:E{MAX_INPUT_ROW}",
    )

    location_formula = (
        f"{quote_sheetname('Lists')}!"
        f"$A$2:$A${len(LOCATIONS) + 1}"
    )

    _add_list_validation(
        worksheet=staffing,
        cell_range=f"A2:A{MAX_INPUT_ROW}",
        formula=location_formula,
        prompt="Select the pathologist's location for today.",
        error="Select a valid sorting location.",
    )

    accessions["E2"].number_format = "0.00"

    accessions["A1"].comment = Comment(
        "Enter each accession number only once.",
        "PGL Sorting Engine",
    )
    accessions["B1"].comment = Comment(
        "Enter the configured two-letter prefix.",
        "PGL Sorting Engine",
    )
    accessions["C1"].comment = Comment(
        "Enter the configured two-letter case type.",
        "PGL Sorting Engine",
    )
    accessions["D1"].comment = Comment(
        "Hospital name must match the configuration workbook.",
        "PGL Sorting Engine",
    )
    accessions["E1"].comment = Comment(
        "Enter a positive numeric workload weight.",
        "PGL Sorting Engine",
    )
    staffing["B1"].comment = Comment(
        "Pathologist ID must match the configuration workbook.",
        "PGL Sorting Engine",
    )

    lists.sheet_state = "hidden"

    workbook.save(path)
    return path


def _configure_input_sheet(
    worksheet: Any,
    headers: tuple[str, ...],
    widths: tuple[int, ...],
    table_name: str,
    tab_color: str,
) -> None:
    """Apply the common layout used by an editable input worksheet."""
    worksheet.sheet_view.showGridLines = False
    worksheet.freeze_panes = "A2"
    worksheet.sheet_properties.tabColor = tab_color

    worksheet.append(list(headers))
    worksheet.append([None] * len(headers))

    for cell in worksheet[1]:
        cell.fill = HEADER_FILL
        cell.font = WHITE_FONT
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
        )
        cell.border = THIN_GRAY_BORDER

    worksheet.row_dimensions[1].height = 24
    worksheet.row_dimensions[2].height = 20

    for column_number, width in enumerate(widths, start=1):
        column_letter = get_column_letter(column_number)
        worksheet.column_dimensions[column_letter].width = width

    last_column = get_column_letter(len(headers))
    table_reference = f"A1:{last_column}2"

    table = Table(
        displayName=table_name,
        ref=table_reference,
    )
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )

    worksheet.add_table(table)

    


def _add_list_validation(
    worksheet: Any,
    cell_range: str,
    formula: str,
    prompt: str,
    error: str,
) -> None:
    """Add single-choice dropdown validation to a range."""
    validation = DataValidation(
        type="list",
        formula1=formula,
        allow_blank=True,
        showDropDown=False,
        showInputMessage=True,
        showErrorMessage=True,
        errorStyle="stop",
    )
    validation.promptTitle = "PGL Sorting Engine"
    validation.prompt = prompt
    validation.errorTitle = "Invalid value"
    validation.error = error

    worksheet.add_data_validation(validation)
    validation.add(cell_range)


def _add_two_letter_validation(
    worksheet: Any,
    cell_range: str,
    field_name: str,
) -> None:
    """Require exactly two characters when a code is entered."""
    validation = DataValidation(
        type="textLength",
        operator="equal",
        formula1="2",
        allow_blank=True,
        showInputMessage=True,
        showErrorMessage=True,
        errorStyle="stop",
    )
    validation.promptTitle = "Two-letter code"
    validation.prompt = (
        f"Enter the configured two-letter {field_name}."
    )
    validation.errorTitle = "Invalid code"
    validation.error = (
        f"The {field_name} must contain exactly two characters."
    )

    worksheet.add_data_validation(validation)
    validation.add(cell_range)


def _add_positive_decimal_validation(
    worksheet: Any,
    cell_range: str,
) -> None:
    """Require a positive numeric workload weight."""
    validation = DataValidation(
        type="decimal",
        operator="greaterThan",
        formula1="0",
        allow_blank=True,
        showInputMessage=True,
        showErrorMessage=True,
        errorStyle="stop",
    )
    validation.promptTitle = "Accession weight"
    validation.prompt = "Enter a numeric weight greater than zero."
    validation.errorTitle = "Invalid weight"
    validation.error = "Weight must be a number greater than zero."

    worksheet.add_data_validation(validation)
    validation.add(cell_range)


def _build_configuration_lists(worksheet: Any) -> None:
    """Populate validation choices for the configuration workbook."""
    worksheet["A1"] = "Locations"
    worksheet["B1"] = "Requirements"

    for row_number, location in enumerate(LOCATIONS, start=2):
        worksheet.cell(
            row=row_number,
            column=1,
            value=location,
        )

    for row_number, requirement in enumerate(
        REQUIREMENTS,
        start=2,
    ):
        worksheet.cell(
            row=row_number,
            column=2,
            value=requirement,
        )


def _build_daily_lists(worksheet: Any) -> None:
    """Populate validation choices for the daily workbook."""
    worksheet["A1"] = "Locations"

    for row_number, location in enumerate(LOCATIONS, start=2):
        worksheet.cell(
            row=row_number,
            column=1,
            value=location,
        )


def _add_configuration_comments(
    pathologists: Any,
    case_types: Any,
    prefixes: Any,
    hospitals: Any,
) -> None:
    """Explain fields that accept delimited lists or special values."""
    pathologists["A1"].comment = Comment(
        "Use a short unique identifier for each pathologist.",
        "PGL Sorting Engine",
    )
    pathologists["C1"].comment = Comment(
        "Separate multiple subspecialties with semicolons. "
        "Example: GI; LIVER",
        "PGL Sorting Engine",
    )

    case_types["A1"].comment = Comment(
        "The two-letter case type received from the LIS.",
        "PGL Sorting Engine",
    )
    case_types["B1"].comment = Comment(
        "Leave blank only when requirement is not_required.",
        "PGL Sorting Engine",
    )
    case_types["C1"].comment = Comment(
        "required: specialty must be present. "
        "preferred: specialty is favored. "
        "not_required: specialty does not affect eligibility.",
        "PGL Sorting Engine",
    )

    prefixes["B1"].comment = Comment(
        "Separate multiple locations with semicolons. "
        "Example: OLOL; BRG; MET",
        "PGL Sorting Engine",
    )
    prefixes["C1"].comment = Comment(
        "Optional hard destination. It must also appear in "
        "allowed_locations.",
        "PGL Sorting Engine",
    )
    prefixes["D1"].comment = Comment(
        "Optional ordered preferences separated by semicolons.",
        "PGL Sorting Engine",
    )

    hospitals["B1"].comment = Comment(
        "Separate multiple locations with semicolons.",
        "PGL Sorting Engine",
    )
    hospitals["C1"].comment = Comment(
        "Optional hard destination. Omega Hospital may use OMEGA here.",
        "PGL Sorting Engine",
    )


def _build_configuration_instructions(
    worksheet: Any,
) -> None:
    """Create the configuration-workbook instruction sheet."""
    worksheet.sheet_view.showGridLines = False
    worksheet.column_dimensions["A"].width = 24
    worksheet.column_dimensions["B"].width = 88

    worksheet.merge_cells("A1:B1")
    worksheet["A1"] = "PGL Sorting Engine — Configuration Workbook"
    worksheet["A1"].font = TITLE_FONT
    worksheet["A1"].alignment = Alignment(
        vertical="center",
    )
    worksheet.row_dimensions[1].height = 30

    rows = (
        (
            "Purpose",
            "Stores stable pathologist and routing configuration. "
            "This file should not be replaced each morning.",
        ),
        (
            "Pathologists",
            "One row per pathologist. Separate multiple "
            "subspecialties with semicolons.",
        ),
        (
            "CaseTypes",
            "Maps each two-letter case type to its subspecialty "
            "requirement.",
        ),
        (
            "Prefixes",
            "Defines allowed, required, and preferred work locations "
            "for each two-letter prefix.",
        ),
        (
            "Hospitals",
            "Defines which work locations may receive cases from each "
            "originating hospital.",
        ),
        (
            "Important",
            "Do not rename sheets or column headings. Hospital names, "
            "prefixes, case types, and pathologist IDs must match the "
            "values used in the daily workbook.",
        ),
        (
            "Multiple values",
            "Use semicolons between multiple values, for example: "
            "OLOL; BRG; MET",
        ),
    )

    _write_instruction_rows(
        worksheet=worksheet,
        starting_row=3,
        rows=rows,
    )

    worksheet["A12"] = "Allowed locations"
    worksheet["A12"].font = SECTION_FONT
    worksheet["B12"] = "; ".join(LOCATIONS)

    worksheet["A14"] = "Requirement values"
    worksheet["A14"].font = SECTION_FONT
    worksheet["B14"] = "; ".join(REQUIREMENTS)


def _build_daily_instructions(
    worksheet: Any,
) -> None:
    """Create the daily-workbook instruction sheet."""
    worksheet.sheet_view.showGridLines = False
    worksheet.column_dimensions["A"].width = 24
    worksheet.column_dimensions["B"].width = 88

    worksheet.merge_cells("A1:B1")
    worksheet["A1"] = "PGL Sorting Engine — Daily Workbook"
    worksheet["A1"].font = TITLE_FONT
    worksheet["A1"].alignment = Alignment(
        vertical="center",
    )
    worksheet.row_dimensions[1].height = 30

    rows = (
        (
            "Purpose",
            "Contains the accessions and pathologist staffing for one "
            "morning's sorting run.",
        ),
        (
            "Accessions",
            "Enter one row per accession. Accession numbers must be "
            "unique.",
        ),
        (
            "Staffing",
            "Enter one row per pathologist working that day. A location "
            "may appear on multiple rows.",
        ),
        (
            "Pathologist IDs",
            "Each ID must exist in the Pathologists sheet of the "
            "configuration workbook.",
        ),
        (
            "Routing values",
            "Prefix, case type, and hospital must exactly match the "
            "configuration workbook.",
        ),
        (
            "Privacy",
            "Do not include patient names or other unnecessary protected "
            "health information.",
        ),
        (
            "Important",
            "Do not rename sheets or column headings.",
        ),
    )

    _write_instruction_rows(
        worksheet=worksheet,
        starting_row=3,
        rows=rows,
    )

    worksheet["A12"] = "Sorting locations"
    worksheet["A12"].font = SECTION_FONT
    worksheet["B12"] = "; ".join(LOCATIONS)


def _write_instruction_rows(
    worksheet: Any,
    starting_row: int,
    rows: tuple[tuple[str, str], ...],
) -> None:
    """Write consistently formatted instruction rows."""
    for row_number, (heading, description) in enumerate(
        rows,
        start=starting_row,
    ):
        heading_cell = worksheet.cell(
            row=row_number,
            column=1,
            value=heading,
        )
        description_cell = worksheet.cell(
            row=row_number,
            column=2,
            value=description,
        )

        heading_cell.font = SECTION_FONT
        heading_cell.fill = SUBHEADER_FILL
        heading_cell.alignment = Alignment(
            vertical="top",
        )

        description_cell.alignment = Alignment(
            vertical="top",
            wrap_text=True,
        )

        heading_cell.border = THIN_GRAY_BORDER
        description_cell.border = THIN_GRAY_BORDER

        worksheet.row_dimensions[row_number].height = 38

    warning_row = starting_row + len(rows) - 1
    worksheet.cell(
        row=warning_row,
        column=1,
    ).fill = NOTE_FILL
    worksheet.cell(
        row=warning_row,
        column=2,
    ).fill = NOTE_FILL


def _build_argument_parser() -> ArgumentParser:
    """Create the command-line argument parser."""
    parser = ArgumentParser(
        description=(
            "Create blank Excel templates for the "
            "PGL Sorting Engine."
        )
    )
    parser.add_argument(
        "--output-dir",
        default="templates",
        help=(
            "Directory where sorting_configuration.xlsx and "
            "daily_sorting.xlsx will be created."
        ),
    )
    return parser


def main() -> None:
    """Generate both templates from the command line."""
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    configuration_path, daily_path = create_sorting_templates(
        arguments.output_dir
    )

    print(f"Created: {configuration_path}")
    print(f"Created: {daily_path}")


if __name__ == "__main__":
    main()