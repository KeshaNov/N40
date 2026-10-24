"""Объекты рабочей области. 1 единица сцены = 1 мм.

Геометрия каждого объекта хранится в локальных координатах с центром габарита в (0,0);
pos() — центр в мире, rotation() — угол, (sx, sy) — масштаб/отражение через transform().
Так W/H/угол из панели свойств напрямую меняют параметры объекта, а мировые
координаты для ядра получаются через sceneTransform().
"""

from __future__ import annotations

import base64
import io
import itertools
import uuid

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
                           QPolygonF, QTransform)
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsPathItem, QStyle

from ..core.geometry import Contour, Contours, bbox, center_contours, transform
from . import style

_counter = itertools.count(1)

MODE_NAMES = {"cut": "Резка", "engrave": "Гравировка контура", "raster": "Растровая гравировка"}


def qtransform_to_np(t: QTransform) -> np.ndarray:
    # Qt: x' = m11·x + m21·y + dx, y' = m12·x + m22·y + dy
    return np.array([[t.m11(), t.m21(), t.dx()], [t.m12(), t.m22(), t.dy()], [0, 0, 1]], dtype=float)


def contours_to_path(contours: Contours) -> QPainterPath:
    path = QPainterPath()
    for c in contours:
        pts = c.points
        if len(pts) < 2:
            continue
        path.moveTo(pts[0, 0], pts[0, 1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        if c.closed:
            path.closeSubpath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    return path


def pil_to_qimage(img: Image.Image) -> QImage:
    g = img.convert("L")
    data = g.tobytes()
    q = QImage(data, g.width, g.height, g.width, QImage.Format.Format_Grayscale8)
    return q.copy()


def qimage_to_pil(q: QImage) -> Image.Image:
    """QImage -> PIL (оттенки серого, прозрачность на белом фоне)."""
    rgba = q.convertToFormat(QImage.Format.Format_RGBA8888)
    img = Image.frombuffer("RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()),
                           "raw", "RGBA", rgba.bytesPerLine(), 1)
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img)
    return bg.convert("L")


class N40Item:
    """Общая часть всех объектов (миксин к QGraphicsItem)."""

    kind = "base"
    is_output = True  # участвует ли в задании лазера

    def _init_common(self, name: str, mode: str) -> None:
        self.uid = uuid.uuid4().hex[:8]
        self.name = name or f"Объект {next(_counter)}"
        self.mode = mode
        self.speed: float | None = None    # None — по умолчанию из настроек
        self.passes = 1
        self.sx = 1.0
        self.sy = 1.0
        self.snap_callback = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

    # ------------------------------------------------------------------ трансформации
    def apply_scale(self) -> None:
        self.prepareGeometryChange()
        self.setTransform(QTransform.fromScale(self.sx, self.sy))

    def local_rect(self) -> QRectF:
        raise NotImplementedError

    @property
    def size(self) -> tuple[float, float]:
        r = self.local_rect()
        return r.width() * abs(self.sx), r.height() * abs(self.sy)

    def set_size(self, w: float | None = None, h: float | None = None) -> None:
        r = self.local_rect()
        if w is not None and r.width() > 1e-9:
            self.sx = np.copysign(max(w, 1e-3) / r.width(), self.sx)
        if h is not None and r.height() > 1e-9:
            self.sy = np.copysign(max(h, 1e-3) / r.height(), self.sy)
        self.apply_scale()

    def flip(self, horizontal: bool) -> None:
        if horizontal:
            self.sx = -self.sx
        else:
            self.sy = -self.sy
        self.setRotation(-self.rotation())
        self.apply_scale()

    def world_rect(self) -> QRectF:
        return self.sceneTransform().mapRect(self.local_rect())

    def world_matrix(self) -> np.ndarray:
        return qtransform_to_np(self.sceneTransform())

    def outline_contours(self) -> Contours:
        """Контур объекта в мировых координатах (для нестинга и булевых операций)."""
        raise NotImplementedError

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.snap_callback and self.scene() \
                and QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            # привязываем левый верхний угол габарита (только при перетаскивании мышью)
            offset = self.world_rect().topLeft() - self.pos()
            tl = value + offset
            snapped = self.snap_callback(tl, self)
            return snapped - offset
        return super().itemChange(change, value)

    # ------------------------------------------------------------------ сериализация
    def base_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "mode": self.mode, "speed": self.speed,
                "passes": self.passes, "sx": self.sx, "sy": self.sy, "rotation": self.rotation(),
                "x": self.pos().x(), "y": self.pos().y(), "z": self.zValue(), "uid": self.uid}

    def load_base(self, d: dict) -> None:
        self.name = d.get("name", self.name)
        self.mode = d.get("mode", self.mode)
        self.speed = d.get("speed")
        self.passes = int(d.get("passes", 1))
        self.sx, self.sy = float(d.get("sx", 1)), float(d.get("sy", 1))
        self.apply_scale()
        self.setRotation(float(d.get("rotation", 0)))
        self.setPos(float(d.get("x", 0)), float(d.get("y", 0)))
        self.setZValue(float(d.get("z", 0)))
        self.uid = d.get("uid", self.uid)

    def thumbnail(self, size: int = 40) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(QColor(style.PAPER_2))
        r = self.world_rect()
        if r.width() <= 0 and r.height() <= 0:
            return pm
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = (size - 6) / max(r.width(), r.height(), 1e-6)
        t = QTransform()
        t.translate(size / 2, size / 2)
        t.scale(k, k)
        t.translate(-r.center().x(), -r.center().y())
        p.setTransform(self.sceneTransform() * t)
        self.paint_content(p, thumbnail=True)
        p.end()
        return pm

    def paint_content(self, painter: QPainter, thumbnail: bool = False, for_raster: bool = False) -> None:
        raise NotImplementedError


class VectorItem(N40Item, QGraphicsPathItem):
    kind = "vector"

    def __init__(self, contours: Contours | list[Contours], name: str = "", mode: str = "cut", centered=False):
        QGraphicsPathItem.__init__(self)
        self._init_common(name, mode)
        parts = contours if contours and isinstance(contours[0], list) else [contours]
        self.parts: list[Contours] = []
        cx = cy = 0.0
        if not centered:
            allc = [c for part in parts for c in part]
            _, cx, cy = center_contours(allc)
            parts = [[Contour(c.points - (cx, cy), c.closed) for c in part] for part in parts]
        self.parts = [list(p) for p in parts]
        self._rebuild()
        self.setPos(cx, cy)

    @property
    def contours(self) -> Contours:
        return [c for part in self.parts for c in part]

    def _rebuild(self) -> None:
        self.prepareGeometryChange()
        self.setPath(contours_to_path(self.contours))
        stroker = QPainterPathStroker()
        stroker.setWidth(1.5)
        self._shape = stroker.createStroke(self.path())
        if any(c.closed for c in self.contours):
            self._shape = self._shape.united(self.path())

    def local_rect(self) -> QRectF:
        return self.path().boundingRect()

    def shape(self) -> QPainterPath:
        return self._shape

    def boundingRect(self) -> QRectF:
        return self.path().boundingRect().adjusted(-1, -1, 1, 1)

    def world_contours(self) -> Contours:
        return transform(self.contours, self.world_matrix())

    def world_parts(self) -> list[Contours]:
        m = self.world_matrix()
        return [transform(p, m) for p in self.parts]

    def outline_contours(self) -> Contours:
        return self.world_contours()

    def paint_content(self, painter: QPainter, thumbnail: bool = False, for_raster: bool = False) -> None:
        if for_raster:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("black"))
            painter.drawPath(self.path())
            return
        color = QColor(style.MODE_COLORS.get(self.mode, style.INK))
        pen = QPen(color, 1.4 if thumbnail else 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        if self.mode == "raster":
            fill = QColor(style.INK)
            fill.setAlpha(60 if not thumbnail else 120)
            painter.setBrush(fill)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        self.paint_content(painter)
        if option.state & QStyle.StateFlag.State_Selected:
            pen = QPen(QColor(style.INK), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.local_rect())
            sel = QPen(QColor(style.YELLOW), 3)
            sel.setCosmetic(True)
            painter.setPen(sel)
            painter.setOpacity(0.55)
            painter.drawPath(self.path())

    def to_dict(self) -> dict:
        d = self.base_dict()
        d["parts"] = [[c.to_list() for c in part] for part in self.parts]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "VectorItem":
        parts = [[Contour.from_list(c) for c in part] for part in d["parts"]]
        item = cls(parts, d.get("name", ""), d.get("mode", "cut"), centered=True)
        item.load_base(d)
        return item


class RasterItem(N40Item, QGraphicsItem):
    kind = "raster"

    def __init__(self, image: Image.Image, width_mm: float, height_mm: float, name: str = ""):
        QGraphicsItem.__init__(self)
        self._init_common(name, "raster")
        self.image = image.convert("L")
        self.qimage = pil_to_qimage(self.image)
        self.w, self.h = float(width_mm), float(height_mm)
        self.dither = True
        self.threshold = 128
        self.invert = False

    def local_rect(self) -> QRectF:
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def boundingRect(self) -> QRectF:
        return self.local_rect()

    def outline_contours(self) -> Contours:
        r = self.local_rect()
        pts = np.array([(r.left(), r.top()), (r.right(), r.top()), (r.right(), r.bottom()), (r.left(), r.bottom())])
        return transform([Contour(pts, True)], self.world_matrix())

    def paint_content(self, painter: QPainter, thumbnail: bool = False, for_raster: bool = False) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        img = self.qimage
        if self.invert:
            img = img.copy()
            img.invertPixels()
        painter.drawImage(self.local_rect(), img)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        self.paint_content(painter)
        if option.state & QStyle.StateFlag.State_Selected:
            pen = QPen(QColor(style.YELLOW), 3)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.local_rect())

    def to_dict(self, embed: bool = False) -> dict:
        d = self.base_dict()
        d.update(w=self.w, h=self.h, dither=self.dither, threshold=self.threshold, invert=self.invert)
        if embed:
            buf = io.BytesIO()
            self.image.save(buf, "PNG")
            d["png"] = base64.b64encode(buf.getvalue()).decode("ascii")
        else:
            d["image_ref"] = self.image
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RasterItem":
        if "image_ref" in d:
            img = d["image_ref"]
        else:
            img = Image.open(io.BytesIO(base64.b64decode(d["png"])))
        item = cls(img, d["w"], d["h"], d.get("name", ""))
        item.load_base(d)
        item.dither = d.get("dither", True)
        item.threshold = d.get("threshold", 128)
        item.invert = d.get("invert", False)
        return item


class RegionItem(VectorItem):
    """Область раскроя (свободный участок материала) или запретная зона. В задание не попадает."""

    kind = "region"
    is_output = False

    def __init__(self, contours, name: str = "", forbidden: bool = False, centered=False):
        self.forbidden = forbidden
        super().__init__(contours, name or ("Запретная зона" if forbidden else "Область раскроя"),
                         "cut", centered=centered)
        self.setZValue(-10)

    def paint_content(self, painter: QPainter, thumbnail: bool = False, for_raster: bool = False) -> None:
        color = QColor(style.RED if self.forbidden else style.YELLOW)
        pen = QPen(color.darker(130), 1.6 if thumbnail else 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(70)
        brush = QBrush(fill, Qt.BrushStyle.BDiagPattern if self.forbidden else Qt.BrushStyle.SolidPattern)
        brush.setTransform(QTransform.fromScale(0.2, 0.2))
        painter.setBrush(brush)
        painter.drawPath(self.path())

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["forbidden"] = self.forbidden
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RegionItem":
        parts = [[Contour.from_list(c) for c in part] for part in d["parts"]]
        item = cls(parts, d.get("name", ""), d.get("forbidden", False), centered=True)
        item.load_base(d)
        return item


def item_from_dict(d: dict) -> N40Item:
    return {"vector": VectorItem, "raster": RasterItem, "region": RegionItem}[d["kind"]].from_dict(d)


def clone_from_dict(d: dict) -> N40Item:
    """Новый объект по описанию (с новым uid) — для копий и вставки из буфера обмена."""
    new = item_from_dict(d)
    new.uid = uuid.uuid4().hex[:8]
    return new


def clone_item(item: N40Item) -> N40Item:
    return clone_from_dict(item.to_dict())


def items_bbox(items) -> QRectF:
    r = QRectF()
    for it in items:
        r = r.united(it.world_rect()) if not r.isNull() else it.world_rect()
    return r
