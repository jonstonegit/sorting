# PGL Sorting Engine

A rules-based Python application for assigning daily pathology accessions to work locations based on:

- accession prefix
- case type and subspecialty requirements
- originating facility
- daily pathologist staffing
- configurable routing overrides
- location-specific business rules
- weighted workload balancing

The application uses a stable Excel configuration workbook plus a daily Excel input workbook and produces a dated Excel results report containing assignments, workload summaries, routing audit details, unassigned cases, routing-override matches, and distribution grids.

The sorter can be run either through:

1. the **Tkinter desktop GUI** for normal daily use, or
2. the **command-line interface (CLI)** for development, testing, and automation.

---

## Supported Locations

- `OLOL`
- `BRG`
- `WH`
- `MET`
- `TEXAS`
- `OMEGA`

---

## How the Sorter Works

Assignments are evaluated using staffing, eligibility, configured routing rules, and workload balance.

### TEXAS

- All `DP` and `DS` cases are assigned to `TEXAS`.
- TEXAS does not have a workload target.
- TEXAS does not participate in ordinary balanced assignment.
- If TEXAS has no staffed pathologist, affected cases are left unassigned for review.

### OMEGA

- When exactly one pathologist is staffed at OMEGA, all cases originating from `Omega Hospital` are assigned to OMEGA.
- OMEGA takes no other cases in that state.
- When OMEGA does not have exactly one staffed pathologist, OMEGA receives no cases.
- Omega Hospital cases then continue through the normal routing process.

### MET

MET has a configurable workload target:

```text
MET target = number of MET pathologists × met_weight_per_pathologist
```

`met_weight_per_pathologist` is maintained in the configuration workbook.

MET uses a soft target for ordinary target-based routing. If MET is below its target, the next eligible case may be assigned even if that case causes the total to cross the target. Once MET is at or above target, additional flexible target-based assignments stop.

Mandatory routing can still cause MET to exceed its normal target.

### OLOL, BRG, and WH

Remaining eligible work is balanced among OLOL, BRG, and WH in proportion to the number of pathologists working at each location.

The goal is to keep effective workload per pathologist approximately equal.

WH begins with a configurable starting weight before new cases are distributed.

### Routing Priority

The engine generally evaluates routing in this order:

1. TEXAS special DP/DS rule
2. OMEGA special staffing rule
3. hospital/facility-specific routing override
4. general prefix/case-type routing override
5. configured mandatory hospital/facility and prefix routing
6. override-based preference routing
7. MET target-based allocation
8. OLOL/BRG/WH proportional workload balancing

Core eligibility rules still apply unless a special hard-coded business rule explicitly controls the case.

---

# Requirements

## Source-code use

- Python 3.11 or later
- `openpyxl`
- Tkinter for the desktop GUI
- Excel or another compatible application for editing `.xlsx` files

Development tools:

- `pytest`
- `ruff`
- `mypy`

Windows executable builds also use:

- `PyInstaller`

## Standalone Windows executable

A PyInstaller-built `PGL_Sorting_Engine.exe` is intended for normal end-user deployment.

The daily end user does not need:

- Python
- VS Code
- WSL
- Git
- a Python virtual environment
- command-line knowledge

Microsoft Excel is recommended because the workflow uses Excel input and output workbooks.

---

# Installation for Development

Clone the repository:

```bash
git clone https://github.com/jonstonegit/sorting.git
cd sorting
```

Create a virtual environment:

```bash
python -m venv .venv
```

On Linux/WSL, activate it with:

```bash
source .venv/bin/activate
```

Install the project and development dependencies:

```bash
pip install -e ".[dev]"
```

Confirm the installed commands:

```bash
which pgl-create-templates
which pgl-sort
which pgl-sort-gui
```

On Windows, equivalent commands can be located in the virtual environment's `Scripts` directory.

---

# Excel Input Workbooks

The project uses two separate workbooks.

## 1. `sorting_configuration.xlsx`

This is the stable configuration workbook. It should normally be maintained over time rather than recreated for each sorting run.

### `Pathologists`

| Column | Description |
|---|---|
| `pathologist_id` | Unique pathologist identifier/initials |
| `display_name` | Name displayed for the pathologist |
| `subspecialties` | Semicolon-separated subspecialties covered by the pathologist |

### `CaseTypes`

| Column | Description |
|---|---|
| `case_type` | Two-letter case type code |
| `subspecialty` | Associated subspecialty |
| `requirement` | `required`, `preferred`, or `not_required` |

### `Prefixes`

| Column | Description |
|---|---|
| `prefix` | Two-letter accession prefix |
| `allowed_locations` | Semicolon-separated eligible locations |
| `required_location` | Mandatory destination, when applicable |
| `preferred_locations` | Semicolon-separated preferred destinations |

### `Hospitals`

| Column | Description |
|---|---|
| `hospital` | Exact originating facility name used by the input data |
| `allowed_locations` | Semicolon-separated eligible locations |
| `required_location` | Mandatory destination, when applicable |

### `AssignmentSettings`

| Column | Description |
|---|---|
| `met_weight_per_pathologist` | MET target weight for each staffed pathologist |
| `wh_starting_weight` | Starting workload assigned to WH before new cases are distributed |

Current template defaults are:

```text
met_weight_per_pathologist = 200
wh_starting_weight = 400
```

TEXAS and OMEGA business rules are fixed in Python and are not configured in `AssignmentSettings`.

### `RoutingOverrides`

Routing overrides allow specific hospital/facility, prefix, and case-type combinations to modify normal routing.

| Column | Description |
|---|---|
| `rule_name` | Descriptive name for the rule |
| `hospital` | Optional exact facility match; blank means the rule is general |
| `prefix` | Two-letter prefix |
| `case_type` | Two-letter case type |
| `routing_mode` | Override behavior |
| `destination_location` | Destination used by modes that require one |
| `preferred_locations` | Ordered semicolon-separated preferred locations |
| `required_subspecialty` | Optional subspecialty condition |
| `weight_cap` | Optional rule-specific weight cap |

Supported routing modes:

- `identify_only`
- `always_required`
- `required_if_subspecialist_present`
- `preferred`
- `preferred_until_target`
- `preferred_until_weight_cap`

A hospital/facility-specific override takes priority over a general prefix/case-type override for the same case.

`preferred_until_weight_cap` uses a strict rule-specific cap. If assigning the next matching case would exceed the cap, that preference is no longer used for that case and normal routing continues.

---

## 2. `daily_sorting.xlsx`

This workbook is completed for each sorting run.

### `Accessions`

| Column | Description |
|---|---|
| `accession_number` | Unique accession number |
| `prefix` | Configured two-letter prefix |
| `case_type` | Configured two-letter case type |
| `hospital` | Configured originating facility |
| `weight` | Positive numeric workload weight |

Accession numbers must be unique within a daily run.

### `Staffing`

The current daily staffing layout uses one row for each sorting location with pathologist selections across the row.

Example:

| location | pathologist_1 | pathologist_2 | pathologist_3 | pathologist_4 |
|---|---|---|---|---|
| OLOL | JS | AB |  |  |
| BRG | CD | EF | GH |  |
| WH | IJ | KL |  |  |
| MET | MN |  |  |  |
| TEXAS | OP |  |  |  |
| OMEGA |  |  |  |  |

Pathologist cells use dropdown lists sourced from the IDs in `sorting_configuration.xlsx`.

Unused staffing cells may be left blank. MET and OMEGA may have no staffed pathologist.

A pathologist may be assigned to only one location in a daily workbook.

The loader also supports the earlier two-column staffing format for backward compatibility.

---

# Creating or Refreshing Templates

## Create both workbooks from scratch

For a new installation:

```bash
pgl-create-templates --output-dir templates
```

This creates:

```text
templates/sorting_configuration.xlsx
templates/daily_sorting.xlsx
```

**Do not routinely regenerate a populated production configuration workbook**, because doing so can overwrite configuration data.

## Refresh only the daily template

When pathologist IDs are added, removed, or changed in the configuration workbook, regenerate only the daily template so its staffing dropdowns reflect the current roster:

```bash
python -c "from pgl_sorting_engine.templates import create_daily_template; create_daily_template('templates/daily_sorting.xlsx', configuration_path='templates/sorting_configuration.xlsx')"
```

Back up any daily workbook containing data you need before replacing it.

---

# Running the Sorter

There are two supported ways to start the application.

---

## Option 1: Desktop GUI

The GUI is recommended for normal daily operations.

### Start the GUI from the Python development environment

Activate the project virtual environment:

```bash
source .venv/bin/activate
```

Then run:

```bash
pgl-sort-gui
```

The GUI can also be started directly as a Python module:

```bash
python -m pgl_sorting_engine.gui
```

### GUI workflow

The GUI provides:

- configuration workbook selection
- daily workbook selection
- report output-folder selection
- **Edit Configuration**
- **Run Sorting**
- **Open Results**
- **Open Output Folder**
- status and progress information
- assigned and unassigned accession totals
- error details when validation or sorting fails

Typical daily workflow:

1. Open **PGL Sorting Engine**.
2. Confirm or select `sorting_configuration.xlsx`.
3. Select the current `daily_sorting.xlsx`.
4. Confirm the report folder.
5. Click **Run Sorting**.
6. Review the assigned and unassigned totals.
7. Click **Open Results**.

The GUI remembers the most recently selected configuration file, daily file, and output directory.

If today's dated report already exists, the GUI asks before replacing it.

### Standalone Windows GUI

For deployment, the application can be packaged as:

```text
PGL_Sorting_Engine.exe
```

The user can launch the program by double-clicking the executable or a Windows desktop shortcut.

A typical deployment layout is:

```text
C:\PGL Sorting\
├── Application\
│   └── PGL_Sorting_Engine.exe
├── Configuration\
│   └── sorting_configuration.xlsx
├── Daily Input\
│   └── daily_sorting.xlsx
└── Reports\
    └── sorting_results_YYYY-MM-DD.xlsx
```

During development, the executable can also be kept in the PyInstaller `dist` directory.

---

## Option 2: Command-Line Interface

The CLI remains useful for development, testing, troubleshooting, and future automation.

Create an output directory if needed:

```bash
mkdir -p output
```

Run:

```bash
pgl-sort \
  --configuration templates/sorting_configuration.xlsx \
  --daily templates/daily_sorting.xlsx \
  --output output/sorting_results.xlsx
```

The date is appended automatically to the output filename.

For example:

```text
output/sorting_results_2026-08-09.xlsx
```

If that dated file already exists, the CLI will stop rather than overwrite it.

To explicitly replace an existing dated report:

```bash
pgl-sort \
  --configuration templates/sorting_configuration.xlsx \
  --daily templates/daily_sorting.xlsx \
  --output output/sorting_results.xlsx \
  --force
```

On success, the CLI prints:

- created report path
- assigned accession count
- unassigned accession count
- total assigned weight

---

# Output Workbook

Each sorting run creates a dated Excel results workbook.

The report currently contains six worksheets.

## `Summary`

Provides:

- input accession count
- assigned accession count
- unassigned accession count
- assigned and unassigned weight
- pathologist count by location
- accession count by location
- assigned weight
- starting weight
- effective weight
- target weight
- variance from target
- assigned weight per pathologist
- effective weight per pathologist

TEXAS and OMEGA display `N/A` for target-based fields because they are governed by special rules.

## `Assignments`

Contains one row for every assigned accession, including:

- accession details
- assigned location
- assignment method
- target weight
- matched routing override
- override mode
- whether the override was applied
- override destination
- override notes
- rule-specific weight-cap data
- decision notes

## `Unassigned`

Lists cases that could not be assigned safely, including:

- accession information
- error code
- summary
- detailed reason for manual review

## `Audit`

Provides detailed assignment reasoning, including:

- eligible locations
- preferred locations
- required location
- subspecialty requirement
- assigned weight before and after assignment
- target weight
- routing-override information
- eligibility notes
- assignment notes
- location exclusion reasons
- rule-specific weight-cap information

## `Routing Override Matches`

Contains assigned accessions that matched a routing override, including:

- rule name
- routing mode
- whether the override activated
- whether the override was applied
- destination
- preferences
- required subspecialty
- final assigned location
- assignment method
- rule-specific weight-cap tracking

## `Distribution Grids`

Contains weight-based grids in this order:

1. `TOTAL`
2. `OLOL`
3. `BRG`
4. `WH`
5. `MET`
6. `TEXAS`
7. `OMEGA`

Each grid displays:

- accession prefixes across columns
- case types down rows
- total assigned weight in each cell
- row totals
- column totals
- overall total

The `TOTAL` grid includes assignments from all six locations.

---

# Validation

The loader validates both workbooks before sorting.

Examples include:

- missing worksheets
- missing required columns
- duplicate accession numbers
- unknown pathologist IDs
- the same pathologist assigned to multiple locations
- unknown prefixes
- unknown case types
- unknown hospitals/facilities
- invalid location names
- invalid or nonpositive weights
- malformed assignment settings
- invalid routing modes
- invalid routing destinations
- duplicate routing overrides
- invalid routing weight caps
- conflicting routing rules

When possible, validation errors include workbook, worksheet, and row information.

Cases that cannot be safely assigned are preserved for manual review rather than silently discarded.

---

# Building the Windows Executable

The repository includes:

```text
build_windows_gui.bat
```

Build the Windows executable from a Windows Python environment rather than from Linux/WSL.

From the Windows project directory, run:

```text
build_windows_gui.bat
```

The script:

1. creates or reuses a Windows build virtual environment
2. installs the project and GUI build dependencies
3. runs PyInstaller
4. creates:

```text
dist\PGL_Sorting_Engine.exe
```

Test the packaged executable with a real configuration and daily workbook before deploying it to another workstation.

---

# Development Checks

Run the full test suite:

```bash
pytest
```

Run linting:

```bash
ruff check . --fix
ruff check .
```

Run static type checking:

```bash
mypy src
```

A normal pre-commit check is:

```bash
pytest
ruff check .
mypy src
```

---

# Updating the Windows Executable

Changes made to the Python source do not automatically update an already-built `.exe`.

After source-code changes:

1. test the updated project
2. refresh the Windows build copy
3. reinstall/update the project in the Windows build environment if needed
4. run PyInstaller again
5. replace the deployed `PGL_Sorting_Engine.exe` with the newly built version

The configuration and daily Excel workbooks should normally remain separate from the executable.

---

# Project Structure

```text
sorting/
├── src/
│   └── pgl_sorting_engine/
│       ├── __init__.py
│       ├── assignment.py
│       ├── eligibility.py
│       ├── enums.py
│       ├── excel_loader.py
│       ├── exceptions.py
│       ├── gui.py
│       ├── models.py
│       ├── reporting.py
│       ├── rules.py
│       ├── runner.py
│       ├── staffing.py
│       ├── templates.py
│       └── validation.py
├── tests/
├── templates/
├── output/
├── build_windows_gui.bat
├── pyproject.toml
└── README.md
```

---

# Data Safety

Do not commit:

- protected health information
- patient-identifying data
- production accession workbooks
- generated production reports
- passwords
- credentials
- other sensitive operational data

Generated reports and operational workbooks containing real accession data should remain outside version control.

The `output/` directory and local build artifacts should remain ignored by Git.

---

# Current Status

Implemented:

- rules-based pathology accession assignment
- stable configuration workbook
- daily accession workbook
- daily staffing configuration
- pathologist subspecialty eligibility
- hard-coded TEXAS routing
- hard-coded OMEGA staffing routing
- configurable MET target
- configurable WH starting weight
- hospital/facility and prefix routing
- configurable routing overrides
- conditional subspecialist routing
- rule-specific routing weight caps
- proportional workload balancing
- unassigned-case handling
- detailed Excel audit reporting
- routing-override reporting
- total and location-specific distribution grids
- dated output filenames
- command-line interface
- Tkinter desktop GUI
- standalone Windows executable build
- automated tests
- linting
- static type checking

Potential future enhancements:

- integration with LigoLab 
- simplified GUI-based configuration maintenance
- automatic daily-template refresh
- automated report delivery to pathologists
- additional reporting and operational integrations
