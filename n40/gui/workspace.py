"""Рабочая область: сцена в мм, сетка, линейки, подложка камеры, инструменты рисования, привязки."""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QGridLayout, QWidget

from ..core import primitives as prim
from ..core.geometry import nearest_vertex
from . import style
from .items import N40Item, RegionItem, VectorItem, contours_to_path

RULER = 22


class WorkScene(QGraphicsScene):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.camera_image: QImage | None = None
        self.camera_visible = True
        self.update_bed()

    def update_bed(self) -> None:
        w, h = self.settings.bed_width, self.settings.bed_height
        pad = max(w, h) * 0.5
        self.setSceneRect(-pad, -pad, w + 2 * pad, h + 2 * pad)
        self.invalidate(self.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer)

    @property
    def bed_rect(self) -> QRectF:
        return QRectF(0, 0, self.settings.bed_width, self.settings.bed_height)

    def set_camera_image(self, img: QImage | None) -> None:
        self.camera_image = img
        self.invalidate(self.bed_rect, QGraphicsScene.SceneLayer.BackgroundLayer)

    def n40_items(self) -> list[N40Item]:
        return [it for it in self.items(Qt.SortOrder.AscendingOrder) if isinstance(it, N40Item)]

    def selected_n40(self) -> list[N40Item]:
        return [it for it in self.selectedItems() if isinstance(it, N40Item)]

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(style.OUTSIDE))
        bed = self.bed_rect
        painter.fillRect(bed, QColor(style.BED))
        if self.camera_image is not None and self.camera_visible:
            painter.save()
            painter.setOpacity(self.settings.camera_opacity)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(bed, self.camera_image)
            painter.restore()

        # сетка: шаг из настроек, главные линии каждые 10 мм
        scale = painter.worldTransform().m11()
        step = max(0.5, float(self.settings.grid_step))
        while step * scale < 4:          # не рисуем слишком плотную сетку
            step *= 2
        r = rect.intersected(bed)
        if r.isEmpty():
            return
        minor = QPen(QColor(0, 0, 0, 22), 0)
        major = QPen(QColor(0, 0, 0, 60), 0)
        lines_minor, lines_major = [], []
        x = math.floor(r.left() / step) * step
        while x <= r.right():
            target = lines_major if abs(x / 10 - round(x / 10)) < 1e-6 else lines_minor
            target.append(QLineF(x, r.top(), x, r.bottom()))
            x += step
        y = math.floor(r.top() / step) * step
        while y <= r.bottom():
            target = lines_major if abs(y / 10 - round(y / 10)) < 1e-6 else lines_minor
            target.append(QLineF(r.left(), y, r.right(), y))
            y += step
        painter.setPen(minor)
        painter.drawLines(lines_minor)
        painter.setPen(major)
        painter.drawLines(lines_major)
        border = QPen(QColor(style.INK), 0)
        painter.setPen(border)
        painter.drawRect(bed)
        # отметка начала координат (дом K40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.RED))
        k = 6 / max(scale, 1e-6)
        painter.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(k * 2, 0), QPointF(0, k * 2)]))


class Ruler(QWidget):
    def __init__(self, view: "WorkView", horizontal: bool):
        super().__init__()
        self.view = view
        self.horizontal = horizontal
        self.cursor_pos: float | None = None
        if horizontal:
            self.setFixedHeight(RULER)
        else:
            self.setFixedWidth(RULER)

    def set_cursor(self, v: float | None) -> None:
        self.cursor_pos = v
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(style.PAPER))
        p.setPen(QPen(QColor(style.INK), 1))
        if self.horizontal:
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        else:
            p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        scale = self.view.transform().m11()
        if scale <= 0:
            return
        # шаг подписей ~ 60 px
        nice = [1, 2, 5, 10, 20, 50, 100, 200, 500]
        major = next((n for n in nice if n * scale >= 60), 1000)
        minor = major / (5 if str(major)[0] in "15" else 4)
        a =self.view.mapToScene(0, 0)
        b = self.view.mapToScene(self.view.viewport().width(), self.view.viewport().height())
        lo, hi = (a.x(), b.x()) if self.horizontal else (a.y(), b.y())
        font = QFont(style.FONT_FAMILY)
        font.setPointSizeF(7)
        p.setFont(font)
        v = math.floor(lo / minor) * minor
        while v <= hi:
            pos = (v - lo) * scale
            is_major = abs(v / major - round(v / major)) < 1e-6
            tick = 9 if is_major else 4
            if self.horizontal:
                p.drawLine(int(pos), self.height() - tick, int(pos), self.height())
                if is_major:
                    p.drawText(int(pos) + 3, 10, f"{v:g}")
            else:
                p.drawLine(self.width() - tick, int(pos), self.width(), int(pos))
                if is_major:
                    p.save()
                    p.translate(10, int(pos) - 3)
                    p.rotate(-90)
                    p.drawText(0, 0, f"{v:g}")
                    p.restore()
            v += minor
        if self.cursor_pos is not None:
            pos = (self.cursor_pos - lo) * scale
            p.setPen(QPen(QColor(style.RED), 1))
            if self.horizontal:
                p.drawLine(int(pos), 0, int(pos), self.height())
            else:
                p.drawLine(0, int(pos), self.width(), int(pos))


class WorkView(QGraphicsView):
    cursor_moved = Signal(float, float)
    view_changed = Signal()
    item_created = Signal(object)        # N40Item
    text_requested = Signal(float, float)
    tool_finished = Signal()

    TOOLS = ("select", "rect", "rrect", "ellipse", "circle", "line", "polyline", "ngon", "text",
             "region", "forbid")

    def __init__(self, scene: WorkScene, settings):
        super().__init__(scene)
        self.settings = settings
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setMouseTracking(True)
        self.setAcceptDrops(False)  # файлы принимает главное окно
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.tool = "select"
        self.ngon_sides = 6
        self.rrect_radius = 5.0
        self._panning = None
        self._start: QPointF | None = None
        self._current: QPointF | None = None
        self._poly: list[QPointF] = []
        self._snap_hint: QPointF | None = None
        self.horizontalScrollBar().valueChanged.connect(self.view_changed)
        self.verticalScrollBar().valueChanged.connect(self.view_changed)

    # ------------------------------------------------------------------ масштаб
    def zoom_fit(self) -> None:
        r = self.scene().bed_rect.adjusted(-10, -10, 10, 10)
        self.fitInView(r, Qt.AspectRatioMode.KeepAspectRatio)
        self.view_changed.emit()

    def zoom_by(self, k: float) -> None:
        s = self.transform().m11() * k
        if 0.2 <= s <= 400:
            self.scale(k, k)
            self.view_changed.emit()

    def wheelEvent(self, e) -> None:
        self.zoom_by(1.2 if e.angleDelta().y() > 0 else 1 / 1.2)

    @property
    def zoom_percent(self) -> float:
        # 100 % — реальный размер (≈ 3.78 px/мм при 96 dpi)
        return self.transform().m11() / (self.logicalDpiX() / 25.4) * 100

    # ------------------------------------------------------------------ привязки
    def snap(self, p: QPointF, exclude=None) -> QPointF:
        self._snap_hint = None
        scale = self.transform().m11()
        if self.settings.snap_nodes:
            tol = 8 / max(scale, 1e-6)
            sets = []
            for it in self.scene().n40_items():
                if it is exclude or (exclude is not None and it.isSelected()):
                    continue
                if isinstance(it, VectorItem):
                    sets.append(it.world_contours())
            hit = nearest_vertex(sets, p.x(), p.y(), tol)
            if hit:
                self._snap_hint = QPointF(*hit)
                return QPointF(*hit)
        if self.settings.snap_grid:
            g = max(0.1, float(self.settings.grid_step))
            return QPointF(round(p.x() / g) * g, round(p.y() / g) * g)
        return p

    def snap_item_pos(self, top_left: QPointF, item) -> QPointF:
        """Колбэк привязки при перетаскивании объектов."""
        if not self.settings.snap_grid:
            return top_left
        g = max(0.1, float(self.settings.grid_step))
        return QPointF(round(top_left.x() / g) * g, round(top_left.y() / g) * g)

    # ------------------------------------------------------------------ инструменты
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._start = self._current = None
        self._poly = []
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if tool == "select" else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor if tool == "select" else Qt.CursorShape.CrossCursor)
        self.viewport().update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.MiddleButton:
            self._panning = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.tool == "select" or e.button() != Qt.MouseButton.LeftButton:
            if e.button() == Qt.MouseButton.RightButton:
                # в режиме выделения правая кнопка открывает контекстное меню и не сбрасывает выделение
                if self.tool != "select":
                    self._finish_poly()
                e.accept()
                return
            super().mousePressEvent(e)
            return
        p = self.snap(self.mapToScene(e.position().toPoint()))
        if self.tool == "text":
            self.text_requested.emit(p.x(), p.y())
            return
        if self.tool in ("polyline", "region", "forbid"):
            if self._poly and len(self._poly) >= 3 and self.tool != "polyline" and \
                    QLineF(p, self._poly[0]).length() * self.transform().m11() < 10:
                self._finish_poly(close=True)
                return
            self._poly.append(p)
            self._current = p
            self.viewport().update()
            return
        self._start = self._current = p

    def mouseMoveEvent(self, e) -> None:
        if self._panning is not None:
            d = e.position() - self._panning
            self._panning = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        sp = self.mapToScene(e.position().toPoint())
        self.cursor_moved.emit(sp.x(), sp.y())
        if self.tool != "select":
            p = self.snap(sp)
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._start is not None:
                p = self._constrain(self._start, p)
            self._current = p
            self.viewport().update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.MiddleButton and self._panning is not None:
            self._panning = None
            self.set_tool(self.tool)
            return
        if self.tool in ("select", "polyline", "region", "forbid", "text") or self._start is None:
            super().mouseReleaseEvent(e)
            return
        a, b = self._start, self._current or self._start
        self._start = None
        if QLineF(a, b).length() < 0.2:
            self.viewport().update()
            return
        contours = self._make_shape(self.tool, a, b)
        if contours:
            names = {"rect": "Прямоугольник", "rrect": "Скруглённый прямоугольник", "ellipse": "Эллипс",
                     "circle": "Окружность", "line": "Линия", "ngon": f"{self.ngon_sides}-угольник"}
            self.item_created.emit(VectorItem(contours, names.get(self.tool, "")))
        self.viewport().update()

    def mouseDoubleClickEvent(self, e) -> None:
        if self.tool in ("polyline", "region", "forbid"):
            self._finish_poly(close=self.tool != "polyline")
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._poly:
            self._finish_poly(close=self.tool != "polyline")
            return
        if e.key() == Qt.Key.Key_Escape:
            if self._poly or self._start:
                self.set_tool(self.tool)
            else:
                self.tool_finished.emit()
            return
        super().keyPressEvent(e)

    def _constrain(self, a: QPointF, b: QPointF) -> QPointF:
        """Shift: квадрат/круг или линия под углом, кратным 45°."""
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if self.tool == "line" or self.tool == "polyline":
            ang = round(math.atan2(dy, dx) / (math.pi / 4)) * math.pi / 4
            d = math.hypot(dx, dy)
            return QPointF(a.x() + d * math.cos(ang), a.y() + d * math.sin(ang))
        s = max(abs(dx), abs(dy))
        return QPointF(a.x() + math.copysign(s, dx or 1), a.y() + math.copysign(s, dy or 1))

    def _make_shape(self, tool: str, a: QPointF, b: QPointF):
        x0, y0 = min(a.x(), b.x()), min(a.y(), b.y())
        w, h = abs(b.x() - a.x()), abs(b.y() - a.y())
        if tool == "rect":
            return prim.rectangle(x0, y0, w, h)
        if tool == "rrect":
            return prim.rectangle(x0, y0, w, h, self.rrect_radius)
        if tool == "ellipse":
            return prim.ellipse(x0 + w / 2, y0 + h / 2, w / 2, h / 2)
        if tool == "circle":
            r = QLineF(a, b).length()
            return prim.circle(a.x(), a.y(), r)
        if tool == "line":
            return prim.line(a.x(), a.y(), b.x(), b.y())
        if tool == "ngon":
            return prim.regular_polygon(a.x(), a.y(), QLineF(a, b).length(), self.ngon_sides,
                                        math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x())))
        return None

    def _finish_poly(self, close: bool = False) -> None:
        pts = self._poly
        self._poly = []
        self._current = None
        if len(pts) >= 2:
            arr = [(p.x(), p.y()) for p in pts]
            if self.tool == "polyline":
                closed = close and len(arr) >= 3
                self.item_created.emit(VectorItem(prim.polygon(arr, closed), "Многоугольник" if closed else "Ломаная"))
            elif len(arr) >= 3:
                self.item_created.emit(RegionItem(prim.polygon(arr, True), forbidden=self.tool == "forbid"))
        self.viewport().update()

    # ------------------------------------------------------------------ предпросмотр
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        pen = QPen(QColor(style.RED), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._start is not None and self._current is not None:
            shape = self._make_shape(self.tool, self._start, self._current)
            if shape:
                painter.drawPath(contours_to_path(shape))
                w = abs(self._current.x() - self._start.x())
                h = abs(self._current.y() - self._start.y())
                self._draw_label(painter, self._current, f"{w:.1f} × {h:.1f} мм")
        if self._poly:
            pts = self._poly + ([self._current] if self._current else [])
            painter.drawPolyline(QPolygonF(pts))
        if self._snap_hint is not None and self.tool != "select":
            k = 5 / max(self.transform().m11(), 1e-6)
            painter.setPen(QPen(QColor(style.BLUE), 0))
            painter.drawRect(QRectF(self._snap_hint.x() - k, self._snap_hint.y() - k, 2 * k, 2 * k))

    def _draw_label(self, painter: QPainter, at: QPointF, text: str) -> None:
        painter.save()
        vp = self.mapFromScene(at)
        painter.resetTransform()
        painter.setFont(style.ui_font(8, True))
        r = painter.fontMetrics().boundingRect(text).adjusted(-4, -2, 4, 2)
        r.moveTopLeft(vp + QPointF(12, 12).toPoint())
        painter.fillRect(r, QColor(style.INK))
        painter.setPen(QColor(style.PAPER))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class WorkArea(QWidget):
    """Вид с линейками."""

    def __init__(self, scene: WorkScene, settings):
        super().__init__()
        self.view = WorkView(scene, settings)
        self.hruler = Ruler(self.view, True)
        self.vruler = Ruler(self.view, False)
        corner = QWidget()
        corner.setFixedSize(RULER, RULER)
        corner.setStyleSheet(f"background:{style.INK};")
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(corner, 0, 0)
        lay.addWidget(self.hruler, 0, 1)
        lay.addWidget(self.vruler, 1, 0)
        lay.addWidget(self.view, 1, 1)
        self.view.view_changed.connect(self._refresh)
        self.view.cursor_moved.connect(self._cursor)

    def _refresh(self) -> None:
        self.hruler.update()
        self.vruler.update()

    def _cursor(self, x: float, y: float) -> None:
        self.hruler.set_cursor(x)
        self.vruler.set_cursor(y)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._refresh()
