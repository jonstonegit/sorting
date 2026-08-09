"""Tests for non-visual GUI helpers."""

from datetime import date
from pathlib import Path

from pgl_sorting_engine import gui


def test_preferences_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    expected = gui.GuiPreferences(
        configuration_path="C:/PGL/sorting_configuration.xlsx",
        daily_path="C:/PGL/daily_sorting.xlsx",
        output_directory="C:/PGL/output",
    )

    gui.save_preferences(expected, path)

    assert gui.load_preferences(path) == expected


def test_invalid_preferences_return_defaults(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert gui.load_preferences(path) == gui.GuiPreferences()


def test_build_report_path_appends_date(tmp_path: Path) -> None:
    output = gui.build_report_path(
        tmp_path,
        run_date=date(2026, 8, 9),
    )

    assert output == (
        tmp_path / "sorting_results_2026-08-09.xlsx"
    )


def test_find_initial_file_prefers_remembered_path(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "sorting_configuration.xlsx"
    workbook.touch()

    assert gui.find_initial_file(
        "sorting_configuration.xlsx",
        str(workbook),
    ) == str(workbook)
