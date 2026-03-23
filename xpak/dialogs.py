import shutil
import subprocess
from urllib.parse import urlparse

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDialogButtonBox, QPushButton, QCheckBox, QFrame, QScrollArea,
    QWidget, QProgressBar, QMessageBox,
)
from xpak.workers import CommandWorker
from xpak.widgets import TerminalOutput
from xpak.logging_service import get_logger
from xpak.settings import get_settings


logger = get_logger("xpak.dialogs")


class AddPacmanRepoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Pacman Repository")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Add a pacman repository")
        title.setStyleSheet("color: #7aa2f7; font-size: 16px; font-weight: 800;")
        layout.addWidget(title)

        description = QLabel(
            "This adds a new repository block to /etc/pacman.conf using a repo name "
            "and a server URI such as https://example.org/$repo/os/$arch."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #565f89; font-size: 12px;")
        layout.addWidget(description)

        name_label = QLabel("Repository name")
        name_label.setStyleSheet("color: #a9b1d6; font-size: 12px;")
        layout.addWidget(name_label)

        self.repo_name_input = QLineEdit()
        self.repo_name_input.setPlaceholderText("customrepo")
        layout.addWidget(self.repo_name_input)

        uri_label = QLabel("Server URI")
        uri_label.setStyleSheet("color: #a9b1d6; font-size: 12px;")
        layout.addWidget(uri_label)

        self.repo_uri_input = QLineEdit()
        self.repo_uri_input.setPlaceholderText("https://example.org/$repo/os/$arch")
        layout.addWidget(self.repo_uri_input)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #f7768e; font-size: 12px;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add Repository")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.repo_uri_input.returnPressed.connect(self._submit)
        self.repo_name_input.setFocus()

    def _submit(self):
        repo_name = self.repo_name().strip()
        repo_uri = self.repo_uri().strip()

        if not repo_name:
            self.error_label.setText("Repository name is required.")
            self.repo_name_input.setFocus()
            return

        if not repo_uri:
            self.error_label.setText("Server URI is required.")
            self.repo_uri_input.setFocus()
            return

        if not all(char.isalnum() or char in "._+-@" for char in repo_name):
            self.error_label.setText("Repository name can only contain letters, numbers, ., _, +, -, and @.")
            self.repo_name_input.setFocus()
            return

        parsed = urlparse(repo_uri)
        if parsed.scheme not in {"http", "https", "ftp", "file"}:
            self.error_label.setText("Enter a valid URI using http, https, ftp, or file.")
            self.repo_uri_input.setFocus()
            return

        if parsed.scheme != "file" and not parsed.netloc:
            self.error_label.setText("Enter a complete server URI, including the hostname.")
            self.repo_uri_input.setFocus()
            return

        self.accept()

    def repo_name(self) -> str:
        return self.repo_name_input.text().strip().lower()

    def repo_uri(self) -> str:
        return self.repo_uri_input.text().strip()


class PasswordDialog(QDialog):
    def __init__(self, parent=None, message: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Authentication Required")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        icon_label = QLabel("  sudo password required")
        icon_label.setStyleSheet("color: #e0af68; font-weight: 700; font-size: 14px;")
        layout.addWidget(icon_label)

        if message:
            msg_label = QLabel(message)
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet("color: #a9b1d6; font-size: 12px;")
            layout.addWidget(msg_label)

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

        self.pwd_input.returnPressed.connect(self.accept)

    def password(self) -> str:
        return self.pwd_input.text()


class ToolCheckDialog(QDialog):
    """Startup dialog that checks for required tools and offers to install them."""

    SETTINGS_KEY = "tool_check_dismissed"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("XPAK - Tool Check")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)
        self._worker: CommandWorker | None = None
        self._build_ui()
        self._check_tools()

    def _begin_operation(self, description: str) -> bool:
        parent = self.parent()
        if parent and hasattr(parent, "begin_operation"):
            ok, msg = parent.begin_operation(description)
            if not ok:
                QMessageBox.warning(
                    self,
                    "Operation In Progress",
                    f"Cannot start {description.lower()}: {msg}.",
                )
            return ok
        return True

    def _end_operation(self):
        parent = self.parent()
        if parent and hasattr(parent, "end_operation"):
            parent.end_operation()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(12)
        outer.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Tool Availability Check")
        title.setStyleSheet("color: #7aa2f7; font-size: 16px; font-weight: 800;")
        outer.addWidget(title)

        sub = QLabel(
            "XPAK requires the following tools for full functionality. "
            "Items marked below are not currently installed."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #565f89; font-size: 12px; margin-bottom: 8px;")
        outer.addWidget(sub)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        self._cards_layout = QVBoxLayout(scroll_content)
        self._cards_layout.setSpacing(10)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(scroll_content)
        outer.addWidget(scroll_area)

        self._terminal = TerminalOutput()
        self._terminal.setMaximumHeight(120)
        self._terminal.setVisible(False)
        outer.addWidget(self._terminal)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        outer.addWidget(self._progress)

        bottom_row = QHBoxLayout()
        self._dismiss_check = QCheckBox("Don't show this again")
        self._dismiss_check.setStyleSheet("color: #565f89; font-size: 12px;")
        bottom_row.addWidget(self._dismiss_check)
        bottom_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self._on_close)
        bottom_row.addWidget(close_btn)
        outer.addLayout(bottom_row)

    def _check_tools(self):
        tools = [
            {
                "id": "yay",
                "name": "yay",
                "description": "AUR helper. Required for searching and installing AUR packages.",
                "installable": False,
                "install_cmd": None,
                "instructions": (
                    "yay must be installed manually from the AUR:\n"
                    "  git clone https://aur.archlinux.org/yay.git\n"
                    "  cd yay && makepkg -si"
                ),
            },
            {
                "id": "flatpak",
                "name": "flatpak",
                "description": "Flatpak runtime. Required for Flatpak package support.",
                "installable": True,
                "install_cmd": ["pacman", "-S", "--noconfirm", "flatpak"],
                "instructions": None,
            },
            {
                "id": "pacman-contrib",
                "name": "pacman-contrib",
                "description": (
                    "Provides checkupdates (safe update checking) and paccache (cache cleanup). "
                    "Required for the Updates tab and cache cleaning."
                ),
                "installable": True,
                "install_cmd": ["pacman", "-S", "--noconfirm", "pacman-contrib"],
                "instructions": None,
            },
        ]

        for tool in tools:
            cmd = tool["id"]
            # pacman-contrib provides commands, check by package name via pacman -Q
            if tool["id"] == "pacman-contrib":
                found = self._is_pkg_installed("pacman-contrib")
            else:
                found = shutil.which(cmd) is not None
            self._add_tool_card(tool, found)

    def _is_pkg_installed(self, pkg_name: str) -> bool:
        try:
            subprocess.run(
                ["pacman", "-Q", pkg_name],
                check=True,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _add_tool_card(self, tool: dict, found: bool):
        card = QFrame()
        card.setObjectName("sidebar-card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)
        card_layout.setContentsMargins(12, 10, 12, 10)

        header_row = QHBoxLayout()
        status_icon = "✓" if found else "✗"
        status_color = "#9ece6a" if found else "#f7768e"
        name_lbl = QLabel(f"{status_icon}  {tool['name']}")
        name_lbl.setStyleSheet(f"color: {status_color}; font-weight: 700; font-size: 13px;")
        header_row.addWidget(name_lbl)
        header_row.addStretch()

        if not found:
            if tool["installable"]:
                install_btn = QPushButton("Install via pacman")
                install_btn.setObjectName("primary")
                install_btn.setFixedWidth(150)
                install_btn.clicked.connect(
                    lambda checked, t=tool: self._install_tool(t)
                )
                header_row.addWidget(install_btn)
            else:
                manual_lbl = QLabel("Manual install required")
                manual_lbl.setStyleSheet("color: #e0af68; font-size: 11px; font-weight: 600;")
                header_row.addWidget(manual_lbl)

        card_layout.addLayout(header_row)

        desc_lbl = QLabel(tool["description"])
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #565f89; font-size: 11px;")
        card_layout.addWidget(desc_lbl)

        if not found and tool["instructions"]:
            instr_lbl = QLabel(tool["instructions"])
            instr_lbl.setWordWrap(True)
            instr_lbl.setStyleSheet(
                "color: #a9b1d6; font-size: 11px; font-family: monospace; "
                "background-color: #0d0e14; padding: 8px; border-radius: 4px;"
            )
            card_layout.addWidget(instr_lbl)

        self._cards_layout.addWidget(card)

    def _install_tool(self, tool: dict):
        logger.info("Requested tool install: %s", tool["name"])
        dlg = PasswordDialog(
            self,
            message=f"Installing {tool['name']} via pacman requires sudo.",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()

        if not self._begin_operation(f"Installing {tool['name']}"):
            return

        self._terminal.setVisible(True)
        self._progress.setVisible(True)
        self._terminal.append_info(f"Installing {tool['name']}...")

        self._worker = CommandWorker(
            tool["install_cmd"],
            sudo=True,
            password=password,
            log_name=f"tool-install:{tool['name']}",
        )
        self._worker.output_line.connect(self._terminal.append_line)
        self._worker.finished.connect(self._on_install_done)
        self._worker.start()

    def _on_install_done(self, success: bool, msg: str):
        self._progress.setVisible(False)
        self._end_operation()
        if success:
            logger.info("Tool install succeeded: %s", msg)
            self._terminal.append_success(msg)
            self._terminal.append_info("Please restart XPAK to apply changes.")
        else:
            logger.error("Tool install failed: %s", msg)
            self._terminal.append_error(msg)

    def _on_close(self):
        if self._dismiss_check.isChecked():
            settings = get_settings()
            settings.setValue(self.SETTINGS_KEY, True)
        self.accept()

    @staticmethod
    def should_show() -> bool:
        settings = get_settings()
        dismissed = settings.value("tool_check_dismissed", False, type=bool)
        return not dismissed


class UpdatePreferencesDialog(QDialog):
    def __init__(
        self,
        parent=None,
        auto_check_xpak: bool = True,
        auto_check_packages: bool = True,
        check_daily: bool = False,
        launch_on_startup: bool = False,
        start_to_tray: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Startup Preferences")
        self.setMinimumWidth(500)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Choose startup preferences")
        title.setStyleSheet("color: #7aa2f7; font-size: 16px; font-weight: 800;")
        layout.addWidget(title)

        description = QLabel(
            "Choose which actions XPAK should perform automatically when it starts. "
            "You can change these later in the Settings tab."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #565f89; font-size: 12px;")
        layout.addWidget(description)

        self.xpak_updates_check = QCheckBox("XPAK version updates")
        self.xpak_updates_check.setChecked(auto_check_xpak)
        self.xpak_updates_check.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.xpak_updates_check)

        self.package_updates_check = QCheckBox("Installed apps and package updates")
        self.package_updates_check.setChecked(auto_check_packages)
        self.package_updates_check.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.package_updates_check)

        self.daily_check_check = QCheckBox("Regularly check updates every day")
        self.daily_check_check.setChecked(check_daily)
        self.daily_check_check.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.daily_check_check)

        launch_title = QLabel("System startup")
        launch_title.setStyleSheet("color: #7aa2f7; font-size: 14px; font-weight: 700; margin-top: 6px;")
        layout.addWidget(launch_title)

        self.launch_on_startup_check = QCheckBox("Launch XPAK automatically on system startup")
        self.launch_on_startup_check.setChecked(launch_on_startup)
        self.launch_on_startup_check.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        self.launch_on_startup_check.toggled.connect(self._sync_startup_controls)
        layout.addWidget(self.launch_on_startup_check)

        self.start_to_tray_check = QCheckBox("If launched on startup, start minimized to tray")
        self.start_to_tray_check.setChecked(start_to_tray)
        self.start_to_tray_check.setStyleSheet("color: #a9b1d6; font-size: 13px;")
        layout.addWidget(self.start_to_tray_check)

        hint = QLabel(
            "If updates are found, XPAK will show a notification dialog and keep the result "
            "visible in the related tab. Daily checks run at most once per calendar day while XPAK is used. "
            "Startup launch uses your desktop autostart folder."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #565f89; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._sync_startup_controls(self.launch_on_startup_check.isChecked())

    def _sync_startup_controls(self, enabled: bool):
        self.start_to_tray_check.setEnabled(enabled)
        if not enabled:
            self.start_to_tray_check.setChecked(False)

    def selected_preferences(self) -> tuple[bool, bool, bool, bool, bool]:
        return (
            self.xpak_updates_check.isChecked(),
            self.package_updates_check.isChecked(),
            self.daily_check_check.isChecked(),
            self.launch_on_startup_check.isChecked(),
            self.start_to_tray_check.isChecked(),
        )
