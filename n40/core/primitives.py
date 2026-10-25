"""Генераторы примитивов. Все размеры в мм, кривые аппроксимируются с допуском TOL."""

from __future__ import annotations

import math

import numpy as np

from .geometry import Contour, Contours, matrix_rotate, matrix_translate, transform

TOL = 0.02  # максимальное отклонение хорды от дуги, мм


def _arc_segments(radius: float, sweep_rad: float) -> int:
    if radius <= TOL:
        return 4
    step = 2 * math.acos(max(-1.0, 1 - TOL / radius))
    return max(8, int(math.ceil(abs(sweep_rad) / step)))


def rectangle(x: float, y: float, w: float, h: float, radius: float = 0.0) -> Contours:
    if radius <= 0:
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        return [Contour(np.array(pts), True)]
    r = min(radius, w / 2, h / 2)
    n = max(2, _arc_segments(r, math.pi / 2))
    pts = []
    corners = [(x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)]
    for cx, cy, start in corners:
        for i in range(n + 1):
            a = math.radians(start + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return [Contour(np.array(pts), True)]


def ellipse(cx: float, cy: float, rx: float, ry: float) -> Contours:
    # кратно 4, чтобы вершины попадали точно в крайние точки и габарит совпадал с размером
    n = -(-_arc_segments(max(rx, ry), 2 * math.pi) // 4) * 4
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return [Contour(np.column_stack([cx + rx * np.cos(t), cy + ry * np.sin(t)]), True)]


def circle(cx: float, cy: float, r: float) -> Contours:
    return ellipse(cx, cy, r, r)


def line(x1: float, y1: float, x2: float, y2: float) -> Contours:
    return [Contour(np.array([(x1, y1), (x2, y2)]), False)]


def polygon(points, closed: bool = True) -> Contours:
    return [Contour(np.array(points, dtype=float), closed)]


def regular_polygon(cx: float, cy: float, r: float, n: int, rotation_deg: float = -90.0) -> Contours:
    """Правильный N-угольник, вписанный в окружность радиуса r. По умолчанию вершина сверху."""
    n = max(3, int(n))
    t = np.radians(rotation_deg) + np.arange(n) * 2 * math.pi / n
    return [Contour(np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)]), True)]


def star(cx: float, cy: float, r_outer: float, r_inner: float, n: int) -> Contours:
    n = max(3, int(n))
    t = np.radians(-90) + np.arange(2 * n) * math.pi / n
    r = np.where(np.arange(2 * n) % 2 == 0, r_outer, r_inner)
    return [Contour(np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)]), True)]


# --------------------------------------------------------------------------- массивы

def linear_array(contours: Contours, count_x: int, count_y: int, step_x: float, step_y: float) -> list[Contours]:
    """Линейный (прямоугольный) массив копий. Возвращает список наборов контуров (первый — оригинал)."""
    out = []
    for j in range(max(1, count_y)):
        for i in range(max(1, count_x)):
            out.append(transform(contours, matrix_translate(i * step_x, j * step_y)))
    return out


def circular_array(contours: Contours, count: int, cx: float, cy: float,
                   total_angle: float = 360.0, rotate_copies: bool = True) -> list[Contours]:
    """Круговой массив вокруг центра (cx, cy)."""
    count = max(1, count)
    full = abs(total_angle - 360.0) < 1e-6
    step = total_angle / (count if full else max(1, count - 1))
    out = []
    from .geometry import bbox
    bb = bbox(contours)
    ox, oy = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2) if bb else (0.0, 0.0)
    for k in range(count):
        a = step * k
        if rotate_copies:
            out.append(transform(contours, matrix_rotate(a, cx, cy)))
        else:
            # сдвигаем копию без поворота: центр копии идёт по окружности
            rot = matrix_rotate(a, cx, cy)
            nx, ny = (rot @ np.array([ox, oy, 1.0]))[:2]
            out.append(transform(contours, matrix_translate(nx - ox, ny - oy)))
    return out
