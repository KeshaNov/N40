"""Мастер калибровки камеры (по образцу Bambu Lab):
1) искажения объектива по шахматной доске (cv2.calibrateCamera);
2) перспектива: 4 опорные точки на кадре ↔ координаты поля в мм
   (точки можно выжечь лазером на подложке — кнопка «Выжечь метки»).
"""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage)

from ..core import camera as cam
from . import style
from .panels import spin
from .workers import bgr_to_qimage


class FrameView(QLabel):
    """Показывает кадр с сохранением пропорций; клик -> координаты в пикселях кадра."""

    clicked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 360)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:{style.INK}; color:{style.PAPER};")
        self.setText("Нет кадра — включите камеру")
        self._img: QImage | None = None
        self.points: list[tuple[float, float]] = []

    def set_frame(self, img: QImage) -> None:
        self._img = img
        self._redraw()

    def _geometry(self):
        if self._img is None:
            return None
        k = min(self.width() / self._img.width(), self.height() / self._img.height())
        w, h = self._img.width() * k, self._img.height() * k
        return k, (self.width() - w) / 2, (self.height() - h) / 2

    def _redraw(self) -> None:
        g = self._geometry()
        if g is None:
            return
        k, ox, oy = g
        pm = QPixmap(self.size())
        pm.fill(QColor(style.INK))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawImage(QPointF(ox, oy), self._img.scaled(int(self._img.width() * k), int(self._img.height() * k),
                                                      Qt.AspectRatioMode.IgnoreAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        p.setFont(style.ui_font(10, True))
        for i, (x, y) in enumerate(self.points):
            c = QPointF(ox + x * k, oy + y * k)
            p.setPen(QPen(QColor(style.RED), 2))
            p.drawLine(c - QPointF(10, 0), c + QPointF(10, 0))
            p.drawLine(c - QPointF(0, 10), c + QPointF(0, 10))
            p.setPen(QColor(style.YELLOW))
            p.drawText(c + QPointF(8, -8), str(i + 1))
        p.end()
        self.setPixmap(pm)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._redraw()

    def mousePressEvent(self, e) -> None:
        g = self._geometry()
        if g is None:
            return
        k, ox, oy = g
        x, y = (e.position().x() - ox) / k, (e.position().y() - oy) / k
        if 0 <= x < self._img.width() and 0 <= y < self._img.height():
            self.clicked.emit(x, y)


class LensPage(QWizardPage):
    def __init__(self, wizard: "CalibrationWizard"):
        super().__init__()
        self.wiz = wizard
        self.setTitle("1. Искажения объектива")
        self.setSubTitle("Положите на стол напечатанную шахматную доску и снимите 10–20 кадров под разными "
                         "углами и в разных частях кадра. Шаг можно пропустить для камер без заметной дисторсии.")
        self.cols, self.rows = QSpinBox(), QSpinBox()
        self.cols.setRange(3, 30)
        self.rows.setRange(3, 30)
        self.cols.setValue(9)
        self.rows.setValue(6)
        self.square = spin(1, 200, 1, " мм")
        self.square.setValue(20)
        self.view = FrameView()
        self.count = QLabel("Кадров: 0")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.btn_capture = QPushButton("Снять кадр")
        self.btn_capture.setObjectName("Primary")
        self.btn_calc = QPushButton("Рассчитать")
        self.btn_reset = QPushButton("Сбросить")
        form = QFormLayout()
        form.addRow("Внутренних углов по горизонтали", self.cols)
        form.addRow("Внутренних углов по вертикали", self.rows)
        form.addRow("Размер клетки", self.square)
        btns = QHBoxLayout()
        for b in (self.btn_capture, self.btn_calc, self.btn_reset):
            btns.addWidget(b)
        btns.addWidget(self.count)
        btns.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.view, 1)
        lay.addLayout(btns)
        lay.addWidget(self.result)
        self.sets: list[np.ndarray] = []
        self.size = None
        self.btn_capture.clicked.connect(self.capture)
        self.btn_calc.clicked.connect(self.calculate)
        self.btn_reset.clicked.connect(self.reset)

    def on_frame(self, frame: np.ndarray) -> None:
        if not self.isVisible():
            return
        self.view.set_frame(bgr_to_qimage(frame))

    def capture(self) -> None:
        frame = self.wiz.last_frame
        if frame is None:
            self.result.setText("Нет кадра с камеры")
            return
        corners = cam.find_chessboard(frame, self.cols.value(), self.rows.value())
        if corners is None:
            self.result.setText("Доска не найдена. Проверьте число внутренних углов и освещение.")
            return
        self.sets.append(corners)
        self.size = (frame.shape[1], frame.shape[0])
        vis = frame.copy()
        cv2.drawChessboardCorners(vis, (self.cols.value(), self.rows.value()), corners, True)
        self.view.set_frame(bgr_to_qimage(vis))
        self.count.setText(f"Кадров: {len(self.sets)}")
        self.result.setText("Кадр добавлен")

    def calculate(self) -> None:
        if len(self.sets) < 5:
            self.result.setText("Нужно минимум 5 кадров")
            return
        mtx, dist, rms = cam.calibrate_lens(self.sets, self.cols.value(), self.rows.value(),
                                            self.square.value(), self.size)
        c = self.wiz.settings.calibration
        c.camera_matrix, c.dist_coeffs, c.image_size, c.rms = mtx.tolist(), dist.tolist(), list(self.size), rms
        self.result.setText(f"Готово. Ошибка репроекции RMS = {rms:.3f} px "
                            f"({'отлично' if rms < 0.5 else 'приемлемо' if rms < 1 else 'стоит переснять'})")

    def reset(self) -> None:
        self.sets.clear()
        self.count.setText("Кадров: 0")
        c = self.wiz.settings.calibration
        c.camera_matrix = c.dist_coeffs = c.rms = None
        self.result.setText("Калибровка объектива сброшена")


class PerspectivePage(QWizardPage):
    burn_markers = Signal(list)   # [(x_mm, y_mm), ...]

    def __init__(self, wizard: "CalibrationWizard"):
        super().__init__()
        self.wiz = wizard
        self.setTitle("2. Привязка к рабочему полю")
        self.setSubTitle("Нажмите «Выжечь метки» (на столе должен лежать лист картона/фанеры) или "
                         "используйте известные точки. Затем нажмите «Взять кадр» и щёлкните по 4 меткам "
                         "в порядке таблицы.")
        s = wizard.settings
        m = 15.0
        default = [(m, m), (s.bed_width - m, m), (s.bed_width - m, s.bed_height - m), (m, s.bed_height - m)]
        self.table = QTableWidget(4, 2)
        self.table.setHorizontalHeaderLabels(["X, мм", "Y, мм"])
        self.table.setVerticalHeaderLabels(["1", "2", "3", "4"])
        for i, (x, y) in enumerate(default):
            self.table.setItem(i, 0, QTableWidgetItem(f"{x:g}"))
            self.table.setItem(i, 1, QTableWidgetItem(f"{y:g}"))
        self.table.setMaximumWidth(220)
        self.view = FrameView()
        self.view.clicked.connect(self.add_point)
        self.btn_burn = QPushButton("Выжечь метки")
        self.btn_burn.setObjectName("Danger")
        self.btn_grab = QPushButton("Взять кадр")
        self.btn_grab.setObjectName("Primary")
        self.btn_clear = QPushButton("Сбросить точки")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        left = QVBoxLayout()
        left.addWidget(self.table)
        left.addWidget(self.btn_burn)
        left.addWidget(self.btn_grab)
        left.addWidget(self.btn_clear)
        left.addStretch(1)
        top = QHBoxLayout()
        top.addLayout(left)
        top.addWidget(self.view, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addWidget(self.result)
        self.btn_grab.clicked.connect(self.grab)
        self.btn_clear.clicked.connect(self.clear)
        self.btn_burn.clicked.connect(lambda: self.burn_markers.emit(self.field_points()))
        self.frame = None

    def field_points(self) -> list[tuple[float, float]]:
        pts = []
        for i in range(4):
            try:
                pts.append((float(self.table.item(i, 0).text().replace(",", ".")),
                            float(self.table.item(i, 1).text().replace(",", "."))))
            except (AttributeError, ValueError):
                pts.append((0.0, 0.0))
        return pts

    def grab(self) -> None:
        frame = self.wiz.last_frame
        if frame is None:
            self.result.setText("Нет кадра с камеры")
            return
        projector = cam.FieldProjector(self.wiz.settings.calibration, 1, 1)
        self.frame = projector.undistort(frame)
        self.view.points = []
        self.view.set_frame(bgr_to_qimage(self.frame))
        self.result.setText("Щёлкните по точке 1")

    def clear(self) -> None:
        self.view.points = []
        if self.frame is not None:
            self.view.set_frame(bgr_to_qimage(self.frame))

    def add_point(self, x: float, y: float) -> None:
        if self.frame is None or len(self.view.points) >= 4:
            return
        self.view.points.append((x, y))
        self.view.set_frame(bgr_to_qimage(self.frame))
        n = len(self.view.points)
        if n < 4:
            self.result.setText(f"Щёлкните по точке {n + 1}")
            return
        h = cam.compute_homography(self.view.points, self.field_points())
        self.wiz.settings.calibration.homography = h.tolist()
        self.result.setText("Перспектива рассчитана. Нажмите «Готово», чтобы сохранить.")


class CalibrationWizard(QWizard):
    def __init__(self, parent, settings, camera_worker):
        super().__init__(parent)
        self.setWindowTitle("Калибровка камеры")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.NextButton, "Далее")
        self.setButtonText(QWizard.WizardButton.BackButton, "Назад")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Готово")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Отмена")
        self.resize(900, 680)
        self.settings = settings
        self.last_frame = None
        self.lens = LensPage(self)
        self.persp = PerspectivePage(self)
        self.addPage(self.lens)
        self.addPage(self.persp)
        self.worker = camera_worker
        if camera_worker is not None:
            camera_worker.raw_frame.connect(self._on_frame)

    def _on_frame(self, frame) -> None:
        self.last_frame = frame
        self.lens.on_frame(frame)

    def done(self, result: int) -> None:
        if self.worker is not None:
            try:
                self.worker.raw_frame.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
        super().done(result)
