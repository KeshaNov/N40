"""Сборка задания: объекты сцены -> операции ядра (векторы в мм, растр — битовая карта)."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QTransform

from ..core.planner import Operation, RasterData
from .items import N40Item, RasterItem, VectorItem

MAX_RASTER_PX = 12000


def render_bitmap(item: N40Item, step_mm: float) -> RasterData | None:
    """Растеризует объект в мировых координатах с шагом step_mm. True — жечь."""
    r = item.world_rect()
    if r.width() <= 0 or r.height() <= 0:
        return None
    w = min(MAX_RASTER_PX, int(math.ceil(r.width() / step_mm)))
    h = min(MAX_RASTER_PX, int(math.ceil(r.height() / step_mm)))
    img = QImage(w, h, QImage.Format.Format_Grayscale8)
    img.fill(Qt.GlobalColor.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, isinstance(item, VectorItem))
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    view = QTransform()
    view.scale(1 / step_mm, 1 / step_mm)
    view.translate(-r.left(), -r.top())
    p.setTransform(item.sceneTransform() * view)
    item.paint_content(p, for_raster=True)
    p.end()

    ptr = img.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine())[:, :w].copy()
    if isinstance(item, RasterItem) and item.dither:
        bw = np.array(Image.fromarray(arr).convert("1"), dtype=bool)  # Floyd–Steinberg
        burn = ~bw
    else:
        thr = item.threshold if isinstance(item, RasterItem) else 128
        burn = arr < thr
    # область вне изображения (поворот) остаётся белой и не жжётся
    return RasterData(burn, r.left(), r.top(), step_mm)


def build_operations(items: list[N40Item], settings) -> list[Operation]:
    groups: dict[tuple, Operation] = {}
    ops: list[Operation] = []
    for it in items:
        if not it.is_output or not it.isVisible():
            continue
        default = {"cut": settings.cut_speed, "engrave": settings.engrave_speed,
                   "raster": settings.raster_speed}[it.mode]
        speed = it.speed or default
        if it.mode == "raster":
            data = render_bitmap(it, settings.raster_step)
            if data is not None and data.bitmap.any():
                ops.append(Operation("raster", speed, it.passes, raster=data, name=it.name))
            continue
        if not isinstance(it, VectorItem):
            continue
        key = (it.mode, round(speed, 3), it.passes)
        op = groups.get(key)
        if op is None:
            op = groups[key] = Operation(it.mode, speed, it.passes, name=it.name)
            ops.append(op)
        op.contours.extend(it.world_contours())
    return ops
