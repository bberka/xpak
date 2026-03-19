#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from xpak.styles import STYLESHEET
from xpak.window import MainWindow
from xpak import APP_NAME
from xpak.logging_service import setup_logging, install_exception_hooks, get_logger


def main():
    setup_logging()
    install_exception_hooks()
    logger = get_logger("xpak.app")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)
    font = QFont("JetBrains Mono", 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(font)
    logger.info("Application starting")
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
