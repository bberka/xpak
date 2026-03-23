from pathlib import Path
import subprocess
import shutil
import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSplitter, QProgressBar,
    QMessageBox, QDialog, QTextEdit, QFrame, QApplication,
    QAbstractItemView, QCheckBox, QScrollArea, QTableWidget,
    QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from xpak import APP_ROOT, INSTALL_SCRIPT
from xpak.workers import (
    CommandWorker, SearchWorker, InstalledLoader, UpdateChecker, AppUpdateChecker,
    build_search_terms,
    format_size_bytes,
    format_size_delta,
    get_pacman_updates,
    get_available_pacman_repos,
    normalize_search_query,
)
from xpak.widgets import TerminalOutput, TerminalPanel, PackageTable, SourceSelector
from xpak.dialogs import PasswordDialog
from xpak.logging_service import get_logger, get_log_dir
from xpak.settings import (
    build_launch_command,
    load_repo_preferences,
    load_startup_preferences,
    load_update_preferences,
    RESTART_INSTANCE_ARG,
    save_repo_preferences,
    save_startup_preferences,
    save_update_preferences,
    sync_autostart_file,
)


logger = get_logger("xpak.tabs")


def open_in_file_manager(path: Path) -> bool:
    path = Path(path).expanduser().resolve()
    uri = path.as_uri()

    # Prefer the desktop file manager D-Bus API so directories do not get
    # handed off to editor associations like VS Code.
    if shutil.which("dbus-send"):
        try:
            subprocess.run(
                [
                    "dbus-send",
                    "--session",
                    "--type=method_call",
                    "--dest=org.freedesktop.FileManager1",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowFolders",
                    f"array:string:{uri}",
                    "string:",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except subprocess.CalledProcessError:
            pass

    # Fall back to common Linux file managers before the generic opener.
    candidates = [
        ["kioclient6", "exec", str(path)],
        ["kioclient5", "exec", str(path)],
        ["kioclient", "exec", str(path)],
        ["dolphin", str(path)],
        ["nautilus", str(path)],
        ["nemo", str(path)],
        ["thunar", str(path)],
        ["pcmanfm", str(path)],
        ["xdg-open", str(path)],
    ]
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue

    return False


class SearchTab(QWidget):
    log_message = pyqtSignal(str, str)

    COLUMNS = ["Name", "Version", "Source", "Repo", "Votes", "Download Size", "Description"]
    MIN_SEARCH_LENGTH = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: CommandWorker | None = None
        self._search_worker: SearchWorker | None = None
        self._selected_pkg: dict | None = None
        self._pending_package_ops: list[dict] = []
        self._results: list[dict] = []
        self._sorted_results: list[dict] = []
        self._query: str = ""
        self._include_pacman_repos: list[str] = []
        self._exclude_pacman_repos: list[str] = []
        self._build_ui()

    def _begin_operation(self, description: str) -> bool:
        window = self.window()
        if hasattr(window, "begin_operation"):
            ok, msg = window.begin_operation(description)
            if not ok:
                self.terminal.append_error(f"Cannot start {description.lower()}: {msg}.")
            return ok
        return True

    def _end_operation(self):
        window = self.window()
        if hasattr(window, "end_operation"):
            window.end_operation()

    def set_operation_controls_enabled(self, enabled: bool):
        search_busy = self._search_worker is not None and self._search_worker.isRunning()
        op_busy = self._worker is not None and self._worker.isRunning()
        selected_packages = self._get_selected_packages()
        installable_selected = [pkg for pkg in selected_packages if not pkg.get("installed", False)]
        single_selected = len(selected_packages) == 1
        selected_installed = bool(single_selected and self._selected_pkg and self._selected_pkg.get("installed", False))

        self.search_input.setEnabled(enabled and not search_busy)
        self.source_selector.setEnabled(enabled and not search_busy)
        self.search_btn.setEnabled(enabled and not search_busy)
        self.install_btn.setEnabled(enabled and not op_busy and bool(installable_selected))
        self.remove_btn.setEnabled(enabled and not op_busy and single_selected and selected_installed)
        self.info_btn.setEnabled(bool(self._selected_pkg) and single_selected and not op_busy)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Search bar row
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            f"Search packages ({self.MIN_SEARCH_LENGTH}+ chars)..."
        )
        self.search_input.returnPressed.connect(self.do_search)
        self.setFocusProxy(self.search_input)

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
        self.sort_combo.addItems(["Relevance", "Name", "Version", "Source", "Repo", "Votes"])
        self.sort_combo.currentTextChanged.connect(self._apply_sort)

        order_lbl = QLabel("Order:")
        order_lbl.setStyleSheet("color: #565f89; font-size: 12px; margin-left: 12px;")
        self.order_combo = QComboBox()
        self.order_combo.addItems(["Ascending", "Descending"])
        self.order_combo.currentTextChanged.connect(self._apply_sort)

        self.search_desc_check = QCheckBox("Search descriptions")
        self.search_desc_check.setChecked(True)
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
        self.table.set_header_sorting_enabled(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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

    def focus_primary_input(self):
        if self.search_input.isEnabled():
            self.search_input.setFocus()
            self.search_input.selectAll()

    def _on_sources_changed(self, sources: list):
        # If a search is currently showing results, re-run or just note the change
        pass

    def do_search(self):
        raw_query = self.search_input.text().strip()
        if not raw_query:
            return
        query = normalize_search_query(raw_query)
        if not query:
            return
        if len(query) < self.MIN_SEARCH_LENGTH:
            msg = f"Enter at least {self.MIN_SEARCH_LENGTH} characters before searching"
            self.status_label.setText(msg)
            self.terminal.append_error(msg)
            return

        sources = self.source_selector.get_sources()
        if not sources:
            self.terminal.append_error("No sources selected")
            return

        if not self._begin_operation(f"Search: {query}"):
            return

        self._results = []
        self._sorted_results = []
        self._query = query
        self.table.setRowCount(0)
        self.terminal.append_info(f"Searching '{query}' in {', '.join(sources)}")
        self.progress.setVisible(True)
        self.search_btn.setEnabled(False)
        self.status_label.setText("Searching...")

        self._include_pacman_repos, self._exclude_pacman_repos = load_repo_preferences()
        self._search_worker = SearchWorker(
            query,
            sources,
            include_pacman_repos=self._include_pacman_repos,
            exclude_pacman_repos=self._exclude_pacman_repos,
        )
        self._search_worker.result_chunk.connect(self._on_result_chunk)
        self._search_worker.search_done.connect(self._on_search_done)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.finished.connect(lambda: (
            self.progress.setVisible(False),
            self._end_operation(),
            self.set_operation_controls_enabled(True),
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
            self._sorted_results = []
            self.table.setRowCount(0)
            if getattr(self, "_search_worker", None) is None:
                self.status_label.setText("0 results")
            return

        sort_key = self.sort_combo.currentText()
        descending = self.order_combo.currentText() == "Descending"
        search_desc = self.search_desc_check.isChecked()
        query_terms = build_search_terms(self._query)
        primary_query = query_terms[0] if query_terms else self._query.lower()

        # Filter: exclude description-only matches when search descriptions is off
        if primary_query and not search_desc:
            results = [
                p for p in self._results
                if any(term in p.get("name", "").lower() for term in query_terms)
            ]
        else:
            results = list(self._results)

        if sort_key == "Relevance":
            def _relevance(pkg):
                name = pkg.get("name", "").lower()
                if name == primary_query:
                    return 0
                if name in query_terms:
                    return 1
                if any(name.startswith(term) for term in query_terms):
                    return 2
                if any(term in name for term in query_terms):
                    return 3
                return 4  # description-only match

            self._sorted_results = sorted(results, key=_relevance, reverse=descending)
        elif sort_key == "Votes":
            def _votes(pkg):
                try:
                    return int(pkg.get("votes", "") or 0)
                except ValueError:
                    return 0

            self._sorted_results = sorted(results, key=_votes, reverse=not descending)
        else:
            key = sort_key.lower()
            self._sorted_results = sorted(
                results,
                key=lambda p: p.get(key, "").lower(),
                reverse=descending,
            )
        self.table.populate(self._sorted_results, self.COLUMNS)
        self.status_label.setText(f"{len(self._sorted_results)} results")

    def _on_selection(self):
        packages = self._get_selected_packages()
        if not packages:
            self._selected_pkg = None
            self.set_operation_controls_enabled(True)
            return

        row = self.table.currentRow()
        item = self.table.item(row, 0)
        if item is not None:
            pkg = item.data(Qt.ItemDataRole.UserRole)
            if pkg:
                self._selected_pkg = pkg
                self.set_operation_controls_enabled(True)
                return

        self._selected_pkg = None
        self.set_operation_controls_enabled(True)

    def _get_selected_packages(self) -> list[dict]:
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        packages = []
        seen = set()
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item is None:
                continue
            pkg = item.data(Qt.ItemDataRole.UserRole)
            if not pkg:
                continue
            key = (pkg.get("source", ""), pkg.get("app_id") or pkg.get("name", ""))
            if key in seen:
                continue
            seen.add(key)
            packages.append(pkg)
        return packages

    def install_package(self):
        selected_packages = self._get_selected_packages()
        if not selected_packages:
            return

        packages_to_install = [pkg for pkg in selected_packages if not pkg.get("installed", False)]
        if not packages_to_install:
            self.terminal.append_error("All selected packages are already installed.")
            return

        if len(selected_packages) > 1:
            package_list = "\n".join(
                f"- {pkg['name']} ({pkg['source']})"
                f"{' [already installed]' if pkg.get('installed', False) else ''}"
                for pkg in selected_packages
            )
            reply = QMessageBox.question(
                self,
                "Confirm Install",
                "Install these selected packages?\n\n"
                f"{package_list}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        batch_map: dict[str, list[str]] = {}
        display_map: dict[str, list[str]] = {}
        for pkg in packages_to_install:
            source = pkg["source"]
            target = pkg.get("app_id") if source == "flatpak" else pkg["name"]
            if not target:
                continue
            batch_map.setdefault(source, [])
            display_map.setdefault(source, [])
            if target not in batch_map[source]:
                batch_map[source].append(target)
                display_map[source].append(pkg["name"])

        if not batch_map:
            self.terminal.append_error("Could not determine install targets for the selected packages.")
            return

        aur_password = ""
        pacman_password = ""
        if "aur" in batch_map:
            dlg = PasswordDialog(
                self,
                message=(
                    "yay requires sudo for AUR package operations. "
                    "Your password will be used to pre-authenticate sudo."
                ),
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            aur_password = dlg.password()
        if "pacman" in batch_map:
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            pacman_password = dlg.password()

        pending_ops = []
        for source, names in batch_map.items():
            if source == "flatpak":
                cmd = ["flatpak", "install", "-y", *names]
                sudo = False
                password = ""
                pre_auth = False
            elif source == "aur":
                cmd = ["yay", "-S", "--noconfirm", "--answerclean=All", "--answerdiff=None", *names]
                sudo = False
                password = aur_password
                pre_auth = True
            else:
                cmd = ["pacman", "-S", "--noconfirm", *names]
                sudo = True
                password = pacman_password
                pre_auth = False

            pending_ops.append(
                {
                    "source": source,
                    "cmd": cmd,
                    "sudo": sudo,
                    "password": password,
                    "pre_auth": pre_auth,
                    "display_names": display_map[source],
                    "log_name": f"search:install:{source}:{','.join(names)}",
                }
            )

        summary = f"Installing {len(packages_to_install)} package{'s' if len(packages_to_install) != 1 else ''}"
        if not self._begin_operation(summary):
            return

        self.progress.setVisible(True)
        self.install_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.info_btn.setEnabled(False)
        self._pending_package_ops = pending_ops
        self._start_next_package_op()

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
                cmd = ["yay", "-S", "--noconfirm", "--answerclean=All", "--answerdiff=None", name]
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
        if not self._begin_operation(f"{verb} {name}"):
            return

        self.terminal.append_info(f"{verb} {name} via {source}")
        self.progress.setVisible(True)
        self.install_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)

        self._worker = CommandWorker(
            cmd,
            sudo=sudo,
            password=password,
            pre_auth=pre_auth,
            log_name=f"search:{operation}:{name}",
        )
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_op_finished)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _start_next_package_op(self):
        if not self._pending_package_ops:
            self.terminal.set_worker(None)
            self.progress.setVisible(False)
            self._end_operation()
            self.set_operation_controls_enabled(True)
            return

        op = self._pending_package_ops.pop(0)
        display_names = ", ".join(op["display_names"])
        self.terminal.append_info(f"Installing {display_names} via {op['source']}")
        self._worker = CommandWorker(
            op["cmd"],
            sudo=op["sudo"],
            password=op["password"],
            pre_auth=op["pre_auth"],
            log_name=op["log_name"],
        )
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_op_finished)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_op_finished(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        if success:
            self.terminal.append_success(msg)
            if self._pending_package_ops:
                self._start_next_package_op()
                return
        else:
            self.terminal.append_error(msg)
            self._pending_package_ops = []
        self.progress.setVisible(False)
        self._end_operation()
        self.set_operation_controls_enabled(True)


class InstalledTab(QWidget):
    COLUMNS = ["Name", "Version", "Source", "Repo", "Installed Size"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packages: list[dict] = []
        self._filtered: list[dict] = []
        self._worker: CommandWorker | None = None
        self._build_ui()
        QTimer.singleShot(200, lambda: self.load_packages(quiet=True))

    def _begin_operation(self, description: str) -> bool:
        window = self.window()
        if hasattr(window, "begin_operation"):
            ok, msg = window.begin_operation(description)
            if not ok:
                self.terminal.append_error(f"Cannot start {description.lower()}: {msg}.")
            return ok
        return True

    def _end_operation(self):
        window = self.window()
        if hasattr(window, "end_operation"):
            window.end_operation()

    def set_operation_controls_enabled(self, enabled: bool):
        loader_busy = hasattr(self, "_loader") and self._loader is not None and self._loader.isRunning()
        worker_busy = self._worker is not None and self._worker.isRunning()

        self.refresh_btn.setEnabled(enabled and not loader_busy)
        self.remove_btn.setEnabled(enabled and not worker_busy and bool(self.table.selectedItems()))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        toolbar = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter installed packages...")
        self.filter_input.textChanged.connect(self._apply_filter)
        self.setFocusProxy(self.filter_input)

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

    def focus_primary_input(self):
        if self.filter_input.isEnabled():
            self.filter_input.setFocus()
            self.filter_input.selectAll()

    def load_packages(self, quiet: bool = False):
        window = self.window()
        if quiet and hasattr(window, "has_active_operation") and window.has_active_operation():
            QTimer.singleShot(1000, lambda: self.load_packages(quiet=True))
            return

        if not self._begin_operation("Loading installed packages"):
            return

        self.progress.setVisible(True)
        self.refresh_btn.setEnabled(False)
        include_pacman_repos, exclude_pacman_repos = load_repo_preferences()
        self._loader = InstalledLoader(
            "all",
            include_pacman_repos=include_pacman_repos,
            exclude_pacman_repos=exclude_pacman_repos,
        )
        self._loader.results_ready.connect(self._on_loaded)
        self._loader.finished.connect(lambda: (
            self.progress.setVisible(False),
            self._end_operation(),
            self.set_operation_controls_enabled(True),
        ))
        self._loader.start()

    def _on_loaded(self, packages: list):
        self._packages = packages
        self._apply_filter()
        self._update_count_label()

    def _apply_filter(self):
        query = self.filter_input.text().lower()
        src = self.source_filter.currentText().lower()
        self._filtered = [
            p for p in self._packages
            if (not query or query in p["name"].lower())
            and (src == "all" or p["source"].lower() == src)
        ]
        self.table.populate(self._filtered, self.COLUMNS)
        self._update_count_label()

    def _update_count_label(self):
        filtered_known = [pkg.get("installed_size_bytes") for pkg in self._filtered if pkg.get("installed_size_bytes") is not None]
        total_known = [pkg.get("installed_size_bytes") for pkg in self._packages if pkg.get("installed_size_bytes") is not None]
        filtered_size = sum(filtered_known)
        total_size = sum(total_known)
        filtered_unknown = len(self._filtered) - len(filtered_known)
        total_unknown = len(self._packages) - len(total_known)
        if len(self._filtered) == len(self._packages):
            if self._packages:
                label = f"{len(self._packages)} packages installed"
                if total_known:
                    label += f" • {format_size_bytes(total_size)} on disk"
                    if total_unknown:
                        label += " known"
                elif total_unknown:
                    label += " • N/A size"
                self.count_label.setText(label)
            else:
                self.count_label.setText("0 packages installed")
            return

        label = f"Showing {len(self._filtered)} / {len(self._packages)} packages"
        if filtered_known:
            label += f" • {format_size_bytes(filtered_size)} shown"
            if filtered_unknown:
                label += " known"
        elif filtered_unknown:
            label += " • N/A shown size"
        if total_known:
            label += f" • {format_size_bytes(total_size)} total"
            if total_unknown:
                label += " known"
        elif total_unknown:
            label += " • N/A total size"
        self.count_label.setText(label)

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

        if not self._begin_operation(f"Removing {pkg['name']}"):
            return

        self.terminal.append_info(f"Removing {pkg['name']}")
        self.progress.setVisible(True)
        self.remove_btn.setEnabled(False)

        self._worker = CommandWorker(
            cmd,
            sudo,
            password,
            log_name=f"installed:remove:{pkg['name']}",
        )
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_remove_done)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_remove_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        self._end_operation()
        if success:
            self.terminal.append_success(msg)
            self.load_packages()
        else:
            self.terminal.append_error(msg)
            self.set_operation_controls_enabled(True)


class UpdatesTab(QWidget):
    COLUMNS = ["Name", "Old Version", "New Version", "Source", "Repo", "Download Size", "Size Change"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updates: list[dict] = []
        self._filtered_updates: list[dict] = []
        self._selected_update: dict | None = None
        self._worker: CommandWorker | None = None
        self._include_pacman_repos: list[str] = []
        self._exclude_pacman_repos: list[str] = []
        self._build_ui()
        self.reload_preferences()

    def _begin_operation(self, description: str) -> bool:
        window = self.window()
        if hasattr(window, "begin_operation"):
            ok, msg = window.begin_operation(description)
            if not ok:
                self.terminal.append_error(f"Cannot start {description.lower()}: {msg}.")
            return ok
        return True

    def _end_operation(self):
        window = self.window()
        if hasattr(window, "end_operation"):
            window.end_operation()

    def set_operation_controls_enabled(self, enabled: bool):
        checker_busy = hasattr(self, "_checker") and self._checker is not None and self._checker.isRunning()
        worker_busy = self._worker is not None and self._worker.isRunning()
        has_updates = bool(self._updates)
        has_selected_update = self._selected_update is not None

        self.check_btn.setEnabled(enabled and not checker_busy)
        self.update_all_btn.setEnabled(enabled and not worker_busy and has_updates)
        self.update_selected_btn.setEnabled(enabled and not worker_busy and has_selected_update)
        self.update_pacman_btn.setEnabled(enabled and not worker_busy)
        self.update_flatpak_btn.setEnabled(
            enabled and not worker_busy and shutil.which("flatpak") is not None
        )
        self.update_aur_btn.setEnabled(
            enabled and not worker_busy and shutil.which("yay") is not None
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        filter_row = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter available updates...")
        self.filter_input.textChanged.connect(self._apply_filter)
        self.setFocusProxy(self.filter_input)
        filter_row.addWidget(self.filter_input)
        layout.addLayout(filter_row)

        toolbar = QHBoxLayout()
        self.check_btn = QPushButton("Check for Updates")
        self.check_btn.clicked.connect(self.check_updates)

        self.update_all_btn = QPushButton("Update All")
        self.update_all_btn.setObjectName("primary")
        self.update_all_btn.setEnabled(False)
        self.update_all_btn.clicked.connect(self.update_all)

        self.update_selected_btn = QPushButton("Update Selected")
        self.update_selected_btn.setObjectName("primary")
        self.update_selected_btn.setEnabled(False)
        self.update_selected_btn.clicked.connect(self.update_selected)

        self.update_pacman_btn = QPushButton("Update Pacman")
        self.update_pacman_btn.setObjectName("success")
        self.update_pacman_btn.setEnabled(True)
        self.update_pacman_btn.clicked.connect(self.update_pacman)

        self.update_flatpak_btn = QPushButton("Update Flatpaks")
        self.update_flatpak_btn.setObjectName("success")
        self.update_flatpak_btn.setEnabled(shutil.which("flatpak") is not None)
        self.update_flatpak_btn.clicked.connect(self.update_flatpak)

        self.update_aur_btn = QPushButton("Update AUR")
        self.update_aur_btn.setObjectName("success")
        self.update_aur_btn.setEnabled(shutil.which("yay") is not None)
        self.update_aur_btn.clicked.connect(self.update_aur)

        self.status_label = QLabel("Not checked")
        self.status_label.setStyleSheet("color: #565f89;")

        toolbar.addWidget(self.check_btn)
        toolbar.addWidget(self.update_all_btn)
        toolbar.addWidget(self.update_selected_btn)
        toolbar.addWidget(self.update_pacman_btn)
        toolbar.addWidget(self.update_flatpak_btn)
        toolbar.addWidget(self.update_aur_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        self.table = PackageTable(self.COLUMNS)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.terminal = TerminalPanel(max_height=200)
        layout.addWidget(self.terminal)

    def focus_primary_input(self):
        if self.filter_input.isEnabled():
            self.filter_input.setFocus()
            self.filter_input.selectAll()

    def reload_preferences(self):
        self._include_pacman_repos, self._exclude_pacman_repos = load_repo_preferences()
        self.set_operation_controls_enabled(True)

    def _apply_filter(self):
        query = self.filter_input.text().strip().lower()
        self._filtered_updates = [
            update for update in self._updates
            if not query or query in update.get("name", "").lower()
        ]
        self.table.populate(self._filtered_updates, self.COLUMNS)
        self._selected_update = None
        self.update_selected_btn.setEnabled(False)
        self._update_status_summary()

    def _on_selection(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        pkg = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self._selected_update = pkg if pkg else None
        self.set_operation_controls_enabled(True)

    def check_updates(self, quiet: bool = False):
        window = self.window()
        if quiet and hasattr(window, "has_active_operation") and window.has_active_operation():
            QTimer.singleShot(1000, lambda: self.check_updates(quiet=True))
            return

        if not self._begin_operation("Checking for updates"):
            return

        self.progress.setVisible(True)
        self.check_btn.setEnabled(False)
        self.update_all_btn.setEnabled(False)
        self.terminal.append_info("Checking for updates")

        self.reload_preferences()
        self._checker = UpdateChecker(
            include_pacman_repos=self._include_pacman_repos,
            exclude_pacman_repos=self._exclude_pacman_repos,
        )
        self._checker.updates_ready.connect(self._on_updates)
        self._checker.finished.connect(lambda: (
            self.progress.setVisible(False),
            self._end_operation(),
            self.set_operation_controls_enabled(True),
        ))
        self._checker.start()

    def _on_updates(self, updates: list):
        self.apply_updates_result(updates, announce=True)

    @staticmethod
    def _collect_size_totals(updates: list[dict], key: str) -> tuple[list[int], int]:
        known_sizes = [update.get(key) for update in updates if update.get(key) is not None]
        return known_sizes, len(updates) - len(known_sizes)

    @staticmethod
    def _format_size_summary(updates: list[dict]) -> str:
        parts = []

        known_downloads, unknown_downloads = UpdatesTab._collect_size_totals(updates, "download_size_bytes")
        if known_downloads:
            parts.append(
                f"{format_size_bytes(sum(known_downloads))} {'known download' if unknown_downloads else 'total download'}"
            )
        elif unknown_downloads:
            parts.append("N/A download size")

        known_changes, unknown_changes = UpdatesTab._collect_size_totals(updates, "size_change_bytes")
        if known_changes:
            parts.append(
                f"{format_size_delta(sum(known_changes))} {'known size change' if unknown_changes else 'total size change'}"
            )

        return " • ".join(parts)

    def apply_updates_result(self, updates: list, announce: bool = False):
        self._updates = updates
        self._apply_filter()
        self.set_operation_controls_enabled(True)
        if announce:
            count = len(updates)
            summary = self._format_size_summary(updates)
            if summary:
                self.terminal.append_success(f"Check complete: {count} updates found • {summary}")
            else:
                self.terminal.append_success(f"Check complete: {count} updates found")

    def _update_status_summary(self):
        count = len(self._filtered_updates)
        if count:
            label = f"{count} update{'s' if count != 1 else ''} available"
            summary = self._format_size_summary(self._filtered_updates)
            if summary:
                label += f" • {summary}"
            self.status_label.setText(label)
            self.status_label.setStyleSheet("color: #e0af68; font-weight: 700;")
        elif self._updates:
            label = f"No matching updates • {len(self._updates)} total pending"
            summary = self._format_size_summary(self._updates)
            if summary:
                label += f" • {summary}"
            self.status_label.setText(label)
            self.status_label.setStyleSheet("color: #565f89; font-weight: 700;")
        else:
            self.status_label.setText("System is up to date")
            self.status_label.setStyleSheet("color: #9ece6a; font-weight: 700;")

    def update_all(self):
        self.reload_preferences()
        if self._include_pacman_repos or self._exclude_pacman_repos:
            self._run_filtered_pacman_update()
            return

        dlg = PasswordDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        self.terminal.append_info("Starting full system update")
        self._run_update(["pacman", "-Syu", "--noconfirm"], sudo=True, password=password)

    def update_selected(self):
        pkg = self._selected_update
        if not pkg:
            return

        source = pkg.get("source", "")
        if source == "flatpak":
            app_id = pkg.get("app_id") or pkg.get("name", "")
            if not app_id:
                self.terminal.append_error("Could not determine the Flatpak app ID for this update.")
                return
            self.terminal.append_info(f"Updating selected Flatpak: {pkg.get('name', app_id)}")
            self._run_update(["flatpak", "update", "-y", app_id], sudo=False)
            return

        if source == "pacman":
            name = pkg.get("name", "")
            if not name:
                self.terminal.append_error("Could not determine the package name for this update.")
                return
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()
            self.terminal.append_info(f"Updating selected package: {name}")
            self._run_update(["pacman", "-S", "--noconfirm", name], sudo=True, password=password)
            return

        self.terminal.append_error(f"Updating a single {source or 'unknown'} package is not supported yet.")

    def update_pacman(self):
        self.reload_preferences()
        if self._include_pacman_repos or self._exclude_pacman_repos:
            self._run_filtered_pacman_update()
            return
        dlg = PasswordDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        self.terminal.append_info("Updating Pacman packages")
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
            ["yay", "-Syu", "--aur", "--noconfirm", "--answerclean=All", "--answerdiff=None"],
            sudo=False,
            password=password,
            pre_auth=True,
        )

    def _run_filtered_pacman_update(self):
        visible_updates, ignored_packages = get_pacman_updates(
            include_repos=self._include_pacman_repos,
            exclude_repos=self._exclude_pacman_repos,
        )
        if not visible_updates:
            self.terminal.append_error("No matching pacman updates are available to install.")
            return

        dlg = PasswordDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        password = dlg.password()
        if ignored_packages:
            self.terminal.append_info(
                f"Updating filtered pacman packages and skipping {len(ignored_packages)} package"
                f"{'s' if len(ignored_packages) != 1 else ''}"
            )
        else:
            self.terminal.append_info("Updating pacman packages")

        cmd = ["pacman", "-Syu", "--noconfirm"]
        if ignored_packages:
            cmd.extend(["--ignore", ",".join(ignored_packages)])
        self._run_update(cmd, sudo=True, password=password)

    def _run_update(self, cmd: list, sudo: bool = False, password: str = "", pre_auth: bool = False):
        if not self._begin_operation(f"Running {' '.join(cmd[:2])}"):
            return

        self.progress.setVisible(True)
        self.update_all_btn.setEnabled(False)
        self._worker = CommandWorker(
            cmd,
            sudo=sudo,
            password=password,
            pre_auth=pre_auth,
            log_name=f"updates:{' '.join(cmd[:2])}",
        )
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_update_done)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_update_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        self._end_operation()
        if success:
            self.terminal.append_success(msg)
            self.check_updates()
        else:
            self.terminal.append_error(msg)
            self.set_operation_controls_enabled(True)


class ToolsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: CommandWorker | None = None
        self._app_update_checker: AppUpdateChecker | None = None
        self._pending_app_update_version: str | None = None
        self._pending_app_update_url: str | None = None
        self._action_buttons: list[QPushButton] = []
        self._build_ui()

    def _begin_operation(self, description: str) -> bool:
        window = self.window()
        if hasattr(window, "begin_operation"):
            ok, msg = window.begin_operation(description)
            if not ok:
                self.terminal.append_error(f"Cannot start {description.lower()}: {msg}.")
            return ok
        return True

    def _end_operation(self):
        window = self.window()
        if hasattr(window, "end_operation"):
            window.end_operation()

    def set_operation_controls_enabled(self, enabled: bool):
        worker_busy = self._worker is not None and self._worker.isRunning()
        checker_busy = self._app_update_checker is not None and self._app_update_checker.isRunning()
        for btn in self._action_buttons:
            btn.setEnabled(enabled and not worker_busy)
        self.check_app_update_btn.setEnabled(enabled and not worker_busy and not checker_busy)
        self.update_app_btn.setEnabled(
            enabled and not worker_busy and not checker_busy and self.update_app_btn.isVisible()
        )
        if hasattr(self, "open_log_folder_btn"):
            self.open_log_folder_btn.setEnabled(enabled)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # App Updates section
        app_update_label = QLabel("XPAK Updates")
        app_update_label.setStyleSheet(
            "color: #7aa2f7; font-weight: 700; font-size: 14px;"
        )
        content_layout.addWidget(app_update_label)

        app_update_row = QHBoxLayout()
        self.check_app_update_btn = QPushButton("Check for XPAK Update")
        self.check_app_update_btn.clicked.connect(self.check_app_update)
        self.setFocusProxy(self.check_app_update_btn)
        app_update_row.addWidget(self.check_app_update_btn)

        self.update_app_btn = QPushButton("Update Now")
        self.update_app_btn.setObjectName("primary")
        self.update_app_btn.setVisible(False)
        self.update_app_btn.clicked.connect(self.update_app)
        app_update_row.addWidget(self.update_app_btn)

        self.app_update_status = QLabel("")
        self.app_update_status.setStyleSheet("color: #565f89; font-size: 12px; margin-left: 12px;")
        app_update_row.addWidget(self.app_update_status)
        app_update_row.addStretch()
        content_layout.addLayout(app_update_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2b3d;")
        content_layout.addWidget(sep)

        logging_label = QLabel("Logging")
        logging_label.setStyleSheet(
            "color: #7aa2f7; font-weight: 700; font-size: 14px; margin-top: 4px;"
        )
        content_layout.addWidget(logging_label)

        logging_row = QHBoxLayout()
        self.open_log_folder_btn = QPushButton("Open Log Folder")
        self.open_log_folder_btn.clicked.connect(self.open_log_folder)
        logging_row.addWidget(self.open_log_folder_btn)

        self.log_path_label = QLabel(str(get_log_dir()))
        self.log_path_label.setStyleSheet("color: #565f89; font-size: 11px;")
        self.log_path_label.setWordWrap(True)
        logging_row.addWidget(self.log_path_label)
        logging_row.addStretch()
        content_layout.addLayout(logging_row)

        sep_logs = QFrame()
        sep_logs.setFrameShape(QFrame.Shape.HLine)
        sep_logs.setStyleSheet("color: #2a2b3d;")
        content_layout.addWidget(sep_logs)

        # Maintenance buttons
        grid_label = QLabel("Maintenance Operations")
        grid_label.setStyleSheet(
            "color: #7aa2f7; font-weight: 700; font-size: 14px; margin-top: 4px;"
        )
        content_layout.addWidget(grid_label)

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
            self._action_buttons.append(btn)

            card_layout.addWidget(t)
            card_layout.addWidget(d)
            card_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

            if i % 2 == 0:
                left_col.addWidget(card)
            else:
                right_col.addWidget(card)

        grid.addLayout(left_col)
        grid.addLayout(right_col)
        content_layout.addLayout(grid)
        content_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)

        self.terminal = TerminalPanel(max_height=200)
        layout.addWidget(self.terminal)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

    def focus_primary_input(self):
        if self.check_app_update_btn.isEnabled():
            self.check_app_update_btn.setFocus()

    def check_app_update(self):
        self.check_app_update_btn.setEnabled(False)
        self._pending_app_update_version = None
        self._pending_app_update_url = None
        self.update_app_btn.setVisible(False)
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

    def open_log_folder(self):
        log_dir = get_log_dir()
        logger.info("Opening log folder: %s", log_dir)
        opened = open_in_file_manager(log_dir)
        if not opened:
            self.terminal.append_error(f"Could not open log folder: {log_dir}")

    def _on_update_available(self, version: str, url: str):
        self.display_app_update_result(version, url, announce=True)

    def display_app_update_result(self, version: str, url: str, announce: bool = False):
        self._pending_app_update_version = version
        self._pending_app_update_url = url
        self.app_update_status.setText(f"Update available: v{version}")
        self.app_update_status.setStyleSheet("color: #e0af68; font-weight: 700; font-size: 12px;")
        self.update_app_btn.setText(f"Update to v{version}")
        self.update_app_btn.setVisible(True)
        self.update_app_btn.setEnabled(True)
        if announce:
            self.terminal.append_info(f"New version available: v{version}")
            self.terminal.append_info(f"Download: {url}")
            self.terminal.append_info("Use the update button to install and restart automatically.")

    def _on_no_update(self):
        self.display_app_up_to_date(announce=True)

    def display_app_up_to_date(self, announce: bool = False):
        self._pending_app_update_version = None
        self._pending_app_update_url = None
        self.update_app_btn.setVisible(False)
        self.app_update_status.setText("Up to date")
        self.app_update_status.setStyleSheet("color: #9ece6a; font-weight: 700; font-size: 12px;")
        if announce:
            self.terminal.append_success("XPAK is up to date")

    def _on_update_check_error(self, msg: str):
        self.display_app_update_error(msg, announce=True)

    def display_app_update_error(self, msg: str, announce: bool = False):
        self._pending_app_update_version = None
        self._pending_app_update_url = None
        self.update_app_btn.setVisible(False)
        self.app_update_status.setText("Check failed")
        self.app_update_status.setStyleSheet("color: #f7768e; font-size: 12px;")
        if announce:
            self.terminal.append_error(f"Update check failed: {msg}")

    def update_app(self):
        version = self._pending_app_update_version
        if not version:
            self.terminal.append_error("No pending app update found. Check for updates again.")
            return

        if not INSTALL_SCRIPT.is_file():
            self.terminal.append_error(f"Could not find installer script: {INSTALL_SCRIPT}")
            self.app_update_status.setText("Install script missing")
            self.app_update_status.setStyleSheet("color: #f7768e; font-size: 12px;")
            return

        answer = QMessageBox.question(
            self,
            "Update XPAK",
            (
                f"Install XPAK v{version} now?\n\n"
                "The app will update itself, then restart automatically."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if not self._begin_operation("Updating XPAK"):
            return

        self.progress.setVisible(True)
        self.update_app_btn.setEnabled(False)
        self.check_app_update_btn.setEnabled(False)
        self.app_update_status.setText(f"Updating to v{version}...")
        self.app_update_status.setStyleSheet("color: #7aa2f7; font-weight: 700; font-size: 12px;")
        self.terminal.append_info(f"Starting self-update to v{version}")

        self._worker = CommandWorker(
            ["bash", str(INSTALL_SCRIPT)],
            sudo=False,
            log_name="maintenance:self-update",
        )
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_app_update_done)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_app_update_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        self._end_operation()

        if success:
            version = self._pending_app_update_version or "latest version"
            self.app_update_status.setText(f"Updated to v{version}. Restarting...")
            self.app_update_status.setStyleSheet("color: #9ece6a; font-weight: 700; font-size: 12px;")
            self.terminal.append_success("Update installed successfully")
            self.terminal.append_info("Restarting XPAK...")
            self._restart_application()
            return

        self.app_update_status.setText("Update failed")
        self.app_update_status.setStyleSheet("color: #f7768e; font-size: 12px;")
        self.update_app_btn.setEnabled(True)
        self.terminal.append_error(msg)
        self.set_operation_controls_enabled(True)

    def _restart_application(self):
        launch_cmd = [
            *build_launch_command(sys.argv[1:], preserve_start_in_tray=True),
            RESTART_INSTANCE_ARG,
        ]

        main_window = self.window()
        if main_window and hasattr(main_window, "prepare_for_restart"):
            main_window.prepare_for_restart()

        try:
            subprocess.Popen(
                launch_cmd,
                cwd=str(APP_ROOT),
                start_new_session=True,
            )
        except Exception as exc:
            logger.exception("Failed to restart XPAK after self-update")
            self.terminal.append_error(f"Automatic restart failed: {exc}")
            self.app_update_status.setText("Updated, restart manually")
            self.app_update_status.setStyleSheet("color: #e0af68; font-weight: 700; font-size: 12px;")
            self.set_operation_controls_enabled(True)
            return

        QTimer.singleShot(250, QApplication.instance().quit)

    def _run(self, cmd: list, sudo: bool = False):
        password = ""
        if sudo:
            dlg = PasswordDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()

        if not self._begin_operation(f"Running {' '.join(cmd[:2])}"):
            return

        self.progress.setVisible(True)
        self._worker = CommandWorker(
            cmd,
            sudo,
            password,
            log_name=f"maintenance:{' '.join(cmd[:2])}",
        )
        self._worker.output_line.connect(self.terminal.append_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()
        self.terminal.set_worker(self._worker)

    def _on_done(self, success: bool, msg: str):
        self.terminal.set_worker(None)
        self.progress.setVisible(False)
        self._end_operation()
        if success:
            self.terminal.append_success(msg)
        else:
            self.terminal.append_error(msg)
        self.set_operation_controls_enabled(True)

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
            logger.exception("Failed to list explicitly installed packages")
            self.terminal.append_error(str(e))

    def fix_broken(self):
        self.terminal.append_info("Attempting to fix broken dependencies")
        self._run(["pacman", "-Dk"], sudo=False)


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._available_repos: list[str] = []
        self._build_ui()
        self.reload_preferences()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Startup Update Checks")
        title.setStyleSheet("color: #7aa2f7; font-weight: 700; font-size: 14px;")
        layout.addWidget(title)

        description = QLabel(
            "Choose whether XPAK should check for updates at startup, limit those checks "
            "to once per day, and whether it should launch automatically when your desktop session starts."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #565f89; font-size: 12px;")
        layout.addWidget(description)

        self.auto_check_xpak = QCheckBox("Check for XPAK version updates on startup")
        self.auto_check_xpak.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.auto_check_xpak)

        self.auto_check_packages = QCheckBox("Check for installed apps and package updates on startup")
        self.auto_check_packages.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.auto_check_packages)

        self.check_daily = QCheckBox("Regularly check updates every day")
        self.check_daily.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.check_daily)

        startup_title = QLabel("Desktop Startup")
        startup_title.setStyleSheet("color: #7aa2f7; font-weight: 700; font-size: 14px; margin-top: 8px;")
        layout.addWidget(startup_title)

        self.launch_on_startup = QCheckBox("Launch XPAK automatically on system startup")
        self.launch_on_startup.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        self.launch_on_startup.toggled.connect(self._sync_startup_controls)
        layout.addWidget(self.launch_on_startup)

        self.start_to_tray = QCheckBox("If launched on startup, start minimized to tray")
        self.start_to_tray.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.start_to_tray)

        repo_title = QLabel("Pacman Repository Filters")
        repo_title.setStyleSheet("color: #7aa2f7; font-weight: 700; font-size: 14px; margin-top: 8px;")
        layout.addWidget(repo_title)

        repo_description = QLabel(
            "Choose which pacman repositories XPAK should use for search, installed packages, and update checks. "
            "Detected repositories are selected by default."
        )
        repo_description.setWordWrap(True)
        repo_description.setStyleSheet("color: #565f89; font-size: 12px;")
        layout.addWidget(repo_description)

        repo_actions = QHBoxLayout()
        self.available_repos_label = QLabel("")
        self.available_repos_label.setStyleSheet("color: #565f89; font-size: 11px;")
        repo_actions.addWidget(self.available_repos_label)
        repo_actions.addStretch()

        self.select_all_repos_btn = QPushButton("Select All")
        self.select_all_repos_btn.clicked.connect(self._select_all_repos)
        repo_actions.addWidget(self.select_all_repos_btn)
        layout.addLayout(repo_actions)

        self.repo_table = QTableWidget(0, 2)
        self.repo_table.setHorizontalHeaderLabels(["Use", "Repository"])
        self.repo_table.verticalHeader().setVisible(False)
        self.repo_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.repo_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.repo_table.setAlternatingRowColors(True)
        self.repo_table.setShowGrid(False)
        self.repo_table.horizontalHeader().setStretchLastSection(True)
        self.repo_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.repo_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.repo_table.setMaximumHeight(220)
        layout.addWidget(self.repo_table)

        action_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save_preferences)
        self.setFocusProxy(self.save_btn)
        action_row.addWidget(self.save_btn)
        action_row.addStretch()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #565f89; font-size: 12px;")
        action_row.addWidget(self.status_label)
        layout.addLayout(action_row)
        layout.addStretch()

    def focus_primary_input(self):
        if self.save_btn.isEnabled():
            self.save_btn.setFocus()

    def set_operation_controls_enabled(self, enabled: bool):
        self.save_btn.setEnabled(enabled)
        self.auto_check_xpak.setEnabled(enabled)
        self.auto_check_packages.setEnabled(enabled)
        self.check_daily.setEnabled(enabled)
        self.launch_on_startup.setEnabled(enabled)
        self.start_to_tray.setEnabled(enabled and self.launch_on_startup.isChecked())
        self.select_all_repos_btn.setEnabled(enabled)
        self.repo_table.setEnabled(enabled)

    def _sync_startup_controls(self, enabled: bool):
        self.start_to_tray.setEnabled(enabled and self.save_btn.isEnabled())
        if not enabled:
            self.start_to_tray.setChecked(False)

    def reload_preferences(self):
        _, auto_check_xpak, auto_check_packages, check_daily = load_update_preferences()
        include_repos, _ = load_repo_preferences()
        launch_on_startup, start_to_tray = load_startup_preferences()
        self.auto_check_xpak.setChecked(auto_check_xpak)
        self.auto_check_packages.setChecked(auto_check_packages)
        self.check_daily.setChecked(check_daily)
        self.launch_on_startup.setChecked(launch_on_startup)
        self.start_to_tray.setChecked(launch_on_startup and start_to_tray)
        self._sync_startup_controls(launch_on_startup)
        self._available_repos = get_available_pacman_repos()
        repo_rows = self._available_repos or include_repos
        self._populate_repo_table(repo_rows, include_repos)
        if self._available_repos:
            self.available_repos_label.setText(f"{len(self._available_repos)} repos detected")
        else:
            self.available_repos_label.setText("Detected repos unavailable")
        self.status_label.setText("")
        self.status_label.setStyleSheet("color: #565f89; font-size: 12px;")

    def save_preferences(self):
        launch_on_startup = self.launch_on_startup.isChecked()
        start_to_tray = launch_on_startup and self.start_to_tray.isChecked()
        save_update_preferences(
            self.auto_check_xpak.isChecked(),
            self.auto_check_packages.isChecked(),
            self.check_daily.isChecked(),
        )
        selected_repos = self._selected_repo_names()
        if self.repo_table.rowCount() > 0 and not selected_repos:
            self.status_label.setText("Select at least one pacman repository")
            self.status_label.setStyleSheet("color: #f7768e; font-weight: 700; font-size: 12px;")
            return

        repos_to_save = selected_repos
        if self._available_repos and len(selected_repos) == len(self._available_repos):
            repos_to_save = []

        save_repo_preferences(repos_to_save, [])
        save_startup_preferences(launch_on_startup, start_to_tray)
        sync_autostart_file(launch_on_startup, start_to_tray)
        window = self.window()
        if hasattr(window, "refresh_tray_preferences"):
            window.refresh_tray_preferences()
        if hasattr(window, "updates_tab"):
            window.updates_tab.reload_preferences()
        if hasattr(window, "installed_tab"):
            window.installed_tab.load_packages(quiet=True)
        self.status_label.setText("Settings saved")
        self.status_label.setStyleSheet("color: #9ece6a; font-weight: 700; font-size: 12px;")

    def _populate_repo_table(self, repos: list[str], selected_repos: list[str]):
        normalized_repos = []
        seen = set()
        for repo in repos:
            name = str(repo).strip().lower()
            if name and name not in seen:
                normalized_repos.append(name)
                seen.add(name)

        selected_set = set(selected_repos)
        use_defaults = not selected_set

        self.repo_table.setRowCount(len(normalized_repos))
        for row, repo in enumerate(normalized_repos):
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            checkbox_item.setCheckState(
                Qt.CheckState.Checked
                if use_defaults or repo in selected_set
                else Qt.CheckState.Unchecked
            )
            self.repo_table.setItem(row, 0, checkbox_item)

            name_item = QTableWidgetItem(repo)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.repo_table.setItem(row, 1, name_item)

    def _selected_repo_names(self) -> list[str]:
        repos = []
        for row in range(self.repo_table.rowCount()):
            checkbox_item = self.repo_table.item(row, 0)
            name_item = self.repo_table.item(row, 1)
            if not checkbox_item or not name_item:
                continue
            if checkbox_item.checkState() == Qt.CheckState.Checked:
                repos.append(name_item.text().strip().lower())
        return repos

    def _select_all_repos(self):
        for row in range(self.repo_table.rowCount()):
            item = self.repo_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)


class ShortcutsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        intro = QLabel(
            "Keyboard shortcuts work while the XPAK window is focused."
        )
        intro.setStyleSheet("color: #a9b1d6;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        sections = [
            (
                "Navigation",
                [
                    ("Ctrl+1", "Open Search"),
                    ("Ctrl+2", "Open Installed"),
                    ("Ctrl+3", "Open Updates"),
                    ("Ctrl+4", "Open Maintenance"),
                    ("Ctrl+5", "Open Settings"),
                    ("Ctrl+6", "Open Shortcuts"),
                ],
            ),
            (
                "Focus",
                [
                    ("Ctrl+F", "Focus the main field or primary action in the current tab"),
                ],
            ),
            (
                "Examples",
                [
                    ("Search", "Ctrl+F focuses the package search input"),
                    ("Installed", "Ctrl+F focuses the installed-package filter"),
                    ("Updates", "Ctrl+F focuses the updates filter"),
                    ("Maintenance", "Ctrl+F focuses the Check for XPAK Update button"),
                    ("Settings", "Ctrl+F focuses the Save Settings button"),
                ],
            ),
        ]

        for title, shortcuts in sections:
            card = QFrame()
            card.setObjectName("sidebar-card")
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(10)

            heading = QLabel(title)
            heading.setStyleSheet("color: #7aa2f7; font-weight: 700; font-size: 14px;")
            card_layout.addWidget(heading)

            for key, description in shortcuts:
                row = QHBoxLayout()

                key_lbl = QLabel(key)
                key_lbl.setStyleSheet(
                    "color: #c0caf5; font-weight: 700; min-width: 90px;"
                )
                desc_lbl = QLabel(description)
                desc_lbl.setStyleSheet("color: #a9b1d6;")
                desc_lbl.setWordWrap(True)

                row.addWidget(key_lbl)
                row.addWidget(desc_lbl, 1)
                card_layout.addLayout(row)

            layout.addWidget(card)

        layout.addStretch()

    def focus_primary_input(self):
        self.setFocus()
