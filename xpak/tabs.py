import subprocess
import shutil

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSplitter, QProgressBar,
    QMessageBox, QDialog, QTextEdit, QFrame,
    QAbstractItemView, QCheckBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from xpak.workers import (
    CommandWorker, SearchWorker, InstalledLoader, UpdateChecker, AppUpdateChecker
)
from xpak.widgets import TerminalOutput, TerminalPanel, PackageTable, SourceSelector
from xpak.dialogs import PasswordDialog


class SearchTab(QWidget):
    log_message = pyqtSignal(str, str)

    COLUMNS = ["Name", "Version", "Source", "Description"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: CommandWorker | None = None
        self._search_worker: SearchWorker | None = None
        self._selected_pkg: dict | None = None
        self._results: list[dict] = []
        self._sorted_results: list[dict] = []
        self._query: str = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Search bar row
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search packages...")
        self.search_input.returnPressed.connect(self.do_search)

        self.source_selector = SourceSelector()
        self.source_selector.sources_changed.connect(self._on_sources_changed)

        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self.do_search)
        self.search_btn.setFixedWidth(90)

        search_row.addWidget(self.search_input)
        search_row.addWidget(self.source_selector)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        # Sort row
        sort_row = QHBoxLayout()
        sort_lbl = QLabel("Sort by:")
        sort_lbl.setStyleSheet("color: #565f89; font-size: 12px;")
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Relevance", "Name", "Version", "Source"])
        self.sort_combo.currentTextChanged.connect(self._apply_sort)

        order_lbl = QLabel("Order:")
        order_lbl.setStyleSheet("color: #565f89; font-size: 12px; margin-left: 12px;")
        self.order_combo = QComboBox()
        self.order_combo.addItems(["Ascending", "Descending"])
        self.order_combo.currentTextChanged.connect(self._apply_sort)

        self.search_desc_check = QCheckBox("Search descriptions")
        self.search_desc_check.setChecked(False)
        self.search_desc_check.setStyleSheet("color: #565f89; font-size: 12px; margin-left: 12px;")
        self.search_desc_check.stateChanged.connect(self._apply_sort)

        sort_row.addWidget(sort_lbl)
        sort_row.addWidget(self.sort_combo)
        sort_row.addWidget(order_lbl)
        sort_row.addWidget(self.order_combo)
        sort_row.addWidget(self.search_desc_check)
        sort_row.addStretch()
        layout.addLayout(sort_row)

        # Results + actions splitter
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = PackageTable(self.COLUMNS)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        splitter.addWidget(self.table)

        # Bottom panel
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

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

        self.terminal = TerminalPanel(max_height=200)
        bottom_layout.addWidget(self.terminal)

        splitter.addWidget(bottom)
        splitter.setSizes([400, 220])
        layout.addWidget(splitter)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

    def _on_sources_changed(self, sources: list):
        # If a search is currently showing results, re-run or just note the change
        pass

    def do_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        sources = self.source_selector.get_sources()
        if not sources:
            self.terminal.append_error("No sources selected")
            return

        self._results = []
        self._sorted_results = []
        self._query = query
        self.table.setRowCount(0)
        self.terminal.append_info(f"Searching '{query}' in {', '.join(sources)}")
        self.progress.setVisible(True)
        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching...")

        self._search_worker = SearchWorker(query, sources)
        self._search_worker.result_chunk.connect(self._on_result_chunk)
        self._search_worker.search_done.connect(self._on_search_done)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.finished.connect(lambda: (
            self.progress.setVisible(False),
            self.search_btn.setEnabled(True),
        ))
        self._search_worker.start()

    def _on_result_chunk(self, results: list):
        self._results.extend(results)
        self._apply_sort()

    def _on_search_done(self, total: int):
        self.terminal.append_success(f"Found {total} package{'s' if total != 1 else ''}")
        self.status_label.setText(f"{total} results")

    def _on_search_error(self, msg: str):
        self.terminal.append_error(msg)

    def _apply_sort(self):
        if not self._results:
            return

        sort_key = self.sort_combo.currentText()
        descending = self.order_combo.currentText() == "Descending"
        search_desc = self.search_desc_check.isChecked()
        query = self._query.lower()

        # Filter: exclude description-only matches when search descriptions is off
        if query and not search_desc:
            results = [p for p in self._results if query in p.get("name", "").lower()]
        else:
            results = list(self._results)

        if sort_key == "Relevance":
            def _relevance(pkg):
                name = pkg.get("name", "").lower()
                if name == query:
                    return 0
                if name.startswith(query):
                    return 1
                if query in name:
                    return 2
                return 3  # description-only match

            self._sorted_results = sorted(results, key=_relevance, reverse=descending)
        else:
            key = sort_key.lower()
            self._sorted_results = sorted(
                results,
                key=lambda p: p.get(key, "").lower(),
                reverse=descending,
            )
        self.table.populate(self._sorted_results, self.COLUMNS)

    def _on_selection(self):
        rows = self.table.selectedItems()
        if not rows:
            self.install_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            self.info_btn.setEnabled(False)
            self._selected_pkg = None
            return

        row = self.table.currentRow()
        item = self.table.item(row, 0)
        if item is not None:
            pkg = item.data(Qt.ItemDataRole.UserRole)
            if pkg:
                self._selected_pkg = pkg
                installed = pkg.get("installed", False)
                self.install_btn.setEnabled(not installed)
                self.remove_btn.setEnabled(installed)
                self.info_btn.setEnabled(True)
                return

        self._selected_pkg = None
        self.install_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.info_btn.setEnabled(False)

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
            self,
            "Confirm Remove",
            f"Remove package '{pkg['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
                    text=True,
                    stderr=subprocess.STDOUT,
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
        password = ""
        pre_auth = False

        if source == "flatpak":
            if operation == "install":
                cmd = ["flatpak", "install", "-y", name]
            else:
                cmd = ["flatpak", "uninstall", "-y", name]
            sudo = False
        elif source == "aur":
            if operation == "install":
                cmd = ["yay", "-S", "--noconfirm", name]
            else:
                cmd = ["yay", "-R", "--noconfirm", name]
            sudo = False
            pre_auth = True
            # Need password to pre-authenticate sudo for yay
            dlg = PasswordDialog(
                self,
                message=(
                    "yay requires sudo for AUR package operations. "
                    "Your password will be used to pre-authenticate sudo."
                ),
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()
        else:
            # pacman
            if operation == "install":
                cmd = ["pacman", "-S", "--noconfirm", name]
            else:
                cmd = ["pacman", "-R", "--noconfirm", name]
            sudo = True
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()

        verb = "Installing" if operation == "install" else "Removing"
        self.terminal.append_info(f"{verb} {name} via {source}")
        self.progress.setVisible(True)
        self.install_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)

        self._worker = CommandWorker(cmd, sudo=sudo, password=password, pre_auth=pre_auth)
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_op_finished)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_op_finished(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
        else:
            self.terminal.append_error(msg)
        self._on_selection()


class InstalledTab(QWidget):
    COLUMNS = ["Name", "Version", "Source"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packages: list[dict] = []
        self._filtered: list[dict] = []
        self._worker: CommandWorker | None = None
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

        self.terminal = TerminalPanel(max_height=160)
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
        self.count_label.setText(
            f"Showing {len(self._filtered)} / {len(self._packages)} packages"
        )

    def remove_selected(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0)
        pkg = None
        if item is not None:
            pkg = item.data(Qt.ItemDataRole.UserRole)
        if not pkg:
            # Fallback to index-based lookup
            if row < 0 or row >= len(self._filtered):
                return
            pkg = self._filtered[row]

        reply = QMessageBox.question(
            self,
            "Confirm Remove",
            f"Remove '{pkg['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
        self.terminal.set_worker(self._worker)

    def _on_remove_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
            self.load_packages()
        else:
            self.terminal.append_error(msg)
        self.remove_btn.setEnabled(True)


class UpdatesTab(QWidget):
    COLUMNS = ["Name", "Old Version", "New Version", "Source"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updates: list[dict] = []
        self._worker: CommandWorker | None = None
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

        self.terminal = TerminalPanel(max_height=200)
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
        dlg = PasswordDialog(
            self,
            message="yay requires sudo for AUR updates. Password will be used to pre-authenticate.",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        self.terminal.append_info("Updating AUR packages via yay")
        self._run_update(
            ["yay", "-Syu", "--aur", "--noconfirm"],
            sudo=False,
            password=password,
            pre_auth=True,
        )

    def _run_update(self, cmd: list, sudo: bool = False, password: str = "", pre_auth: bool = False):
        self.progress.setVisible(True)
        self.update_all_btn.setEnabled(False)
        self._worker = CommandWorker(cmd, sudo=sudo, password=password, pre_auth=pre_auth)
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_update_done)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_update_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        if success:
            self.terminal.append_success(msg)
            self.check_updates()
        else:
            self.terminal.append_error(msg)
        self.update_all_btn.setEnabled(True)


class ToolsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: CommandWorker | None = None
        self._app_update_checker: AppUpdateChecker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # App Updates section
        app_update_label = QLabel("App Updates")
        app_update_label.setStyleSheet(
            "color: #7aa2f7; font-weight: 700; font-size: 14px;"
        )
        layout.addWidget(app_update_label)

        app_update_row = QHBoxLayout()
        self.check_app_update_btn = QPushButton("Check for App Update")
        self.check_app_update_btn.clicked.connect(self.check_app_update)
        app_update_row.addWidget(self.check_app_update_btn)

        self.app_update_status = QLabel("")
        self.app_update_status.setStyleSheet("color: #565f89; font-size: 12px; margin-left: 12px;")
        app_update_row.addWidget(self.app_update_status)
        app_update_row.addStretch()
        layout.addLayout(app_update_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2b3d;")
        layout.addWidget(sep)

        # Maintenance buttons
        grid_label = QLabel("Maintenance Operations")
        grid_label.setStyleSheet(
            "color: #7aa2f7; font-weight: 700; font-size: 14px; margin-top: 4px;"
        )
        layout.addWidget(grid_label)

        ops = [
            (
                "Clean Package Cache",
                "Remove cached packages to free disk space",
                self.clean_cache,
                "#e0af68",
            ),
            (
                "Remove Orphans",
                "Remove packages no longer needed as dependencies",
                self.remove_orphans,
                "#f7768e",
            ),
            (
                "Sync Databases",
                "Force refresh of package databases",
                self.sync_databases,
                "#7aa2f7",
            ),
            (
                "Clean Flatpak Cache",
                "Remove unused Flatpak runtimes and data",
                self.clean_flatpak,
                "#73daca",
            ),
            (
                "List Explicitly Installed",
                "Show packages you installed explicitly",
                self.list_explicit,
                "#9ece6a",
            ),
            (
                "Fix Broken Packages",
                "Attempt to repair broken dependencies",
                self.fix_broken,
                "#bb9af7",
            ),
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

        self.terminal = TerminalPanel(max_height=200)
        layout.addWidget(self.terminal)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

    def check_app_update(self):
        self.check_app_update_btn.setEnabled(False)
        self.app_update_status.setText("Checking...")
        self.app_update_status.setStyleSheet("color: #565f89; font-size: 12px;")

        self._app_update_checker = AppUpdateChecker()
        self._app_update_checker.update_available.connect(self._on_update_available)
        self._app_update_checker.no_update.connect(self._on_no_update)
        self._app_update_checker.error.connect(self._on_update_check_error)
        self._app_update_checker.finished.connect(
            lambda: self.check_app_update_btn.setEnabled(True)
        )
        self._app_update_checker.start()

    def _on_update_available(self, version: str, url: str):
        self.app_update_status.setText(f"Update available: v{version}")
        self.app_update_status.setStyleSheet("color: #e0af68; font-weight: 700; font-size: 12px;")
        self.terminal.append_info(f"New version available: v{version}")
        self.terminal.append_info(f"Download: {url}")
        self.terminal.append_info("Run install.sh or: cd ~/.local/lib/xpak && git pull")

    def _on_no_update(self):
        self.app_update_status.setText("Up to date")
        self.app_update_status.setStyleSheet("color: #9ece6a; font-weight: 700; font-size: 12px;")
        self.terminal.append_success("XPAK is up to date")

    def _on_update_check_error(self, msg: str):
        self.app_update_status.setText("Check failed")
        self.app_update_status.setStyleSheet("color: #f7768e; font-size: 12px;")
        self.terminal.append_error(f"Update check failed: {msg}")

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
        self.terminal.set_worker(self._worker)

    def _on_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
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
                ["pacman", "-Qdtq"],
                text=True,
                stderr=subprocess.DEVNULL,
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
                ["pacman", "-Qe"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.strip().splitlines():
                self.terminal.append_line(f"  {line}", "#c0caf5")
        except Exception as e:
            self.terminal.append_error(str(e))

    def fix_broken(self):
        self.terminal.append_info("Attempting to fix broken dependencies")
        self._run(["pacman", "-Dk"], sudo=False)
