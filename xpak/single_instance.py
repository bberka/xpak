from __future__ import annotations

import os
import time

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from xpak.logging_service import get_logger


logger = get_logger("xpak.single_instance")


class SingleInstanceManager(QObject):
    activation_requested = pyqtSignal()

    def __init__(self, app_id: str):
        super().__init__()
        self._server_name = _build_server_name(app_id)
        self._server: QLocalServer | None = None

    def activate_existing_instance(self, timeout_ms: int = 500) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self._server_name)
        if not socket.waitForConnected(timeout_ms):
            return False

        logger.info("Existing instance detected, forwarding activation request")
        socket.write(b"activate\n")
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True

    def start(self, retry_timeout_ms: int = 0, retry_interval_ms: int = 100) -> bool:
        deadline = time.monotonic() + max(retry_timeout_ms, 0) / 1000

        while True:
            if self._listen_once():
                return True

            if not self._server:
                return False

            if self._server.serverError() != QLocalServer.SocketError.AddressInUseError:
                logger.error(
                    "Failed to start single-instance server '%s': %s",
                    self._server_name,
                    self._server.errorString(),
                )
                return False

            if not self._server_is_active():
                logger.warning("Removing stale single-instance server '%s'", self._server_name)
                QLocalServer.removeServer(self._server_name)
                if self._listen_once():
                    logger.info("Single-instance server recovered on %s", self._server_name)
                    return True
                continue

            if retry_timeout_ms <= 0 or time.monotonic() >= deadline:
                logger.warning(
                    "Single-instance server '%s' is still active",
                    self._server_name,
                )
                return False

            time.sleep(max(retry_interval_ms, 1) / 1000)

    def stop(self):
        if not self._server:
            return
        if self._server.isListening():
            logger.info("Stopping single-instance server on %s", self._server_name)
            self._server.close()
        QLocalServer.removeServer(self._server_name)

    def _handle_new_connection(self):
        if not self._server:
            return

        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(lambda sock=socket: self._read_socket(sock))
            socket.disconnected.connect(socket.deleteLater)

    def _read_socket(self, socket: QLocalSocket):
        payload = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
        if payload == "activate":
            logger.info("Received activation request from a second launch")
            self.activation_requested.emit()
        socket.disconnectFromServer()

    def _listen_once(self) -> bool:
        if self._server is None:
            self._server = QLocalServer(self)
            self._server.newConnection.connect(self._handle_new_connection)
        return self._server.listen(self._server_name)

    def _server_is_active(self, timeout_ms: int = 200) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self._server_name)
        connected = socket.waitForConnected(timeout_ms)
        if connected:
            socket.disconnectFromServer()
        return connected


def _build_server_name(app_id: str) -> str:
    user_id = getattr(os, "getuid", lambda: "nouid")()
    return f"{app_id.lower()}-{user_id}-single-instance"
