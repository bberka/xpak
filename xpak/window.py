from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTabWidget, QStatusBar, QMessageBox,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtGui import QShowEvent

from xpak import APP_NAME, APP_VERSION
from xpak.tabs import SearchTab, InstalledTab, UpdatesTab, ToolsTab, SettingsTab, ShortcutsTab
from xpak.dialogs import ToolCheckDialog, UpdatePreferencesDialog
from xpak.workers import UpdateChecker, AppUpdateChecker
from xpak.logging_service import get_logger
from xpak.settings import (
    load_update_preferences,
    save_update_preferences,
    should_prompt_for_update_preferences,
)


logger = get_logger("xpak.window")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._active_operation: str | None = None
        self._initial_focus_scheduled = False
        self._startup_package_checker: UpdateChecker | None = None
        self._startup_app_checker: AppUpdateChecker | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 800)
        self.resize(1200, 800)
        self._build_ui()
        self._build_statusbar()
        self._setup_shortcuts()
        QTimer.singleShot(300, self._check_tools_on_startup)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if self._initial_focus_scheduled:
            return
        self._initial_focus_scheduled = True
        self._schedule_focus_current_tab_primary_input()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar - no backend badges
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet("background-color: #16171f; border-bottom: 1px solid #2a2b3d;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel(APP_NAME)
        title.setStyleSheet(
            "color: #7aa2f7; font-size: 18px; font-weight: 800; letter-spacing: 2px;"
        )
        subtitle = QLabel("Package Manager")
        subtitle.setStyleSheet(
            "color: #3b4261; font-size: 12px; margin-left: 6px; margin-top: 4px;"
        )

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addStretch()

        version_lbl = QLabel(f"v{APP_VERSION}")
        version_lbl.setStyleSheet("color: #3b4261; font-size: 11px;")
        header_layout.addWidget(version_lbl)

        main_layout.addWidget(header)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)

        self.search_tab = SearchTab()
        self.installed_tab = InstalledTab()
        self.updates_tab = UpdatesTab()
        self.tools_tab = ToolsTab()
        self.settings_tab = SettingsTab()
        self.shortcuts_tab = ShortcutsTab()

        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.installed_tab, "Installed")
        self.tabs.addTab(self.updates_tab, "Updates")
        self.tabs.addTab(self.tools_tab, "Maintenance")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.addTab(self.shortcuts_tab, "Shortcuts")
        self.tabs.currentChanged.connect(lambda _: self.focus_current_tab_primary_input())

        main_layout.addWidget(self.tabs)
        self._set_operation_controls_enabled(True)

    def _build_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage(f"{APP_NAME} ready")

    def _check_tools_on_startup(self):
        if ToolCheckDialog.should_show():
            dlg = ToolCheckDialog(self)
            dlg.exec()
        self._maybe_prompt_update_preferences()
        self.settings_tab.reload_preferences()
        self._start_startup_update_checks()
        self._schedule_focus_current_tab_primary_input()

    def _setup_shortcuts(self):
        self._shortcuts: list[QShortcut] = []

        self._register_shortcut("Ctrl+F", self.focus_current_tab_primary_input)

        for index, sequence in enumerate(("Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6")):
            self._register_shortcut(
                sequence,
                lambda idx=index: self._activate_tab(idx),
            )

    def _register_shortcut(self, sequence: str, callback):
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def _activate_tab(self, index: int):
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
            self._schedule_focus_current_tab_primary_input()

    def _schedule_focus_current_tab_primary_input(self):
        for delay in (0, 75, 200):
            QTimer.singleShot(delay, self.focus_current_tab_primary_input)

    def focus_current_tab_primary_input(self):
        current_tab = self.tabs.currentWidget()
        if current_tab and hasattr(current_tab, "focus_primary_input"):
            current_tab.focus_primary_input()

    def begin_operation(self, description: str) -> tuple[bool, str]:
        if self._active_operation:
            logger.warning(
                "Blocked operation '%s' because '%s' is already active",
                description,
                self._active_operation,
            )
            return False, f"'{self._active_operation}' is already in progress"

        self._active_operation = description
        logger.info("Operation started: %s", description)
        self.statusbar.showMessage(f"{APP_NAME}: {description} in progress")
        self._set_operation_controls_enabled(False)
        return True, ""

    def end_operation(self):
        if self._active_operation:
            logger.info("Operation finished: %s", self._active_operation)
        self._active_operation = None
        self._set_operation_controls_enabled(True)
        self.statusbar.showMessage(f"{APP_NAME} ready")

    def has_active_operation(self) -> bool:
        return self._active_operation is not None

    def _set_operation_controls_enabled(self, enabled: bool):
        for tab in (
            getattr(self, "search_tab", None),
            getattr(self, "installed_tab", None),
            getattr(self, "updates_tab", None),
            getattr(self, "tools_tab", None),
            getattr(self, "settings_tab", None),
            getattr(self, "shortcuts_tab", None),
        ):
            if tab and hasattr(tab, "set_operation_controls_enabled"):
                tab.set_operation_controls_enabled(enabled)

    def _maybe_prompt_update_preferences(self):
        if not should_prompt_for_update_preferences():
            return

        _, auto_check_xpak, auto_check_packages = load_update_preferences()
        dlg = UpdatePreferencesDialog(
            self,
            auto_check_xpak=auto_check_xpak,
            auto_check_packages=auto_check_packages,
        )
        if dlg.exec():
            selected_xpak, selected_packages = dlg.selected_preferences()
            save_update_preferences(selected_xpak, selected_packages)

    def _start_startup_update_checks(self):
        _, auto_check_xpak, auto_check_packages = load_update_preferences()
        if auto_check_xpak:
            self._run_startup_xpak_update_check()
        if auto_check_packages:
            self._run_startup_package_update_check()

    def _run_startup_xpak_update_check(self):
        if self._startup_app_checker and self._startup_app_checker.isRunning():
            return

        self._startup_app_checker = AppUpdateChecker()
        self._startup_app_checker.update_available.connect(self._on_startup_xpak_update_available)
        self._startup_app_checker.no_update.connect(
            lambda: self.tools_tab.display_app_up_to_date(announce=False)
        )
        self._startup_app_checker.error.connect(
            lambda msg: logger.warning("Background XPAK update check failed: %s", msg)
        )
        self._startup_app_checker.start()

    def _run_startup_package_update_check(self):
        if self._startup_package_checker and self._startup_package_checker.isRunning():
            return

        self._startup_package_checker = UpdateChecker()
        self._startup_package_checker.updates_ready.connect(self._on_startup_package_updates_ready)
        self._startup_package_checker.start()

    def _on_startup_xpak_update_available(self, version: str, url: str):
        self.tools_tab.display_app_update_result(version, url, announce=False)
        answer = QMessageBox.information(
            self,
            "XPAK Update Available",
            f"A new XPAK version is available: v{version}.\n\nOpen the Maintenance tab now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.tabs.setCurrentWidget(self.tools_tab)
            self._schedule_focus_current_tab_primary_input()

    def _on_startup_package_updates_ready(self, updates: list):
        self.updates_tab.apply_updates_result(updates, announce=False)
        if not updates:
            return

        count = len(updates)
        answer = QMessageBox.information(
            self,
            "Package Updates Available",
            f"{count} package update{'s' if count != 1 else ''} were found.\n\nOpen the Updates tab now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.tabs.setCurrentWidget(self.updates_tab)
            self._schedule_focus_current_tab_primary_input()
