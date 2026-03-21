#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
from PyQt6.QtGui import QFont
from xpak.styles import STYLESHEET
from xpak.window import MainWindow
from xpak import APP_NAME
from xpak.logging_service import setup_logging, install_exception_hooks, get_logger
from xpak.single_instance import SingleInstanceManager
from xpak.settings import (
    is_restart_launch_from_args,
    should_start_in_tray_from_args,
    strip_internal_args,
)


def main():
    setup_logging()
    install_exception_hooks()
    logger = get_logger("xpak.app")

    restarting = is_restart_launch_from_args(sys.argv[1:])
    argv = [sys.argv[0], *strip_internal_args(sys.argv[1:])]

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    start_in_tray = (
        should_start_in_tray_from_args(sys.argv[1:])
        and QSystemTrayIcon.isSystemTrayAvailable()
    )

    single_instance = SingleInstanceManager(APP_NAME)
    if not restarting and single_instance.activate_existing_instance():
        logger.info("Activation forwarded to existing instance, exiting")
        sys.exit(0)
    if not single_instance.start(retry_timeout_ms=10000 if restarting else 0):
        logger.warning("Continuing without single-instance enforcement")
    app.aboutToQuit.connect(single_instance.stop)

    app.setStyleSheet(STYLESHEET)
    font = QFont("JetBrains Mono", 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(font)
    logger.info("Application starting")
    window = MainWindow()
    single_instance.activation_requested.connect(window.bring_to_front)
    window.set_start_hidden_to_tray(start_in_tray)
    if not start_in_tray:
        window.show()
    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
