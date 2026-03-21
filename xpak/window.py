from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QMenu, QMessageBox, QStatusBar, QStyle, QSystemTrayIcon, QTabWidget,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut, QShowEvent

from xpak import APP_NAME, APP_VERSION
from xpak.tabs import SearchTab, InstalledTab, UpdatesTab, ToolsTab, SettingsTab, ShortcutsTab
from xpak.dialogs import ToolCheckDialog, UpdatePreferencesDialog
from xpak.workers import UpdateChecker, AppUpdateChecker
from xpak.logging_service import get_logger
from xpak.settings import (
    load_startup_preferences,
    load_update_preferences,
    mark_packages_checked_today,
    mark_xpak_checked_today,
    save_update_preferences,
    save_startup_preferences,
    should_run_daily_package_check,
    should_run_daily_xpak_check,
    sync_autostart_file,
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
        self._startup_package_check_requested = False
        self._startup_xpak_result_handled = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._start_hidden_to_tray = False
        self._close_to_tray_enabled = False
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 800)
        self.resize(1200, 800)
        self._build_ui()
        self._build_statusbar()
        self._setup_shortcuts()
        self.refresh_tray_preferences()
        QTimer.singleShot(300, self._check_tools_on_startup)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if self._initial_focus_scheduled:
            return
        self._initial_focus_scheduled = True
        self._schedule_focus_current_tab_primary_input()

    def closeEvent(self, event: QCloseEvent):
        if self._close_to_tray_enabled and self._tray_icon and self._tray_icon.isVisible():
            event.ignore()
            self.hide()
            self._tray_icon.showMessage(
                APP_NAME,
                "XPAK is still running in the system tray.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return
        super().closeEvent(event)

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
        self.refresh_tray_preferences()
        self._start_startup_update_checks()
        if self._start_hidden_to_tray and self._tray_icon:
            self.hide()
            self._tray_icon.showMessage(
                APP_NAME,
                "XPAK started in the system tray.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
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

        _, auto_check_xpak, auto_check_packages, check_daily = load_update_preferences()
        launch_on_startup, start_to_tray = load_startup_preferences()
        dlg = UpdatePreferencesDialog(
            self,
            auto_check_xpak=auto_check_xpak,
            auto_check_packages=auto_check_packages,
            check_daily=check_daily,
            launch_on_startup=launch_on_startup,
            start_to_tray=start_to_tray,
        )
        if dlg.exec():
            (
                selected_xpak,
                selected_packages,
                selected_daily,
                selected_launch,
                selected_tray,
            ) = dlg.selected_preferences()
            save_update_preferences(selected_xpak, selected_packages, selected_daily)
            save_startup_preferences(selected_launch, selected_tray)
            sync_autostart_file(selected_launch, selected_tray)

    def _start_startup_update_checks(self):
        _, auto_check_xpak, auto_check_packages, check_daily = load_update_preferences()
        should_check_xpak = auto_check_xpak and self._should_run_xpak_check(check_daily)
        should_check_packages = auto_check_packages and self._should_run_package_check(check_daily)

        self._startup_package_check_requested = should_check_packages
        self._startup_xpak_result_handled = False

        if should_check_xpak:
            self._run_startup_xpak_update_check()
        elif should_check_packages:
            self._run_startup_package_update_check()

    def _should_run_xpak_check(self, check_daily: bool) -> bool:
        return not check_daily or should_run_daily_xpak_check()

    def _should_run_package_check(self, check_daily: bool) -> bool:
        return not check_daily or should_run_daily_package_check()

    def _run_startup_xpak_update_check(self):
        if self._startup_app_checker and self._startup_app_checker.isRunning():
            return

        self._startup_app_checker = AppUpdateChecker()
        self._startup_app_checker.update_available.connect(self._on_startup_xpak_update_available)
        self._startup_app_checker.no_update.connect(self._on_startup_xpak_no_update)
        self._startup_app_checker.error.connect(self._on_startup_xpak_check_error)
        self._startup_app_checker.finished.connect(self._on_startup_xpak_check_finished)
        self._startup_app_checker.start()

    def _run_startup_package_update_check(self):
        if self._startup_package_checker and self._startup_package_checker.isRunning():
            return

        self._startup_package_checker = UpdateChecker()
        self._startup_package_checker.updates_ready.connect(self._on_startup_package_updates_ready)
        self._startup_package_checker.finished.connect(self._on_startup_package_check_finished)
        self._startup_package_checker.start()

    def _on_startup_xpak_update_available(self, version: str, url: str):
        if not self._start_hidden_to_tray:
            mark_xpak_checked_today()
        self.tools_tab.display_app_update_result(version, url, announce=False)
        self._startup_xpak_result_handled = True
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
        self._run_deferred_startup_package_check()

    def _on_startup_xpak_no_update(self):
        if not self._start_hidden_to_tray:
            mark_xpak_checked_today()
        self.tools_tab.display_app_up_to_date(announce=False)
        self._startup_xpak_result_handled = True
        self._run_deferred_startup_package_check()

    def _on_startup_xpak_check_error(self, msg: str):
        logger.warning("Background XPAK update check failed: %s", msg)
        self.tools_tab.display_app_update_error(msg, announce=False)
        self._startup_xpak_result_handled = True
        self._run_deferred_startup_package_check()

    def _on_startup_xpak_check_finished(self):
        self._startup_app_checker = None
        if not self._startup_xpak_result_handled:
            self._run_deferred_startup_package_check()

    def _on_startup_package_updates_ready(self, updates: list):
        if not self._start_hidden_to_tray:
            mark_packages_checked_today()
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

    def _on_startup_package_check_finished(self):
        self._startup_package_checker = None

    def _run_deferred_startup_package_check(self):
        if not self._startup_package_check_requested:
            return

        self._startup_package_check_requested = False
        self._run_startup_package_update_check()

    def set_start_hidden_to_tray(self, enabled: bool):
        self._start_hidden_to_tray = enabled

    def refresh_tray_preferences(self):
        launch_on_startup, start_to_tray = load_startup_preferences()
        self._close_to_tray_enabled = (
            launch_on_startup and start_to_tray and QSystemTrayIcon.isSystemTrayAvailable()
        )
        if self._close_to_tray_enabled:
            self._ensure_tray_icon()
        elif self._tray_icon:
            self._tray_icon.hide()

    def _ensure_tray_icon(self):
        if self._tray_icon is not None:
            self._tray_icon.show()
            return

        icon = QIcon.fromTheme("system-software-install")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)

        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip(APP_NAME)
        self._tray_icon.activated.connect(self._on_tray_activated)

        self._tray_menu = QMenu(self)
        show_action = QAction("Show XPAK", self)
        show_action.triggered.connect(self._show_from_tray)
        self._tray_menu.addAction(show_action)

        hide_action = QAction("Hide XPAK", self)
        hide_action.triggered.connect(self.hide)
        self._tray_menu.addAction(hide_action)

        self._tray_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_from_tray)
        self._tray_menu.addAction(quit_action)

        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible():
                self.hide()
            else:
                self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._schedule_focus_current_tab_primary_input()

    def _quit_from_tray(self):
        self._close_to_tray_enabled = False
        if self._tray_icon:
            self._tray_icon.hide()
        self.close()

    def prepare_for_restart(self):
        self._close_to_tray_enabled = False
        if self._tray_icon:
            self._tray_icon.hide()

    def bring_to_front(self):
        if self._tray_icon and not self.isVisible():
            self._show_from_tray()
            return

        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        self._schedule_focus_current_tab_primary_input()
