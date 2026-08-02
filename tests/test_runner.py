"""Tests for the pgl-sort command runner."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from pgl_sorting_engine import runner


def test_run_sorting_loads_runs_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import MappingProxyType

    from pgl_sorting_engine import SortingRunResult

    result = SortingRunResult(
        input_accession_count=0,
        assignments=(),
        unassigned_accessions=(),
        location_summaries=MappingProxyType({}),
    )
    engine = SimpleNamespace(run=lambda accessions: result)
    data = SimpleNamespace(
        accessions=("accession",),
        build_engine=lambda: engine,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        runner,
        "load_sorting_workbooks",
        lambda configuration_path, daily_path: data,
    )

    def fake_report(received_result: object, output_path: Path) -> Path:
        captured["result"] = received_result
        captured["output_path"] = output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.touch()
        return output_path

    monkeypatch.setattr(runner, "create_sorting_report", fake_report)
    output_path = tmp_path / "output" / "sorting_results.xlsx"

    returned_result = runner.run_sorting(
        configuration_path="configuration.xlsx",
        daily_path="daily.xlsx",
        output_path=output_path,
    )

    assert returned_result is result
    assert captured["result"] is result
    assert captured["output_path"] == output_path
    assert output_path.exists()

def test_add_date_to_output_path() -> None:
    output_path = runner.add_date_to_output_path(
        "output/sorting_results.xlsx",
        run_date=date(2026, 8, 2),
    )

    assert output_path == Path(
        "output/sorting_results_2026-08-02.xlsx"
    )

def test_run_sorting_requires_force_to_replace_output(tmp_path: Path) -> None:
    output_path = tmp_path / "sorting_results.xlsx"
    output_path.touch()

    with pytest.raises(FileExistsError, match="--force"):
        runner.run_sorting(
            configuration_path="configuration.xlsx",
            daily_path="daily.xlsx",
            output_path=output_path,
        )
