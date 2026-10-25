"""Кодировщик протокола LHYMICRO-GL (контроллеры Lihuiyu M2 Nano и совместимые).

Реализация написана по описанию протокола из открытых проектов MeerK40t (MIT)
и K40 Whisperer (GPL-3.0); код не скопирован, а переписан с нуля.

ВНИМАНИЕ: протокол не документирован производителем. Перед работой на реальном
станке сравните вывод с K40 Whisperer (экспорт .EGV) и проверьте на малой мощности.

Команды (в «компактном» режиме):
    B / T — движение по X вправо / влево
    R / L — движение по Y вниз / вверх (Y вниз — от домашней позиции)
    M     — диагональ (направления берутся из последних B/T и R/L)
    D / U — лазер включить / выключить
Расстояние после команды: ''=0, a..y = 1..25, |a..|z = 26..51, 'NNN' = 52..254, 'z' = 255 (повторяется).
"""

from __future__ import annotations

from ..planner import Program

CODE_RIGHT = "B"
CODE_LEFT = "T"
CODE_BOTTOM = "R"
CODE_TOP = "L"
CODE_ANGLE = "M"
CODE_ON = "D"
CODE_OFF = "U"

CMD_HOME = "IPP\n"
CMD_UNLOCK = "IS2P\n"
CMD_STOP = "I*\n"
CMD_PAUSE = "PN!\n"
CMD_RESUME = "PN&\n"

_LOOKUP = [""] + [chr(ord("a") + i) for i in range(25)] + ["|" + chr(ord("a") + i) for i in range(26)]


def encode_distance(v: int) -> str:
    if v < 0:
        raise ValueError("Расстояние не может быть отрицательным")
    out = "z" * (v // 255)
    v %= 255
    if v >= 52:
        return out + "%03d" % v
    return out + _LOOKUP[v]


# --------------------------------------------------------------------------- скорость

# Таймер контроллера: значение = 65536 − (m · период_мс + b), где период — время одного шага
_GEARING = {
    # плата: (b, m)
    "M3": (8.0, 12120.0),   # M3 Nano (Zareff 3020): обновлённая M2, кодирование скорости то же
    "M2": (8.0, 12120.0),
    "M1": (8.0, 12120.0),
    "M": (8.0, 12120.0),
    "B2": (8.0, 12120.0),
    "A": (64.0, 11148.0),
    "B": (64.0, 11148.0),
    "B1": (64.0, 11148.0),
}

MIN_SPEED = 5.0     # мм/с — ниже 16-битный таймер переполняется (нужен отдельный режим)
MAX_SPEED = 500.0


def _encode16(v: int) -> str:
    v = max(0, min(65535, int(v)))
    return "%03d%03d" % ((v >> 8) & 0xFF, v & 0xFF)


def _gear(speed: float) -> int:
    if speed < 25.4:
        return 1
    if speed < 60:
        return 2
    if speed < 127:
        return 3
    return 4


def speed_code(speed: float, board: str = "M2", raster_step: int = 0) -> str:
    """Код скорости: 'CV<16бит><шестерня>000000000C' (вектор) или 'V<16бит><шестерня>G<шаг>' (растр)."""
    speed = max(MIN_SPEED, min(MAX_SPEED, float(speed)))
    b, m = _GEARING.get(board, _GEARING["M2"])
    period_ms = 25.4 / speed  # 1 шаг = 0.0254 мм -> частота шагов = speed/0.0254 Гц
    value = 65536 - round(m * period_ms + b)
    gear = _gear(speed)
    if raster_step:
        return "V%s%dG%03d" % (_encode16(value), gear, raster_step)
    suffix = "C" if board.startswith("M") else ""
    return "CV%s%d000000000%s" % (_encode16(value), gear, suffix)


# --------------------------------------------------------------------------- движения

class LhyEncoder:
    """Строит поток команд для одного программного блока (компактный режим)."""

    def __init__(self, x: int, y: int):
        self.x, self.y = x, y
        self.right = True
        self.bottom = True
        self.laser = False
        self.out: list[str] = []

    def _set_laser(self, on: bool) -> None:
        if on != self.laser:
            self.out.append(CODE_ON if on else CODE_OFF)
            self.laser = on

    def _move_x(self, dx: int) -> None:
        if dx == 0:
            return
        self.right = dx > 0
        self.out.append((CODE_RIGHT if self.right else CODE_LEFT) + encode_distance(abs(dx)))

    def _move_y(self, dy: int) -> None:
        if dy == 0:
            return
        self.bottom = dy > 0
        self.out.append((CODE_BOTTOM if self.bottom else CODE_TOP) + encode_distance(abs(dy)))

    def _move_diag(self, dx: int, dy: int, n: int) -> None:
        r, bt = dx > 0, dy > 0
        if r != self.right:
            self.out.append(CODE_RIGHT if r else CODE_LEFT)
            self.right = r
        if bt != self.bottom:
            self.out.append(CODE_BOTTOM if bt else CODE_TOP)
            self.bottom = bt
        self.out.append(CODE_ANGLE + encode_distance(n))

    def line_to(self, x: int, y: int, on: bool) -> None:
        """Прямая из текущей точки, разложенная Брезенхэмом на серии прямых и диагональных шагов."""
        self._set_laser(on)
        dx, dy = x - self.x, y - self.y
        if dx == 0 and dy == 0:
            return
        if dx == 0:
            self._move_y(dy)
        elif dy == 0:
            self._move_x(dx)
        elif abs(dx) == abs(dy):
            self._move_diag(dx, dy, abs(dx))
        else:
            self._bresenham(dx, dy)
        self.x, self.y = x, y

    def _bresenham(self, dx: int, dy: int) -> None:
        sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
        ax, ay = abs(dx), abs(dy)
        x_major = ax >= ay
        major, minor = (ax, ay) if x_major else (ay, ax)
        err = major // 2
        run_kind, run_len = None, 0
        for _ in range(major):
            err -= minor
            if err < 0:
                err += major
                kind = "d"
            else:
                kind = "s"
            if kind == run_kind:
                run_len += 1
            else:
                self._flush(run_kind, run_len, sx, sy, x_major)
                run_kind, run_len = kind, 1
        self._flush(run_kind, run_len, sx, sy, x_major)

    def _flush(self, kind, n, sx, sy, x_major) -> None:
        if not kind or n == 0:
            return
        if kind == "d":
            self._move_diag(sx, sy, n)
        elif x_major:
            self._move_x(sx * n)
        else:
            self._move_y(sy * n)

    def text(self) -> str:
        return "".join(self.out)


def rapid_move(dx: int, dy: int) -> str:
    """Быстрое перемещение (лазер выключен) вне компактного режима."""
    s = "I"
    if dx:
        s += (CODE_RIGHT if dx > 0 else CODE_LEFT) + encode_distance(abs(dx))
    if dy:
        s += (CODE_BOTTOM if dy > 0 else CODE_TOP) + encode_distance(abs(dy))
    return s + "S1P\n"


def encode_program(program: Program, x: int, y: int, board: str = "M2") -> tuple[str, int, int]:
    """Кодирует блок задания, начинающийся в (x, y). Возвращает (команды, x_конец, y_конец).

    Перед блоком головка подводится быстрым перемещением к первой точке.
    """
    if not program.moves:
        return "", x, y
    fx, fy, _ = program.moves[0]
    parts = []
    if (fx, fy) != (x, y):
        parts.append(rapid_move(fx - x, fy - y))
    enc = LhyEncoder(fx, fy)
    for mx, my, on in program.moves[1:]:
        enc.line_to(mx, my, on)
    enc._set_laser(False)
    parts.append("I" + speed_code(program.speed, board) + "N" + CODE_BOTTOM + CODE_RIGHT + "S1E")
    parts.append(enc.text())
    parts.append("FNSE-\n")
    return "".join(parts), enc.x, enc.y


def encode_job(programs: list[Program], board: str = "M2", return_home: bool = True) -> list[str]:
    """Полное задание как список команд (каждую можно отправлять отдельно, дожидаясь завершения)."""
    x = y = 0
    cmds = []
    for p in programs:
        text, x, y = encode_program(p, x, y, board)
        if text:
            cmds.append(text)
    if return_home and (x or y):
        cmds.append(rapid_move(-x, -y))
    return cmds


EGV_HEADER = ("Document type : LHYMICRO-GL file\n"
              "File version: 1.0.01\n"
              "Copyright: Unknown\n"
              "Creator-Software: N40\n\n"
              "%0%0%0%0%")


def to_egv(cmds: list[str]) -> str:
    return EGV_HEADER + "".join(cmds)
