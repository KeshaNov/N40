"""Боковые панели: объекты, свойства, лазер, камера."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from .items import MODE_NAMES, N40Item, RasterItem, RegionItem, items_bbox


def spin(lo=-10000.0, hi=10000.0, dec=2, suffix=" мм", step=1.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    return s


def caption(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Caption")
    return lbl


class ObjectsPanel(QWidget):
    """Список объектов с миниатюрами; выделение синхронизировано со сценой."""

    visibility_changed = Signal()

    def __init__(self, scene):
        super().__init__()
        self.setObjectName("Panel")
        self.scene = scene
        self.list = QListWidget()
        self.list.setIconSize(QSize(40, 40))
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._to_scene)
        self.list.itemChanged.connect(self._renamed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(caption("Объекты проекта"))
        lay.addWidget(self.list)
        self._syncing = False

    def refresh(self) -> None:
        self._syncing = True
        self.list.clear()
        for it in reversed(self.scene.n40_items()):
            mode = "Область" if isinstance(it, RegionItem) else MODE_NAMES.get(it.mode, it.mode)
            w, h = it.size
            row = QListWidgetItem(QIcon(it.thumbnail()), f"{it.name}\n{mode} · {w:.1f}×{h:.1f} мм")
            row.setData(Qt.ItemDataRole.UserRole, it)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked if it.isVisible() else Qt.CheckState.Unchecked)
            self.list.addItem(row)
            row.setSelected(it.isSelected())
        self._syncing = False

    def sync_selection(self) -> None:
        self._syncing = True
        for i in range(self.list.count()):
            row = self.list.item(i)
            row.setSelected(row.data(Qt.ItemDataRole.UserRole).isSelected())
        self._syncing = False

    def _to_scene(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.scene.clearSelection()
        for row in self.list.selectedItems():
            row.data(Qt.ItemDataRole.UserRole).setSelected(True)
        self._syncing = False

    def _renamed(self, row: QListWidgetItem) -> None:
        if self._syncing:
            return
        it: N40Item = row.data(Qt.ItemDataRole.UserRole)
        it.name = row.text().split("\n")[0]
        visible = row.checkState() == Qt.CheckState.Checked
        if visible != it.isVisible():
            it.setVisible(visible)
            self.visibility_changed.emit()


class PropertiesPanel(QWidget):
    """Положение, размер, угол и параметры обработки выделенных объектов."""

    edited = Signal()  # после изменения (для undo и обновления списка)
    before_edit = Signal()

    def __init__(self, scene, settings):
        super().__init__()
        self.setObjectName("Panel")
        self.scene = scene
        self.settings = settings
        self.items: list[N40Item] = []
        self._loading = False

        self.x, self.y = spin(), spin()
        self.w, self.h = spin(0.01), spin(0.01)
        self.angle = spin(-360, 360, 2, "°", 1)
        self.lock = QCheckBox("Сохранять пропорции")
        self.lock.setChecked(True)
        geo = QGroupBox("Геометрия")
        g = QGridLayout(geo)
        g.addWidget(caption("X"), 0, 0); g.addWidget(self.x, 1, 0)
        g.addWidget(caption("Y"), 0, 1); g.addWidget(self.y, 1, 1)
        g.addWidget(caption("Ширина"), 2, 0); g.addWidget(self.w, 3, 0)
        g.addWidget(caption("Высота"), 2, 1); g.addWidget(self.h, 3, 1)
        g.addWidget(caption("Угол"), 4, 0); g.addWidget(self.angle, 5, 0)
        g.addWidget(self.lock, 5, 1)

        self.mode = QComboBox()
        for key, title in MODE_NAMES.items():
            self.mode.addItem(title, key)
        self.speed = spin(0, 500, 1, " мм/с", 1)
        self.speed.setSpecialValueText("по умолчанию")
        self.passes = QSpinBox()
        self.passes.setRange(1, 50)
        self.passes.setKeyboardTracking(False)
        laser = QGroupBox("Обработка")
        f = QFormLayout(laser)
        f.addRow("Режим", self.mode)
        f.addRow("Скорость", self.speed)
        f.addRow("Проходы", self.passes)

        self.raster_box = QGroupBox("Растр")
        r = QFormLayout(self.raster_box)
        self.dither = QCheckBox("Дизеринг (Флойд–Стейнберг)")
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 254)
        self.threshold.setKeyboardTracking(False)
        self.invert = QCheckBox("Инвертировать")
        r.addRow(self.dither)
        r.addRow("Порог", self.threshold)
        r.addRow(self.invert)

        self.info = QLabel("Ничего не выделено")
        self.info.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 10)
        lay.addWidget(self.info)
        lay.addWidget(geo)
        lay.addWidget(laser)
        lay.addWidget(self.raster_box)
        lay.addStretch(1)

        for s in (self.x, self.y):
            s.valueChanged.connect(self._apply_pos)
        self.w.valueChanged.connect(lambda: self._apply_size("w"))
        self.h.valueChanged.connect(lambda: self._apply_size("h"))
        self.angle.valueChanged.connect(self._apply_angle)
        self.mode.currentIndexChanged.connect(self._apply_laser)
        self.speed.valueChanged.connect(self._apply_laser)
        self.passes.valueChanged.connect(self._apply_laser)
        self.dither.toggled.connect(self._apply_raster)
        self.threshold.valueChanged.connect(self._apply_raster)
        self.invert.toggled.connect(self._apply_raster)
        self.set_items([])

    def set_items(self, items: list[N40Item]) -> None:
        self.items = items
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        items = self.items
        enabled = bool(items)
        for wdg in (self.x, self.y, self.w, self.h, self.angle, self.mode, self.speed, self.passes):
            wdg.setEnabled(enabled)
        single = len(items) == 1
        self.angle.setEnabled(single)
        if not items:
            self.info.setText("Ничего не выделено")
            self.raster_box.setVisible(False)
            self._loading = False
            return
        r = items_bbox(items)
        self.x.setValue(r.left())
        self.y.setValue(r.top())
        if single:
            w, h = items[0].size
            self.info.setText(items[0].name)
            self.angle.setValue(items[0].rotation())
        else:
            w, h = r.width(), r.height()
            self.info.setText(f"Выделено объектов: {len(items)}")
        self.w.setValue(w)
        self.h.setValue(h)
        first = items[0]
        self.mode.setCurrentIndex(max(0, self.mode.findData(first.mode)))
        self.mode.setEnabled(not isinstance(first, (RasterItem, RegionItem)))
        self.speed.setValue(first.speed or 0)
        self.passes.setValue(first.passes)
        rasters = [it for it in items if isinstance(it, RasterItem)]
        self.raster_box.setVisible(bool(rasters))
        if rasters:
            self.dither.setChecked(rasters[0].dither)
            self.threshold.setValue(rasters[0].threshold)
            self.invert.setChecked(rasters[0].invert)
        self._loading = False

    def _begin(self) -> bool:
        if self._loading or not self.items:
            return False
        self.before_edit.emit()
        return True

    def _done(self) -> None:
        self.refresh()
        self.edited.emit()

    def _apply_pos(self) -> None:
        if not self._begin():
            return
        r = items_bbox(self.items)
        dx, dy = self.x.value() - r.left(), self.y.value() - r.top()
        for it in self.items:
            it.moveBy(dx, dy)
        self._done()

    def _apply_size(self, which: str) -> None:
        if not self._begin():
            return
        if len(self.items) == 1:
            it = self.items[0]
            w0, h0 = it.size
            w, h = self.w.value(), self.h.value()
            if self.lock.isChecked():
                k = w / w0 if which == "w" and w0 else (h / h0 if h0 else 1)
                w, h = w0 * k, h0 * k
            tl = it.world_rect().topLeft()
            it.set_size(w, h)
            d = tl - it.world_rect().topLeft()
            it.moveBy(d.x(), d.y())
        else:
            r = items_bbox(self.items)
            kx = self.w.value() / r.width() if r.width() else 1
            ky = self.h.value() / r.height() if r.height() else 1
            if self.lock.isChecked():
                kx = ky = kx if which == "w" else ky
            for it in self.items:
                if abs(it.rotation() % 90) > 1e-6 and abs(kx - ky) > 1e-9:
                    continue  # неравномерное масштабирование повёрнутых объектов не поддерживается
                w, h = it.size
                swap = round(it.rotation() / 90) % 2 == 1
                it.set_size(w * (ky if swap else kx), h * (kx if swap else ky))
                c = it.pos()
                it.setPos(r.left() + (c.x() - r.left()) * kx, r.top() + (c.y() - r.top()) * ky)
        self._done()

    def _apply_angle(self) -> None:
        if not self._begin() or len(self.items) != 1:
            return
        self.items[0].setRotation(self.angle.value())
        self._done()

    def _apply_laser(self) -> None:
        if not self._begin():
            return
        mode = self.mode.currentData()
        for it in self.items:
            if not isinstance(it, (RasterItem, RegionItem)):
                it.mode = mode
            it.speed = self.speed.value() or None
            it.passes = self.passes.value()
            it.update()
        self._done()

    def _apply_raster(self) -> None:
        if not self._begin():
            return
        for it in self.items:
            if isinstance(it, RasterItem):
                it.dither = self.dither.isChecked()
                it.threshold = self.threshold.value()
                it.invert = self.invert.isChecked()
                it.update()
        self._done()


class LaserPanel(QWidget):
    """Управление станком: подключение, перемещение, задание."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.state = QLabel("Не подключён")
        self.state.setObjectName("Big")
        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.setObjectName("Primary")
        self.btn_home = QPushButton("Домой")
        self.btn_unlock = QPushButton("Разблокировать")
        self.jog_step = QComboBox()
        for v in ("0.1", "1", "5", "10", "50"):
            self.jog_step.addItem(f"{v} мм", float(v))
        self.jog_step.setCurrentIndex(2)
        self.jog = {}
        grid = QGridLayout()
        for key, (r, c, text) in {"up": (0, 1, "↑"), "left": (1, 0, "←"), "right": (1, 2, "→"),
                                  "down": (2, 1, "↓")}.items():
            b = QPushButton(text)
            b.setFixedSize(44, 36)
            self.jog[key] = b
            grid.addWidget(b, r, c)
        grid.addWidget(self.jog_step, 1, 1)

        # скорости по умолчанию для векторных режимов (объект может переопределить в «Свойствах»)
        self.engrave_speed = spin(1, 500, 1, " мм/с", 1)
        self.cut_speed = spin(1, 500, 1, " мм/с", 1)
        self.engrave_speed.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.cut_speed.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)

        self.btn_frame = QPushButton("Рамка")
        self.btn_frame.setToolTip("Обвести габарит задания без лазера")
        self.btn_start = QPushButton("Старт")
        self.btn_start.setObjectName("Primary")
        self.btn_pause = QPushButton("Пауза")
        self.btn_pause.setCheckable(True)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setObjectName("Danger")
        self.btn_egv = QPushButton("Экспорт EGV…")
        self.only_selected = QCheckBox("Только выделенные объекты")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.estimate = QLabel("")
        self.estimate.setObjectName("Caption")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(caption("Станок"))
        lay.addWidget(self.state)
        row = QHBoxLayout()
        row.addWidget(self.btn_connect)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.btn_home)
        row.addWidget(self.btn_unlock)
        lay.addLayout(row)
        jog_box = QGroupBox("Перемещение")
        jl = QVBoxLayout(jog_box)
        jl.addLayout(grid)
        lay.addWidget(jog_box)
        speeds = QGroupBox("Скорость")
        sf = QFormLayout(speeds)
        sf.addRow("Гравировка контура", self.engrave_speed)
        sf.addRow("Резка", self.cut_speed)
        lay.addWidget(speeds)
        job = QGroupBox("Задание")
        jv = QVBoxLayout(job)
        jv.addWidget(self.only_selected)
        r1 = QHBoxLayout()
        r1.addWidget(self.btn_frame)
        r1.addWidget(self.btn_egv)
        jv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(self.btn_start)
        r2.addWidget(self.btn_pause)
        r2.addWidget(self.btn_stop)
        jv.addLayout(r2)
        jv.addWidget(self.progress)
        jv.addWidget(self.estimate)
        lay.addWidget(job)
        note = QLabel("Мощность K40 задаётся ручкой на панели станка. "
                      "Перед первым запуском проверьте задание на малой мощности.")
        note.setWordWrap(True)
        note.setObjectName("Caption")
        lay.addWidget(note)
        lay.addStretch(1)


class CameraPanel(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.setObjectName("Panel")
        self.btn_toggle = QPushButton("Включить камеру")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setObjectName("Primary")
        self.show_underlay = QCheckBox("Показывать подложку")
        self.show_underlay.setChecked(True)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(int(settings.camera_opacity * 100))
        self.btn_freeze = QPushButton("Заморозить кадр")
        self.btn_freeze.setCheckable(True)
        self.btn_calibrate = QPushButton("Мастер калибровки…")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Caption")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(caption("Камера над полем"))
        lay.addWidget(self.btn_toggle)
        lay.addWidget(self.show_underlay)
        lay.addWidget(caption("Прозрачность"))
        lay.addWidget(self.opacity)
        lay.addWidget(self.btn_freeze)
        lay.addWidget(self.btn_calibrate)
        lay.addWidget(self.status)
        hint = QLabel("Раскрой по фото: включите камеру, обведите инструментом «Область раскроя» "
                      "свободный участок обрезка (или отметьте «Запретные зоны»), затем запустите нестинг.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
