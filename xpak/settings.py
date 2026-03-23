import shlex
import sys
from datetime import date
from pathlib import Path

from PyQt6.QtCore import QSettings

from xpak import APP_DESKTOP_FILE, APP_ENTRYPOINT, APP_ICON_FILE, APP_ICON_NAME, APP_NAME, APP_ID


SETTINGS_ORG = "xpak"
SETTINGS_APP = "xpak"

UPDATE_PREFS_CONFIGURED_KEY = "updates/preferences_configured"
AUTO_CHECK_XPAK_UPDATES_KEY = "updates/auto_check_xpak"
AUTO_CHECK_PACKAGE_UPDATES_KEY = "updates/auto_check_packages"
CHECK_UPDATES_DAILY_KEY = "updates/check_daily"
LEGACY_EXCLUDE_SYSTEM_UPDATES_KEY = "updates/exclude_system_updates"
INCLUDED_PACMAN_REPOS_KEY = "pacman/include_repos"
EXCLUDED_PACMAN_REPOS_KEY = "pacman/exclude_repos"
LAST_XPAK_UPDATE_CHECK_DATE_KEY = "updates/last_xpak_check_date"
LAST_PACKAGE_UPDATE_CHECK_DATE_KEY = "updates/last_package_check_date"
LAUNCH_ON_SYSTEM_STARTUP_KEY = "startup/launch_on_system_startup"
START_TO_TRAY_ON_SYSTEM_STARTUP_KEY = "startup/start_to_tray"
RESTART_INSTANCE_ARG = "--xpak-restart"

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / APP_DESKTOP_FILE
DEFAULT_LAUNCHER = Path.home() / ".local" / "bin" / "xpak"


def get_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def load_update_preferences() -> tuple[bool, bool, bool, bool]:
    settings = get_settings()
    if settings.contains(LEGACY_EXCLUDE_SYSTEM_UPDATES_KEY):
        settings.remove(LEGACY_EXCLUDE_SYSTEM_UPDATES_KEY)
    configured = settings.value(UPDATE_PREFS_CONFIGURED_KEY, False, type=bool)
    auto_check_xpak = settings.value(AUTO_CHECK_XPAK_UPDATES_KEY, True, type=bool)
    auto_check_packages = settings.value(AUTO_CHECK_PACKAGE_UPDATES_KEY, True, type=bool)
    check_daily = settings.value(CHECK_UPDATES_DAILY_KEY, False, type=bool)
    return configured, auto_check_xpak, auto_check_packages, check_daily


def save_update_preferences(
    auto_check_xpak: bool,
    auto_check_packages: bool,
    check_daily: bool = False,
):
    settings = get_settings()
    settings.setValue(UPDATE_PREFS_CONFIGURED_KEY, True)
    settings.setValue(AUTO_CHECK_XPAK_UPDATES_KEY, auto_check_xpak)
    settings.setValue(AUTO_CHECK_PACKAGE_UPDATES_KEY, auto_check_packages)
    settings.setValue(CHECK_UPDATES_DAILY_KEY, check_daily)
    settings.remove(LEGACY_EXCLUDE_SYSTEM_UPDATES_KEY)
    settings.sync()


def load_repo_preferences() -> tuple[list[str], list[str]]:
    settings = get_settings()
    included = _normalize_repo_list(settings.value(INCLUDED_PACMAN_REPOS_KEY, []))
    excluded = _normalize_repo_list(settings.value(EXCLUDED_PACMAN_REPOS_KEY, []))
    return included, excluded


def save_repo_preferences(included_repos: list[str], excluded_repos: list[str]):
    settings = get_settings()
    settings.setValue(INCLUDED_PACMAN_REPOS_KEY, _normalize_repo_list(included_repos))
    settings.setValue(EXCLUDED_PACMAN_REPOS_KEY, _normalize_repo_list(excluded_repos))
    settings.sync()


def should_prompt_for_update_preferences() -> bool:
    configured, _, _, _ = load_update_preferences()
    return not configured


def should_run_daily_xpak_check() -> bool:
    return _is_daily_check_due(LAST_XPAK_UPDATE_CHECK_DATE_KEY)


def should_run_daily_package_check() -> bool:
    return _is_daily_check_due(LAST_PACKAGE_UPDATE_CHECK_DATE_KEY)


def mark_xpak_checked_today():
    _mark_checked_today(LAST_XPAK_UPDATE_CHECK_DATE_KEY)


def mark_packages_checked_today():
    _mark_checked_today(LAST_PACKAGE_UPDATE_CHECK_DATE_KEY)


def load_startup_preferences() -> tuple[bool, bool]:
    settings = get_settings()
    launch_on_startup = settings.value(LAUNCH_ON_SYSTEM_STARTUP_KEY, False, type=bool)
    start_to_tray = settings.value(START_TO_TRAY_ON_SYSTEM_STARTUP_KEY, False, type=bool)
    return launch_on_startup, start_to_tray


def save_startup_preferences(launch_on_startup: bool, start_to_tray: bool):
    settings = get_settings()
    settings.setValue(LAUNCH_ON_SYSTEM_STARTUP_KEY, launch_on_startup)
    settings.setValue(START_TO_TRAY_ON_SYSTEM_STARTUP_KEY, launch_on_startup and start_to_tray)
    settings.sync()


def sync_autostart_file(launch_on_startup: bool, start_to_tray: bool):
    if not launch_on_startup:
        if AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
        return

    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    exec_command = _build_autostart_exec_command(start_to_tray=start_to_tray)
    AUTOSTART_FILE.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Version=1.0",
                f"Name={APP_NAME}",
                f"Comment=Start {APP_NAME} automatically on login",
                f"Exec={exec_command}",
                f"Icon={APP_ICON_FILE if APP_ICON_FILE.is_file() else APP_ICON_NAME}",
                "Terminal=false",
                "Categories=System;PackageManager;",
                f"StartupWMClass={APP_ID}",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        ),
        encoding="utf-8",
    )


def should_start_in_tray_from_args(argv: list[str]) -> bool:
    if "--start-in-tray" not in argv:
        return False
    launch_on_startup, start_to_tray = load_startup_preferences()
    return launch_on_startup and start_to_tray


def build_launch_command(
    argv: list[str] | None = None,
    *,
    preserve_start_in_tray: bool = False,
) -> list[str]:
    args = list(argv or [])
    if preserve_start_in_tray:
        args = [arg for arg in args if arg != RESTART_INSTANCE_ARG]
    else:
        args = strip_internal_args(args)
    if DEFAULT_LAUNCHER.is_file():
        return [str(DEFAULT_LAUNCHER), *args]
    return [sys.executable, str(APP_ENTRYPOINT), *args]


def strip_internal_args(argv: list[str]) -> list[str]:
    return [arg for arg in argv if arg not in {"--start-in-tray", RESTART_INSTANCE_ARG}]


def is_restart_launch_from_args(argv: list[str]) -> bool:
    return RESTART_INSTANCE_ARG in argv


def _build_autostart_exec_command(start_to_tray: bool) -> str:
    parts = build_launch_command()

    if start_to_tray:
        parts.append("--start-in-tray")

    return " ".join(shlex.quote(part) for part in parts)


def _is_daily_check_due(settings_key: str) -> bool:
    settings = get_settings()
    last_check = settings.value(settings_key, "", type=str)
    return last_check != date.today().isoformat()


def _mark_checked_today(settings_key: str):
    settings = get_settings()
    settings.setValue(settings_key, date.today().isoformat())
    settings.sync()


def _normalize_repo_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)

    normalized = []
    seen = set()
    for item in items:
        repo = str(item).strip().lower()
        if repo and repo not in seen:
            normalized.append(repo)
            seen.add(repo)
    return normalized
