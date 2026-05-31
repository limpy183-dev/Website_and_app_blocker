"""Shared UI helpers."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget


def error(parent: QWidget | None, msg: str, title: str = "Error") -> None:
    QMessageBox.critical(parent, title, msg)


def info(parent: QWidget | None, msg: str, title: str = "FocusFortress") -> None:
    QMessageBox.information(parent, title, msg)


def confirm(parent: QWidget | None, msg: str, title: str = "Confirm") -> bool:
    btn = QMessageBox.question(
        parent, title, msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return btn == QMessageBox.StandardButton.Yes
