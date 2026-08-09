"""Tkinter desktop interface for the PGL Sorting Engine."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from tkinter import (
    BOTH,
    LEFT,
    RIGHT,
    BooleanVar,
    StringVar,
    Text,
    Tk,
    Toplevel,
    X,
    filedialog,
    messagebox,
    ttk,
)
from typing import Final

from pgl_sorting_engine.assignment import SortingRunResult
from pgl_sorting_engine.exceptions import SortingEngineError
from pgl_sorting_engine.runner import add_date_to_output_path, run_sorting

APP_TITLE: Final = "PGL Sorting Engine"
CONFIGURATION_FILENAME: Final = "sorting_configuration.xlsx"
DAILY_FILENAME: Final = "daily_sorting.xlsx"
OUTPUT_BASENAME: Final = "sorting_results.xlsx"
PREFERENCES_FILENAME: Final = "gui_preferences.json"


@dataclass(frozen=True, slots=True)
class GuiPreferences:
    """Paths remembered between GUI sessions."""

    configuration_path: str = ""
    daily_path: str = ""
    output_directory: str = ""


@dataclass(frozen=True, slots=True)
class _RunSuccess:
    """Successful worker-thread result."""

    result: SortingRunResult
    report_path: Path


@dataclass(frozen=True, slots=True)
class _RunFailure:
    """Failed worker-thread result."""

    error: Exception


_WorkerMessage = _RunSuccess | _RunFailure


def preferences_directory() -> Path:
    """Return the per-user directory used for GUI preferences."""
    appdata = os.environ.get("APPDATA")

    if sys.platform == "win32" and appdata:
        return Path(appdata) / "PGL Sorting Engine"

    return Path.home() / ".pgl_sorting_engine"


def preferences_path() -> Path:
    """Return the GUI-preferences JSON path."""
    return preferences_directory() / PREFERENCES_FILENAME


def load_preferences(path: Path | None = None) -> GuiPreferences:
    """Load remembered paths, falling back safely when unavailable."""
    source = path or preferences_path()

    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GuiPreferences()

    if not isinstance(raw, dict):
        return GuiPreferences()

    return GuiPreferences(
        configuration_path=str(raw.get("configuration_path", "") or ""),
        daily_path=str(raw.get("daily_path", "") or ""),
        output_directory=str(raw.get("output_directory", "") or ""),
    )


def save_preferences(
    preferences: GuiPreferences,
    path: Path | None = None,
) -> None:
    """Persist remembered GUI paths."""
    destination = path or preferences_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(asdict(preferences), indent=2),
        encoding="utf-8",
    )


def default_output_directory() -> Path:
    """Return a friendly default output folder for a desktop user."""
    documents = Path.home() / "Documents"

    if documents.exists():
        return documents / "PGL Sorting Reports"

    return Path.home() / "PGL Sorting Reports"


def application_search_directories() -> tuple[Path, ...]:
    """Return likely places to find the standard input workbooks."""
    directories: list[Path] = [Path.cwd()]

    if getattr(sys, "frozen", False):
        directories.append(Path(sys.executable).resolve().parent)
    else:
        directories.append(Path(__file__).resolve().parents[2])

    expanded: list[Path] = []

    for directory in directories:
        expanded.extend((directory, directory / "templates"))

    unique: list[Path] = []

    for directory in expanded:
        if directory not in unique:
            unique.append(directory)

    return tuple(unique)


def find_initial_file(
    filename: str,
    remembered_path: str = "",
) -> str:
    """Return a remembered or automatically discovered workbook path."""
    if remembered_path:
        remembered = Path(remembered_path).expanduser()

        if remembered.is_file():
            return str(remembered)

    for directory in application_search_directories():
        candidate = directory / filename

        if candidate.is_file():
            return str(candidate)

    return ""


def build_report_path(
    output_directory: str | Path,
    *,
    run_date: date | None = None,
) -> Path:
    """Build the dated report path used by both GUI and CLI workflows."""
    base_path = Path(output_directory) / OUTPUT_BASENAME
    return add_date_to_output_path(base_path, run_date=run_date)


def _running_under_wsl() -> bool:
    """Return whether the application is running inside WSL."""
    try:
        version = Path("/proc/version").read_text(
            encoding="utf-8"
        )
    except OSError:
        return False

    return "microsoft" in version.lower()


def open_path(path: str | Path) -> None:
    """Open a file or directory with the operating system."""
    target = Path(path).resolve()

    if sys.platform == "win32":
        startfile = os.startfile
        startfile(str(target))
        return

    if _running_under_wsl():
        converted = subprocess.run(
            ["wslpath", "-w", str(target)],
            check=True,
            capture_output=True,
            text=True,
        )

        windows_path = converted.stdout.strip()

        subprocess.Popen(
            [
                "cmd.exe",
                "/C",
                "start",
                "",
                windows_path,
            ]
        )
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
        return

    subprocess.Popen(["xdg-open", str(target)])


class SortingApp(Tk):
    """Desktop application for running the PGL sorter."""

    def __init__(self) -> None:
        super().__init__()

        self.title(APP_TITLE)
        self.minsize(760, 520)
        self.geometry("820x560")

        remembered = load_preferences()

        configuration_path = find_initial_file(
            CONFIGURATION_FILENAME,
            remembered.configuration_path,
        )
        daily_path = find_initial_file(
            DAILY_FILENAME,
            remembered.daily_path,
        )

        output_directory = remembered.output_directory

        if not output_directory:
            output_directory = str(default_output_directory())

        self.configuration_var = StringVar(value=configuration_path)
        self.daily_var = StringVar(value=daily_path)
        self.output_var = StringVar(value=output_directory)
        self.status_var = StringVar(value="Ready.")
        self.summary_var = StringVar(
            value="Choose the two Excel workbooks, then click Run Sorting."
        )
        self.open_results_enabled = BooleanVar(value=False)

        self._last_report_path: Path | None = None
        self._worker_queue: queue.Queue[_WorkerMessage] = queue.Queue()
        self._worker_running = False

        self._configure_style()
        self._build_interface()
        self.after(150, self._poll_worker_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)

        if "vista" in style.theme_names():
            style.theme_use("vista")

        style.configure(
            "Title.TLabel",
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "Section.TLabel",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Run.TButton",
            font=("Segoe UI", 11, "bold"),
            padding=(18, 10),
        )

    def _build_interface(self) -> None:
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(
            outer,
            text=APP_TITLE,
            style="Title.TLabel",
        ).pack(anchor="w")

        ttk.Label(
            outer,
            text=(
                "Select the configuration and daily workbooks. "
                "The report will be created with today's date."
            ),
        ).pack(anchor="w", pady=(4, 22))

        files_frame = ttk.LabelFrame(
            outer,
            text="Input files",
            padding=16,
        )
        files_frame.pack(fill=X)

        self._build_path_row(
            parent=files_frame,
            row=0,
            label="Configuration",
            variable=self.configuration_var,
            browse_command=self._browse_configuration,
            action_text="Edit",
            action_command=self._open_configuration,
        )

        self._build_path_row(
            parent=files_frame,
            row=1,
            label="Daily sorting",
            variable=self.daily_var,
            browse_command=self._browse_daily,
        )

        output_frame = ttk.LabelFrame(
            outer,
            text="Output",
            padding=16,
        )
        output_frame.pack(fill=X, pady=(16, 0))

        self._build_path_row(
            parent=output_frame,
            row=0,
            label="Report folder",
            variable=self.output_var,
            browse_command=self._browse_output_directory,
            directory=True,
            action_text="Open",
            action_command=self._open_output_directory,
        )

        action_frame = ttk.Frame(outer)
        action_frame.pack(fill=X, pady=(24, 0))

        self.run_button = ttk.Button(
            action_frame,
            text="Run Sorting",
            style="Run.TButton",
            command=self._start_sorting,
        )
        self.run_button.pack(side=LEFT)

        self.open_results_button = ttk.Button(
            action_frame,
            text="Open Results",
            command=self._open_results,
            state="disabled",
        )
        self.open_results_button.pack(side=LEFT, padx=(12, 0))

        self.open_output_button = ttk.Button(
            action_frame,
            text="Open Output Folder",
            command=self._open_output_directory,
        )
        self.open_output_button.pack(side=LEFT, padx=(8, 0))

        status_frame = ttk.LabelFrame(
            outer,
            text="Status",
            padding=16,
        )
        status_frame.pack(fill=BOTH, expand=True, pady=(20, 0))

        self.progress = ttk.Progressbar(
            status_frame,
            mode="indeterminate",
        )
        self.progress.pack(fill=X)

        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            style="Section.TLabel",
        ).pack(anchor="w", pady=(16, 4))

        ttk.Label(
            status_frame,
            textvariable=self.summary_var,
            wraplength=720,
            justify=LEFT,
        ).pack(anchor="w")

    def _build_path_row(
        self,
        *,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: StringVar,
        browse_command: Callable[[], None],
        directory: bool = False,
        action_text: str | None = None,
        action_command: Callable[[], None] | None = None,
    ) -> None:
        ttk.Label(
            parent,
            text=label,
            width=15,
        ).grid(
            row=row,
            column=0,
            sticky="w",
            pady=6,
        )

        entry = ttk.Entry(
            parent,
            textvariable=variable,
        )
        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            padx=(8, 8),
            pady=6,
        )

        ttk.Button(
            parent,
            text="Browse Folder" if directory else "Browse",
            command=browse_command,
        ).grid(
            row=row,
            column=2,
            padx=(0, 8),
            pady=6,
        )

        if action_text and action_command:
            ttk.Button(
                parent,
                text=action_text,
                command=action_command,
            ).grid(
                row=row,
                column=3,
                pady=6,
            )

        parent.columnconfigure(1, weight=1)

    def _browse_configuration(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose sorting configuration workbook",
            filetypes=(("Excel workbooks", "*.xlsx"), ("All files", "*.*")),
            initialdir=self._initial_directory(self.configuration_var.get()),
        )

        if selected:
            self.configuration_var.set(selected)
            self._remember_preferences()

    def _browse_daily(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose daily sorting workbook",
            filetypes=(("Excel workbooks", "*.xlsx"), ("All files", "*.*")),
            initialdir=self._initial_directory(self.daily_var.get()),
        )

        if selected:
            self.daily_var.set(selected)
            self._remember_preferences()

    def _browse_output_directory(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose report output folder",
            initialdir=self._initial_directory(self.output_var.get()),
        )

        if selected:
            self.output_var.set(selected)
            self._remember_preferences()

    @staticmethod
    def _initial_directory(value: str) -> str:
        if not value:
            return str(Path.home())

        path = Path(value).expanduser()

        if path.is_dir():
            return str(path)

        if path.parent.is_dir():
            return str(path.parent)

        return str(Path.home())

    def _open_configuration(self) -> None:
        path = Path(self.configuration_var.get()).expanduser()

        if not path.is_file():
            messagebox.showerror(
                APP_TITLE,
                "Choose a valid sorting_configuration.xlsx file first.",
            )
            return

        try:
            open_path(path)
        except OSError as exc:
            self._show_error_details(
                "Could not open configuration workbook.",
                str(exc),
            )

    def _open_output_directory(self) -> None:
        raw_path = self.output_var.get().strip()

        if not raw_path:
            messagebox.showerror(
                APP_TITLE,
                "Choose an output folder first.",
            )
            return

        path = Path(raw_path).expanduser()

        try:
            path.mkdir(parents=True, exist_ok=True)
            open_path(path)
        except OSError as exc:
            self._show_error_details(
                "Could not open output folder.",
                str(exc),
            )

    def _open_results(self) -> None:
        if self._last_report_path is None:
            return

        try:
            open_path(self._last_report_path)
        except OSError as exc:
            self._show_error_details(
                "Could not open the results workbook.",
                str(exc),
            )

    def _start_sorting(self) -> None:
        if self._worker_running:
            return

        validation_error = self._validate_paths()

        if validation_error is not None:
            messagebox.showerror(APP_TITLE, validation_error)
            return

        configuration_path = Path(
            self.configuration_var.get()
        ).expanduser()
        daily_path = Path(self.daily_var.get()).expanduser()
        output_directory = Path(
            self.output_var.get()
        ).expanduser()

        output_directory.mkdir(parents=True, exist_ok=True)

        report_path = build_report_path(output_directory)

        force = False

        if report_path.exists():
            replace = messagebox.askyesno(
                APP_TITLE,
                (
                    f"A report for today already exists:\n\n"
                    f"{report_path.name}\n\n"
                    "Replace it?"
                ),
            )

            if not replace:
                self.status_var.set("Run cancelled.")
                return

            force = True

        self._remember_preferences()
        self._worker_running = True
        self._last_report_path = None
        self.open_results_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Sorting accessions...")
        self.summary_var.set(
            "Validating the workbooks and creating the Excel report."
        )

        worker = threading.Thread(
            target=self._run_worker,
            args=(
                configuration_path,
                daily_path,
                report_path,
                force,
            ),
            daemon=True,
        )
        worker.start()

    def _validate_paths(self) -> str | None:
        configuration_path = Path(
            self.configuration_var.get()
        ).expanduser()
        daily_path = Path(self.daily_var.get()).expanduser()
        output_raw = self.output_var.get().strip()

        if not configuration_path.is_file():
            return (
                "The configuration workbook could not be found.\n\n"
                "Choose sorting_configuration.xlsx and try again."
            )

        if not daily_path.is_file():
            return (
                "The daily sorting workbook could not be found.\n\n"
                "Choose daily_sorting.xlsx and try again."
            )

        if not output_raw:
            return "Choose a report output folder."

        output_directory = Path(output_raw).expanduser()

        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"The output folder could not be created:\n\n{exc}"

        return None

    def _run_worker(
        self,
        configuration_path: Path,
        daily_path: Path,
        report_path: Path,
        force: bool,
    ) -> None:
        try:
            result = run_sorting(
                configuration_path=configuration_path,
                daily_path=daily_path,
                output_path=report_path,
                force=force,
            )
        except (FileExistsError, OSError, SortingEngineError, ValueError) as exc:
            self._worker_queue.put(_RunFailure(exc))
            return
        except Exception as exc:
            self._worker_queue.put(_RunFailure(exc))
            return

        self._worker_queue.put(
            _RunSuccess(
                result=result,
                report_path=report_path,
            )
        )

    def _poll_worker_queue(self) -> None:
        try:
            message = self._worker_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_worker_queue)
            return

        if isinstance(message, _RunSuccess):
            self._finish_success(message)
        else:
            self._finish_failure(message.error)

        self.after(150, self._poll_worker_queue)

    def _finish_success(self, message: _RunSuccess) -> None:
        self._worker_running = False
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.open_results_button.configure(state="normal")
        self._last_report_path = message.report_path

        result = message.result
        self.status_var.set("Sorting complete.")

        summary = (
            f"Assigned: {result.assigned_accession_count:,} accessions   |   "
            f"Unassigned: {result.unassigned_accession_count:,}   |   "
            f"Assigned weight: {result.total_assigned_weight}\n"
            f"Report: {message.report_path}"
        )

        self.summary_var.set(summary)

        if result.unassigned_accession_count:
            messagebox.showwarning(
                APP_TITLE,
                (
                    "Sorting completed, but some accessions require review.\n\n"
                    f"Unassigned: {result.unassigned_accession_count}\n\n"
                    "Open the report and review the Unassigned sheet."
                ),
            )
        else:
            messagebox.showinfo(
                APP_TITLE,
                (
                    "Sorting completed successfully.\n\n"
                    f"Assigned: {result.assigned_accession_count:,}\n"
                    f"Report: {message.report_path.name}"
                ),
            )

    def _finish_failure(self, error: Exception) -> None:
        self._worker_running = False
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.open_results_button.configure(state="disabled")
        self.status_var.set("Sorting failed.")
        self.summary_var.set(
            "No report was created. Review the error details and correct "
            "the input workbook or configuration."
        )

        self._show_error_details(
            "Sorting could not be completed.",
            str(error),
        )

    def _show_error_details(
        self,
        heading: str,
        details: str,
    ) -> None:
        window = Toplevel(self)
        window.title(f"{APP_TITLE} - Error")
        window.geometry("760x430")
        window.minsize(620, 320)
        window.transient(self)
        window.grab_set()

        outer = ttk.Frame(window, padding=18)
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(
            outer,
            text=heading,
            style="Section.TLabel",
        ).pack(anchor="w")

        text = Text(
            outer,
            wrap="word",
            height=16,
        )
        text.pack(fill=BOTH, expand=True, pady=(10, 12))
        text.insert("1.0", details)
        text.configure(state="disabled")

        ttk.Button(
            outer,
            text="Close",
            command=window.destroy,
        ).pack(side=RIGHT)

    def _remember_preferences(self) -> None:
        preferences = GuiPreferences(
            configuration_path=self.configuration_var.get().strip(),
            daily_path=self.daily_var.get().strip(),
            output_directory=self.output_var.get().strip(),
        )

        try:
            save_preferences(preferences)
        except OSError:
            # Preference persistence should never block the sorting workflow.
            pass


def main() -> int:
    """Start the desktop application."""
    app = SortingApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
