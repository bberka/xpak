#!/usr/bin/env python3
"""
CachyPKG - A GUI Package Manager for CachyOS / KDE Plasma
Supports: pacman, yay (AUR), flatpak
"""

import sys
import subprocess
import shutil
import json
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QTextEdit, QSplitter, QProgressBar, QMessageBox,
    QComboBox, QCheckBox, QFrame, QStatusBar, QToolBar, QSizePolicy,
    QDialog, QDialogButtonBox, QScrollArea, QAbstractItemView
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QSize, QTimer, QPropertyAnimation,
    QEasingCurve, QObject
)
from PyQt6.QtGui import (
    QFont, QIcon, QColor, QPalette, QAction, QKeySequence,
    QTextCursor, QPixmap
)


# ─── Stylesheet ────────────────────────────────────────────────────────────────

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1a1b26;
    color: #c0caf5;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #2a2b3d;
    background-color: #1a1b26;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #16171f;
    color: #565f89;
    padding: 10px 22px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.5px;
}

QTabBar::tab:selected {
    background-color: #1a1b26;
    color: #7aa2f7;
    border-bottom: 2px solid #7aa2f7;
}

QTabBar::tab:hover:!selected {
    color: #c0caf5;
    background-color: #1e2030;
}

QLineEdit {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    padding: 8px 14px;
    color: #c0caf5;
    font-size: 13px;
    selection-background-color: #3d59a1;
}

QLineEdit:focus {
    border: 1px solid #7aa2f7;
}

QLineEdit::placeholder {
    color: #3b4261;
}

QPushButton {
    background-color: #2a2b3d;
    color: #c0caf5;
    border: 1px solid #3b4261;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #3b4261;
    border-color: #7aa2f7;
    color: #7aa2f7;
}

QPushButton:pressed {
    background-color: #7aa2f7;
    color: #1a1b26;
}

QPushButton:disabled {
    background-color: #16171f;
    color: #3b4261;
    border-color: #1e2030;
}

QPushButton#primary {
    background-color: #7aa2f7;
    color: #1a1b26;
    border: none;
    font-weight: 700;
}

QPushButton#primary:hover {
    background-color: #89b4fa;
    color: #1a1b26;
}

QPushButton#danger {
    background-color: #f7768e;
    color: #1a1b26;
    border: none;
    font-weight: 700;
}

QPushButton#danger:hover {
    background-color: #ff9e64;
}

QPushButton#success {
    background-color: #9ece6a;
    color: #1a1b26;
    border: none;
    font-weight: 700;
}

QPushButton#success:hover {
    background-color: #73daca;
}

QTableWidget {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    gridline-color: #1e2030;
    color: #c0caf5;
    selection-background-color: #2a2b3d;
    selection-color: #7aa2f7;
    outline: none;
}

QTableWidget::item {
    padding: 6px 10px;
    border-bottom: 1px solid #1e2030;
}

QTableWidget::item:selected {
    background-color: #2a2b3d;
    color: #7aa2f7;
}

QTableWidget::item:hover {
    background-color: #1e2030;
}

QHeaderView::section {
    background-color: #1e2030;
    color: #565f89;
    padding: 8px 10px;
    border: none;
    border-right: 1px solid #2a2b3d;
    border-bottom: 1px solid #2a2b3d;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
}

QTextEdit {
    background-color: #0d0e14;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    color: #a9b1d6;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: #3d59a1;
}

QScrollBar:vertical {
    background-color: #16171f;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #2a2b3d;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3b4261;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #16171f;
    height: 8px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #2a2b3d;
    border-radius: 4px;
}

QProgressBar {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 6px;
    text-align: center;
    color: #c0caf5;
    font-size: 11px;
    height: 16px;
}

QProgressBar::chunk {
    background-color: #7aa2f7;
    border-radius: 5px;
}

QComboBox {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    padding: 8px 14px;
    color: #c0caf5;
    min-width: 130px;
}

QComboBox:focus {
    border-color: #7aa2f7;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #1e2030;
    border: 1px solid #2a2b3d;
    color: #c0caf5;
    selection-background-color: #2a2b3d;
    selection-color: #7aa2f7;
    outline: none;
}

QStatusBar {
    background-color: #16171f;
    color: #565f89;
    border-top: 1px solid #2a2b3d;
    font-size: 12px;
}

QSplitter::handle {
    background-color: #2a2b3d;
}

QToolBar {
    background-color: #16171f;
    border-bottom: 1px solid #2a2b3d;
    spacing: 6px;
    padding: 4px 8px;
}

QToolBar::separator {
    background-color: #2a2b3d;
    width: 1px;
    margin: 4px 4px;
}

QCheckBox {
    spacing: 8px;
    color: #c0caf5;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3b4261;
    border-radius: 4px;
    background-color: #16171f;
}

QCheckBox::indicator:checked {
    background-color: #7aa2f7;
    border-color: #7aa2f7;
}

QLabel#badge-aur {
    background-color: #bb9af7;
    color: #1a1b26;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#badge-flatpak {
    background-color: #73daca;
    color: #1a1b26;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#badge-pacman {
    background-color: #7aa2f7;
    color: #1a1b26;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}

QFrame#sidebar-card {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 10px;
    padding: 12px;
}

QDialog {
    background-color: #1a1b26;
    color: #c0caf5;
}

QMessageBox {
    background-color: #1a1b26;
    color: #c0caf5;
}
"""


# ─── Backend Worker ─────────────────────────────────────────────────────────────

class CommandWorker(QThread):
    output_line = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(int)

    def __init__(self, cmd: list[str], sudo: bool = False, password: str = ""):
        super().__init__()
        self.cmd = cmd
        self.sudo = sudo
        self.password = password
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            if self.sudo and self.password:
                full_cmd = ["sudo", "-S"] + self.cmd
                process = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                process.stdin.write(self.password + "\n")
                process.stdin.flush()
            else:
                process = subprocess.Popen(
                    self.cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    bufsize=1
                )

            for line in iter(process.stdout.readline, ""):
                if self._abort:
                    process.terminate()
                    self.finished.emit(False, "Operation aborted")
                    return
                line = line.rstrip()
                if line:
                    self.output_line.emit(line)

            process.wait()
            success = process.returncode == 0
            msg = "Operation completed successfully" if success else f"Operation failed (exit {process.returncode})"
            self.finished.emit(success, msg)

        except FileNotFoundError as e:
            self.finished.emit(False, f"Command not found: {e}")
        except Exception as e:
            self.finished.emit(False, str(e))


class SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query: str, source: str):
        super().__init__()
        self.query = query
        self.source = source  # "pacman", "aur", "flatpak", "all"

    def run(self):
        results = []
        try:
            if self.source in ("pacman", "all"):
                results += self._search_pacman()
            if self.source in ("aur", "all") and shutil.which("yay"):
                results += self._search_aur()
            if self.source in ("flatpak", "all") and shutil.which("flatpak"):
                results += self._search_flatpak()
            self.results_ready.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _search_pacman(self) -> list:
        try:
            out = subprocess.check_output(
                ["pacman", "-Ss", self.query],
                text=True, stderr=subprocess.DEVNULL
            )
            return self._parse_pacman_output(out, "pacman")
        except subprocess.CalledProcessError:
            return []

    def _search_aur(self) -> list:
        try:
            out = subprocess.check_output(
                ["yay", "-Ssa", "--aur", self.query],
                text=True, stderr=subprocess.DEVNULL
            )
            return self._parse_pacman_output(out, "aur")
        except subprocess.CalledProcessError:
            return []

    def _search_flatpak(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "search", "--columns=application,name,version,description", self.query],
                text=True, stderr=subprocess.DEVNULL
            )
            results = []
            for line in out.strip().splitlines()[1:]:  # skip header
                parts = line.split("\t")
                if len(parts) >= 2:
                    results.append({
                        "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                        "app_id": parts[0].strip(),
                        "version": parts[2].strip() if len(parts) > 2 else "",
                        "description": parts[3].strip() if len(parts) > 3 else "",
                        "source": "flatpak",
                        "installed": self._is_flatpak_installed(parts[0].strip()),
                    })
            return results
        except subprocess.CalledProcessError:
            return []

    def _parse_pacman_output(self, out: str, source: str) -> list:
        results = []
        lines = out.strip().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("    ") or not line:
                i += 1
                continue
            desc = lines[i + 1].strip() if i + 1 < len(lines) else ""
            # e.g. "extra/firefox 123.0-1 [installed]"
            parts = line.split()
            if not parts:
                i += 2
                continue
            repo_name = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            installed = "[installed]" in line
            name = repo_name.split("/")[-1] if "/" in repo_name else repo_name
            results.append({
                "name": name,
                "version": version,
                "description": desc,
                "source": source,
                "installed": installed,
                "repo": repo_name.split("/")[0] if "/" in repo_name else source,
            })
            i += 2
        return results

    def _is_flatpak_installed(self, app_id: str) -> bool:
        try:
            out = subprocess.check_output(
                ["flatpak", "list", "--app", "--columns=application"],
                text=True, stderr=subprocess.DEVNULL
            )
            return app_id in out
        except Exception:
            return False


class InstalledLoader(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def run(self):
        results = []
        if self.source in ("pacman", "all"):
            results += self._list_pacman()
        if self.source in ("flatpak", "all") and shutil.which("flatpak"):
            results += self._list_flatpak()
        self.results_ready.emit(results)

    def _list_pacman(self) -> list:
        try:
            out = subprocess.check_output(
                ["pacman", "-Q"],
                text=True, stderr=subprocess.DEVNULL
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    pkgs.append({
                        "name": parts[0],
                        "version": parts[1],
                        "source": "pacman",
                        "description": "",
                    })
            return pkgs
        except Exception:
            return []

    def _list_flatpak(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "list", "--app", "--columns=application,name,version"],
                text=True, stderr=subprocess.DEVNULL
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    pkgs.append({
                        "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                        "app_id": parts[0].strip(),
                        "version": parts[2].strip() if len(parts) > 2 else "",
                        "source": "flatpak",
                        "description": "",
                    })
            return pkgs
        except Exception:
            return []


class UpdateChecker(QThread):
    updates_ready = pyqtSignal(list)

    def run(self):
        updates = []
        updates += self._check_pacman_updates()
        if shutil.which("flatpak"):
            updates += self._check_flatpak_updates()
        self.updates_ready.emit(updates)

    def _check_pacman_updates(self) -> list:
        try:
            # checkupdates is non-root and safe
            out = subprocess.check_output(
                ["checkupdates"],
                text=True, stderr=subprocess.DEVNULL
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    pkgs.append({
                        "name": parts[0],
                        "old_version": parts[1],
                        "new_version": parts[3],
                        "source": "pacman",
                    })
            return pkgs
        except subprocess.CalledProcessError:
            return []  # exit 2 = no updates, which is fine
        except FileNotFoundError:
            # fallback if checkupdates not installed
            return []

    def _check_flatpak_updates(self) -> list:
        try:
            out = subprocess.check_output(
                ["flatpak", "remote-ls", "--updates", "--columns=application,name,version"],
                text=True, stderr=subprocess.DEVNULL
            )
            pkgs = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if parts and parts[0]:
                    pkgs.append({
                        "name": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
                        "old_version": "",
                        "new_version": parts[2].strip() if len(parts) > 2 else "",
                        "source": "flatpak",
                    })
            return pkgs
        except Exception:
            return []


# ─── Password Dialog ────────────────────────────────────────────────────────────

class PasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Authentication Required")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        icon_label = QLabel("  sudo password required")
        icon_label.setStyleSheet("color: #e0af68; font-weight: 700; font-size: 14px;")
        layout.addWidget(icon_label)

        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_input.setPlaceholderText("Enter sudo password...")
        layout.addWidget(self.pwd_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def password(self) -> str:
        return self.pwd_input.text()


# ─── Terminal Output Widget ─────────────────────────────────────────────────────

class TerminalOutput(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(180)

    def append_line(self, line: str, color: str = "#a9b1d6"):
        self.moveCursor(QTextCursor.MoveOperation.End)
        html = f'<span style="color:{color}; white-space:pre-wrap;">{self._escape(line)}</span><br>'
        self.insertHtml(html)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def append_success(self, msg: str):
        self.append_line(f"✓ {msg}", "#9ece6a")

    def append_error(self, msg: str):
        self.append_line(f"✗ {msg}", "#f7768e")

    def append_info(self, msg: str):
        self.append_line(f"» {msg}", "#7aa2f7")

    def clear_log(self):
        self.clear()

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ─── Package Table ──────────────────────────────────────────────────────────────

class PackageTable(QTableWidget):
    def __init__(self, columns: list[str], parent=None):
        super().__init__(parent)
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.setSortingEnabled(True)
        self.setStyleSheet("""
            QTableWidget { alternate-background-color: #1e2030; }
        """)

    def populate(self, packages: list[dict], columns: list[str]):
        self.setSortingEnabled(False)
        self.setRowCount(0)
        for pkg in packages:
            row = self.rowCount()
            self.insertRow(row)
            for col_idx, col in enumerate(columns):
                key = col.lower().replace(" ", "_")
                val = str(pkg.get(key, pkg.get(col.lower(), "")))
                item = QTableWidgetItem(val)
                if col.lower() == "source":
                    item.setForeground(QColor(self._source_color(val)))
                self.setItem(row, col_idx, item)
        self.setSortingEnabled(True)

    @staticmethod
    def _source_color(source: str) -> str:
        colors = {
            "pacman": "#7aa2f7",
            "aur": "#bb9af7",
            "flatpak": "#73daca",
        }
        return colors.get(source.lower(), "#c0caf5")


# ─── Search Tab ────────────────────────────────────────────────────────────────

class SearchTab(QWidget):
    log_message = pyqtSignal(str, str)

    COLUMNS = ["Name", "Version", "Source", "Description"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[CommandWorker] = None
        self._search_worker: Optional[SearchWorker] = None
        self._selected_pkg: Optional[dict] = None
        self._results: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Search bar
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search packages...")
        self.search_input.returnPressed.connect(self.do_search)

        self.source_combo = QComboBox()
        self.source_combo.addItems(["All Sources", "pacman", "AUR", "Flatpak"])

        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self.do_search)
        self.search_btn.setFixedWidth(90)

        search_row.addWidget(self.search_input)
        search_row.addWidget(self.source_combo)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        # Results + actions splitter
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = PackageTable(self.COLUMNS)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        splitter.addWidget(self.table)

        # Bottom panel: info + actions
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        # Action row
        action_row = QHBoxLayout()
        self.install_btn = QPushButton("Install")
        self.install_btn.setObjectName("success")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self.install_package)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self.remove_package)

        self.info_btn = QPushButton("Package Info")
        self.info_btn.setEnabled(False)
        self.info_btn.clicked.connect(self.show_info)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #565f89;")

        action_row.addWidget(self.install_btn)
        action_row.addWidget(self.remove_btn)
        action_row.addWidget(self.info_btn)
        action_row.addStretch()
        action_row.addWidget(self.status_label)
        bottom_layout.addLayout(action_row)

        self.terminal = TerminalOutput()
        self.terminal.setMaximumHeight(200)
        bottom_layout.addWidget(self.terminal)

        splitter.addWidget(bottom)
        splitter.setSizes([400, 220])
        layout.addWidget(splitter)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

    def do_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        src_map = {
            "All Sources": "all",
            "pacman": "pacman",
            "AUR": "aur",
            "Flatpak": "flatpak",
        }
        source = src_map[self.source_combo.currentText()]
        self.table.setRowCount(0)
        self.terminal.append_info(f"Searching '{query}' in {self.source_combo.currentText()}")
        self.progress.setVisible(True)
        self.search_btn.setEnabled(False)

        self._search_worker = SearchWorker(query, source)
        self._search_worker.results_ready.connect(self._on_results)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.finished.connect(lambda: (
            self.progress.setVisible(False),
            self.search_btn.setEnabled(True),
        ))
        self._search_worker.start()

    def _on_results(self, results: list):
        self._results = results
        self.table.populate(results, self.COLUMNS)
        count = len(results)
        self.terminal.append_success(f"Found {count} package{'s' if count != 1 else ''}")
        self.status_label.setText(f"{count} results")

    def _on_search_error(self, msg: str):
        self.terminal.append_error(msg)

    def _on_selection(self):
        rows = self.table.selectedItems()
        if not rows:
            self.install_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            self.info_btn.setEnabled(False)
            self._selected_pkg = None
            return
        row = self.table.currentRow()
        if row < len(self._results):
            self._selected_pkg = self._results[row]
            installed = self._selected_pkg.get("installed", False)
            self.install_btn.setEnabled(not installed)
            self.remove_btn.setEnabled(installed)
            self.info_btn.setEnabled(True)

    def install_package(self):
        if not self._selected_pkg:
            return
        pkg = self._selected_pkg
        name = pkg.get("app_id") if pkg["source"] == "flatpak" else pkg["name"]
        self._run_package_op(pkg["source"], "install", name)

    def remove_package(self):
        if not self._selected_pkg:
            return
        pkg = self._selected_pkg
        name = pkg.get("app_id") if pkg["source"] == "flatpak" else pkg["name"]
        reply = QMessageBox.question(
            self, "Confirm Remove",
            f"Remove package '{pkg['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_package_op(pkg["source"], "remove", name)

    def show_info(self):
        if not self._selected_pkg:
            return
        pkg = self._selected_pkg
        name = pkg["name"]
        source = pkg["source"]
        try:
            if source == "flatpak":
                out = subprocess.check_output(
                    ["flatpak", "info", pkg.get("app_id", name)],
                    text=True, stderr=subprocess.STDOUT
                )
            else:
                cmd = ["yay", "-Si", name] if source == "aur" else ["pacman", "-Si", name]
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            out = e.output or "No info available"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Package Info: {name}")
        dlg.resize(560, 420)
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(out)
        layout.addWidget(text)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec()

    def _run_package_op(self, source: str, operation: str, name: str):
        if source == "flatpak":
            if operation == "install":
                cmd = ["flatpak", "install", "-y", name]
                sudo = False
            else:
                cmd = ["flatpak", "uninstall", "-y", name]
                sudo = False
        elif source == "aur":
            if operation == "install":
                cmd = ["yay", "-S", "--noconfirm", name]
            else:
                cmd = ["yay", "-R", "--noconfirm", name]
            sudo = False
        else:
            if operation == "install":
                cmd = ["pacman", "-S", "--noconfirm", name]
            else:
                cmd = ["pacman", "-R", "--noconfirm", name]
            sudo = True

        password = ""
        if sudo:
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()

        verb = "Installing" if operation == "install" else "Removing"
        self.terminal.append_info(f"{verb} {name} via {source}")
        self.progress.setVisible(True)
        self.install_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)

        self._worker = CommandWorker(cmd, sudo, password)
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_op_finished)
        self._worker.start()

    def _on_op_finished(self, success: bool, msg: str):
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
        else:
            self.terminal.append_error(msg)
        self._on_selection()


# ─── Installed Tab ──────────────────────────────────────────────────────────────

class InstalledTab(QWidget):
    COLUMNS = ["Name", "Version", "Source"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packages: list[dict] = []
        self._filtered: list[dict] = []
        self._worker: Optional[CommandWorker] = None
        self._build_ui()
        QTimer.singleShot(200, self.load_packages)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        toolbar = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter installed packages...")
        self.filter_input.textChanged.connect(self._apply_filter)

        self.source_filter = QComboBox()
        self.source_filter.addItems(["All", "pacman", "Flatpak"])
        self.source_filter.currentTextChanged.connect(self._apply_filter)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_packages)

        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self.remove_selected)

        toolbar.addWidget(self.filter_input)
        toolbar.addWidget(self.source_filter)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.remove_btn)
        layout.addLayout(toolbar)

        self.count_label = QLabel("Loading...")
        self.count_label.setStyleSheet("color: #565f89; font-size: 12px;")
        layout.addWidget(self.count_label)

        self.table = PackageTable(self.COLUMNS)
        self.table.selectionModel().selectionChanged.connect(
            lambda: self.remove_btn.setEnabled(bool(self.table.selectedItems()))
        )
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.terminal = TerminalOutput()
        self.terminal.setMaximumHeight(160)
        layout.addWidget(self.terminal)

    def load_packages(self):
        self.progress.setVisible(True)
        self.refresh_btn.setEnabled(False)
        self._loader = InstalledLoader("all")
        self._loader.results_ready.connect(self._on_loaded)
        self._loader.finished.connect(lambda: (
            self.progress.setVisible(False),
            self.refresh_btn.setEnabled(True),
        ))
        self._loader.start()

    def _on_loaded(self, packages: list):
        self._packages = packages
        self._apply_filter()
        total = len(packages)
        self.count_label.setText(f"{total} packages installed")

    def _apply_filter(self):
        query = self.filter_input.text().lower()
        src = self.source_filter.currentText().lower()
        self._filtered = [
            p for p in self._packages
            if (not query or query in p["name"].lower())
            and (src == "all" or p["source"].lower() == src)
        ]
        self.table.populate(self._filtered, self.COLUMNS)
        self.count_label.setText(f"Showing {len(self._filtered)} / {len(self._packages)} packages")

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._filtered):
            return
        pkg = self._filtered[row]
        reply = QMessageBox.question(
            self, "Confirm Remove",
            f"Remove '{pkg['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if pkg["source"] == "flatpak":
            cmd = ["flatpak", "uninstall", "-y", pkg.get("app_id", pkg["name"])]
            sudo = False
            password = ""
        else:
            cmd = ["pacman", "-R", "--noconfirm", pkg["name"]]
            sudo = True
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()

        self.terminal.append_info(f"Removing {pkg['name']}")
        self.progress.setVisible(True)
        self.remove_btn.setEnabled(False)

        self._worker = CommandWorker(cmd, sudo, password)
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_remove_done)
        self._worker.start()

    def _on_remove_done(self, success: bool, msg: str):
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
            self.load_packages()
        else:
            self.terminal.append_error(msg)
        self.remove_btn.setEnabled(True)


# ─── Updates Tab ───────────────────────────────────────────────────────────────

class UpdatesTab(QWidget):
    COLUMNS = ["Name", "Old Version", "New Version", "Source"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updates: list[dict] = []
        self._worker: Optional[CommandWorker] = None
        self._build_ui()
        QTimer.singleShot(400, self.check_updates)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        toolbar = QHBoxLayout()
        self.check_btn = QPushButton("Check for Updates")
        self.check_btn.clicked.connect(self.check_updates)

        self.update_all_btn = QPushButton("Update All")
        self.update_all_btn.setObjectName("primary")
        self.update_all_btn.setEnabled(False)
        self.update_all_btn.clicked.connect(self.update_all)

        self.update_flatpak_btn = QPushButton("Update Flatpaks")
        self.update_flatpak_btn.setObjectName("success")
        self.update_flatpak_btn.setEnabled(shutil.which("flatpak") is not None)
        self.update_flatpak_btn.clicked.connect(self.update_flatpak)

        self.update_aur_btn = QPushButton("Update AUR")
        self.update_aur_btn.setEnabled(shutil.which("yay") is not None)
        self.update_aur_btn.clicked.connect(self.update_aur)

        self.status_label = QLabel("Not checked")
        self.status_label.setStyleSheet("color: #565f89;")

        toolbar.addWidget(self.check_btn)
        toolbar.addWidget(self.update_all_btn)
        toolbar.addWidget(self.update_flatpak_btn)
        toolbar.addWidget(self.update_aur_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        self.table = PackageTable(self.COLUMNS)
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.terminal = TerminalOutput()
        self.terminal.setMaximumHeight(200)
        layout.addWidget(self.terminal)

    def check_updates(self):
        self.progress.setVisible(True)
        self.check_btn.setEnabled(False)
        self.update_all_btn.setEnabled(False)
        self.terminal.append_info("Checking for updates")

        self._checker = UpdateChecker()
        self._checker.updates_ready.connect(self._on_updates)
        self._checker.finished.connect(lambda: (
            self.progress.setVisible(False),
            self.check_btn.setEnabled(True),
        ))
        self._checker.start()

    def _on_updates(self, updates: list):
        self._updates = updates
        self.table.populate(updates, self.COLUMNS)
        count = len(updates)
        if count:
            self.status_label.setText(f"{count} update{'s' if count != 1 else ''} available")
            self.status_label.setStyleSheet("color: #e0af68; font-weight: 700;")
            self.update_all_btn.setEnabled(True)
        else:
            self.status_label.setText("System is up to date")
            self.status_label.setStyleSheet("color: #9ece6a; font-weight: 700;")
        self.terminal.append_success(f"Check complete: {count} updates found")

    def update_all(self):
        dlg = PasswordDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        self.terminal.append_info("Starting full system update")
        self._run_update(["pacman", "-Syu", "--noconfirm"], sudo=True, password=password)

    def update_flatpak(self):
        self.terminal.append_info("Updating Flatpak packages")
        self._run_update(["flatpak", "update", "-y"], sudo=False)

    def update_aur(self):
        self.terminal.append_info("Updating AUR packages via yay")
        self._run_update(["yay", "-Syu", "--aur", "--noconfirm"], sudo=False)

    def _run_update(self, cmd: list, sudo: bool = False, password: str = ""):
        self.progress.setVisible(True)
        self.update_all_btn.setEnabled(False)
        self._worker = CommandWorker(cmd, sudo, password)
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_update_done)
        self._worker.start()

    def _on_update_done(self, success: bool, msg: str):
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
            self.check_updates()
        else:
            self.terminal.append_error(msg)
        self.update_all_btn.setEnabled(True)


# ─── Tools Tab ─────────────────────────────────────────────────────────────────

class ToolsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[CommandWorker] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Tool availability summary
        avail = QHBoxLayout()
        for tool, cmd in [("pacman", "pacman"), ("yay", "yay"), ("flatpak", "flatpak"), ("paru", "paru")]:
            found = shutil.which(cmd) is not None
            lbl = QLabel(f"{'✓' if found else '✗'}  {tool}")
            lbl.setStyleSheet(
                f"color: {'#9ece6a' if found else '#f7768e'}; "
                f"font-weight: 700; padding: 4px 12px; "
                f"background-color: {'#1e2030'}; border-radius: 6px;"
            )
            avail.addWidget(lbl)
        avail.addStretch()
        layout.addLayout(avail)

        # Maintenance buttons
        grid_label = QLabel("Maintenance Operations")
        grid_label.setStyleSheet("color: #7aa2f7; font-weight: 700; font-size: 14px; margin-top: 8px;")
        layout.addWidget(grid_label)

        ops = [
            ("Clean Package Cache", "Remove cached packages to free disk space",
             self.clean_cache, "#e0af68"),
            ("Remove Orphans", "Remove packages no longer needed as dependencies",
             self.remove_orphans, "#f7768e"),
            ("Sync Databases", "Force refresh of package databases",
             self.sync_databases, "#7aa2f7"),
            ("Clean Flatpak Cache", "Remove unused Flatpak runtimes and data",
             self.clean_flatpak, "#73daca"),
            ("List Explicitly Installed", "Show packages you installed explicitly",
             self.list_explicit, "#9ece6a"),
            ("Fix Broken Packages", "Attempt to repair broken dependencies",
             self.fix_broken, "#bb9af7"),
        ]

        grid = QHBoxLayout()
        left_col = QVBoxLayout()
        right_col = QVBoxLayout()

        for i, (title, desc, fn, color) in enumerate(ops):
            card = QFrame()
            card.setObjectName("sidebar-card")
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(6)

            t = QLabel(title)
            t.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 13px;")
            d = QLabel(desc)
            d.setStyleSheet("color: #565f89; font-size: 11px;")
            d.setWordWrap(True)

            btn = QPushButton("Run")
            btn.clicked.connect(fn)
            btn.setFixedWidth(70)

            card_layout.addWidget(t)
            card_layout.addWidget(d)
            card_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

            if i % 2 == 0:
                left_col.addWidget(card)
            else:
                right_col.addWidget(card)

        grid.addLayout(left_col)
        grid.addLayout(right_col)
        layout.addLayout(grid)
        layout.addStretch()

        self.terminal = TerminalOutput()
        self.terminal.setMaximumHeight(200)
        layout.addWidget(self.terminal)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

    def _run(self, cmd: list, sudo: bool = False):
        password = ""
        if sudo:
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()

        self.progress.setVisible(True)
        self._worker = CommandWorker(cmd, sudo, password)
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, success: bool, msg: str):
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
        else:
            self.terminal.append_error(msg)

    def clean_cache(self):
        self.terminal.append_info("Cleaning package cache (keeping 2 versions)")
        self._run(["paccache", "-r", "-k", "2"], sudo=True)

    def remove_orphans(self):
        try:
            out = subprocess.check_output(
                ["pacman", "-Qdtq"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except subprocess.CalledProcessError:
            out = ""
        if not out:
            self.terminal.append_success("No orphaned packages found")
            return
        self.terminal.append_info(f"Found orphans: {out.replace(chr(10), ' ')}")
        orphans = out.split()
        self._run(["pacman", "-Rns", "--noconfirm"] + orphans, sudo=True)

    def sync_databases(self):
        self.terminal.append_info("Syncing package databases")
        self._run(["pacman", "-Sy"], sudo=True)

    def clean_flatpak(self):
        self.terminal.append_info("Removing unused Flatpak runtimes")
        self._run(["flatpak", "uninstall", "--unused", "-y"])

    def list_explicit(self):
        self.terminal.append_info("Explicitly installed packages:")
        try:
            out = subprocess.check_output(
                ["pacman", "-Qe"], text=True, stderr=subprocess.DEVNULL
            )
            for line in out.strip().splitlines():
                self.terminal.append_line(f"  {line}", "#c0caf5")
        except Exception as e:
            self.terminal.append_error(str(e))

    def fix_broken(self):
        self.terminal.append_info("Attempting to fix broken dependencies")
        self._run(["pacman", "-Dk"], sudo=False)


# ─── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NPAK")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        self._build_ui()
        self._build_statusbar()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet("background-color: #16171f; border-bottom: 1px solid #2a2b3d;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("NPAK")
        title.setStyleSheet(
            "color: #7aa2f7; font-size: 18px; font-weight: 800; letter-spacing: 2px;"
        )
        subtitle = QLabel("Package Manager")
        subtitle.setStyleSheet("color: #3b4261; font-size: 12px; margin-left: 6px; margin-top: 4px;")

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addStretch()

        # Backend badges
        for tool, color in [("pacman", "#7aa2f7"), ("yay", "#bb9af7"), ("flatpak", "#73daca")]:
            available = shutil.which(tool) is not None
            badge = QLabel(tool)
            badge.setStyleSheet(
                f"color: {'#1a1b26' if available else '#3b4261'}; "
                f"background-color: {color if available else '#1e2030'}; "
                f"border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700; "
                f"margin-left: 4px;"
            )
            header_layout.addWidget(badge)

        main_layout.addWidget(header)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)

        self.search_tab = SearchTab()
        self.installed_tab = InstalledTab()
        self.updates_tab = UpdatesTab()
        self.tools_tab = ToolsTab()

        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.installed_tab, "Installed")
        self.tabs.addTab(self.updates_tab, "Updates")
        self.tabs.addTab(self.tools_tab, "Maintenance")

        main_layout.addWidget(self.tabs)

    def _build_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("NPAK ready")


# ─── Entry Point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NPAK")
    app.setOrganizationName("NPAK")
    app.setStyleSheet(STYLESHEET)

    # Use system font as fallback
    font = QFont("JetBrains Mono", 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
