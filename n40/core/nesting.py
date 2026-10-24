"""Нестинг (раскрой) деталей на листе или в произвольной свободной области.

Алгоритм — жадная раскладка «вверх-влево» (Y вниз, как у K40) на базе shapely:
1. Детали сортируются по убыванию площади.
2. Свободная область = контейнер − объединение уже размещённых деталей (с зазором).
   Отверстия размещённых деталей остаются свободными, поэтому мелкие детали
   попадают внутрь вырезов крупных.
3. Для каждого допустимого угла поворота перебираются позиции-кандидаты:
   совмещение углов габарита детали с вершинами свободной области плюс
   регулярная сетка; выбирается позиция с минимальным (y, x).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from shapely import affinity, prepared
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .geometry import Contours, fill_polygon_holes, iter_polygons, to_shapely


class NestCancelled(Exception):
    pass


@dataclass
class NestPart:
    key: object               # идентификатор исходного объекта
    contours: Contours        # мировые координаты, мм
    copies: int = 1


@dataclass
class NestParams:
    sheet_width: float = 300.0
    sheet_height: float = 200.0
    gap: float = 2.0                 # зазор между деталями, мм
    margin: float = 5.0              # отступ от края листа, мм
    angles: list[float] = field(default_factory=lambda: [0.0, 90.0, 180.0, 270.0])
    use_holes: bool = True           # размещать детали в отверстиях
    grid_step: float = 0.0           # шаг сетки кандидатов, 0 — авто
    container: BaseGeometry | None = None  # свободная область (раскрой по фото); None — прямоугольный лист
    forbidden: list[BaseGeometry] = field(default_factory=list)  # запретные зоны


@dataclass
class Placement:
    key: object
    copy_index: int
    angle: float
    # Аффинное преобразование исходных координат детали: сначала поворот вокруг (0,0), затем сдвиг
    dx: float
    dy: float


@dataclass
class NestResult:
    placements: list[Placement]
    unplaced: list[tuple[object, int]]
    utilization: float          # K, %
    parts_area: float
    sheet_area: float


def angles_from_step(step: float) -> list[float]:
    step = max(1.0, float(step))
    return [round(a, 6) for a in np.arange(0.0, 360.0 - 1e-9, step)]


def nest(parts: list[NestPart], params: NestParams,
         progress: Callable[[int, int], None] | None = None,
         is_cancelled: Callable[[], bool] | None = None) -> NestResult:
    if params.container is not None:
        container = params.container
    else:
        container = box(0, 0, params.sheet_width, params.sheet_height)
    sheet_area = float(container.area)
    if params.margin > 0:
        container = container.buffer(-params.margin, join_style=2)
    for zone in params.forbidden:
        container = container.difference(zone)

    jobs = []
    for part in parts:
        geom = to_shapely(part.contours, fill_holes=not params.use_holes)
        if geom.is_empty:
            continue
        for i in range(max(1, part.copies)):
            jobs.append((part, i, geom))
    jobs.sort(key=lambda j: -j[2].area)

    free = container
    placements: list[Placement] = []
    unplaced: list[tuple[object, int]] = []
    parts_area = 0.0
    rotated_cache: dict[tuple[int, float], tuple[BaseGeometry, BaseGeometry]] = {}
    origin = container.bounds[:2] if not container.is_empty else (0.0, 0.0)
    envelope = None  # габарит уже размещённых деталей

    total = len(jobs)
    for n, (part, copy_index, geom) in enumerate(jobs):
        if is_cancelled and is_cancelled():
            raise NestCancelled()
        if progress:
            progress(n, total)
        best = None
        free_prep = prepared.prep(free)
        free_bounds = free.bounds if not free.is_empty else None
        if free_bounds is None:
            unplaced.append((part.key, copy_index))
            continue
        for angle in params.angles:
            ck = (id(part), angle)
            if ck not in rotated_cache:
                rot = affinity.rotate(geom, angle, origin=(0, 0)) if angle else geom
                # Зазор учитывается в свободной области (размещённые детали раздуты на gap)
                rotated_cache[ck] = (rot, rot)
            rot, test = rotated_cache[ck]
            pos = _find_position(test, free, free_prep, free_bounds, params.grid_step,
                                 origin, envelope, is_cancelled)
            if pos is None:
                continue
            dx, dy, score = pos
            if best is None or score < best[0]:
                best = (score, angle, dx, dy, rot, test)
        if best is None:
            unplaced.append((part.key, copy_index))
            continue
        _, angle, dx, dy, rot, test = best
        # Свободная область уменьшается на деталь с полным зазором вокруг
        blocker = affinity.translate(rot, dx, dy)
        if params.gap > 0:
            blocker = blocker.buffer(params.gap, join_style=2)
        if not params.use_holes:
            blocker = fill_polygon_holes(blocker)
        free = free.difference(blocker)
        b = affinity.translate(rot, dx, dy).bounds
        envelope = b if envelope is None else (min(envelope[0], b[0]), min(envelope[1], b[1]),
                                               max(envelope[2], b[2]), max(envelope[3], b[3]))
        placements.append(Placement(part.key, copy_index, angle, dx, dy))
        parts_area += geom.area

    if progress:
        progress(total, total)
    util = parts_area / sheet_area * 100.0 if sheet_area > 0 else 0.0
    return NestResult(placements, unplaced, util, parts_area, sheet_area)


def _find_position(test: BaseGeometry, free: BaseGeometry, free_prep, free_bounds,
                   grid_step: float, origin, envelope, is_cancelled) -> tuple[float, float, tuple] | None:
    """Сдвиг, при котором test целиком лежит в free и габарит раскладки растёт меньше всего.

    Кандидаты проверяются в порядке (площадь общего габарита от угла листа, y, x), поэтому
    позиции внутри отверстий и пустот уже размещённых деталей (рост = 0) пробуются первыми.
    """
    tminx, tminy, tmaxx, tmaxy = test.bounds
    tw, th = tmaxx - tminx, tmaxy - tminy
    fminx, fminy, fmaxx, fmaxy = free_bounds
    if tw > fmaxx - fminx + 1e-9 or th > fmaxy - fminy + 1e-9:
        return None

    cands: list[tuple[float, float]] = []
    # 1) вершины свободной области -> углы габарита детали
    verts = []
    for poly in iter_polygons(free):
        verts.append(np.asarray(poly.exterior.coords))
        verts.extend(np.asarray(r.coords) for r in poly.interiors)
    if verts:
        v = np.vstack(verts)
        if len(v) > 4000:
            v = v[:: int(math.ceil(len(v) / 4000))]
        for ox, oy in ((tminx, tminy), (tmaxx, tminy), (tminx, tmaxy), (tmaxx, tmaxy)):
            cands.extend(zip(v[:, 0] - ox, v[:, 1] - oy))
    # 2) регулярная сетка
    step = grid_step if grid_step > 0 else max(1.0, min(tw, th) / 3.0, (fmaxx - fminx) / 150.0)
    xs = np.arange(fminx - tminx, fmaxx - tmaxx + 1e-9, step)
    ys = np.arange(fminy - tminy, fmaxy - tmaxy + 1e-9, step)
    if len(xs) and len(ys):
        gx, gy = np.meshgrid(xs, ys)
        cands.extend(zip(gx.ravel(), gy.ravel()))

    arr = np.array(cands, dtype=float)
    if not len(arr):
        return None
    # отбрасываем кандидатов, где габарит выходит за пределы свободной области
    ok = (arr[:, 0] + tminx >= fminx - 1e-6) & (arr[:, 0] + tmaxx <= fmaxx + 1e-6) & \
         (arr[:, 1] + tminy >= fminy - 1e-6) & (arr[:, 1] + tmaxy <= fmaxy + 1e-6)
    arr = np.unique(np.round(arr[ok], 4), axis=0)
    if not len(arr):
        return None
    ox, oy = origin
    ex = arr[:, 0] + tmaxx
    ey = arr[:, 1] + tmaxy
    if envelope is not None:
        ex = np.maximum(ex, envelope[2])
        ey = np.maximum(ey, envelope[3])
    area = np.round((ex - ox) * (ey - oy), 2)
    order = np.lexsort((arr[:, 0], arr[:, 1], area))
    for idx_i, idx in enumerate(order):
        if is_cancelled and idx_i % 200 == 0 and is_cancelled():
            raise NestCancelled()
        dx, dy = arr[idx]
        if free_prep.contains(affinity.translate(test, dx, dy)):
            return float(dx), float(dy), (float(area[idx]), float(dy), float(dx))
    return None
