STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1a1b26;
    color: #c0caf5;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #2a2b3d;
    background-color: #1a1b26;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #16171f;
    color: #565f89;
    padding: 10px 22px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.5px;
}

QTabBar::tab:selected {
    background-color: #1a1b26;
    color: #7aa2f7;
    border-bottom: 2px solid #7aa2f7;
}

QTabBar::tab:hover:!selected {
    color: #c0caf5;
    background-color: #1e2030;
}

QLineEdit {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    padding: 8px 14px;
    color: #c0caf5;
    font-size: 13px;
    selection-background-color: #3d59a1;
}

QLineEdit:focus {
    border: 1px solid #7aa2f7;
}

QLineEdit::placeholder {
    color: #3b4261;
}

QPushButton {
    background-color: #2a2b3d;
    color: #c0caf5;
    border: 1px solid #3b4261;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #3b4261;
    border-color: #7aa2f7;
    color: #7aa2f7;
}

QPushButton:pressed {
    background-color: #7aa2f7;
    color: #1a1b26;
}

QPushButton:disabled {
    background-color: #16171f;
    color: #3b4261;
    border-color: #1e2030;
}

QPushButton#primary {
    background-color: #7aa2f7;
    color: #1a1b26;
    border: none;
    font-weight: 700;
}

QPushButton#primary:hover {
    background-color: #89b4fa;
    color: #1a1b26;
}

QPushButton#danger {
    background-color: #f7768e;
    color: #1a1b26;
    border: none;
    font-weight: 700;
}

QPushButton#danger:hover {
    background-color: #ff9e64;
}

QPushButton#success {
    background-color: #9ece6a;
    color: #1a1b26;
    border: none;
    font-weight: 700;
}

QPushButton#success:hover {
    background-color: #73daca;
}

QTableWidget {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    gridline-color: #1e2030;
    color: #c0caf5;
    selection-background-color: #2a2b3d;
    selection-color: #7aa2f7;
    outline: none;
}

QTableWidget::item {
    padding: 6px 10px;
    border-bottom: 1px solid #1e2030;
}

QTableWidget::item:selected {
    background-color: #2a2b3d;
    color: #7aa2f7;
}

QTableWidget::item:hover {
    background-color: #1e2030;
}

QHeaderView::section {
    background-color: #1e2030;
    color: #565f89;
    padding: 8px 10px;
    border: none;
    border-right: 1px solid #2a2b3d;
    border-bottom: 1px solid #2a2b3d;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
}

QTextEdit {
    background-color: #0d0e14;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    color: #a9b1d6;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: #3d59a1;
}

QScrollBar:vertical {
    background-color: #16171f;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #2a2b3d;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3b4261;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #16171f;
    height: 8px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #2a2b3d;
    border-radius: 4px;
}

QProgressBar {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 6px;
    text-align: center;
    color: #c0caf5;
    font-size: 11px;
    height: 16px;
}

QProgressBar::chunk {
    background-color: #7aa2f7;
    border-radius: 5px;
}

QComboBox {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 8px;
    padding: 8px 14px;
    color: #c0caf5;
    min-width: 130px;
}

QComboBox:focus {
    border-color: #7aa2f7;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #1e2030;
    border: 1px solid #2a2b3d;
    color: #c0caf5;
    selection-background-color: #2a2b3d;
    selection-color: #7aa2f7;
    outline: none;
}

QStatusBar {
    background-color: #16171f;
    color: #565f89;
    border-top: 1px solid #2a2b3d;
    font-size: 12px;
}

QSplitter::handle {
    background-color: #2a2b3d;
}

QToolBar {
    background-color: #16171f;
    border-bottom: 1px solid #2a2b3d;
    spacing: 6px;
    padding: 4px 8px;
}

QToolBar::separator {
    background-color: #2a2b3d;
    width: 1px;
    margin: 4px 4px;
}

QCheckBox {
    spacing: 8px;
    color: #c0caf5;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3b4261;
    border-radius: 4px;
    background-color: #16171f;
}

QCheckBox::indicator:checked {
    background-color: #7aa2f7;
    border-color: #7aa2f7;
}

QFrame#sidebar-card {
    background-color: #16171f;
    border: 1px solid #2a2b3d;
    border-radius: 10px;
    padding: 12px;
}

QDialog {
    background-color: #1a1b26;
    color: #c0caf5;
}

QMessageBox {
    background-color: #1a1b26;
    color: #c0caf5;
}

QMenu {
    background-color: #1e2030;
    border: 1px solid #2a2b3d;
    color: #c0caf5;
    padding: 4px 0;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
}

QMenu::item:selected {
    background-color: #2a2b3d;
    color: #7aa2f7;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}

QMenu::indicator:checked {
    background-color: #7aa2f7;
    border: 1px solid #7aa2f7;
    border-radius: 3px;
}

QMenu::indicator:unchecked {
    background-color: #16171f;
    border: 1px solid #3b4261;
    border-radius: 3px;
}
"""
