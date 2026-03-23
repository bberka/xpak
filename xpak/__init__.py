from pathlib import Path


APP_VERSION = "1.12.0"
APP_NAME = "XPAK"
APP_ID = "xpak"
APP_DESKTOP_FILE = f"{APP_ID}.desktop"
APP_ICON_NAME = "system-software-install"
APP_ROOT = Path(__file__).resolve().parent.parent
APP_ICON_FILE = APP_ROOT / "assets" / f"{APP_ID}.svg"
APP_ENTRYPOINT = APP_ROOT / "xpak.py"
INSTALL_SCRIPT = APP_ROOT / "install.sh"
