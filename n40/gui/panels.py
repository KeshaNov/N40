"""Панели левой колонки (станок, скорость, перемещение, объекты, свойства, камера) и шапки."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QSizePolicy, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core.settings import CUSTOM_MODEL, LASER_MODELS
from .items import MODE_NAMES, N40Item, RasterItem, RegionItem, items_bbox
from .style import make_icon


def spin(lo=-10000.0, hi=10000.0, dec=2, suffix=" мм", step=1.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    # не NoButtons: с нашим QSS поле ввода у такого спинбокса схлопывается до 1 px и значение не видно
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
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
        self.list.setMinimumHeight(200)
        self.only_selected = QCheckBox("Обрабатывать лазером только выделенные")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.only_selected)
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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.info)
        lay.addWidget(geo)
        lay.addWidget(laser)
        lay.addWidget(self.raster_box)

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


class Section(QWidget):
    """Сворачиваемый раздел левой панели (по образцу Bambu Studio)."""

    def __init__(self, title: str, content: QWidget, expanded: bool = True):
        super().__init__()
        self.title = title.upper()
        self.header = QPushButton()
        self.header.setObjectName("SectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.toggled.connect(self._toggle)
        self.body = QWidget()
        self.body.setObjectName("Panel")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(12, 10, 12, 14)
        bl.addWidget(content)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self._toggle(expanded)

    def _toggle(self, on: bool) -> None:
        self.body.setVisible(on)
        self.header.setText(("▾  " if on else "▸  ") + self.title)


class MachinePanel(QWidget):
    """Модель лазера и подключение."""

    def __init__(self, settings):
        super().__init__()
        self.model = QComboBox()
        for name in LASER_MODELS:
            self.model.addItem(name)
        self.model.addItem(CUSTOM_MODEL)
        self.btn_settings = QPushButton()
        self.btn_settings.setIcon(make_icon("gear"))
        self.btn_settings.setObjectName("Square")
        self.btn_settings.setToolTip("Параметры станка: поле, плата, скорости")
        self.info = caption("")
        self.state = QLabel("Не подключён")
        self.state.setObjectName("State")
        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.setObjectName("Primary")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(self.model, 1)
        row.addWidget(self.btn_settings)
        lay.addLayout(row)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        row.addWidget(self.state, 1)
        row.addWidget(self.btn_connect)
        lay.addLayout(row)
        self.show_settings(settings)

    def show_settings(self, settings) -> None:
        self.model.blockSignals(True)
        idx = self.model.findText(settings.laser_model)
        self.model.setCurrentIndex(idx if idx >= 0 else self.model.count() - 1)
        self.model.blockSignals(False)
        self.info.setText(f"Поле {settings.bed_width:g} × {settings.bed_height:g} мм · плата {settings.board}")


class SpeedPanel(QWidget):
    """Скорости по умолчанию для режимов обработки (объект может переопределить в «Свойствах»)."""

    def __init__(self):
        super().__init__()
        self.engrave_speed = spin(1, 500, 1, " мм/с", 1)
        self.cut_speed = spin(1, 500, 1, " мм/с", 1)
        self.raster_speed = spin(1, 500, 1, " мм/с", 1)
        for s in (self.engrave_speed, self.cut_speed, self.raster_speed):
            s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Гравировка контура", self.engrave_speed)
        form.addRow("Резка", self.cut_speed)
        form.addRow("Растровая гравировка", self.raster_speed)
        note = QLabel("Мощность K40 задаётся ручкой на панели станка.")
        note.setObjectName("Caption")
        note.setWordWrap(True)
        form.addRow(note)


# направление (dx, dy) -> подпись; Y вниз, как у K40
JOG_DIRECTIONS = {(-1, -1): "↖", (0, -1): "↑", (1, -1): "↗",
                  (-1, 0): "←", (1, 0): "→",
                  (-1, 1): "↙", (0, 1): "↓", (1, 1): "↘"}
JOG_STEPS = (0.1, 1.0, 5.0, 10.0, 50.0)
JOG_BUTTON = 52  # все кнопки перемещения одного размера


class JogPanel(QWidget):
    """Перемещение головы: симметричная сетка 3×3 (в центре — «Домой») и шаг."""

    def __init__(self):
        super().__init__()
        self.jog: dict[tuple[int, int], QPushButton] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for (dx, dy), text in JOG_DIRECTIONS.items():
            b = QPushButton(text)
            b.setObjectName("Jog")
            b.setFixedSize(JOG_BUTTON, JOG_BUTTON)
            grid.addWidget(b, dy + 1, dx + 1)
            self.jog[(dx, dy)] = b
        self.btn_home = QPushButton("⌂")
        self.btn_home.setObjectName("JogHome")
        self.btn_home.setToolTip("Домой (левый верхний угол)")
        self.btn_home.setFixedSize(JOG_BUTTON, JOG_BUTTON)
        grid.addWidget(self.btn_home, 1, 1)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.step_group = QButtonGroup(self)
        self.step_group.setExclusive(True)
        for i, v in enumerate(JOG_STEPS):
            b = QPushButton(f"{v:g}")
            b.setObjectName("Step")
            b.setCheckable(True)
            b.setFixedSize(JOG_BUTTON, 30)
            self.step_group.addButton(b, i)
            steps.addWidget(b)
        self.step_group.button(JOG_STEPS.index(5.0)).setChecked(True)

        self.btn_unlock = QPushButton("Разблокировать каретку")
        self.btn_unlock.setToolTip("Отключить моторы, чтобы двигать голову рукой")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(self._centered(grid))
        lay.addWidget(caption("Шаг, мм"), 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(self._centered(steps))
        lay.addWidget(self.btn_unlock)

    @staticmethod
    def _centered(inner) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        row.addLayout(inner)
        row.addStretch(1)
        return row

    @property
    def step_mm(self) -> float:
        return JOG_STEPS[max(0, self.step_group.checkedId())]


class JobBar(QWidget):
    """Управление заданием в шапке окна (как кнопка «Печать» в Bambu Studio)."""

    def __init__(self):
        super().__init__()
        self.estimate = QLabel("")
        self.estimate.setObjectName("HeaderInfo")
        self.progress = QProgressBar()
        self.progress.setObjectName("HeaderProgress")
        self.progress.setFixedWidth(150)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        self.btn_frame = QPushButton("Рамка")
        self.btn_frame.setToolTip("Обвести габарит задания без лазера")
        self.btn_pause = QPushButton("Пауза")
        self.btn_pause.setCheckable(True)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setObjectName("HeaderStop")
        self.btn_start = QPushButton("Старт")
        self.btn_start.setObjectName("HeaderStart")
        for b in (self.btn_frame, self.btn_pause):
            b.setObjectName("HeaderButton")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.estimate)
        lay.addWidget(self.progress)
        lay.addSpacing(8)
        for b in (self.btn_frame, self.btn_pause, self.btn_stop, self.btn_start):
            b.setFixedHeight(30)
            lay.addWidget(b)


class CameraPanel(QWidget):
    def __init__(self, settings):
        super().__init__()
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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.btn_toggle)
        lay.addWidget(self.show_underlay)
        lay.addWidget(caption("Прозрачность"))
        lay.addWidget(self.opacity)
        row = QHBoxLayout()
        row.addWidget(self.btn_freeze)
        row.addWidget(self.btn_calibrate)
        lay.addLayout(row)
        lay.addWidget(self.status)
        hint = QLabel("Раскрой по фото: включите камеру, обведите инструментом «Область раскроя» "
                      "свободный участок обрезка (или отметьте «Запретные зоны»), затем нажмите «Авторасстановка».")
        hint.setWordWrap(True)
        hint.setObjectName("Caption")
        lay.addWidget(hint)
