"""Планировщик траекторий: из операций (векторы/растр в мм) строит задание в шагах контроллера.

Порядок: растровая гравировка → векторная гравировка → резка.
Внутри резки внутренние контуры режутся раньше внешних (деталь не выпадает до вырезки отверстий),
в пределах одного уровня вложенности — обход «ближайший сосед».
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Point, Polygon

from .geometry import Contour

MM_PER_STEP = 0.0254  # 1 шаг K40 = 1/1000 дюйма


def mm_to_steps(v: float) -> int:
    return int(round(v / MM_PER_STEP))


@dataclass
class RasterData:
    bitmap: np.ndarray           # bool (H, W): True — жечь
    x0: float                    # мм, левый верхний угол
    y0: float
    step_mm: float               # шаг строк и пикселей, мм


@dataclass
class Operation:
    kind: str                    # "raster" | "engrave" | "cut"
    speed: float                 # мм/с
    passes: int = 1
    contours: list[Contour] = field(default_factory=list)
    raster: RasterData | None = None
    name: str = ""


@dataclass
class Program:
    """Один блок задания с постоянной скоростью. moves — (x, y, laser_on) в шагах."""
    speed: float
    moves: list[tuple[int, int, bool]]
    raster_step: int = 0
    name: str = ""


_ORDER = {"raster": 0, "engrave": 1, "cut": 2}


def plan(operations: list[Operation], start=(0, 0)) -> list[Program]:
    programs: list[Program] = []
    pos = start
    for op in sorted(operations, key=lambda o: _ORDER.get(o.kind, 9)):
        for _ in range(max(1, op.passes)):
            if op.kind == "raster" and op.raster is not None:
                moves = _raster_moves(op.raster)
            else:
                moves = _vector_moves(op.contours, pos, inner_first=op.kind == "cut")
            if moves:
                programs.append(Program(op.speed, moves, name=op.name))
                pos = moves[-1][:2]
    return programs


# --------------------------------------------------------------------------- вектор

def _nesting_depth(contours: list[Contour]) -> list[int]:
    polys = [Polygon(c.points) if c.closed and len(c.points) >= 3 else None for c in contours]
    depth = []
    for i, c in enumerate(contours):
        p = Point(c.points[0])
        d = 0
        for j, other in enumerate(polys):
            if j != i and other is not None and other.is_valid and other.contains(p):
                d += 1
        depth.append(d)
    return depth


def _vector_moves(contours: list[Contour], start, inner_first: bool) -> list[tuple[int, int, bool]]:
    items = [c for c in contours if len(c.points) >= 2]
    if not items:
        return []
    depth = _nesting_depth(items) if inner_first else [0] * len(items)
    moves: list[tuple[int, int, bool]] = []
    cur = np.array(start, dtype=float) * MM_PER_STEP
    for level in sorted(set(depth), reverse=True):
        pool = [c for c, d in zip(items, depth) if d == level]
        while pool:
            best_i, best_d, best_shift, best_rev = 0, float("inf"), 0, False
            for i, c in enumerate(pool):
                if c.closed:
                    d = np.sum((c.points - cur) ** 2, axis=1)
                    k = int(np.argmin(d))
                    if d[k] < best_d:
                        best_i, best_d, best_shift, best_rev = i, float(d[k]), k, False
                else:
                    for rev, pt in ((False, c.points[0]), (True, c.points[-1])):
                        d = float(np.sum((pt - cur) ** 2))
                        if d < best_d:
                            best_i, best_d, best_shift, best_rev = i, d, 0, rev
            c = pool.pop(best_i)
            pts = c.points
            if c.closed:
                pts = np.roll(pts, -best_shift, axis=0)
                pts = np.vstack([pts, pts[:1]])
            elif best_rev:
                pts = pts[::-1]
            steps = np.rint(pts / MM_PER_STEP).astype(int)
            moves.append((int(steps[0, 0]), int(steps[0, 1]), False))
            for x, y in steps[1:]:
                if (x, y) != moves[-1][:2]:
                    moves.append((int(x), int(y), True))
            cur = pts[-1]
    return moves


# --------------------------------------------------------------------------- растр

def _raster_moves(r: RasterData) -> list[tuple[int, int, bool]]:
    """Построчная гравировка «змейкой»: только строки, где есть что жечь."""
    moves: list[tuple[int, int, bool]] = []
    h, w = r.bitmap.shape
    forward = True
    for row in range(h):
        line = r.bitmap[row]
        if not line.any():
            continue
        y = mm_to_steps(r.y0 + (row + 0.5) * r.step_mm)
        padded = np.concatenate([[False], line, [False]])
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        runs = list(zip(edges[::2], edges[1::2]))  # [start, end) в пикселях
        if not forward:
            runs = [(e, s) for s, e in reversed(runs)]
        for a, b in runs:
            xa = mm_to_steps(r.x0 + a * r.step_mm)
            xb = mm_to_steps(r.x0 + b * r.step_mm)
            moves.append((xa, y, False))
            moves.append((xb, y, True))
        forward = not forward
    return moves


def job_bounds(programs: list[Program]) -> tuple[int, int, int, int] | None:
    pts = [(x, y) for p in programs for x, y, _ in p.moves]
    if not pts:
        return None
    a = np.array(pts)
    return int(a[:, 0].min()), int(a[:, 1].min()), int(a[:, 0].max()), int(a[:, 1].max())


def estimate_time(programs: list[Program], start=(0, 0)) -> float:
    """Грубая оценка длительности, с."""
    t = 0.0
    pos = np.array(start, dtype=float)
    for p in programs:
        for x, y, _ in p.moves:
            d = float(np.hypot(x - pos[0], y - pos[1])) * MM_PER_STEP
            t += d / max(p.speed, 0.1)
            pos = np.array((x, y), dtype=float)
    return t
