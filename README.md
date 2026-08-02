# PGL Sorting Engine

A rules-based Python application for assigning daily pathology accessions to work locations based on:

* accession prefix
* case type and subspecialty requirements
* originating hospital
* daily pathologist staffing
* location-specific business rules
* weighted workload balancing

The application uses two Excel workbooks as input and produces a dated Excel report containing assignments, workload summaries, audit details, unassigned cases, and distribution grids.

## Supported Locations

* `OLOL`
* `BRG`
* `WH`
* `MET`
* `TEXAS`
* `OMEGA`

## Assignment Rules

Assignments are processed in the following order.

### TEXAS

* All `DP` and `DS` cases are assigned to `TEXAS`.
* TEXAS does not have a workload target.
* If TEXAS has no staffed pathologist, affected cases are left unassigned for review.

### OMEGA

* When exactly one pathologist is staffed at OMEGA, all cases originating from `Omega Hospital` are assigned to OMEGA.
* When the OMEGA pathologist count is not exactly one, OMEGA receives no cases.
* In that situation, Omega Hospital cases continue through the normal routing process.

### MET

* MET has a configurable workload target:

  ```text
  MET target = number of MET pathologists × met_weight_per_pathologist
  ```

* The value of `met_weight_per_pathologist` is maintained in the configuration workbook.

### OLOL, BRG, and WH

* Remaining eligible work is balanced among OLOL, BRG, and WH.
* Work is distributed in proportion to the number of pathologists assigned to each location.
* The goal is to keep effective weight per pathologist approximately equal.
* WH begins with a configurable starting weight that is included when calculating its effective workload.

## Requirements

* Python 3.11 or later
* `openpyxl`
* Excel or another compatible application for editing `.xlsx` files

Development tools:

* `pytest`
* `ruff`
* `mypy`

## Installation

Clone the repository:

```bash
git clone https://github.com/jonstonegit/sorting.git
cd sorting
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the project and development dependencies:

```bash
pip install -e ".[dev]"
```

Confirm that the command-line tools are installed:

```bash
which pgl-create-templates
which pgl-sort
```

## Excel Input Workbooks

The project uses two separate workbooks.

### 1. `sorting_configuration.xlsx`

This is the stable configuration workbook. It contains:

#### `Pathologists`

| Column           | Description                                                   |
| ---------------- | ------------------------------------------------------------- |
| `pathologist_id` | Unique pathologist identifier                                 |
| `display_name`   | Name displayed for the pathologist                            |
| `subspecialties` | Semicolon-separated subspecialties covered by the pathologist |

#### `CaseTypes`

| Column         | Description                                |
| -------------- | ------------------------------------------ |
| `case_type`    | Two-letter case type code                  |
| `subspecialty` | Associated subspecialty                    |
| `requirement`  | `required`, `preferred`, or `not_required` |

#### `Prefixes`

| Column                | Description                                |
| --------------------- | ------------------------------------------ |
| `prefix`              | Two-letter accession prefix                |
| `allowed_locations`   | Semicolon-separated eligible locations     |
| `required_location`   | Mandatory destination, when applicable     |
| `preferred_locations` | Semicolon-separated preferred destinations |

#### `Hospitals`

| Column              | Description                            |
| ------------------- | -------------------------------------- |
| `hospital`          | Exact hospital or facility name        |
| `allowed_locations` | Semicolon-separated eligible locations |
| `required_location` | Mandatory destination, when applicable |

#### `AssignmentSettings`

| Column                       | Description                                                       |
| ---------------------------- | ----------------------------------------------------------------- |
| `met_weight_per_pathologist` | MET target weight for each staffed pathologist                    |
| `wh_starting_weight`         | Starting workload assigned to WH before new cases are distributed |

TEXAS and OMEGA business rules are fixed in the Python application and are not configured in this worksheet.

### 2. `daily_sorting.xlsx`

This workbook is completed for each sorting run.

#### `Accessions`

| Column             | Description                      |
| ------------------ | -------------------------------- |
| `accession_number` | Unique accession number          |
| `prefix`           | Configured two-letter prefix     |
| `case_type`        | Configured two-letter case type  |
| `hospital`         | Configured originating hospital  |
| `weight`           | Positive numeric workload weight |

Accession numbers must be unique within a daily run.

#### `Staffing`

| Column           | Description                                |
| ---------------- | ------------------------------------------ |
| `location`       | Location where the pathologist is working  |
| `pathologist_id` | Identifier from the configuration workbook |

A pathologist may be assigned to only one location in a daily workbook.

## Create Fresh Templates

Generate both input workbooks:

```bash
pgl-create-templates --output-dir templates
```

This creates:

```text
templates/sorting_configuration.xlsx
templates/daily_sorting.xlsx
```

The configuration workbook should normally be maintained over time. The daily workbook is updated for each sorting run.

## Run the Sorter

Create an output directory:

```bash
mkdir -p output
```

Run the sorting engine:

```bash
pgl-sort \
  --configuration templates/sorting_configuration.xlsx \
  --daily templates/daily_sorting.xlsx \
  --output output/sorting_results.xlsx \
  --force
```

The date is appended automatically to the output filename. For example:

```text
output/sorting_results_2026-08-02.xlsx
```

Omit `--force` when an existing report should not be replaced.

## Output Workbook

The generated results workbook contains five sheets.

### `Summary`

Provides:

* input, assigned, and unassigned accession totals
* assigned and unassigned weight
* pathologist count by location
* assigned weight
* starting weight
* effective weight
* target weight
* variance from target
* assigned and effective weight per pathologist

TEXAS and OMEGA display `N/A` for target-based fields because they are governed by special rules.

### `Assignments`

Contains one row for every assigned accession, including:

* accession details
* assigned location
* assignment method
* location target
* decision notes

### `Unassigned`

Lists cases that could not be assigned safely, including an error code, summary, and details for manual review.

### `Audit`

Provides detailed routing information, including:

* eligible locations
* preferred locations
* required location
* subspecialty requirement
* location weight before and after assignment
* eligibility notes
* assignment notes
* location exclusion reasons

### `Distribution Grids`

Contains separate grids for:

* OLOL
* BRG
* WH
* MET

Each grid displays:

* accession prefixes across the columns
* case types down the rows
* total assigned weight in each cell
* row totals
* column totals
* overall location weight

## Validation

The loader validates both workbooks before sorting. Examples include:

* missing worksheets or required columns
* duplicate accession numbers
* unknown pathologist IDs
* a pathologist assigned to multiple locations
* unknown prefixes, case types, or hospitals
* invalid location names
* invalid or nonpositive weights
* malformed assignment settings
* conflicting routing rules

Invalid cases are reported with workbook, worksheet, and row information when available.

## Development Checks

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

## Project Structure

```text
sorting/
├── src/
│   └── pgl_sorting_engine/
│       ├── assignment.py
│       ├── eligibility.py
│       ├── enums.py
│       ├── excel_loader.py
│       ├── exceptions.py
│       ├── models.py
│       ├── reporting.py
│       ├── rules.py
│       ├── runner.py
│       ├── staffing.py
│       ├── templates.py
│       └── validation.py
├── tests/
├── templates/
├── pyproject.toml
└── README.md
```

## Data Safety

Do not commit protected health information, patient-identifying data, passwords, credentials, or production workbooks to GitHub.

Generated reports and local operational files should be kept outside version control when they contain real accession data.

## Current Status

Implemented:

* Excel template generation
* configuration and daily workbook validation
* staffing and subspecialty eligibility
* special TEXAS and OMEGA routing
* configurable MET and WH workload settings
* weighted assignment
* unassigned-case handling
* detailed Excel reporting
* dated output filenames
* automated tests, linting, and type checking

Planned:

* automated email delivery of results
* refine sorting preferences
