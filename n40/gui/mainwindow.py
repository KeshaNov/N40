"""Главное окно N40."""

from __future__ import annotations

import copy
import json
import math
import subprocess
from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QImage, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QScrollArea, QSizePolicy,
                               QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from .. import APP_NAME, __version__
from ..core import geometry as geo
from ..core import planner, updater
from ..core.driver import lhymicro
from ..core.importers import ALL_EXT, RASTER_EXT, ImportError_, import_file
from ..core.nesting import NestParams, NestPart
from ..core.planner import mm_to_steps
from ..core.settings import CUSTOM_MODEL, LASER_MODELS, Settings
from . import style
from .calibration import CalibrationWizard
from .dialogs import (PRIMITIVE_FIELDS, ArrayDialog, ImportDialog, NestDialog, OffsetDialog, PrimitiveDialog,
                      SettingsDialog, TextDialog, ask_update)
from .items import (N40Item, RasterItem, RegionItem, VectorItem, clone_from_dict, clone_item, item_from_dict,
                    items_bbox, qimage_to_pil)
from .jobbuilder import build_operations
from .panels import (CameraPanel, JobBar, JogPanel, MachinePanel, ObjectsPanel, PropertiesPanel, Section,
                     SpeedPanel, spin)
from .workers import CameraWorker, LaserWorker, NestWorker, UpdateWorker
from .workspace import WorkArea, WorkScene

FILE_FILTER = ("Все поддерживаемые (*.svg *.dxf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.pdf *.ai);;"
               "SVG (*.svg);;DXF (*.dxf);;Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;"
               "PDF / Illustrator (*.pdf *.ai)")
PROJECT_FILTER = "Проект N40 (*.n40)"
CLIPBOARD_MIME = "application/x-n40-items"  # объекты N40 в системном буфере обмена (JSON)


class DownloadWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, info):
        super().__init__()
        self.info = info

    def run(self) -> None:
        try:
            self.finished_ok.emit(str(updater.download(self.info)))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.setWindowTitle(f"{APP_NAME}")
        self.setWindowIcon(style.app_icon())
        self.setAcceptDrops(True)
        self.project_path: Path | None = None
        self.undo_stack: list[list[dict]] = []
        self.redo_stack: list[list[dict]] = []
        self._drag_snapshot = None
        self._drag_positions = None
        self.camera: CameraWorker | None = None
        self.camera_frozen = False
        self.nest_dialog = None

        self.scene = WorkScene(self.settings)
        self.area = WorkArea(self.scene, self.settings)
        self.view = self.area.view

        # Раскладка как в Bambu Studio: шапка с заданием, панель функций сверху,
        # слева колонка настроек (станок → скорость → перемещение → объекты → свойства → камера)
        self.machine = MachinePanel(self.settings)
        self.speeds = SpeedPanel()
        self.jog = JogPanel()
        self.objects = ObjectsPanel(self.scene)
        self.props = PropertiesPanel(self.scene, self.settings)
        self.camera_panel = CameraPanel(self.settings)
        self.job = JobBar()

        self._build_actions()
        self._build_menus()
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._build_header())
        cl.addWidget(self._build_toolbar())
        splitter = QSplitter()
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self.area)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setSizes([350, 1050])
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {style.INK}; }}")
        cl.addWidget(splitter, 1)
        self.setCentralWidget(center)
        self._build_status()

        self.laser = LaserWorker(self.settings.board)
        self.laser.status.connect(self._laser_status)
        self.laser.connected_changed.connect(self._laser_connected)
        self.laser.progress.connect(lambda a, b: self.job.progress.setValue(int(a / max(b, 1) * 100)))
        self.laser.job_finished.connect(self._job_finished)
        self.laser.start()
        self._wire_panels()

        self.scene.selectionChanged.connect(self._selection_changed)
        self.view.item_created.connect(self._item_created)
        self.view.text_requested.connect(self._create_text)
        self.view.size_requested.connect(self._create_by_size)
        self.view.cursor_moved.connect(self._cursor_moved)
        self.view.view_changed.connect(self._update_zoom_label)
        self.view.tool_finished.connect(lambda: self.tool_actions["select"].trigger())
        self.view.viewport().installEventFilter(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self._last_paste_at: QPointF | None = None
        self._paste_serial = 0

        qs = QSettings("N40", "N40")
        geom = qs.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.resize(1400, 860)
        QTimer.singleShot(0, self.view.zoom_fit)
        if self.settings.check_updates:
            QTimer.singleShot(1500, self.check_updates)

    # ================================================================== построение UI
    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Header")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # селектор по имени, иначе фон шапки перекроет стили кнопок задания
        w.setStyleSheet(f"QWidget#Header {{ background: {style.INK}; }}")
        w.setFixedHeight(48)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 0, 10, 0)
        mark = QLabel("N40")
        mark.setStyleSheet(f"color:{style.PAPER}; font-size:20pt; font-weight:900; letter-spacing:-1px;")
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{style.RED}; font-size:14pt;")
        sub = QLabel("ЛАЗЕРНЫЙ ГРАВЕР")
        sub.setStyleSheet(f"color:{style.GREY}; letter-spacing:2px; font-size:8pt; font-weight:600;")
        lay.addWidget(mark)
        lay.addWidget(dot)
        lay.addSpacing(12)
        lay.addWidget(sub)
        lay.addStretch(1)
        self.header_job = QLabel("")
        self.header_job.setStyleSheet(f"color:{style.YELLOW}; font-weight:700; letter-spacing:1px;")
        lay.addWidget(self.header_job)
        lay.addSpacing(12)
        lay.addWidget(self.job)
        return w

    def _build_sidebar(self) -> QScrollArea:
        """Левая колонка настроек в порядке Bambu Studio: сверху станок, ниже объекты."""
        body = QWidget()
        body.setObjectName("SidebarBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sections = {
            "machine": Section("Станок", self.machine),
            "speed": Section("Скорость", self.speeds),
            "jog": Section("Перемещение", self.jog),
            "objects": Section("Объекты", self.objects),
            "props": Section("Свойства объекта", self.props),
            "camera": Section("Камера", self.camera_panel, expanded=False),
        }
        for sec in self.sections.values():
            lay.addWidget(sec)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("Sidebar")
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(330)
        return scroll

    def _act(self, text, slot=None, shortcut=None, icon=None, checkable=False, tip=None) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(style.make_icon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if checkable:
            a.setCheckable(True)
        if slot:
            a.triggered.connect(slot)
        a.setToolTip(tip or text + (f"  ({QKeySequence(shortcut).toString()})" if shortcut else ""))
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        A = self._act
        self.a_new = A("Новый проект", self.new_project, "Ctrl+N")
        self.a_open = A("Открыть проект…", self.open_project, "Ctrl+O")
        self.a_save = A("Сохранить", self.save_project, "Ctrl+S")
        self.a_save_as = A("Сохранить как…", lambda: self.save_project(True), "Ctrl+Shift+S")
        self.a_import = A("Импорт файлов…", self.import_dialog, "Ctrl+I", "import")
        self.a_export_svg = A("Экспорт в SVG…", self.export_svg)
        self.a_egv = A("Экспорт EGV…", self.export_egv)
        self.a_settings = A("Настройки…", self.open_settings, "Ctrl+,")
        self.a_quit = A("Выход", self.close, "Ctrl+Q")

        self.a_undo = A("Отменить", self.undo, "Ctrl+Z", "undo")
        self.a_redo = A("Повторить", self.redo, "Ctrl+Y", "redo")
        # Ctrl+C / Ctrl+X / Ctrl+V и их альтернативы Windows (Ctrl+Insert, Shift+Delete, Shift+Insert)
        self.a_copy = A("Копировать", self.copy_selected, None, "copy", tip="Копировать  (Ctrl+C)")
        self.a_copy.setShortcuts(QKeySequence.StandardKey.Copy)
        self.a_cut = A("Вырезать", self.cut_selected, None, "cut", tip="Вырезать  (Ctrl+X)")
        self.a_cut.setShortcuts(QKeySequence.StandardKey.Cut)
        self.a_paste = A("Вставить", lambda: self.paste(), None, "paste", tip="Вставить  (Ctrl+V)")
        self.a_paste.setShortcuts(QKeySequence.StandardKey.Paste)
        self.a_dup = A("Дублировать", self.duplicate, "Ctrl+D", "duplicate")
        self.a_del = A("Удалить", self.delete_selected, "Delete", "delete")
        self.a_all = A("Выделить всё", self.select_all, "Ctrl+A")

        self.a_rot_cw = A("Повернуть на 90° по часовой", lambda: self.rotate_selected(90), "Ctrl+R", "rot_cw")
        self.a_rot_ccw = A("Повернуть на 90° против часовой", lambda: self.rotate_selected(-90), "Ctrl+Shift+R", "rot_ccw")
        self.a_flip_h = A("Отразить по горизонтали", lambda: self.flip_selected(True), "Ctrl+H", "flip_h")
        self.a_flip_v = A("Отразить по вертикали", lambda: self.flip_selected(False), "Ctrl+Shift+H", "flip_v")
        self.align_actions = {k: A(t, lambda _=False, k=k: self.align(k), None, "align_" + k)
                              for k, t in (("left", "Выровнять по левому краю"), ("hcenter", "Выровнять по центру"),
                                           ("right", "Выровнять по правому краю"), ("top", "Выровнять по верху"),
                                           ("vcenter", "Выровнять по середине"), ("bottom", "Выровнять по низу"))}
        self.a_dist_h = A("Распределить по горизонтали", lambda: self.distribute(True), None, "dist_h")
        self.a_dist_v = A("Распределить по вертикали", lambda: self.distribute(False), None, "dist_v")
        self.a_group = A("Группировать", self.group, "Ctrl+G", "group")
        self.a_ungroup = A("Разгруппировать", self.ungroup, "Ctrl+Shift+G", "ungroup")
        self.a_union = A("Объединение", lambda: self.boolean("union"), None, "union")
        self.a_diff = A("Вычитание (нижний − верхние)", lambda: self.boolean("difference"), None, "difference")
        self.a_inter = A("Пересечение", lambda: self.boolean("intersection"), None, "intersection")
        self.a_array = A("Массив…", self.array, "Ctrl+M", "array")
        self.a_offset = A("Смещение контура…", self.offset, None, "offset")
        self.a_arrange = A("Авторасстановка", self.auto_arrange, "Ctrl+Shift+N", "nest",
                           tip="Авторасстановка: разложить объекты на поле без наложений  (Ctrl+Shift+N)")
        self.a_nest = A("Нестинг с параметрами…", self.nest)

        self.a_fit = A("Показать всё поле", self.view.zoom_fit, "Ctrl+0")
        self.a_zoom_in = A("Увеличить", lambda: self.view.zoom_by(1.25), "Ctrl+=")
        self.a_zoom_out = A("Уменьшить", lambda: self.view.zoom_by(0.8), "Ctrl+-")
        self.a_snap_grid = A("Привязка к сетке", self._toggle_snaps, None, checkable=True)
        self.a_snap_grid.setChecked(self.settings.snap_grid)
        self.a_snap_nodes = A("Привязка к узлам", self._toggle_snaps, None, checkable=True)
        self.a_snap_nodes.setChecked(self.settings.snap_nodes)
        self.grid_group = QActionGroup(self)
        self.grid_actions = []
        for v in (1, 5, 10):
            a = A(f"Сетка {v} мм", lambda _=False, v=v: self._set_grid(v), None, checkable=True)
            a.setChecked(abs(self.settings.grid_step - v) < 1e-6)
            self.grid_group.addAction(a)
            self.grid_actions.append(a)

        self.a_updates = A("Проверить обновления", lambda: self.check_updates(manual=True))
        self.a_about = A("О программе", self.about)

        tools = [("select", "Выделение", "V"), ("rect", "Прямоугольник", "R"),
                 ("rrect", "Скруглённый прямоугольник", None), ("ellipse", "Эллипс", "E"),
                 ("circle", "Окружность (от центра)", "C"), ("line", "Линия", "L"),
                 ("polyline", "Многоугольник / ломаная (двойной щелчок — завершить)", "P"),
                 ("ngon", "Правильный N-угольник", "N"), ("text", "Текст", "T"),
                 ("region", "Область раскроя (по фото)", None), ("forbid", "Запретная зона", None)]
        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for key, title, sc in tools:
            a = A(title, lambda _=False, k=key: self._set_tool(k), sc, key if key != "forbid" else "forbid",
                  checkable=True)
            self.tool_group.addAction(a)
            self.tool_actions[key] = a
        self.tool_actions["select"].setChecked(True)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("Файл")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as, None, self.a_import, self.a_export_svg,
                  self.a_egv, None, self.a_settings, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("Правка")
        for a in (self.a_undo, self.a_redo, None, self.a_cut, self.a_copy, self.a_paste, None, self.a_dup,
                  self.a_del, None, self.a_all):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("Объект")
        for a in (self.a_rot_cw, self.a_rot_ccw, self.a_flip_h, self.a_flip_v, None):
            m.addSeparator() if a is None else m.addAction(a)
        al = m.addMenu("Выравнивание")
        for a in self.align_actions.values():
            al.addAction(a)
        al.addSeparator()
        al.addAction(self.a_dist_h)
        al.addAction(self.a_dist_v)
        m.addSeparator()
        m.addAction(self.a_group)
        m.addAction(self.a_ungroup)
        bm = m.addMenu("Булевы операции")
        for a in (self.a_union, self.a_diff, self.a_inter):
            bm.addAction(a)
        m.addAction(self.a_array)
        m.addAction(self.a_offset)
        m = mb.addMenu("Рисование")
        for a in self.tool_actions.values():
            m.addAction(a)
        m.addSeparator()
        m.addAction(self._act("Число сторон N-угольника…", self._ask_sides))
        m.addAction(self._act("Радиус скругления…", self._ask_radius))
        m = mb.addMenu("Раскрой")
        m.addAction(self.a_arrange)
        m.addAction(self.a_nest)
        m = mb.addMenu("Вид")
        for a in (self.a_fit, self.a_zoom_in, self.a_zoom_out, None, self.a_snap_grid, self.a_snap_nodes, None):
            m.addSeparator() if a is None else m.addAction(a)
        for a in self.grid_actions:
            m.addAction(a)
        m = mb.addMenu("Справка")
        m.addAction(self.a_updates)
        m.addAction(self.a_about)

    def _build_toolbar(self) -> QToolBar:
        """Панель функций над рабочим полем: импорт, примитивы, правка, преобразования, авторасстановка."""
        bar = QToolBar("Функции")
        bar.setObjectName("Actions")
        bar.setMovable(False)
        for a in (self.a_import, None, self.a_undo, self.a_redo, None):
            bar.addSeparator() if a is None else bar.addAction(a)
        for key, a in self.tool_actions.items():
            bar.addAction(a)
            if key in ("select", "text"):
                bar.addSeparator()
        bar.addSeparator()
        for a in (self.a_dup, self.a_del, None, self.a_rot_ccw, self.a_rot_cw, self.a_flip_h, self.a_flip_v):
            bar.addSeparator() if a is None else bar.addAction(a)
        bar.addWidget(self._dropdown("align_left", "Выравнивание и распределение",
                                     [*self.align_actions.values(), None, self.a_dist_h, self.a_dist_v]))
        bar.addSeparator()
        for a in (self.a_group, self.a_ungroup):
            bar.addAction(a)
        bar.addWidget(self._dropdown("union", "Булевы операции", [self.a_union, self.a_diff, self.a_inter]))
        for a in (self.a_array, self.a_offset):
            bar.addAction(a)
        bar.addSeparator()
        bar.addWidget(self._build_arrange_button())
        return bar

    def _dropdown(self, icon: str, tip: str, actions: list) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(style.make_icon(icon))
        btn.setToolTip(tip)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        for a in actions:
            menu.addSeparator() if a is None else menu.addAction(a)
        btn.setMenu(menu)
        return btn

    def _build_arrange_button(self) -> QToolButton:
        """Кнопка «Авторасстановка»: щелчок — разложить, стрелка — настройки."""
        btn = QToolButton()
        btn.setDefaultAction(self.a_arrange)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        box = QWidget()
        box.setObjectName("Panel")
        form = QFormLayout(box)
        form.setContentsMargins(12, 10, 12, 10)
        self.arrange_rotate = QCheckBox("Вращать объекты")
        self.arrange_rotate.setToolTip("Разрешить поворот на 90°, 180° и 270° для плотной раскладки")
        self.arrange_rotate.setChecked(self.settings.arrange_rotate)
        self.arrange_gap = spin(0, 100, 1, " мм", 0.5)
        self.arrange_gap.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.arrange_gap.setValue(self.settings.arrange_gap)
        form.addRow(self.arrange_rotate)
        form.addRow("Зазор между объектами", self.arrange_gap)

        def save():
            self.settings.arrange_rotate = self.arrange_rotate.isChecked()
            self.settings.arrange_gap = self.arrange_gap.value()
            self.settings.save()

        self.arrange_rotate.toggled.connect(save)
        self.arrange_gap.valueChanged.connect(save)
        menu = QMenu(btn)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(box)
        menu.addAction(wa)
        menu.addSeparator()
        menu.addAction(self.a_nest)
        btn.setMenu(menu)
        return btn

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.lbl_coords = QLabel("X —  Y —")
        self.lbl_zoom = QLabel("")
        self.lbl_laser = QLabel("Лазер: не подключён")
        self.lbl_k = QLabel("")
        sb.addWidget(self.lbl_coords)
        sb.addWidget(self.lbl_zoom)
        sb.addWidget(self.lbl_k)
        sb.addPermanentWidget(self.lbl_laser)

    def _wire_panels(self) -> None:
        self.machine.btn_connect.clicked.connect(self._toggle_connect)
        self.machine.btn_settings.clicked.connect(self.open_settings)
        self.machine.model.currentTextChanged.connect(self._model_chosen)
        self.jog.btn_home.clicked.connect(lambda: self.laser.submit("home"))
        self.jog.btn_unlock.clicked.connect(lambda: self.laser.submit("unlock"))
        for (dx, dy), btn in self.jog.jog.items():
            btn.clicked.connect(lambda _=False, dx=dx, dy=dy: self._jog(dx, dy))
        self.job.btn_frame.clicked.connect(self.frame_job)
        self.job.btn_start.clicked.connect(self.start_job)
        self.job.btn_pause.toggled.connect(self._pause)
        self.job.btn_stop.clicked.connect(self.stop_job)
        self._sync_speeds()
        for box in (self.speeds.engrave_speed, self.speeds.cut_speed, self.speeds.raster_speed):
            box.valueChanged.connect(self._speeds_edited)
        cp = self.camera_panel
        cp.btn_toggle.toggled.connect(self._toggle_camera)
        cp.show_underlay.toggled.connect(self._camera_visibility)
        cp.opacity.valueChanged.connect(self._camera_opacity)
        cp.btn_freeze.toggled.connect(lambda f: setattr(self, "camera_frozen", f))
        cp.btn_calibrate.clicked.connect(self.calibrate_camera)
        self.props.before_edit.connect(self.push_undo)
        self.props.edited.connect(self._after_edit)
        self.objects.visibility_changed.connect(self.scene.update)

    # ================================================================== состояние / undo
    def snapshot(self) -> list[dict]:
        return [it.to_dict() for it in self.scene.n40_items()]

    def restore(self, snap: list[dict]) -> None:
        for it in self.scene.n40_items():
            self.scene.removeItem(it)
        for d in snap:
            self._add_item(item_from_dict(d), select=False)
        self._after_edit()

    def push_undo(self) -> None:
        self.undo_stack.append(self.snapshot())
        if len(self.undo_stack) > 60:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.restore(self.undo_stack.pop())

    def redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.restore(self.redo_stack.pop())

    def eventFilter(self, obj, event) -> bool:
        # undo для перетаскивания мышью: снимок при нажатии, фиксация при отпускании если что-то сдвинулось
        et = event.type()
        if obj is self.view.viewport() and self.view.tool == "select":
            if et == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_snapshot = self.snapshot()
                self._drag_positions = None
                QTimer.singleShot(0, self._capture_drag_positions)
            elif et == event.Type.MouseButtonRelease and self._drag_snapshot is not None:
                moved = self._drag_positions is not None and any(
                    it.pos() != p for it, p in self._drag_positions)
                if moved:
                    self.undo_stack.append(self._drag_snapshot)
                    self.redo_stack.clear()
                    self._after_edit()
                self._drag_snapshot = None
        return super().eventFilter(obj, event)

    def _capture_drag_positions(self) -> None:
        self._drag_positions = [(it, QPointF(it.pos())) for it in self.scene.selected_n40()]

    def _after_edit(self) -> None:
        self.objects.refresh()
        self.props.set_items(self.scene.selected_n40())

    def _selection_changed(self) -> None:
        try:
            sel = self.scene.selected_n40()
        except RuntimeError:  # окно закрывается без closeEvent (выход из приложения)
            return
        self.props.set_items(sel)
        self.objects.sync_selection()

    # ================================================================== объекты
    def _add_item(self, item: N40Item, select: bool = True) -> N40Item:
        item.snap_callback = self.view.snap_item_pos
        self.scene.addItem(item)
        if select:
            item.setSelected(True)
        return item

    def _item_created(self, item: N40Item) -> None:
        self.push_undo()
        self.scene.clearSelection()
        self._add_item(item)
        self._after_edit()

    def _create_text(self, x: float, y: float) -> None:
        dlg = TextDialog(self)
        if dlg.exec():
            contours = dlg.contours(x, y)
            if contours:
                self._item_created(VectorItem(contours, f"Текст «{dlg.text.text()[:20]}»", "engrave"))

    def _set_tool(self, key: str) -> None:
        self.view.set_tool(key)
        self.tool_actions[key].setChecked(True)
        if key in PRIMITIVE_FIELDS:
            self.statusBar().showMessage("Растяните мышью или щёлкните по полю, чтобы задать размеры цифрами", 6000)

    def _create_by_size(self, tool: str, x: float, y: float) -> None:
        """Щелчок инструментом без протягивания: размеры примитива вводятся цифрами."""
        if tool not in PRIMITIVE_FIELDS:
            return
        overrides = {"rrect": {"r": self.view.rrect_radius}, "ngon": {"n": self.view.ngon_sides}}.get(tool)
        dlg = PrimitiveDialog(self, tool, x, y, self.settings.primitive_sizes.get(tool), overrides)
        if not dlg.exec():
            return
        values = dlg.values()
        self.settings.primitive_sizes[tool] = values
        self.settings.save()
        if tool == "rrect":
            self.view.rrect_radius = values["r"]
        elif tool == "ngon":
            self.view.ngon_sides = values["n"]
        self._item_created(VectorItem(dlg.contours(), dlg.name()))

    def _ask_sides(self) -> None:
        n, ok = QInputDialog.getInt(self, "N-угольник", "Число сторон:", self.view.ngon_sides, 3, 100)
        if ok:
            self.view.ngon_sides = n

    def _ask_radius(self) -> None:
        r, ok = QInputDialog.getDouble(self, "Скругление", "Радиус, мм:", self.view.rrect_radius, 0, 1000, 2)
        if ok:
            self.view.rrect_radius = r

    def selected(self) -> list[N40Item]:
        return self.scene.selected_n40()

    def select_all(self) -> None:
        for it in self.scene.n40_items():
            it.setSelected(True)

    def delete_selected(self) -> None:
        sel = self.selected()
        if not sel:
            return
        self.push_undo()
        for it in sel:
            self.scene.removeItem(it)
        self._after_edit()

    def duplicate(self) -> None:
        sel = self.selected()
        if not sel:
            return
        self.push_undo()
        self.scene.clearSelection()
        for it in sel:
            c = clone_item(it)
            c.moveBy(5, 5)
            self._add_item(c)
        self._after_edit()

    # ------------------------------------------------------------------ буфер обмена
    def copy_selected(self) -> None:
        sel = self.selected()
        if not sel:
            return
        data = [it.to_dict(embed=True) if isinstance(it, RasterItem) else it.to_dict() for it in sel]
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        QApplication.clipboard().setMimeData(mime)
        self._last_paste_at = None
        self._paste_serial = 0
        self.statusBar().showMessage(f"Скопировано объектов: {len(sel)}", 2000)

    def cut_selected(self) -> None:
        if self.selected():
            self.copy_selected()
            self.delete_selected()

    def can_paste(self) -> bool:
        mime = QApplication.clipboard().mimeData()
        return mime is not None and (mime.hasFormat(CLIPBOARD_MIME) or mime.hasImage())

    def _cursor_scene_pos(self) -> QPointF | None:
        vp = self.view.viewport()
        p = vp.mapFromGlobal(QCursor.pos())
        return self.view.mapToScene(p) if vp.rect().contains(p) else None

    def paste(self, at: QPointF | None = None) -> None:
        """Вставка объектов N40 или изображения из буфера обмена.

        Левый верхний угол вставки — под курсором (или в точке вызова контекстного меню);
        если курсор вне рабочего поля или вставка повторяется в той же точке — со сдвигом 5 мм.
        """
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        items: list[N40Item] = []
        if mime.hasFormat(CLIPBOARD_MIME):
            try:
                dicts = json.loads(bytes(mime.data(CLIPBOARD_MIME)).decode("utf-8"))
                items = [clone_from_dict(d) for d in dicts]
            except (ValueError, KeyError, TypeError):
                return
        elif mime.hasImage():
            q = QImage(mime.imageData())
            if q.isNull():
                return
            dpm = q.dotsPerMeterX() or 3780  # 3780 точек/м = 96 dpi
            w_mm, h_mm = q.width() / dpm * 1000, q.height() / dpm * 1000
            item = RasterItem(qimage_to_pil(q), w_mm, h_mm, "Изображение из буфера")
            item.setPos(w_mm / 2, h_mm / 2)
            items = [item]
        if not items:
            return

        target = at if at is not None else self._cursor_scene_pos()
        if target is not None:
            target = self.view.snap_item_pos(target, None)
        if target is not None and target != self._last_paste_at:
            self._paste_serial = 0
            self._last_paste_at = target
            r = items_bbox(items)
            delta = target - r.topLeft()
        else:
            self._paste_serial += 1
            delta = QPointF(5, 5) * self._paste_serial
            if target is not None:
                r = items_bbox(items)
                delta += target - r.topLeft()
        self.push_undo()
        self.scene.clearSelection()
        for it in items:
            it.moveBy(delta.x(), delta.y())
            self._add_item(it)
        self._after_edit()
        self.statusBar().showMessage(f"Вставлено объектов: {len(items)}", 2000)

    def _context_menu(self, pos) -> None:
        if self.view.tool != "select":
            return
        hit = next((it for it in self.view.items(pos) if isinstance(it, N40Item)), None)
        if hit is not None and not hit.isSelected():
            self.scene.clearSelection()
            hit.setSelected(True)
        has_sel = bool(self.selected())
        at = self.view.mapToScene(pos)
        menu = QMenu(self)
        cut = menu.addAction(self.a_cut.icon(), "Вырезать", self.cut_selected)
        cut.setShortcut(QKeySequence(QKeySequence.StandardKey.Cut))
        copy = menu.addAction(self.a_copy.icon(), "Копировать", self.copy_selected)
        copy.setShortcut(QKeySequence(QKeySequence.StandardKey.Copy))
        paste = menu.addAction(self.a_paste.icon(), "Вставить сюда", lambda: self.paste(at))
        paste.setShortcut(QKeySequence(QKeySequence.StandardKey.Paste))
        menu.addSeparator()
        dup = menu.addAction(self.a_dup.icon(), "Дублировать", self.duplicate)
        dup.setShortcut(self.a_dup.shortcut())
        rot = menu.addAction(self.a_rot_cw.icon(), "Повернуть на 90°", lambda: self.rotate_selected(90))
        flip = menu.addAction(self.a_flip_h.icon(), "Отразить по горизонтали", lambda: self.flip_selected(True))
        menu.addSeparator()
        delete = menu.addAction(self.a_del.icon(), "Удалить", self.delete_selected)
        delete.setShortcut(self.a_del.shortcut())
        for a in (cut, copy, dup, rot, flip, delete):
            a.setEnabled(has_sel)
        paste.setEnabled(self.can_paste())
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def rotate_selected(self, angle: float) -> None:
        sel = self.selected()
        if not sel:
            return
        self.push_undo()
        c = items_bbox(sel).center()
        a = math.radians(angle)
        for it in sel:
            p = it.pos() - c
            it.setPos(c.x() + p.x() * math.cos(a) - p.y() * math.sin(a),
                      c.y() + p.x() * math.sin(a) + p.y() * math.cos(a))
            it.setRotation((it.rotation() + angle) % 360)
        self._after_edit()

    def flip_selected(self, horizontal: bool) -> None:
        sel = self.selected()
        if not sel:
            return
        self.push_undo()
        c = items_bbox(sel).center()
        for it in sel:
            it.flip(horizontal)
            p = it.pos()
            it.setPos(2 * c.x() - p.x(), p.y()) if horizontal else it.setPos(p.x(), 2 * c.y() - p.y())
        self._after_edit()

    def align(self, kind: str) -> None:
        sel = self.selected()
        if not sel:
            return
        self.push_undo()
        ref = items_bbox(sel) if len(sel) > 1 else self.scene.bed_rect  # один объект — по полю
        for it in sel:
            r = it.world_rect()
            dx = dy = 0.0
            if kind == "left":
                dx = ref.left() - r.left()
            elif kind == "right":
                dx = ref.right() - r.right()
            elif kind == "hcenter":
                dx = ref.center().x() - r.center().x()
            elif kind == "top":
                dy = ref.top() - r.top()
            elif kind == "bottom":
                dy = ref.bottom() - r.bottom()
            elif kind == "vcenter":
                dy = ref.center().y() - r.center().y()
            it.moveBy(dx, dy)
        self._after_edit()

    def distribute(self, horizontal: bool) -> None:
        sel = self.selected()
        if len(sel) < 3:
            self.statusBar().showMessage("Для распределения выделите минимум 3 объекта", 3000)
            return
        self.push_undo()
        key = (lambda it: it.world_rect().left()) if horizontal else (lambda it: it.world_rect().top())
        sel.sort(key=key)
        rects = [it.world_rect() for it in sel]
        if horizontal:
            total = rects[-1].right() - rects[0].left()
            gap = (total - sum(r.width() for r in rects)) / (len(sel) - 1)
            pos = rects[0].left()
            for it, r in zip(sel, rects):
                it.moveBy(pos - r.left(), 0)
                pos += r.width() + gap
        else:
            total = rects[-1].bottom() - rects[0].top()
            gap = (total - sum(r.height() for r in rects)) / (len(sel) - 1)
            pos = rects[0].top()
            for it, r in zip(sel, rects):
                it.moveBy(0, pos - r.top())
                pos += r.height() + gap
        self._after_edit()

    def _vectors(self, minimum: int = 1) -> list[VectorItem] | None:
        vec = [it for it in self.selected() if type(it) is VectorItem]
        if len(vec) < minimum:
            self.statusBar().showMessage(f"Выделите векторные объекты (минимум {minimum})", 3000)
            return None
        return vec

    def group(self) -> None:
        vec = self._vectors(2)
        if not vec:
            return
        self.push_undo()
        vec.sort(key=lambda it: it.zValue())
        parts = [p for it in vec for p in it.world_parts()]
        g = VectorItem(parts, "Группа", vec[0].mode)
        g.speed, g.passes = vec[0].speed, vec[0].passes
        for it in vec:
            self.scene.removeItem(it)
        self._add_item(g)
        self._after_edit()

    def ungroup(self) -> None:
        vec = [it for it in self._vectors(1) or [] if len(it.parts) > 1]
        if not vec:
            # одиночный составной контур — разбиваем на отдельные контуры
            vec = [it for it in self._vectors(1) or [] if len(it.contours) > 1]
            if not vec:
                return
            self.push_undo()
            for it in vec:
                for c in it.world_contours():
                    self._add_item(VectorItem([c], f"{it.name} · контур", it.mode))
                self.scene.removeItem(it)
            self._after_edit()
            return
        self.push_undo()
        for it in vec:
            for i, part in enumerate(it.world_parts()):
                new = VectorItem(part, f"{it.name} · {i + 1}", it.mode)
                new.speed, new.passes = it.speed, it.passes
                self._add_item(new)
            self.scene.removeItem(it)
        self._after_edit()

    def boolean(self, op: str) -> None:
        vec = self._vectors(2)
        if not vec:
            return
        vec.sort(key=lambda it: (it.zValue(), self.scene.items(Qt.SortOrder.AscendingOrder).index(it)))
        result = geo.boolean(op, [it.world_contours() for it in vec])
        if not result:
            self.statusBar().showMessage("Результат операции пуст", 3000)
            return
        self.push_undo()
        names = {"union": "Объединение", "difference": "Вычитание", "intersection": "Пересечение"}
        new = VectorItem(result, names[op], vec[0].mode)
        for it in vec:
            self.scene.removeItem(it)
        self._add_item(new)
        self._after_edit()

    def array(self) -> None:
        sel = self.selected()
        if not sel:
            return
        r = items_bbox(sel)
        dlg = ArrayDialog(self, r.width(), r.height(), (r.center().x(), r.center().y()))
        if not dlg.exec():
            return
        self.push_undo()
        if dlg.circular:
            n, total = dlg.count.value(), dlg.total.value()
            full = abs(total - 360) < 1e-6
            step = total / (n if full else max(1, n - 1))
            cx, cy = dlg.cx.value(), dlg.cy.value()
            for k in range(1, n):
                a = math.radians(step * k)
                for it in sel:
                    c = clone_item(it)
                    p = it.pos() - QPointF(cx, cy)
                    c.setPos(cx + p.x() * math.cos(a) - p.y() * math.sin(a),
                             cy + p.x() * math.sin(a) + p.y() * math.cos(a))
                    if dlg.rotate.isChecked():
                        c.setRotation(it.rotation() + step * k)
                    self._add_item(c, select=False)
        else:
            sx, sy = dlg.linear_steps()
            for j in range(dlg.ny.value()):
                for i in range(dlg.nx.value()):
                    if i == 0 and j == 0:
                        continue
                    for it in sel:
                        c = clone_item(it)
                        c.moveBy(i * sx, j * sy)
                        self._add_item(c, select=False)
        self._after_edit()

    def offset(self) -> None:
        vec = self._vectors(1)
        if not vec:
            return
        dlg = OffsetDialog(self)
        if not dlg.exec():
            return
        self.push_undo()
        for it in vec:
            result = geo.offset([c for c in it.world_contours() if c.closed], dlg.delta.value(),
                                dlg.join.currentData())
            if result:
                new = VectorItem(result, f"{it.name} · смещение", it.mode)
                self._add_item(new)
            if not dlg.keep.isChecked():
                self.scene.removeItem(it)
        self._after_edit()

    # ================================================================== импорт / проект
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        projects = [p for p in paths if p.lower().endswith(".n40")]
        if projects:
            self.load_project(Path(projects[0]))
        files = [p for p in paths if Path(p).suffix.lower() in ALL_EXT]
        if files:
            pos = self.view.mapToScene(self.view.mapFromGlobal(self.mapToGlobal(e.position().toPoint())))
            self.import_files(files, drop_at=pos)

    def import_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Импорт файлов", "", FILE_FILTER)
        if files:
            self.import_files(files)

    def import_files(self, files: list[str], drop_at: QPointF | None = None) -> None:
        has_svg = any(f.lower().endswith((".svg", ".pdf", ".ai")) for f in files)
        has_raster = any(Path(f).suffix.lower() in RASTER_EXT for f in files)
        has_dxf = any(f.lower().endswith(".dxf") for f in files)
        dlg = ImportDialog(self, self.settings, has_svg, has_raster, has_dxf)
        if (has_svg or has_raster or has_dxf) and not dlg.exec():
            return
        opts = dlg.options()
        if dlg.remember.isChecked():
            self.settings.svg_dpi = opts.svg_dpi
            self.settings.save()
        self.push_undo()
        self.scene.clearSelection()
        errors, warnings = [], []
        cursor_x = drop_at.x() if drop_at else 10.0
        cursor_y = drop_at.y() if drop_at else 10.0
        added = []
        for f in files:
            try:
                objs = import_file(f, opts)
            except ImportError_ as exc:
                errors.append(f"{Path(f).name}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(f).name}: {exc}")
                continue
            for o in objs:
                warnings.extend(f"{Path(f).name}: {w}" for w in o.warnings)
                if o.kind == "vector":
                    item = VectorItem(o.contours, o.name, "cut")
                else:
                    item = RasterItem(o.image, o.width_mm, o.height_mm, o.name)
                    item.setPos(o.width_mm / 2, o.height_mm / 2)
                # раскладываем импортированные файлы по полю друг за другом
                r = item.world_rect()
                item.moveBy(cursor_x - r.left(), cursor_y - r.top())
                cursor_x += r.width() + 5
                if cursor_x > self.settings.bed_width and drop_at is None:
                    cursor_x = 10
                    cursor_y += r.height() + 5
                self._add_item(item)
                added.append(item)
        self._after_edit()
        if added:
            self.statusBar().showMessage(f"Импортировано объектов: {len(added)}", 4000)
        if errors or warnings:
            QMessageBox.warning(self, "Импорт", "\n".join(errors + warnings))

    def new_project(self) -> None:
        if self.scene.n40_items() and QMessageBox.question(self, "Новый проект", "Очистить рабочую область?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.push_undo()
        for it in self.scene.n40_items():
            self.scene.removeItem(it)
        self.project_path = None
        self._after_edit()

    def save_project(self, save_as: bool = False) -> None:
        path = self.project_path
        if save_as or path is None:
            fn, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", "проект.n40", PROJECT_FILTER)
            if not fn:
                return
            path = Path(fn)
        data = {"app": "N40", "version": __version__,
                "items": [it.to_dict(embed=True) if isinstance(it, RasterItem) else it.to_dict()
                          for it in self.scene.n40_items()]}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.project_path = path
        self.setWindowTitle(f"{APP_NAME} — {path.name}")
        self.statusBar().showMessage("Проект сохранён", 3000)

    def open_project(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", PROJECT_FILTER)
        if fn:
            self.load_project(Path(fn))

    def load_project(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Открыть проект", f"Не удалось прочитать файл: {exc}")
            return
        self.push_undo()
        self.restore(data.get("items", []))
        self.project_path = path
        self.setWindowTitle(f"{APP_NAME} — {path.name}")

    def export_svg(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Экспорт SVG", "проект.svg", "SVG (*.svg)")
        if not fn:
            return
        w, h = self.settings.bed_width, self.settings.bed_height
        colors = {"cut": style.RED, "engrave": style.BLUE, "raster": style.INK}
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">']
        for it in self.scene.n40_items():
            if not isinstance(it, VectorItem) or not it.is_output:
                continue
            d = []
            for c in it.world_contours():
                pts = c.points
                d.append("M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in pts) + (" Z" if c.closed else ""))
            out.append(f'<path d="{" ".join(d)}" fill="none" stroke="{colors[it.mode]}" stroke-width="0.1"/>')
        out.append("</svg>")
        Path(fn).write_text("\n".join(out), encoding="utf-8")

    # ================================================================== нестинг
    def auto_arrange(self) -> None:
        """Раскладывает выделенные (или все) объекты на рабочем поле без наложений.

        Работает без лазера. Если на поле есть «Область раскроя» — раскладывает только в ней,
        запретные зоны обходит. Расчёт идёт в фоне, интерфейс не блокируется.
        """
        if getattr(self, "_arrange_worker", None) is not None and self._arrange_worker.isRunning():
            return
        items = [it for it in self.selected() if it.is_output] or \
                [it for it in self.scene.n40_items() if it.is_output and it.isVisible()]
        if not items:
            self.statusBar().showMessage("Нет объектов для авторасстановки", 3000)
            return
        s = self.settings
        gap = s.arrange_gap
        params = NestParams(sheet_width=s.bed_width, sheet_height=s.bed_height, gap=gap, margin=0.0,
                            angles=[0.0, 90.0, 180.0, 270.0] if s.arrange_rotate else [0.0], use_holes=True)
        regions = [it for it in self.scene.n40_items() if isinstance(it, RegionItem) and not it.forbidden]
        forbidden = [it for it in self.scene.n40_items() if isinstance(it, RegionItem) and it.forbidden]
        if regions:
            from shapely.ops import unary_union
            params.container = unary_union([geo.to_shapely(r.world_contours()) for r in regions])
        params.forbidden = [geo.to_shapely(r.world_contours()) for r in forbidden]

        worker = NestWorker([NestPart(it, it.outline_contours(), 1) for it in items], params)
        self._arrange_worker = worker
        self.a_arrange.setEnabled(False)
        worker.progress.connect(lambda a, b: self.statusBar().showMessage(
            f"Авторасстановка… {int(a / max(b, 1) * 100)} %"))
        worker.done.connect(self._arrange_done)
        worker.failed.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        worker.finished.connect(lambda: self.a_arrange.setEnabled(True))
        worker.start()

    def _arrange_done(self, result) -> None:
        if result.placements:
            self._apply_nest(result)
        msg = f"Авторасстановка: размещено {len(result.placements)}, K = {result.utilization:.1f} %"
        if result.unplaced:
            msg += f", не поместилось {len(result.unplaced)} — оставлены на месте"
            s = self.settings
            names = []
            for item, _copy in result.unplaced[:8]:
                w, h = item.world_rect().width(), item.world_rect().height()
                names.append(f"• {item.name} — {w:.1f} × {h:.1f} мм")
            QMessageBox.warning(self, "Авторасстановка",
                                f"Не поместилось объектов: {len(result.unplaced)}\n" + "\n".join(names) +
                                f"\n\nРабочее поле: {s.bed_width:g} × {s.bed_height:g} мм "
                                "(меняется в «Файл → Настройки → Станок»).\n"
                                "Эти объекты оставлены на прежнем месте и могут перекрываться с остальными. "
                                "Уменьшите зазор, разрешите вращение или освободите место на поле.")
        self.statusBar().showMessage(msg, 6000)

    def nest(self) -> None:
        outputs = [it for it in self.scene.n40_items() if it.is_output]
        sel = [it for it in self.selected() if it.is_output] or outputs
        if not sel:
            QMessageBox.information(self, "Нестинг", "Нет деталей для раскладки")
            return
        regions = [it for it in self.scene.n40_items() if isinstance(it, RegionItem) and not it.forbidden]
        forbidden = [it for it in self.scene.n40_items() if isinstance(it, RegionItem) and it.forbidden]
        dlg = NestDialog(self, self.settings, [(it, it.name) for it in sel], bool(regions), bool(forbidden))
        self.nest_dialog = dlg

        def run():
            params = NestParams(sheet_width=dlg.sheet_w.value(), sheet_height=dlg.sheet_h.value(),
                                gap=dlg.gap.value(), margin=dlg.margin.value(), angles=dlg.angles(),
                                use_holes=dlg.holes.isChecked())
            if dlg.use_region.isChecked() and regions:
                from shapely.ops import unary_union
                params.container = unary_union([geo.to_shapely(r.world_contours()) for r in regions])
            if dlg.use_forbidden.isChecked():
                params.forbidden = [geo.to_shapely(r.world_contours()) for r in forbidden]
            parts = [NestPart(it, it.outline_contours(), sb.value()) for (it, _), sb in zip(dlg.parts, dlg.copies)]
            worker = NestWorker(parts, params)
            dlg.worker = worker
            worker.progress.connect(lambda a, b: dlg.progress.setValue(int(a / max(b, 1) * 100)))
            worker.done.connect(dlg.show_result)
            worker.failed.connect(lambda msg: dlg.result_info.setText(msg))
            worker.finished.connect(lambda: (dlg.btn_run.setEnabled(True), dlg.btn_stop.setEnabled(False)))
            dlg.btn_run.setEnabled(False)
            dlg.btn_stop.setEnabled(True)
            dlg.btn_apply.setEnabled(False)
            dlg.result_label.setText("")
            dlg.result_info.setText("Расчёт…")
            worker.start()

        def apply():
            if dlg.result:
                self._apply_nest(dlg.result)
                dlg.accept()

        dlg.btn_run.clicked.connect(run)
        dlg.btn_stop.clicked.connect(lambda: dlg.worker and dlg.worker.cancel())
        dlg.btn_apply.clicked.connect(apply)
        dlg.exec()
        self.nest_dialog = None

    def _apply_nest(self, result) -> None:
        self.push_undo()
        self.scene.clearSelection()
        # раскладка считалась от исходного положения деталей — запоминаем его до перемещений
        orig = {}
        for pl in result.placements:
            orig.setdefault(id(pl.key), (QPointF(pl.key.pos()), pl.key.rotation()))
        for pl in result.placements:
            src: N40Item = pl.key
            p, rot = orig[id(src)]
            it = src if pl.copy_index == 0 else clone_item(src)
            a = math.radians(pl.angle)
            it.setPos(p.x() * math.cos(a) - p.y() * math.sin(a) + pl.dx,
                      p.x() * math.sin(a) + p.y() * math.cos(a) + pl.dy)
            it.setRotation((rot + pl.angle) % 360)
            if pl.copy_index:
                self._add_item(it, select=False)
        self.lbl_k.setText(f"K = {result.utilization:.1f} %")
        self._after_edit()

    # ================================================================== лазер
    def _toggle_connect(self) -> None:
        if self.laser.usb.connected:
            self.laser.submit("disconnect")
        else:
            self.laser.submit("connect")

    def _laser_connected(self, ok: bool) -> None:
        self.machine.btn_connect.setText("Отключить" if ok else "Подключить")
        self.machine.state.setText("Подключён" if ok else "Не подключён")

    def _laser_status(self, text: str) -> None:
        self.lbl_laser.setText("Лазер: " + text)
        self.statusBar().showMessage(text, 5000)

    def _sync_speeds(self) -> None:
        sp, s = self.speeds, self.settings
        for box, value in ((sp.engrave_speed, s.engrave_speed), (sp.cut_speed, s.cut_speed),
                           (sp.raster_speed, s.raster_speed)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _speeds_edited(self) -> None:
        self.settings.engrave_speed = self.speeds.engrave_speed.value()
        self.settings.cut_speed = self.speeds.cut_speed.value()
        self.settings.raster_speed = self.speeds.raster_speed.value()
        self.settings.save()

    def _model_chosen(self, name: str) -> None:
        """Выбор модели лазера: подставляет плату и размер поля из пресета."""
        s = self.settings
        s.laser_model = name
        if name in LASER_MODELS:
            s.board, s.bed_width, s.bed_height = LASER_MODELS[name]
        elif name == CUSTOM_MODEL:
            self.open_settings()
        s.save()
        self._apply_machine_settings()

    def _apply_machine_settings(self) -> None:
        self.laser.board = self.settings.board
        self.scene.update_bed()
        self.machine.show_settings(self.settings)
        self.view.zoom_fit()
        if self.camera:
            self.camera.reload_calibration()

    def _jog(self, dx: int, dy: int) -> None:
        step = mm_to_steps(self.jog.step_mm)
        self.laser.submit("move", (dx * step, dy * step))

    def _pause(self, paused: bool) -> None:
        self.laser.set_paused(paused)
        self.job.btn_pause.setText("Продолжить" if paused else "Пауза")

    def stop_job(self) -> None:
        self.laser.request_stop()
        self.job.btn_pause.setChecked(False)

    def build_programs(self):
        items = self.selected() if self.objects.only_selected.isChecked() else self.scene.n40_items()
        ops = build_operations(items, self.settings)
        programs = planner.plan(ops)
        if not programs:
            QMessageBox.information(self, "Задание", "Нечего обрабатывать: нет видимых объектов для лазера")
            return None
        b = planner.job_bounds(programs)
        lim_x, lim_y = mm_to_steps(self.settings.bed_width), mm_to_steps(self.settings.bed_height)
        if b[0] < 0 or b[1] < 0:
            QMessageBox.warning(self, "Задание", "Часть задания левее или выше начала координат (0,0). "
                                                 "Переместите объекты на рабочее поле.")
            return None
        if b[2] > lim_x or b[3] > lim_y:
            if QMessageBox.question(self, "Задание", "Задание выходит за пределы рабочего поля. Продолжить?") \
                    != QMessageBox.StandardButton.Yes:
                return None
        return programs

    def start_job(self) -> None:
        if not self.laser.usb.connected:
            QMessageBox.information(self, "Старт", "Сначала подключите лазер")
            return
        programs = self.build_programs()
        if not programs:
            return
        t = planner.estimate_time(programs)
        self.job.estimate.setText(f"Оценка времени ≈ {t / 60:.1f} мин")
        if QMessageBox.question(self, "Старт",
                                f"Блоков: {len(programs)}, оценка времени ≈ {t / 60:.1f} мин.\n"
                                "Крышка закрыта, вытяжка и охлаждение включены?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.job.progress.setValue(0)
        self.header_job.setText("ИДЁТ ЗАДАНИЕ")
        self.laser.submit("job", programs)
        if self.settings.rapid_return_home:
            self.laser.submit("moveto", (0, 0))

    def _job_finished(self, ok: bool, msg: str) -> None:
        self.header_job.setText("")
        self.job.btn_pause.setChecked(False)
        if ok:
            self.job.progress.setValue(100)
        self._laser_status(msg)

    def frame_job(self) -> None:
        if not self.laser.usb.connected:
            QMessageBox.information(self, "Рамка", "Сначала подключите лазер")
            return
        programs = self.build_programs()
        if not programs:
            return
        x0, y0, x1, y1 = planner.job_bounds(programs)
        for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)):
            self.laser.submit("moveto", p)

    def export_egv(self) -> None:
        programs = self.build_programs()
        if not programs:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Экспорт EGV", "задание.egv", "EGV (*.egv)")
        if not fn:
            return
        cmds = lhymicro.encode_job(programs, self.settings.board, self.settings.rapid_return_home)
        Path(fn).write_text(lhymicro.to_egv(cmds), encoding="ascii")
        self.statusBar().showMessage("EGV сохранён", 3000)

    def burn_markers(self, points: list[tuple[float, float]]) -> None:
        if not self.laser.usb.connected:
            QMessageBox.information(self, "Метки", "Сначала подключите лазер")
            return
        from ..core import primitives as prim
        contours = []
        for x, y in points:
            contours += prim.line(x - 4, y, x + 4, y) + prim.line(x, y - 4, x, y + 4) + prim.circle(x, y, 2)
        programs = planner.plan([planner.Operation("engrave", self.settings.engrave_speed, 1, contours)])
        if QMessageBox.question(self, "Метки", "Выжечь 4 калибровочные метки на материале?") \
                == QMessageBox.StandardButton.Yes:
            self.laser.submit("job", programs)
            self.laser.submit("moveto", (0, 0))

    # ================================================================== камера
    def _toggle_camera(self, on: bool) -> None:
        cp = self.camera_panel
        if on:
            self.camera = CameraWorker(self.settings)
            self.camera.field_image.connect(self._camera_frame)
            self.camera.error.connect(self._camera_error)
            self.camera.start()
            cp.btn_toggle.setText("Выключить камеру")
            calibrated = self.settings.calibration.homography is not None
            cp.status.setText("Калибровка загружена" if calibrated
                              else "Камера не откалибрована: кадр растянут на поле без коррекции")
        else:
            if self.camera:
                self.camera.stop()
                self.camera = None
            cp.btn_toggle.setText("Включить камеру")
            self.scene.set_camera_image(None)

    def _camera_frame(self, img) -> None:
        if not self.camera_frozen:
            self.scene.set_camera_image(img)

    def _camera_error(self, msg: str) -> None:
        self.camera_panel.status.setText(msg)
        self.camera_panel.btn_toggle.setChecked(False)

    def _camera_visibility(self, v: bool) -> None:
        self.scene.camera_visible = v
        self.scene.update()

    def _camera_opacity(self, v: int) -> None:
        self.settings.camera_opacity = v / 100
        self.scene.update()

    def calibrate_camera(self) -> None:
        if not self.camera_panel.btn_toggle.isChecked():
            self.camera_panel.btn_toggle.setChecked(True)
        backup = copy.deepcopy(self.settings.calibration)
        wiz = CalibrationWizard(self, self.settings, self.camera)
        wiz.zone.burn_markers.connect(self.burn_markers)
        if wiz.exec():
            self.settings.save()
            if self.camera:
                self.camera.reload_calibration()
            self.camera_panel.status.setText("Калибровка сохранена")
        else:
            self.settings.calibration = backup

    # ================================================================== прочее
    def _toggle_snaps(self) -> None:
        self.settings.snap_grid = self.a_snap_grid.isChecked()
        self.settings.snap_nodes = self.a_snap_nodes.isChecked()
        self.settings.save()

    def _set_grid(self, v: float) -> None:
        self.settings.grid_step = float(v)
        self.settings.save()
        self.scene.update()

    def _cursor_moved(self, x: float, y: float) -> None:
        self.lbl_coords.setText(f"X {x:8.2f}   Y {y:8.2f} мм")

    def _update_zoom_label(self) -> None:
        self.lbl_zoom.setText(f"Масштаб {self.view.zoom_percent:.0f} %")

    def open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec():
            dlg.apply()
            s = self.settings
            # поле или плата изменены вручную и не совпадают с пресетом -> «Пользовательский»
            if LASER_MODELS.get(s.laser_model) != (s.board, s.bed_width, s.bed_height):
                s.laser_model = CUSTOM_MODEL
                s.save()
            self._sync_speeds()
            self._apply_machine_settings()
            self.a_snap_grid.setChecked(s.snap_grid)
            self.a_snap_nodes.setChecked(s.snap_nodes)
            for a, v in zip(self.grid_actions, (1, 5, 10)):
                a.setChecked(abs(s.grid_step - v) < 1e-6)

    def check_updates(self, manual: bool = False) -> None:
        self._upd = UpdateWorker()
        self._upd.found.connect(self._update_found)
        if manual:
            self._upd.finished.connect(lambda: None if getattr(self, "_upd_found", False) else
                                       self.statusBar().showMessage(f"Установлена последняя версия {__version__}",
                                                                    4000))
        self._upd.start()

    def _update_found(self, info) -> None:
        self._upd_found = True
        if not ask_update(self, info):
            return
        if not info.installer_url:
            import webbrowser
            webbrowser.open(info.page_url)
            return
        self._dl = DownloadWorker(info)
        self._dl.finished_ok.connect(self._run_installer)
        self._dl.failed.connect(lambda m: QMessageBox.warning(self, "Обновление", m))
        self.statusBar().showMessage("Загрузка обновления…")
        self._dl.start()

    def _run_installer(self, path: str) -> None:
        if QMessageBox.question(self, "Обновление", "Обновление загружено. Закрыть N40 и установить?") \
                == QMessageBox.StandardButton.Yes:
            subprocess.Popen([path, "/SILENT", "/CLOSEAPPLICATIONS"], close_fds=True)
            self.close()

    def about(self) -> None:
        QMessageBox.about(self, "О программе",
                          f"<h2>N40 {__version__}</h2>"
                          "<p>Управление CO₂-лазером K40 (M2 Nano, LHYMICRO-GL).</p>"
                          "<p>Протокол реализован по открытым проектам MeerK40t и K40 Whisperer.</p>"
                          "<p>github.com/KeshaNov/N40</p>")

    def closeEvent(self, e) -> None:
        # сцена при уничтожении шлёт selectionChanged уже удалённым объектам
        self.scene.selectionChanged.disconnect(self._selection_changed)
        QSettings("N40", "N40").setValue("geometry", self.saveGeometry())
        self.settings.save()
        if self.camera:
            self.camera.stop()
        self.laser.shutdown()
        super().closeEvent(e)
