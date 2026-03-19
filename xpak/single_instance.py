from __future__ import annotations

import os

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

    def start(self) -> bool:
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_new_connection)

        if self._server.listen(self._server_name):
            logger.info("Single-instance server listening on %s", self._server_name)
            return True

        if self._server.serverError() != QLocalServer.SocketError.AddressInUseError:
            logger.error(
                "Failed to start single-instance server '%s': %s",
                self._server_name,
                self._server.errorString(),
            )
            return False

        logger.warning("Removing stale single-instance server '%s'", self._server_name)
        QLocalServer.removeServer(self._server_name)

        if self._server.listen(self._server_name):
            logger.info("Single-instance server recovered on %s", self._server_name)
            return True

        logger.error(
            "Failed to recover single-instance server '%s': %s",
            self._server_name,
            self._server.errorString(),
        )
        return False

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


def _build_server_name(app_id: str) -> str:
    user_id = getattr(os, "getuid", lambda: "nouid")()
    return f"{app_id.lower()}-{user_id}-single-instance"
