"""Диалоги: импорт, текст, массивы, смещение контура, нестинг, настройки, обновление."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainterPath
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFontComboBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core.geometry import Contour
from ..core.importers import ImportOptions
from .panels import spin

import numpy as np


def _buttons(dlg: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Title")
    return lbl


# --------------------------------------------------------------------------- импорт

class ImportDialog(QDialog):
    def __init__(self, parent, settings, has_svg: bool, has_raster: bool, has_dxf: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Параметры импорта")
        self.dpi = QComboBox()
        for v, t in ((96, "96 dpi — Inkscape 0.92+, браузеры"), (90, "90 dpi — Inkscape до 0.92"),
                     (72, "72 dpi — Adobe Illustrator")):
            self.dpi.addItem(t, float(v))
        idx = self.dpi.findData(float(settings.svg_dpi))
        self.dpi.setCurrentIndex(idx if idx >= 0 else 0)
        self.scale = spin(0.1, 10000, 2, " %", 1)
        self.scale.setValue(100)
        self.raster_dpi = QSpinBox()
        self.raster_dpi.setRange(0, 4800)
        self.raster_dpi.setSpecialValueText("из файла")
        self.raster_dpi.setSuffix(" dpi")
        self.remember = QCheckBox("Запомнить DPI для SVG")
        self.dxf_units = QComboBox()
        for title, mm in (("Авто (из файла)", None), ("Миллиметры", 1.0), ("Сантиметры", 10.0),
                          ("Метры", 1000.0), ("Дюймы", 25.4)):
            self.dxf_units.addItem(title, mm)
        form = QFormLayout()
        if has_svg:
            form.addRow("Разрешение SVG", self.dpi)
            form.addRow("", self.remember)
        if has_dxf:
            form.addRow("Единицы DXF", self.dxf_units)
        if has_raster:
            form.addRow("Разрешение растра", self.raster_dpi)
        form.addRow("Масштаб", self.scale)
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Импорт"))
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Импортировать"))

    def options(self) -> ImportOptions:
        return ImportOptions(svg_dpi=self.dpi.currentData(), scale=self.scale.value() / 100.0,
                             raster_dpi=float(self.raster_dpi.value()) or None,
                             dxf_units_mm=self.dxf_units.currentData())


# --------------------------------------------------------------------------- текст

def text_to_contours(text: str, font: QFont, height_mm: float, x: float, y: float) -> list[Contour]:
    """Текст системным шрифтом -> замкнутые контуры (кривые). height_mm — кегль (em)."""
    f = QFont(font)
    f.setPixelSize(100)
    path = QPainterPath()
    lines = text.split("\n")
    line_h = 100 * 1.25
    for i, line in enumerate(lines):
        path.addText(0, 100 + i * line_h, f, line)
    k = height_mm / 100.0
    out = []
    for poly in path.toSubpathPolygons():
        pts = np.array([(p.x() * k + x, p.y() * k + y) for p in poly])
        if len(pts) >= 3:
            out.append(Contour(pts, True))
    return out


class TextDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Текст")
        self.text = QLineEdit("N40")
        self.font = QFontComboBox()
        self.size = spin(1, 500, 1, " мм", 1)
        self.size.setValue(20)
        self.bold = QCheckBox("Жирный")
        self.italic = QCheckBox("Курсив")
        form = QFormLayout()
        form.addRow("Текст", self.text)
        form.addRow("Шрифт", self.font)
        form.addRow("Кегль", self.size)
        row = QHBoxLayout()
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        form.addRow("", row)
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Текст в кривые"))
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Создать"))

    def contours(self, x: float, y: float) -> list[Contour]:
        f = self.font.currentFont()
        f.setBold(self.bold.isChecked())
        f.setItalic(self.italic.isChecked())
        return text_to_contours(self.text.text(), f, self.size.value(), x, y)


# --------------------------------------------------------------------------- массивы

class ArrayDialog(QDialog):
    def __init__(self, parent, bbox_w: float, bbox_h: float, center):
        super().__init__(parent)
        self.setWindowTitle("Массив")
        self.tabs = QTabWidget()
        lin = QWidget()
        f = QFormLayout(lin)
        self.nx, self.ny = QSpinBox(), QSpinBox()
        for s in (self.nx, self.ny):
            s.setRange(1, 500)
        self.nx.setValue(3)
        self.ny.setValue(1)
        self.gap_x, self.gap_y = spin(-1000, 1000), spin(-1000, 1000)
        self.gap_x.setValue(5)
        self.gap_y.setValue(5)
        f.addRow("Копий по X", self.nx)
        f.addRow("Копий по Y", self.ny)
        f.addRow("Зазор по X", self.gap_x)
        f.addRow("Зазор по Y", self.gap_y)
        self.bw, self.bh = bbox_w, bbox_h
        circ = QWidget()
        g = QFormLayout(circ)
        self.count = QSpinBox()
        self.count.setRange(2, 360)
        self.count.setValue(6)
        self.cx, self.cy = spin(), spin()
        self.cx.setValue(center[0])
        self.cy.setValue(center[1] + max(bbox_h, 10) * 1.5)
        self.total = spin(1, 360, 1, "°")
        self.total.setValue(360)
        self.rotate = QCheckBox("Поворачивать копии")
        self.rotate.setChecked(True)
        g.addRow("Количество", self.count)
        g.addRow("Центр X", self.cx)
        g.addRow("Центр Y", self.cy)
        g.addRow("Общий угол", self.total)
        g.addRow("", self.rotate)
        self.tabs.addTab(lin, "ЛИНЕЙНЫЙ")
        self.tabs.addTab(circ, "КРУГОВОЙ")
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Массив"))
        lay.addWidget(self.tabs)
        lay.addWidget(_buttons(self, "Создать"))

    @property
    def circular(self) -> bool:
        return self.tabs.currentIndex() == 1

    def linear_steps(self) -> tuple[float, float]:
        return self.bw + self.gap_x.value(), self.bh + self.gap_y.value()


class OffsetDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Смещение контура")
        self.delta = spin(-100, 100, 2)
        self.delta.setValue(1)
        self.join = QComboBox()
        self.join.addItem("Скруглённые углы", "round")
        self.join.addItem("Острые углы", "miter")
        self.join.addItem("Срезанные углы", "square")
        self.keep = QCheckBox("Сохранить исходный контур")
        self.keep.setChecked(True)
        form = QFormLayout()
        form.addRow("Смещение (+ наружу)", self.delta)
        form.addRow("Углы", self.join)
        form.addRow("", self.keep)
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Эквидистанта"))
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Применить"))


# --------------------------------------------------------------------------- нестинг

class NestDialog(QDialog):
    def __init__(self, parent, settings, parts: list, has_region: bool, has_forbidden: bool):
        """parts — список (item, name)."""
        super().__init__(parent)
        self.setWindowTitle("Нестинг")
        self.setMinimumWidth(520)
        self.parts = parts
        self.worker = None
        self.result = None

        self.sheet_w, self.sheet_h = spin(1, 5000), spin(1, 5000)
        self.sheet_w.setValue(settings.bed_width)
        self.sheet_h.setValue(settings.bed_height)
        self.gap = spin(0, 100)
        self.gap.setValue(2)
        self.margin = spin(0, 100)
        self.margin.setValue(3)
        self.use_region = QCheckBox("Раскладывать только в «Области раскроя» (по фото)")
        self.use_region.setChecked(has_region)
        self.use_region.setEnabled(has_region)
        self.use_forbidden = QCheckBox("Учитывать запретные зоны")
        self.use_forbidden.setChecked(has_forbidden)
        self.use_forbidden.setEnabled(has_forbidden)
        self.holes = QCheckBox("Размещать мелкие детали в отверстиях крупных")
        self.holes.setChecked(True)

        self.rot_fixed = QRadioButton("Углы:")
        self.rot_fixed.setChecked(True)
        self.angle_boxes = {a: QCheckBox(f"{a}°") for a in (0, 90, 180, 270)}
        for a, cb in self.angle_boxes.items():
            cb.setChecked(True)
        self.rot_step = QRadioButton("Произвольный шаг:")
        self.step = spin(1, 180, 0, "°", 5)
        self.step.setValue(15)

        sheet = QGroupBox("Лист")
        f = QFormLayout(sheet)
        row = QHBoxLayout()
        row.addWidget(self.sheet_w)
        row.addWidget(QLabel("×"))
        row.addWidget(self.sheet_h)
        f.addRow("Размер", row)
        f.addRow("Зазор между деталями", self.gap)
        f.addRow("Отступ от края", self.margin)
        f.addRow(self.use_region)
        f.addRow(self.use_forbidden)
        f.addRow(self.holes)

        rot = QGroupBox("Поворот деталей")
        rl = QVBoxLayout(rot)
        r1 = QHBoxLayout()
        r1.addWidget(self.rot_fixed)
        for cb in self.angle_boxes.values():
            r1.addWidget(cb)
        r1.addStretch(1)
        r2 = QHBoxLayout()
        r2.addWidget(self.rot_step)
        r2.addWidget(self.step)
        r2.addStretch(1)
        rl.addLayout(r1)
        rl.addLayout(r2)

        self.table = QTableWidget(len(parts), 2)
        self.table.setHorizontalHeaderLabels(["Деталь", "Копий"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.copies: list[QSpinBox] = []
        for i, (_item, name) in enumerate(parts):
            cell = QTableWidgetItem(name)
            cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(i, 0, cell)
            sb = QSpinBox()
            sb.setRange(1, 1000)
            self.table.setCellWidget(i, 1, sb)
            self.copies.append(sb)
        self.table.setMaximumHeight(160)

        self.progress = QProgressBar()
        self.result_label = QLabel("")
        self.result_label.setObjectName("Big")
        self.result_info = QLabel("")
        self.result_info.setWordWrap(True)
        self.btn_run = QPushButton("Рассчитать")
        self.btn_run.setObjectName("Primary")
        self.btn_stop = QPushButton("Остановить")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setEnabled(False)
        self.btn_apply = QPushButton("Применить раскладку")
        self.btn_apply.setEnabled(False)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(_title("Нестинг"))
        lay.addWidget(sheet)
        lay.addWidget(rot)
        lay.addWidget(self.table)
        lay.addWidget(self.progress)
        res = QHBoxLayout()
        res.addWidget(self.result_label)
        res.addWidget(self.result_info, 1)
        lay.addLayout(res)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_stop)
        btns.addStretch(1)
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

    def angles(self) -> list[float]:
        from ..core.nesting import angles_from_step
        if self.rot_step.isChecked():
            return angles_from_step(self.step.value())
        return [float(a) for a, cb in self.angle_boxes.items() if cb.isChecked()] or [0.0]

    def show_result(self, result) -> None:
        self.result = result
        self.result_label.setText(f"K = {result.utilization:.1f} %")
        msg = f"Размещено {len(result.placements)} шт."
        if result.unplaced:
            msg += f", не поместилось: {len(result.unplaced)}"
        msg += f"\nПлощадь деталей {result.parts_area:.0f} мм² из {result.sheet_area:.0f} мм²"
        self.result_info.setText(msg)
        self.btn_apply.setEnabled(bool(result.placements))

    def closeEvent(self, e) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        super().closeEvent(e)

    def reject(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        super().reject()


# --------------------------------------------------------------------------- настройки

class SettingsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.s = settings
        tabs = QTabWidget()

        # Станок
        w1 = QWidget()
        f1 = QFormLayout(w1)
        self.bed_w, self.bed_h = spin(10, 2000), spin(10, 2000)
        self.bed_w.setValue(settings.bed_width)
        self.bed_h.setValue(settings.bed_height)
        self.board = QComboBox()
        for b in ("M2", "M1", "M", "B2", "B1", "B", "A"):
            self.board.addItem(b, b)
        self.board.setCurrentIndex(max(0, self.board.findData(settings.board)))
        self.cut, self.engr, self.rast = spin(1, 500, 1, " мм/с"), spin(1, 500, 1, " мм/с"), spin(1, 500, 1, " мм/с")
        self.cut.setValue(settings.cut_speed)
        self.engr.setValue(settings.engrave_speed)
        self.rast.setValue(settings.raster_speed)
        self.rstep = spin(0.0254, 1, 4, " мм", 0.0254)
        self.rstep.setValue(settings.raster_step)
        self.home = QCheckBox("Возвращать головку домой после задания")
        self.home.setChecked(settings.rapid_return_home)
        f1.addRow("Рабочее поле, ширина", self.bed_w)
        f1.addRow("Рабочее поле, высота", self.bed_h)
        f1.addRow("Плата контроллера", self.board)
        f1.addRow("Скорость резки", self.cut)
        f1.addRow("Скорость гравировки контура", self.engr)
        f1.addRow("Скорость растра", self.rast)
        f1.addRow("Шаг растра", self.rstep)
        f1.addRow("", self.home)

        # Рабочая область
        w2 = QWidget()
        f2 = QFormLayout(w2)
        self.grid = QComboBox()
        for v in (1, 5, 10):
            self.grid.addItem(f"{v} мм", float(v))
        self.grid.setCurrentIndex(max(0, self.grid.findData(float(settings.grid_step))))
        self.snap_grid = QCheckBox("Привязка к сетке")
        self.snap_grid.setChecked(settings.snap_grid)
        self.snap_nodes = QCheckBox("Привязка к узлам объектов")
        self.snap_nodes.setChecked(settings.snap_nodes)
        self.svg_dpi = QComboBox()
        for v in (96, 90, 72):
            self.svg_dpi.addItem(f"{v} dpi", float(v))
        self.svg_dpi.setCurrentIndex(max(0, self.svg_dpi.findData(float(settings.svg_dpi))))
        f2.addRow("Шаг сетки", self.grid)
        f2.addRow("", self.snap_grid)
        f2.addRow("", self.snap_nodes)
        f2.addRow("DPI для SVG по умолчанию", self.svg_dpi)

        # Камера
        w3 = QWidget()
        f3 = QFormLayout(w3)
        self.cam_usb = QRadioButton("USB (UVC)")
        self.cam_url = QRadioButton("Сетевой поток")
        (self.cam_url if settings.camera_source == "url" else self.cam_usb).setChecked(True)
        self.cam_index = QSpinBox()
        self.cam_index.setRange(0, 16)
        self.cam_index.setValue(settings.camera_index)
        self.url = QLineEdit(settings.camera_url)
        self.url.setPlaceholderText("rtsp://…  http://…/flv  http://…/mjpeg")
        self.ppm = spin(0.5, 10, 1, " px/мм", 0.5)
        self.ppm.setValue(settings.camera_px_per_mm)
        f3.addRow(self.cam_usb)
        f3.addRow("Индекс устройства", self.cam_index)
        f3.addRow(self.cam_url)
        f3.addRow("URL", self.url)
        f3.addRow("Разрешение подложки", self.ppm)
        hint = QLabel("Anycubic Kobra 3: по USB камера определяется как UVC; по сети — поток с IP принтера "
                      "(адрес зависит от прошивки, например http://<IP>:18088/flv).")
        hint.setWordWrap(True)
        hint.setObjectName("Caption")
        f3.addRow(hint)

        # Прочее
        w4 = QWidget()
        f4 = QFormLayout(w4)
        self.updates = QCheckBox("Проверять обновления на GitHub при запуске")
        self.updates.setChecked(settings.check_updates)
        f4.addRow(self.updates)

        tabs.addTab(w1, "СТАНОК")
        tabs.addTab(w2, "ПОЛЕ")
        tabs.addTab(w3, "КАМЕРА")
        tabs.addTab(w4, "ПРОЧЕЕ")
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Настройки"))
        lay.addWidget(tabs)
        lay.addWidget(_buttons(self, "Сохранить"))

    def apply(self) -> None:
        s = self.s
        s.bed_width, s.bed_height = self.bed_w.value(), self.bed_h.value()
        s.board = self.board.currentData()
        s.cut_speed, s.engrave_speed, s.raster_speed = self.cut.value(), self.engr.value(), self.rast.value()
        s.raster_step = self.rstep.value()
        s.rapid_return_home = self.home.isChecked()
        s.grid_step = self.grid.currentData()
        s.snap_grid, s.snap_nodes = self.snap_grid.isChecked(), self.snap_nodes.isChecked()
        s.svg_dpi = self.svg_dpi.currentData()
        s.camera_source = "url" if self.cam_url.isChecked() else "usb"
        s.camera_index = self.cam_index.value()
        s.camera_url = self.url.text().strip()
        s.camera_px_per_mm = self.ppm.value()
        s.check_updates = self.updates.isChecked()
        s.save()


def ask_update(parent, info) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("Обновление")
    box.setText(f"Доступна новая версия N40: {info.version}")
    box.setInformativeText((info.notes[:600] + "…") if len(info.notes) > 600 else info.notes)
    yes = box.addButton("Скачать и установить", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes
