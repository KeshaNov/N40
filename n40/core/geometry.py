"""Базовая геометрия: контуры в мм, аффинные преобразования, булевы операции, смещения.

Система координат как у K40: начало в левом верхнем углу, ось Y направлена вниз.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence

import numpy as np
import pyclipper
from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass
class Contour:
    """Ломаная линия в мм. closed=True — замкнутый контур (последняя точка не дублирует первую)."""

    points: np.ndarray  # (N, 2) float64
    closed: bool = True

    def __post_init__(self) -> None:
        pts = np.asarray(self.points, dtype=float).reshape(-1, 2)
        if self.closed and len(pts) > 2 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        self.points = pts

    def copy(self) -> "Contour":
        return Contour(self.points.copy(), self.closed)

    def closed_points(self) -> np.ndarray:
        """Точки с замыканием (для отрисовки и резки)."""
        if self.closed and len(self.points) > 1:
            return np.vstack([self.points, self.points[:1]])
        return self.points

    def length(self) -> float:
        pts = self.closed_points()
        if len(pts) < 2:
            return 0.0
        return float(np.sum(np.hypot(*np.diff(pts, axis=0).T)))

    def to_list(self) -> dict:
        return {"points": self.points.round(5).tolist(), "closed": self.closed}

    @classmethod
    def from_list(cls, data: dict) -> "Contour":
        return cls(np.array(data["points"], dtype=float), bool(data["closed"]))


Contours = List[Contour]  # typing.List: сборка под Windows 7 на Python 3.8


# --------------------------------------------------------------------------- bbox / transforms

def bbox(contours: Iterable[Contour]) -> tuple[float, float, float, float] | None:
    """(minx, miny, maxx, maxy) или None для пустого набора."""
    pts = [c.points for c in contours if len(c.points)]
    if not pts:
        return None
    allp = np.vstack(pts)
    return float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()), float(allp[:, 1].max())


def matrix_translate(dx: float, dy: float) -> np.ndarray:
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=float)


def matrix_scale(sx: float, sy: float, cx: float = 0.0, cy: float = 0.0) -> np.ndarray:
    return matrix_translate(cx, cy) @ np.diag([sx, sy, 1.0]) @ matrix_translate(-cx, -cy)


def matrix_rotate(angle_deg: float, cx: float = 0.0, cy: float = 0.0) -> np.ndarray:
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    return matrix_translate(cx, cy) @ rot @ matrix_translate(-cx, -cy)


def transform(contours: Iterable[Contour], m: np.ndarray) -> Contours:
    out = []
    for c in contours:
        pts = c.points
        if len(pts):
            pts = pts @ m[:2, :2].T + m[:2, 2]
        out.append(Contour(pts, c.closed))
    return out


def translate(contours: Iterable[Contour], dx: float, dy: float) -> Contours:
    return [Contour(c.points + (dx, dy), c.closed) for c in contours]


def center_contours(contours: Contours) -> tuple[Contours, float, float]:
    """Сдвигает контуры так, чтобы центр их габарита был в (0,0). Возвращает (контуры, cx, cy)."""
    bb = bbox(contours)
    if bb is None:
        return contours, 0.0, 0.0
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return translate(contours, -cx, -cy), cx, cy


# --------------------------------------------------------------------------- shapely conversion

def to_shapely(contours: Iterable[Contour], fill_holes: bool = False) -> BaseGeometry:
    """Замкнутые контуры -> (Multi)Polygon по правилу even-odd (отверстия сохраняются)."""
    geom: BaseGeometry = Polygon()
    for c in contours:
        if not c.closed or len(c.points) < 3:
            continue
        poly = Polygon(c.points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        geom = unary_union([geom, poly]) if fill_holes else geom.symmetric_difference(poly)
    if fill_holes:
        geom = fill_polygon_holes(geom)
    return geom


def fill_polygon_holes(geom: BaseGeometry) -> BaseGeometry:
    polys = list(iter_polygons(geom))
    return unary_union([Polygon(p.exterior) for p in polys]) if polys else Polygon()


def iter_polygons(geom: BaseGeometry) -> Iterable[Polygon]:
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, (MultiPolygon, GeometryCollection)):
        for g in geom.geoms:
            yield from iter_polygons(g)


def from_shapely(geom: BaseGeometry) -> Contours:
    out: Contours = []
    if geom is None or geom.is_empty:
        return out
    if isinstance(geom, LineString):
        return [Contour(np.array(geom.coords), closed=False)]
    if isinstance(geom, (MultiPolygon, GeometryCollection)) or hasattr(geom, "geoms"):
        for g in geom.geoms:
            out.extend(from_shapely(g))
        return out
    if isinstance(geom, Polygon):
        out.append(Contour(np.array(geom.exterior.coords), True))
        for ring in geom.interiors:
            out.append(Contour(np.array(ring.coords), True))
    return out


# --------------------------------------------------------------------------- boolean / offset

def boolean(op: str, shapes: Sequence[Contours]) -> Contours:
    """op: 'union' | 'difference' | 'intersection' | 'xor'. Для difference из первого вычитаются остальные."""
    geoms = [to_shapely(s) for s in shapes]
    geoms = [g for g in geoms if not g.is_empty]
    if not geoms:
        return []
    if op == "union":
        result = unary_union(geoms)
    elif op == "difference":
        result = geoms[0].difference(unary_union(geoms[1:])) if len(geoms) > 1 else geoms[0]
    elif op == "intersection":
        result = geoms[0]
        for g in geoms[1:]:
            result = result.intersection(g)
    elif op == "xor":
        result = geoms[0]
        for g in geoms[1:]:
            result = result.symmetric_difference(g)
    else:
        raise ValueError(op)
    return from_shapely(result)


_CLIPPER_SCALE = 1000.0  # мм -> мкм (целые для clipper)


def offset(contours: Contours, delta: float, join: str = "round") -> Contours:
    """Смещение замкнутых контуров на delta мм (наружу > 0) через pyclipper."""
    jt = {"round": pyclipper.JT_ROUND, "miter": pyclipper.JT_MITER, "square": pyclipper.JT_SQUARE}[join]
    pco = pyclipper.PyclipperOffset(2.0, 0.01 * _CLIPPER_SCALE)
    for c in contours:
        if len(c.points) < 2:
            continue
        path = pyclipper.scale_to_clipper(c.points.tolist(), _CLIPPER_SCALE)
        if c.closed:
            pco.AddPath(path, jt, pyclipper.ET_CLOSEDPOLYGON)
        else:
            pco.AddPath(path, jt, pyclipper.ET_OPENROUND)
    result = pco.Execute(delta * _CLIPPER_SCALE)
    return [Contour(np.array(pyclipper.scale_from_clipper(p, _CLIPPER_SCALE)), True) for p in result]


# --------------------------------------------------------------------------- сшивка контуров

def join_contours(contours: Contours, tol: float = 0.02) -> Contours:
    """Сшивает открытые ломаные с совпадающими концами (в пределах tol мм) в цепочки.

    CAD-программы (например, КОМПАС-3D) экспортируют контур детали как набор отдельных
    отрезков и сплайнов. Цепочка, конец которой совпал с началом, становится замкнутым контуром.
    """
    closed = [c for c in contours if c.closed]
    open_ = [c.points for c in contours if not c.closed and len(c.points) >= 2]
    if not open_:
        return list(contours)

    def key(p):
        return int(round(p[0] / tol)), int(round(p[1] / tol))

    ends: dict[tuple[int, int], set[int]] = {}
    for i, pts in enumerate(open_):
        for p in (pts[0], pts[-1]):
            ends.setdefault(key(p), set()).add(i)

    def find(p, used):
        kx, ky = key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in ends.get((kx + dx, ky + dy), ()):
                    if j in used:
                        continue
                    pts = open_[j]
                    if np.hypot(*(pts[0] - p)) <= tol:
                        return j, pts
                    if np.hypot(*(pts[-1] - p)) <= tol:
                        return j, pts[::-1]
        return None

    used: set[int] = set()
    out = list(closed)
    for i in range(len(open_)):
        if i in used:
            continue
        used.add(i)
        chain = [open_[i]]
        for forward in (True, False):  # наращиваем цепочку с конца, затем с начала
            while True:
                tip = chain[-1][-1] if forward else chain[0][0]
                if len(chain) > 1 or len(chain[0]) > 2:
                    head = chain[0][0] if forward else chain[-1][-1]
                    if np.hypot(*(tip - head)) <= tol:
                        break  # цепочка замкнулась
                hit = find(tip, used)
                if hit is None:
                    break
                j, pts = hit
                used.add(j)
                if forward:
                    chain.append(pts[1:])
                else:
                    chain.insert(0, pts[::-1][:-1])
        pts = np.vstack(chain)
        is_closed = len(pts) > 3 and np.hypot(*(pts[0] - pts[-1])) <= tol
        out.append(Contour(pts[:-1] if is_closed else pts, is_closed))
    return out


def outline_geometry(contours: Contours) -> BaseGeometry:
    """Площадная форма объекта для раскладки: замкнутые контуры плюс открытые линии
    (осевые, штриховка); если замкнутых нет совсем (только линии, например гравировка) —
    выпуклая оболочка всех точек."""
    geom = to_shapely(contours)
    if not geom.is_empty and geom.area > 1e-6:
        lines = [LineString(c.points).buffer(0.05, quad_segs=2) for c in contours
                 if not c.closed and len(c.points) >= 2]
        return unary_union([geom, *lines]) if lines else geom
    pts = [c.points for c in contours if len(c.points)]
    if not pts:
        return Polygon()
    from shapely.geometry import MultiPoint
    hull = MultiPoint(np.vstack(pts)).convex_hull
    return hull.buffer(0.05) if hull.area < 1e-6 else hull


# --------------------------------------------------------------------------- misc

def polygon_area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def contours_area(contours: Contours) -> float:
    return float(to_shapely(contours).area)


def nearest_vertex(contour_sets: Iterable[Contours], x: float, y: float, tol: float) -> tuple[float, float] | None:
    """Ближайший узел (вершина) в радиусе tol мм."""
    best, best_d = None, tol * tol
    for contours in contour_sets:
        for c in contours:
            if not len(c.points):
                continue
            d = np.sum((c.points - (x, y)) ** 2, axis=1)
            i = int(np.argmin(d))
            if d[i] < best_d:
                best_d, best = float(d[i]), (float(c.points[i, 0]), float(c.points[i, 1]))
    return best


def rotate_shapely(geom: BaseGeometry, angle: float) -> BaseGeometry:
    return affinity.rotate(geom, angle, origin=(0, 0))
