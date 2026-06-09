"""表格行勾选框（自绘对勾，避免 QSS 在 macOS 上不显示 SVG）."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QLabel


class CheckToggle(QLabel):
    """可点击的勾选框，选中时绘制蓝色对勾."""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setObjectName("rowCheckBox")
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._redraw()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self._redraw()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mousePressEvent(event)

    def _redraw(self) -> None:
        pix = QPixmap(22, 22)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)

        border = QColor("#3498db" if self._checked else "#7f8c8d")
        box_pen = QPen(border)
        box_pen.setWidth(2)
        painter.setPen(box_pen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(2, 2, 17, 17, 3, 3)

        if self._checked:
            check_pen = QPen(QColor("#3498db"))
            check_pen.setWidth(2)
            check_pen.setCapStyle(Qt.RoundCap)
            check_pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(check_pen)
            painter.drawLine(5, 11, 9, 15)
            painter.drawLine(9, 15, 17, 7)

        painter.end()
        self.setPixmap(pix)
