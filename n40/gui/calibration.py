"""Мастер калибровки камеры (по образцу Bambu Lab):
1) искажения объектива по шахматной доске (cv2.calibrateCamera); доску можно скачать в PDF;
2) рабочая зона: четыре угла перетаскиваются мышью на края поля (или на выжженные метки),
   всё за пределами зоны отбрасывается, подложка показывает только рабочее поле.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QImage, QPageLayout, QPageSize, QPainter,
                           QPainterPath, QPdfWriter, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget, QWizard, QWizardPage)

from ..core import camera as cam
from . import style
from .panels import caption, spin
from .workers import bgr_to_qimage

CORNER_NAMES = ("Левый верхний", "Правый верхний", "Правый нижний", "Левый нижний")
CORNER_SHORT = ("ЛВ", "ПВ", "ПН", "ЛН")
MARKER_INSET = 15.0  # мм — отступ выжигаемых меток от краёв поля


# --------------------------------------------------------------------------- шахматная доска

def save_chessboard_pdf(path: str, cols: int, rows: int, square_mm: float) -> None:
    """Сохраняет шахматную доску в PDF A4 в натуральную величину.

    cols × rows — внутренние углы (как вводятся в мастере), клеток на 1 больше по каждой оси.
    Бросает ValueError, если доска не помещается на лист.
    """
    nx, ny = cols + 1, rows + 1
    bw, bh = nx * square_mm, ny * square_mm
    landscape = bw > bh
    page_w, page_h = (297.0, 210.0) if landscape else (210.0, 297.0)
    margin, text_h = 12.0, 26.0
    avail_w, avail_h = page_w - 2 * margin, page_h - 2 * margin - text_h
    if bw > avail_w or bh > avail_h:
        max_sq = math.floor(min(avail_w / nx, avail_h / ny) * 10) / 10
        raise ValueError(f"Доска {bw:g} × {bh:g} мм не помещается на лист A4. "
                         f"Уменьшите клетку до {max_sq:g} мм или число углов.")

    writer = QPdfWriter(path)
    writer.setResolution(600)
    writer.setTitle(f"N40 — шахматная доска {cols}×{rows}, клетка {square_mm:g} мм")
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4),
                                     QPageLayout.Orientation.Landscape if landscape
                                     else QPageLayout.Orientation.Portrait,
                                     QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter))
    k = 600 / 25.4  # точек на мм
    p = QPainter(writer)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    x0 = (page_w - bw) / 2
    y0 = margin + text_h
    for j in range(ny):
        for i in range(nx):
            if (i + j) % 2 == 0:
                p.fillRect(QRectF((x0 + i * square_mm) * k, (y0 + j * square_mm) * k,
                                  square_mm * k, square_mm * k), QColor("black"))

    p.setPen(QColor("black"))
    font = QFont(style.FONT_FAMILY)
    font.setPointSizeF(12)
    font.setBold(True)
    p.setFont(font)
    p.drawText(QPointF(margin * k, (margin + 5) * k),
               f"N40 · шахматная доска для калибровки камеры: {cols} × {rows} внутренних углов, клетка {square_mm:g} мм")
    font.setBold(False)
    font.setPointSizeF(9)
    p.setFont(font)
    p.drawText(QPointF(margin * k, (margin + 11) * k),
               "Печатайте в масштабе 100 % (отключите «Подогнать по размеру страницы»). "
               "Наклейте на ровную жёсткую основу.")
    # контрольная линейка 50 мм для проверки масштаба печати
    ry = (margin + 18) * k
    rx = margin * k
    pen = QPen(QColor("black"), 0.3 * k)
    p.setPen(pen)
    p.drawLine(QPointF(rx, ry), QPointF(rx + 50 * k, ry))
    for t in range(0, 51, 10):
        h = 2.5 if t % 50 == 0 else 1.5
        p.drawLine(QPointF(rx + t * k, ry - h * k), QPointF(rx + t * k, ry))
    p.drawText(QPointF(rx + 53 * k, ry), "← после печати линия должна быть ровно 50 мм")
    p.end()


# --------------------------------------------------------------------------- просмотр кадра

class FrameView(QWidget):
    """Кадр с камеры с сохранением пропорций.

    Если задан quad (4 точки в пикселях кадра), углы можно перетаскивать мышью и сдвигать стрелками
    (Shift — по 10 px); при перетаскивании показывается лупа. Область вне зоны затемняется.
    """

    quad_changed = Signal()

    HANDLE = 9      # полуразмер маркера угла, px экрана
    PICK = 18       # радиус захвата, px экрана

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 360)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._img: QImage | None = None
        self.quad: list[QPointF] | None = None
        self.active = -1
        self._dragging = False

    # ------------------------------------------------------------------ данные
    def set_frame(self, img: QImage) -> None:
        self._img = img
        self.update()

    def set_quad(self, pts) -> None:
        self.quad = [QPointF(float(x), float(y)) for x, y in pts] if pts is not None else None
        self.update()

    def quad_points(self) -> list[tuple[float, float]]:
        return [(p.x(), p.y()) for p in self.quad] if self.quad else []

    # ------------------------------------------------------------------ геометрия
    def _geometry(self):
        if self._img is None or self._img.isNull():
            return None
        k = min(self.width() / self._img.width(), self.height() / self._img.height())
        return k, (self.width() - self._img.width() * k) / 2, (self.height() - self._img.height() * k) / 2

    def _to_view(self, p: QPointF) -> QPointF:
        k, ox, oy = self._geometry()
        return QPointF(ox + p.x() * k, oy + p.y() * k)

    def _to_image(self, p: QPointF) -> QPointF:
        k, ox, oy = self._geometry()
        x = min(max((p.x() - ox) / k, 0.0), self._img.width() - 1.0)
        y = min(max((p.y() - oy) / k, 0.0), self._img.height() - 1.0)
        return QPointF(x, y)

    # ------------------------------------------------------------------ отрисовка
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(style.INK))
        g = self._geometry()
        if g is None:
            p.setPen(QColor(style.PAPER))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Нет кадра — включите камеру")
            return
        k, ox, oy = g
        target = QRectF(ox, oy, self._img.width() * k, self._img.height() * k)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(target, self._img)
        if not self.quad:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        poly = QPolygonF([self._to_view(q) for q in self.quad])
        outside = QPainterPath()
        outside.addRect(target)
        inside = QPainterPath()
        inside.addPolygon(poly)
        inside.closeSubpath()
        p.fillPath(outside.subtracted(inside), QColor(0, 0, 0, 150))
        p.setPen(QPen(QColor(style.YELLOW), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(poly)
        p.setFont(style.ui_font(9, True))
        for i, q in enumerate(poly):
            color = QColor(style.RED) if i == self.active else QColor(style.YELLOW)
            p.setPen(QPen(QColor(style.INK), 1))
            p.setBrush(color)
            h = self.HANDLE
            p.drawRect(QRectF(q.x() - h, q.y() - h, 2 * h, 2 * h))
            p.setPen(QPen(QColor(style.INK), 1))
            p.drawLine(QPointF(q.x() - h, q.y()), QPointF(q.x() + h, q.y()))
            p.drawLine(QPointF(q.x(), q.y() - h), QPointF(q.x(), q.y() + h))
            p.setPen(QColor(style.PAPER))
            p.drawText(q + QPointF(h + 4, -h - 2), str(i + 1))
        if self._dragging and 0 <= self.active < 4:
            self._draw_loupe(p, self.quad[self.active])

    def _draw_loupe(self, p: QPainter, at: QPointF) -> None:
        """Лупа ×4 вокруг перетаскиваемого угла — для точного попадания в край поля."""
        src_half, size = 24, 192
        src = QRectF(at.x() - src_half, at.y() - src_half, 2 * src_half, 2 * src_half)
        corner = 0 if at.x() > self._img.width() / 2 else 1  # лупа в противоположной от угла стороне
        x = 10 if corner == 0 else self.width() - size - 10
        dst = QRectF(x, 10, size, size)
        p.save()
        p.setClipRect(dst)
        p.fillRect(dst, QColor(style.INK))
        p.drawImage(dst, self._img, src)
        p.restore()
        p.setPen(QPen(QColor(style.RED), 1))
        c = dst.center()
        p.drawLine(QPointF(c.x() - 14, c.y()), QPointF(c.x() + 14, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 14), QPointF(c.x(), c.y() + 14))
        p.setPen(QPen(QColor(style.YELLOW), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(dst)

    # ------------------------------------------------------------------ мышь и клавиатура
    def mousePressEvent(self, e) -> None:
        if not self.quad or self._geometry() is None:
            return
        pos = e.position()
        dists = [math.hypot(self._to_view(q).x() - pos.x(), self._to_view(q).y() - pos.y()) for q in self.quad]
        i = min(range(4), key=dists.__getitem__)
        if dists[i] <= self.PICK:
            self.active = i
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._dragging and 0 <= self.active < 4:
            self.quad[self.active] = self._to_image(e.position())
            self.update()
            self.quad_changed.emit()
        elif self.quad and self._geometry() is not None:
            pos = e.position()
            near = any(math.hypot(self._to_view(q).x() - pos.x(), self._to_view(q).y() - pos.y()) <= self.PICK
                       for q in self.quad)
            self.setCursor(Qt.CursorShape.SizeAllCursor if near else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e) -> None:
        if self._dragging:
            self._dragging = False
            self.update()

    def keyPressEvent(self, e) -> None:
        if not self.quad or not 0 <= self.active < 4:
            return super().keyPressEvent(e)
        step = 10.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        d = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
             Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}.get(e.key())
        if d is None:
            if e.key() == Qt.Key.Key_Tab:
                self.active = (self.active + 1) % 4
                self.update()
                return
            return super().keyPressEvent(e)
        q = self.quad[self.active]
        self.quad[self.active] = QPointF(min(max(q.x() + d[0], 0), self._img.width() - 1),
                                         min(max(q.y() + d[1], 0), self._img.height() - 1))
        self.update()
        self.quad_changed.emit()

    def focusNextPrevChild(self, _next: bool) -> bool:
        return False  # Tab переключает углы, а не фокус


# --------------------------------------------------------------------------- шаг 1: объектив

class LensPage(QWizardPage):
    def __init__(self, wizard: "CalibrationWizard"):
        super().__init__()
        self.wiz = wizard
        self.setTitle("1. Искажения объектива")
        self.setSubTitle("Скачайте и распечатайте шахматную доску, положите её на стол и снимите 10–20 кадров "
                         "под разными углами и в разных частях кадра. Шаг можно пропустить — нажмите «Далее».")
        self.cols, self.rows = QSpinBox(), QSpinBox()
        self.cols.setRange(3, 30)
        self.rows.setRange(3, 30)
        self.cols.setValue(9)
        self.rows.setValue(6)
        self.square = spin(1, 200, 1, " мм")
        self.square.setValue(20)
        self.btn_download = QPushButton("Скачать шахматную доску (PDF)…")
        self.btn_download.setToolTip("Доска с выбранными параметрами в натуральную величину, лист A4")
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
        top = QHBoxLayout()
        top.addLayout(form)
        top.addStretch(1)
        top.addWidget(self.btn_download, 0, Qt.AlignmentFlag.AlignBottom)
        btns = QHBoxLayout()
        for b in (self.btn_capture, self.btn_calc, self.btn_reset):
            btns.addWidget(b)
        btns.addWidget(self.count)
        btns.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.view, 1)
        lay.addLayout(btns)
        lay.addWidget(self.result)
        self.sets: list[np.ndarray] = []
        self.size = None
        self.btn_download.clicked.connect(self.download_board)
        self.btn_capture.clicked.connect(self.capture)
        self.btn_calc.clicked.connect(self.calculate)
        self.btn_reset.clicked.connect(self.reset)

    def download_board(self) -> None:
        cols, rows, sq = self.cols.value(), self.rows.value(), self.square.value()
        name = f"Шахматная доска {cols}x{rows} {sq:g}мм.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить шахматную доску", name, "PDF (*.pdf)")
        if not path:
            return
        try:
            save_chessboard_pdf(path, cols, rows, sq)
        except ValueError as exc:
            QMessageBox.warning(self, "Шахматная доска", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Шахматная доска", f"Не удалось сохранить файл: {exc}")
            return
        self.result.setText("Доска сохранена. Печатайте в масштабе 100 % и проверьте контрольную линейку 50 мм.")
        if QMessageBox.question(self, "Шахматная доска", "Доска сохранена. Открыть PDF для печати?") \
                == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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


# --------------------------------------------------------------------------- шаг 2: рабочая зона

class WorkZonePage(QWizardPage):
    burn_markers = Signal(list)   # [(x_mm, y_mm), ...]

    def __init__(self, wizard: "CalibrationWizard"):
        super().__init__()
        self.wiz = wizard
        self.setTitle("2. Рабочая зона")
        self.setSubTitle("Камера видит больше, чем нужно: перетащите четыре жёлтых угла точно на углы "
                         "рабочего поля. Всё за рамкой будет отброшено. Стрелки сдвигают выбранный угол на 1 px "
                         "(Shift — на 10), Tab — следующий угол.")
        self.frame: np.ndarray | None = None

        self.mode_corners = QRadioButton("По углам рабочего поля")
        self.mode_markers = QRadioButton("По выжженным меткам (точнее)")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_corners)
        self.mode_group.addButton(self.mode_markers)
        self.table = QTableWidget(4, 2)
        self.table.setHorizontalHeaderLabels(["X, мм", "Y, мм"])
        self.table.setVerticalHeaderLabels([f"{i + 1}" for i in range(4)])
        self.table.setFixedWidth(240)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setFixedHeight(self.table.horizontalHeader().sizeHint().height() + 4 * 28 + 4)
        self.btn_burn = QPushButton("Выжечь метки")
        self.btn_burn.setObjectName("Danger")
        self.btn_burn.setToolTip("Положите на стол картон или фанеру: лазер выжжет 4 крестика в точках таблицы")
        self.btn_grab = QPushButton("Обновить кадр")
        self.btn_reset = QPushButton("Сбросить рамку")
        self.preview = QLabel()
        self.preview.setFixedSize(240, 170)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"background:{style.INK}; color:{style.GREY};")
        self.preview.setText("Предпросмотр")
        self.view = FrameView()
        self.result = QLabel("")
        self.result.setWordWrap(True)

        left = QVBoxLayout()
        left.addWidget(caption("Привязка"))
        left.addWidget(self.mode_corners)
        left.addWidget(self.mode_markers)
        left.addWidget(self.table)
        left.addWidget(self.btn_burn)
        row = QHBoxLayout()
        row.addWidget(self.btn_grab)
        row.addWidget(self.btn_reset)
        left.addLayout(row)
        left.addWidget(caption("Результат: только рабочее поле"))
        left.addWidget(self.preview)
        left.addStretch(1)
        top = QHBoxLayout()
        top.addLayout(left)
        top.addWidget(self.view, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addWidget(self.result)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self._update_preview)
        self.mode_group.buttonToggled.connect(self._mode_changed)
        self.table.itemChanged.connect(lambda _i: self._recompute())
        self.btn_grab.clicked.connect(self.grab)
        self.btn_reset.clicked.connect(self.reset_quad)
        self.btn_burn.clicked.connect(lambda: self.burn_markers.emit(self.field_points()))
        self.view.quad_changed.connect(self._recompute)

        cal = wizard.settings.calibration
        (self.mode_markers if cal.zone_mode == "markers" else self.mode_corners).setChecked(True)
        self._mode_changed()

    # ------------------------------------------------------------------ точки поля
    def default_field_points(self) -> list[tuple[float, float]]:
        s = self.wiz.settings
        m = MARKER_INSET if self.mode_markers.isChecked() else 0.0
        return [(m, m), (s.bed_width - m, m), (s.bed_width - m, s.bed_height - m), (m, s.bed_height - m)]

    def field_points(self) -> list[tuple[float, float]]:
        pts = []
        for i in range(4):
            try:
                pts.append((float(self.table.item(i, 0).text().replace(",", ".")),
                            float(self.table.item(i, 1).text().replace(",", "."))))
            except (AttributeError, ValueError):
                pts.append(self.default_field_points()[i])
        return pts

    def _fill_table(self, pts, editable: bool) -> None:
        self.table.blockSignals(True)
        for i, (x, y) in enumerate(pts):
            for j, v in enumerate((x, y)):
                item = QTableWidgetItem(f"{v:g}")
                if not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, j, item)
        self.table.blockSignals(False)

    def _mode_changed(self, *_args) -> None:
        markers = self.mode_markers.isChecked()
        cal = self.wiz.settings.calibration
        saved = cal.field_points if cal.field_points and (cal.zone_mode == "markers") == markers else None
        self._fill_table(saved or self.default_field_points(), editable=markers)
        self.btn_burn.setVisible(markers)
        self.table.setVerticalHeaderLabels([f"{i + 1}" if markers else f"{i + 1} · {CORNER_SHORT[i]}"
                                            for i in range(4)])
        for i in range(4):
            self.table.verticalHeaderItem(i).setToolTip(f"Метка {i + 1}" if markers else CORNER_NAMES[i])
        self._recompute()

    # ------------------------------------------------------------------ кадр и рамка
    def initializePage(self) -> None:
        if self.frame is None:
            self.grab()

    def grab(self) -> None:
        frame = self.wiz.last_frame
        if frame is None:
            self.result.setText("Нет кадра с камеры. Включите камеру и нажмите «Обновить кадр».")
            return
        projector = cam.FieldProjector(self.wiz.settings.calibration, 1, 1)
        self.frame = projector.undistort(frame)
        self.view.set_frame(bgr_to_qimage(self.frame))
        if self.view.quad is None:
            self._init_quad()
        self._recompute()

    def _init_quad(self) -> None:
        """Рамка из сохранённой калибровки, иначе — с отступом 10 % от краёв кадра."""
        h, w = self.frame.shape[:2]
        cal = self.wiz.settings.calibration
        pts = cal.image_points
        if pts and all(0 <= x < w and 0 <= y < h for x, y in pts):
            self.view.set_quad(pts)
        else:
            mx, my = w * 0.1, h * 0.1
            self.view.set_quad([(mx, my), (w - mx, my), (w - mx, h - my), (mx, h - my)])
        self.view.active = 0

    def reset_quad(self) -> None:
        if self.frame is None:
            return
        self.wiz.settings.calibration.image_points = None
        self._init_quad()
        self._recompute()

    def _recompute(self) -> None:
        if self.frame is None or not self.view.quad:
            return
        img_pts = self.view.quad_points()
        field = self.field_points()
        if cv2.contourArea(np.array(img_pts, dtype=np.float32)) < 100:
            self.result.setText("Рамка слишком маленькая или перекручена")
            return
        h = cam.compute_homography(img_pts, field)
        cal = self.wiz.settings.calibration
        cal.homography = h.tolist()
        cal.image_points = [list(p) for p in img_pts]
        cal.field_points = [list(p) for p in field]
        cal.zone_mode = "markers" if self.mode_markers.isChecked() else "corners"
        s = self.wiz.settings
        self.result.setText(f"Рабочая зона задана: {s.bed_width:g} × {s.bed_height:g} мм. "
                            "Нажмите «Готово», чтобы сохранить.")
        self._preview_timer.start()

    def _update_preview(self) -> None:
        if self.frame is None or self.wiz.settings.calibration.homography is None:
            return
        s = self.wiz.settings
        ppm = min(self.preview.width() / s.bed_width, self.preview.height() / s.bed_height)
        h = np.diag([ppm, ppm, 1.0]) @ np.array(s.calibration.homography, dtype=np.float64)
        size = (max(1, int(s.bed_width * ppm)), max(1, int(s.bed_height * ppm)))
        warped = cv2.warpPerspective(self.frame, h, size, flags=cv2.INTER_AREA)
        self.preview.setPixmap(QPixmap.fromImage(bgr_to_qimage(warped)))

    def validatePage(self) -> bool:
        if self.wiz.settings.calibration.homography is None:
            QMessageBox.information(self, "Рабочая зона", "Сначала задайте рабочую зону на кадре с камеры.")
            return False
        return True


class CalibrationWizard(QWizard):
    def __init__(self, parent, settings, camera_worker):
        super().__init__(parent)
        self.setWindowTitle("Калибровка камеры")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.NextButton, "Далее")
        self.setButtonText(QWizard.WizardButton.BackButton, "Назад")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Готово")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Отмена")
        self.resize(1040, 720)
        self.settings = settings
        self.last_frame = None
        self.lens = LensPage(self)
        self.zone = WorkZonePage(self)
        self.addPage(self.lens)
        self.addPage(self.zone)
        self.worker = camera_worker
        if camera_worker is not None:
            camera_worker.raw_frame.connect(self._on_frame)

    def _on_frame(self, frame) -> None:
        first = self.last_frame is None
        self.last_frame = frame
        self.lens.on_frame(frame)
        if first and self.currentPage() is self.zone:
            self.zone.grab()

    def done(self, result: int) -> None:
        if self.worker is not None:
            try:
                self.worker.raw_frame.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
        super().done(result)
