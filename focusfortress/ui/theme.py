"""Modern theme system: color palette, typography, and QSS stylesheet.

The whole UI uses a single dark "glass-lite" theme inspired by modern
productivity apps. Every widget pulls its look from the central QSS string
below so changes here cascade everywhere.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Color tokens
# ---------------------------------------------------------------------------

class Colors:
    # Base surfaces
    BG          = "#0f1115"   # app background
    SURFACE     = "#161a22"   # panel / card background
    SURFACE_ALT = "#1c2230"   # elevated surface (hovered / selected card)
    SURFACE_HI  = "#232a3a"   # highest elevation
    BORDER      = "#262c3b"   # subtle separators
    BORDER_HI   = "#343c52"   # stronger separators / focused borders

    # Text
    TEXT        = "#e8ecf4"
    TEXT_MUTED  = "#8b94a8"
    TEXT_FAINT  = "#5a6275"

    # Accents (indigo -> violet gradient family)
    ACCENT      = "#6366f1"   # indigo-500
    ACCENT_HOV  = "#7c7ff5"
    ACCENT_DIM  = "#4f52c7"
    ACCENT_SOFT = "rgba(99,102,241,0.15)"

    # Semantic
    SUCCESS     = "#22c55e"
    SUCCESS_SOFT= "rgba(34,197,94,0.15)"
    WARNING     = "#f59e0b"
    WARNING_SOFT= "rgba(245,158,11,0.15)"
    DANGER      = "#ef4444"
    DANGER_SOFT = "rgba(239,68,68,0.15)"
    INFO        = "#38bdf8"


# ---------------------------------------------------------------------------
# Full QSS
# ---------------------------------------------------------------------------

STYLESHEET = f"""
/* ============================================================
   Base
   ============================================================ */
QWidget {{
    background-color: {Colors.BG};
    color: {Colors.TEXT};
    font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

QToolTip {{
    background-color: {Colors.SURFACE_HI};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER_HI};
    padding: 6px 10px;
    border-radius: 6px;
}}

QMainWindow, QDialog {{
    background-color: {Colors.BG};
}}

/* ============================================================
   Scroll bars
   ============================================================ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {Colors.BORDER_HI};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {Colors.TEXT_FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {Colors.BORDER_HI};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {Colors.TEXT_FAINT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ============================================================
   Sidebar
   ============================================================ */
QFrame#Sidebar {{
    background-color: {Colors.SURFACE};
    border: none;
    border-right: 1px solid {Colors.BORDER};
}}

QLabel#Brand {{
    color: {Colors.TEXT};
    font-size: 18px;
    font-weight: 700;
    padding: 4px 0;
    letter-spacing: 0.3px;
}}

QLabel#BrandSub {{
    color: {Colors.TEXT_MUTED};
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 1.2px;
}}

QPushButton#NavButton {{
    background-color: transparent;
    color: {Colors.TEXT_MUTED};
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13.5px;
    font-weight: 500;
}}
QPushButton#NavButton:hover {{
    background-color: {Colors.SURFACE_ALT};
    color: {Colors.TEXT};
}}
QPushButton#NavButton:checked {{
    background-color: {Colors.ACCENT_SOFT};
    color: {Colors.TEXT};
    font-weight: 600;
}}

QLabel#NavSection {{
    color: {Colors.TEXT_FAINT};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 8px 8px 4px 8px;
}}

/* ============================================================
   Header bar inside each page
   ============================================================ */
QLabel#PageTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {Colors.TEXT};
}}
QLabel#PageSubtitle {{
    font-size: 13px;
    color: {Colors.TEXT_MUTED};
}}

/* ============================================================
   Card
   ============================================================ */
QFrame#Card {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 14px;
}}
QFrame#Card:hover {{
    border: 1px solid {Colors.BORDER_HI};
}}

QLabel#CardTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {Colors.TEXT};
}}
QLabel#CardSubtitle {{
    font-size: 12px;
    color: {Colors.TEXT_MUTED};
}}

QLabel#StatNumber {{
    font-size: 26px;
    font-weight: 700;
    color: {Colors.TEXT};
}}
QLabel#StatLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {Colors.TEXT_MUTED};
    letter-spacing: 1px;
}}

/* ============================================================
   Buttons
   ============================================================ */
QPushButton {{
    background-color: {Colors.SURFACE_ALT};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {Colors.SURFACE_HI};
    border-color: {Colors.BORDER_HI};
}}
QPushButton:pressed {{ background-color: {Colors.SURFACE}; }}
QPushButton:disabled {{ color: {Colors.TEXT_FAINT}; background-color: {Colors.SURFACE}; }}

QPushButton[variant="primary"] {{
    background-color: {Colors.ACCENT};
    color: white;
    border: 1px solid {Colors.ACCENT};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background-color: {Colors.ACCENT_HOV};
    border-color: {Colors.ACCENT_HOV};
}}
QPushButton[variant="primary"]:pressed {{ background-color: {Colors.ACCENT_DIM}; }}

QPushButton[variant="success"] {{
    background-color: {Colors.SUCCESS};
    color: white;
    border: 1px solid {Colors.SUCCESS};
    font-weight: 600;
}}
QPushButton[variant="danger"] {{
    background-color: transparent;
    color: {Colors.DANGER};
    border: 1px solid {Colors.DANGER_SOFT};
}}
QPushButton[variant="danger"]:hover {{
    background-color: {Colors.DANGER_SOFT};
}}
QPushButton[variant="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {Colors.TEXT_MUTED};
}}
QPushButton[variant="ghost"]:hover {{
    color: {Colors.TEXT};
    background-color: {Colors.SURFACE_ALT};
}}

/* Toggle-style button (the Enable/Enabled pill) */
QPushButton[variant="toggle"] {{
    background-color: {Colors.SURFACE_ALT};
    color: {Colors.TEXT_MUTED};
    border: 1px solid {Colors.BORDER};
    border-radius: 14px;
    padding: 6px 16px;
    font-weight: 600;
    min-width: 84px;
}}
QPushButton[variant="toggle"]:hover {{ color: {Colors.TEXT}; }}
QPushButton[variant="toggle"]:checked {{
    background-color: {Colors.SUCCESS};
    color: white;
    border-color: {Colors.SUCCESS};
}}

/* ============================================================
   Inputs
   ============================================================ */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QTimeEdit,
QDateEdit, QDateTimeEdit, QComboBox {{
    background-color: {Colors.BG};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {Colors.ACCENT};
    selection-color: white;
}}
QPlainTextEdit, QTextEdit {{ padding: 8px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{
    border: 1px solid {Colors.ACCENT};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {Colors.TEXT_FAINT};
    background-color: {Colors.SURFACE};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: right center;
    width: 22px;
    border: none;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {Colors.TEXT_MUTED};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {Colors.SURFACE};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER_HI};
    border-radius: 8px;
    selection-background-color: {Colors.ACCENT_SOFT};
    selection-color: {Colors.TEXT};
    padding: 4px;
    outline: 0;
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {Colors.TEXT_MUTED};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {Colors.TEXT_MUTED};
}}

/* ============================================================
   Checkboxes / Radios
   ============================================================ */
QCheckBox, QRadioButton {{
    spacing: 9px;
    color: {Colors.TEXT};
    padding: 4px 0;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {Colors.BORDER_HI};
    background-color: {Colors.SURFACE};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {Colors.ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {Colors.ACCENT};
    border-color: {Colors.ACCENT};
    image: none;
}}
QRadioButton::indicator:checked {{
    background-color: {Colors.ACCENT};
    border-color: {Colors.ACCENT};
}}

/* ============================================================
   Lists / Tables
   ============================================================ */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 10px;
    outline: 0;
    padding: 4px;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin: 1px 2px;
    color: {Colors.TEXT};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {Colors.SURFACE_ALT};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {Colors.ACCENT_SOFT};
    color: {Colors.TEXT};
}}

QTableWidget {{
    gridline-color: {Colors.BORDER};
    selection-background-color: {Colors.ACCENT_SOFT};
    selection-color: {Colors.TEXT};
}}
QTableWidget::item {{
    padding: 8px;
    border: none;
}}
QHeaderView::section {{
    background-color: {Colors.SURFACE};
    color: {Colors.TEXT_MUTED};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {Colors.BORDER};
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.6px;
}}
QTableCornerButton::section {{
    background-color: {Colors.SURFACE};
    border: none;
}}

/* ============================================================
   Tabs (inner sub-tabs in Blocks page)
   ============================================================ */
QTabWidget::pane {{
    border: none;
    background-color: transparent;
    top: -1px;
}}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background-color: transparent;
    color: {Colors.TEXT_MUTED};
    padding: 8px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {Colors.TEXT}; }}
QTabBar::tab:selected {{
    color: {Colors.TEXT};
    border-bottom: 2px solid {Colors.ACCENT};
    font-weight: 600;
}}

/* ============================================================
   Group boxes
   ============================================================ */
QGroupBox {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER};
    border-radius: 12px;
    margin-top: 18px;
    padding: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 10px;
    left: 12px;
    color: {Colors.TEXT};
    background-color: {Colors.BG};
}}

/* ============================================================
   Splitter
   ============================================================ */
QSplitter::handle {{
    background-color: transparent;
}}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical   {{ height: 8px; }}

/* ============================================================
   Status bar
   ============================================================ */
QStatusBar {{
    background-color: {Colors.SURFACE};
    color: {Colors.TEXT_MUTED};
    border-top: 1px solid {Colors.BORDER};
}}
QStatusBar::item {{ border: none; }}

/* ============================================================
   Menus
   ============================================================ */
QMenu {{
    background-color: {Colors.SURFACE};
    border: 1px solid {Colors.BORDER_HI};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {Colors.ACCENT_SOFT};
    color: {Colors.TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {Colors.BORDER};
    margin: 4px 8px;
}}

/* ============================================================
   Status pills (used via objectName)
   ============================================================ */
QLabel#StatusPillOk {{
    background-color: {Colors.SUCCESS_SOFT};
    color: {Colors.SUCCESS};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QLabel#StatusPillOff {{
    background-color: {Colors.SURFACE_ALT};
    color: {Colors.TEXT_MUTED};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QLabel#StatusPillWarn {{
    background-color: {Colors.WARNING_SOFT};
    color: {Colors.WARNING};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the FocusFortress dark theme to the QApplication."""
    app.setStyle("Fusion")

    # Load a nice default font, falling back gracefully.
    font = QFont("Segoe UI Variable", 10)
    if not QFontDatabase.families().__contains__("Segoe UI Variable"):
        font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Dark palette (so any unstyled native widget still looks coherent).
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(Colors.BG))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(Colors.TEXT))
    pal.setColor(QPalette.ColorRole.Base,            QColor(Colors.BG))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(Colors.SURFACE))
    pal.setColor(QPalette.ColorRole.Text,            QColor(Colors.TEXT))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(Colors.SURFACE_HI))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(Colors.TEXT))
    pal.setColor(QPalette.ColorRole.Button,          QColor(Colors.SURFACE_ALT))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(Colors.TEXT))
    pal.setColor(QPalette.ColorRole.BrightText,      QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(Colors.ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(Colors.TEXT_FAINT))
    pal.setColor(QPalette.ColorRole.Link,            QColor(Colors.ACCENT_HOV))
    app.setPalette(pal)

    app.setStyleSheet(STYLESHEET)
