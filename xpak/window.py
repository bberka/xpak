from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTabWidget, QStatusBar,
)
from PyQt6.QtCore import QTimer, QSettings
from PyQt6.QtGui import QShortcut, QKeySequence

from xpak import APP_NAME, APP_VERSION
from xpak.tabs import SearchTab, InstalledTab, UpdatesTab, ToolsTab, ShortcutsTab
from xpak.dialogs import ToolCheckDialog
from xpak.logging_service import get_logger


logger = get_logger("xpak.window")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._active_operation: str | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 800)
        self.resize(1200, 800)
        self._build_ui()
        self._build_statusbar()
        self._setup_shortcuts()
        QTimer.singleShot(0, self.focus_current_tab_primary_input)
        QTimer.singleShot(300, self._check_tools_on_startup)

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
        self.shortcuts_tab = ShortcutsTab()

        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.installed_tab, "Installed")
        self.tabs.addTab(self.updates_tab, "Updates")
        self.tabs.addTab(self.tools_tab, "Maintenance")
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
        self.focus_current_tab_primary_input()

    def _setup_shortcuts(self):
        self._shortcuts: list[QShortcut] = []

        self._register_shortcut("Ctrl+F", self.focus_current_tab_primary_input)

        for index, sequence in enumerate(("Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5")):
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
            self.focus_current_tab_primary_input()

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
            getattr(self, "shortcuts_tab", None),
        ):
            if tab and hasattr(tab, "set_operation_controls_enabled"):
                tab.set_operation_controls_enabled(enabled)
