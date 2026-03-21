from pathlib import Path


APP_VERSION = "1.6.7"
APP_NAME = "XPAK"
APP_ROOT = Path(__file__).resolve().parent.parent
APP_ENTRYPOINT = APP_ROOT / "xpak.py"
INSTALL_SCRIPT = APP_ROOT / "install.sh"
