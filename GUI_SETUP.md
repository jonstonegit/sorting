# PGL Sorting Engine GUI

This package adds a Tkinter desktop interface without changing the sorting logic.

## Files to copy

Copy:

```text
src/pgl_sorting_engine/gui.py
tests/test_gui.py
pyproject.toml
build_windows_gui.bat
```

into the corresponding locations in the repository.

`pyproject.toml` adds:

```text
pgl-sort-gui
```

and the optional `gui-build` dependency containing PyInstaller.

## Test locally in the existing development environment

From the project root:

```bash
pip install -e .
pytest
ruff check . --fix
ruff check .
mypy src
pgl-sort-gui
```

When developing under WSL, the Tkinter window may require WSLg. If the GUI cannot display there, run it with a normal Windows Python installation instead.

## GUI workflow

The end user:

1. Chooses `sorting_configuration.xlsx`.
2. Chooses `daily_sorting.xlsx`.
3. Chooses the report output folder.
4. Clicks **Run Sorting**.
5. Opens the dated Excel results workbook with **Open Results**.

The GUI remembers the last paths used.

If today's report already exists, the user is asked whether it should be replaced.

## Build a Windows executable

PyInstaller must be run from Windows to create a Windows `.exe`. Do not build the distributable executable from WSL/Linux.

On a Windows computer:

1. Install Python 3.11 or newer.
2. Copy or clone the repository to Windows.
3. Double-click:

```text
build_windows_gui.bat
```

or run it from Command Prompt.

The finished executable is:

```text
dist\PGL_Sorting_Engine.exe
```

The end user does not need VS Code, Git, a command prompt, or knowledge of `pgl-sort`.

## Operational recommendation

Keep the stable configuration workbook in a controlled shared folder and give the user write access only if they are expected to edit routing rules.

Do not place production accession workbooks or generated reports in the Git repository.
