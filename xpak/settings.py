from PyQt6.QtCore import QSettings


SETTINGS_ORG = "xpak"
SETTINGS_APP = "xpak"

UPDATE_PREFS_CONFIGURED_KEY = "updates/preferences_configured"
AUTO_CHECK_XPAK_UPDATES_KEY = "updates/auto_check_xpak"
AUTO_CHECK_PACKAGE_UPDATES_KEY = "updates/auto_check_packages"


def get_settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def load_update_preferences() -> tuple[bool, bool, bool]:
    settings = get_settings()
    configured = settings.value(UPDATE_PREFS_CONFIGURED_KEY, False, type=bool)
    auto_check_xpak = settings.value(AUTO_CHECK_XPAK_UPDATES_KEY, True, type=bool)
    auto_check_packages = settings.value(AUTO_CHECK_PACKAGE_UPDATES_KEY, True, type=bool)
    return configured, auto_check_xpak, auto_check_packages


def save_update_preferences(auto_check_xpak: bool, auto_check_packages: bool):
    settings = get_settings()
    settings.setValue(UPDATE_PREFS_CONFIGURED_KEY, True)
    settings.setValue(AUTO_CHECK_XPAK_UPDATES_KEY, auto_check_xpak)
    settings.setValue(AUTO_CHECK_PACKAGE_UPDATES_KEY, auto_check_packages)
    settings.sync()


def should_prompt_for_update_preferences() -> bool:
    configured, _, _ = load_update_preferences()
    return not configured
