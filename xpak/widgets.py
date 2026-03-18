from PyQt6.QtWidgets import (
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPushButton, QMenu, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor, QAction


class TerminalOutput(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(180)

    def append_line(self, line: str, color: str = "#a9b1d6"):
        self.moveCursor(QTextCursor.MoveOperation.End)
        html = f'<span style="color:{color}; white-space:pre-wrap;">{self._escape(line)}</span><br>'
        self.insertHtml(html)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def append_success(self, msg: str):
        self.append_line(f"✓ {msg}", "#9ece6a")

    def append_error(self, msg: str):
        self.append_line(f"✗ {msg}", "#f7768e")

    def append_info(self, msg: str):
        self.append_line(f"» {msg}", "#7aa2f7")

    def clear_log(self):
        self.clear()

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TerminalPanel(QWidget):
    """TerminalOutput with a persistent input bar for interactive processes."""

    def __init__(self, max_height: int = 200, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._terminal = TerminalOutput()
        self._terminal.setMaximumHeight(max_height)
        layout.addWidget(self._terminal)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Send input to process...")
        self._input.setEnabled(False)
        self._input.returnPressed.connect(self._send)

        self._btn = QPushButton("Send")
        self._btn.setFixedWidth(60)
        self._btn.setEnabled(False)
        self._btn.clicked.connect(self._send)

        input_row.addWidget(self._input)
        input_row.addWidget(self._btn)
        layout.addLayout(input_row)

        self._worker = None

    # Proxy terminal methods so existing code works unchanged
    def append_line(self, line: str, color: str = "#a9b1d6"):
        self._terminal.append_line(line, color)

    def append_success(self, msg: str):
        self._terminal.append_success(msg)

    def append_error(self, msg: str):
        self._terminal.append_error(msg)

    def append_info(self, msg: str):
        self._terminal.append_info(msg)

    def clear_log(self):
        self._terminal.clear_log()

    def set_worker(self, worker):
        """Call with a running CommandWorker to enable input, or None to disable."""
        self._worker = worker
        enabled = worker is not None
        self._input.setEnabled(enabled)
        self._btn.setEnabled(enabled)
        if enabled:
            self._input.setFocus()

    def _send(self):
        text = self._input.text().strip()
        if not text or not self._worker:
            return
        self._worker.send_input(text)
        self._terminal.append_line(f"> {text}", "#565f89")
        self._input.clear()


class PackageTable(QTableWidget):
    def __init__(self, columns: list, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.setSortingEnabled(True)
        self.setStyleSheet("""
            QTableWidget { alternate-background-color: #1e2030; }
        """)

    def populate(self, packages: list, columns: list):
        """Populate table rows. Stores the full package dict in UserRole on column 0."""
        self.setSortingEnabled(False)
        self.setRowCount(0)
        for pkg in packages:
            row = self.rowCount()
            self.insertRow(row)
            for col_idx, col in enumerate(columns):
                key = col.lower().replace(" ", "_")
                val = str(pkg.get(key, pkg.get(col.lower(), "")))
                item = QTableWidgetItem(val)
                if col_idx == 0:
                    # Store the full package dict for later retrieval after sorting
                    item.setData(Qt.ItemDataRole.UserRole, pkg)
                if col.lower() == "source":
                    item.setForeground(QColor(self._source_color(val)))
                self.setItem(row, col_idx, item)
        self.setSortingEnabled(True)

    @staticmethod
    def _source_color(source: str) -> str:
        colors = {
            "pacman": "#7aa2f7",
            "aur": "#bb9af7",
            "flatpak": "#73daca",
        }
        return colors.get(source.lower(), "#c0caf5")


class SourceSelector(QPushButton):
    """A QPushButton that opens a QMenu with checkable actions for each package source."""
    sources_changed = pyqtSignal(list)

    _ALL_SOURCES = ["pacman", "aur", "flatpak"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions: dict[str, QAction] = {}
        self._menu = QMenu(self)
        self._build_menu()
        self.setMenu(self._menu)
        self._update_text()

    def _build_menu(self):
        for source in self._ALL_SOURCES:
            action = QAction(source, self._menu)
            action.setCheckable(True)
            action.setChecked(True)
            action.triggered.connect(self._on_action_triggered)
            self._menu.addAction(action)
            self._actions[source] = action

    def _on_action_triggered(self):
        # Ensure at least one source stays checked
        checked = [s for s, a in self._actions.items() if a.isChecked()]
        if not checked:
            # Re-check the sender to prevent all-unchecked state
            for action in self._menu.actions():
                if action == self.sender():
                    action.setChecked(True)
                    break
        self._update_text()
        self.sources_changed.emit(self.get_sources())

    def _update_text(self):
        checked = self.get_sources()
        if set(checked) == set(self._ALL_SOURCES):
            self.setText("All Sources \u25be")
        else:
            self.setText(", ".join(s.upper() for s in checked) + " \u25be")

    def get_sources(self) -> list:
        """Return list of currently selected source names."""
        return [s for s, a in self._actions.items() if a.isChecked()]

    def set_sources(self, sources: list):
        """Set which sources are checked."""
        for source, action in self._actions.items():
            action.setChecked(source in sources)
        self._update_text()
