"""Импорт файлов: SVG (svgelements), DXF (ezdxf), растр (Pillow), PDF/AI (через Inkscape или растр QtPdf).

Результат импорта — список ImportedObject в мм, координаты Y вниз.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .geometry import Contour, Contours, join_contours

MM_PER_INCH = 25.4
FLATTEN_TOL = 0.02  # мм

VECTOR_EXT = {".svg", ".dxf"}
RASTER_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
DOC_EXT = {".pdf", ".ai"}
ALL_EXT = VECTOR_EXT | RASTER_EXT | DOC_EXT


class ImportError_(Exception):
    """Ошибка импорта с сообщением для пользователя."""


@dataclass
class ImportedObject:
    name: str
    kind: str                         # "vector" | "raster"
    contours: Contours = field(default_factory=list)
    image: Image.Image | None = None  # для raster
    width_mm: float = 0.0             # для raster
    height_mm: float = 0.0
    x_mm: float = 0.0                 # левый верхний угол
    y_mm: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportOptions:
    svg_dpi: float = 96.0       # 96 (Inkscape ≥0.92), 90 (старый Inkscape), 72 (Illustrator)
    scale: float = 1.0          # ручной масштаб
    raster_dpi: float | None = None  # None — из файла, иначе принудительно
    dxf_units_mm: float | None = None  # мм в одной единице DXF; None — определить автоматически


def import_file(path: str | Path, opts: ImportOptions | None = None) -> list[ImportedObject]:
    opts = opts or ImportOptions()
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".svg":
        objs = import_svg(path, opts)
    elif ext == ".dxf":
        objs = import_dxf(path, opts)
    elif ext in RASTER_EXT:
        objs = [import_raster(path, opts)]
    elif ext in DOC_EXT:
        objs = import_pdf(path, opts)
    else:
        raise ImportError_(f"Неподдерживаемый формат: {ext}")
    return objs


# --------------------------------------------------------------------------- SVG

def import_svg(path: Path, opts: ImportOptions) -> list[ImportedObject]:
    from svgelements import SVG, Path as SPath, Shape, Line, Move, Close, SVGText, SVGImage

    try:
        svg = SVG.parse(str(path), ppi=opts.svg_dpi, reify=True)
    except Exception as exc:  # noqa: BLE001 — svgelements бросает разное
        raise ImportError_(f"Не удалось прочитать SVG: {exc}") from exc

    # svgelements переводит всё (включая viewBox и единицы width/height) в пиксели с заданным ppi
    k = MM_PER_INCH / opts.svg_dpi * opts.scale
    contours: Contours = []
    warnings: list[str] = []
    texts = images = 0
    for el in svg.elements():
        if isinstance(el, SVGText):
            texts += 1
            continue
        if isinstance(el, SVGImage):
            images += 1
            continue
        if not isinstance(el, Shape):
            continue
        if el.values.get("visibility") == "hidden" or el.values.get("display") == "none":
            continue
        p = SPath(el)
        p.reify()
        current: list = []
        start = None

        def flush(closed: bool):
            nonlocal current
            if len(current) >= 2:
                contours.append(Contour(np.array(current) * k, closed and len(current) > 2))
            current = []

        for seg in p:
            if isinstance(seg, Move):
                flush(False)
                start = (seg.end.x, seg.end.y)
                current = [start]
            elif isinstance(seg, Close):
                flush(True)
                current = [start] if start else []
            elif isinstance(seg, Line):
                if not current:
                    current = [(seg.start.x, seg.start.y)]
                current.append((seg.end.x, seg.end.y))
            else:
                if not current:
                    current = [(seg.start.x, seg.start.y)]
                try:
                    length_mm = seg.length(error=1e-3) * k
                except Exception:  # noqa: BLE001
                    length_mm = 10.0
                n = max(4, int(length_mm / 0.25))
                pts = seg.npoint(np.linspace(0, 1, n + 1)[1:])
                current.extend(map(tuple, pts))
        flush(False)

    if texts:
        warnings.append(f"Пропущено текстовых элементов: {texts} (преобразуйте текст в кривые)")
    if images:
        warnings.append(f"Пропущено встроенных изображений: {images}")
    if not contours:
        raise ImportError_("В SVG не найдено векторных контуров")
    contours = join_contours(contours)
    return [ImportedObject(path.stem, "vector", contours, warnings=warnings)]


# --------------------------------------------------------------------------- DXF

_DXF_UNITS_MM = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4}
_IMPERIAL_UNITS = {1, 2, 8, 9, 10}


def dxf_units_mm(header) -> float:
    """Сколько мм в одной единице чертежа.

    КОМПАС-3D (и ряд других CAD) пишет $INSUNITS=1 («дюймы») при чертеже в миллиметрах,
    но правильно ставит $MEASUREMENT=1 (метрическая система). Если заголовок противоречит
    сам себе, доверяем $MEASUREMENT и считаем единицы миллиметрами.
    """
    units = int(header.get("$INSUNITS", 0) or 0)
    metric = int(header.get("$MEASUREMENT", 1) or 0) == 1
    if units in _IMPERIAL_UNITS and metric:
        return 1.0
    return _DXF_UNITS_MM.get(units, 1.0)


def import_dxf(path: Path, opts: ImportOptions) -> list[ImportedObject]:
    import ezdxf
    from ezdxf import disassemble, path as dxfpath

    try:
        doc = ezdxf.readfile(str(path))
    except (IOError, ezdxf.DXFStructureError) as exc:
        raise ImportError_(f"Не удалось прочитать DXF: {exc}") from exc

    unit_mm = opts.dxf_units_mm if opts.dxf_units_mm else dxf_units_mm(doc.header)
    k = unit_mm * opts.scale
    contours: Contours = []
    skipped = 0
    for entity in disassemble.recursive_decompose(doc.modelspace()):
        if entity.dxftype() in ("TEXT", "MTEXT", "HATCH", "DIMENSION", "POINT"):
            skipped += entity.dxftype() != "POINT"
            continue
        try:
            p = dxfpath.make_path(entity)
        except TypeError:
            continue
        for sub in p.sub_paths():
            pts = np.array([(v.x, v.y) for v in sub.flattening(FLATTEN_TOL / max(k, 1e-9))])
            if len(pts) < 2:
                continue
            closed = bool(sub.is_closed) or np.allclose(pts[0], pts[-1])
            contours.append(Contour(pts * k, closed))
    if not contours:
        raise ImportError_("В DXF не найдено поддерживаемых примитивов")
    contours = join_contours(contours)
    # DXF: ось Y вверх -> переворачиваем
    maxy = max(c.points[:, 1].max() for c in contours)
    for c in contours:
        c.points = np.column_stack([c.points[:, 0], maxy - c.points[:, 1]])
    warnings = [f"Пропущено текстов/штриховок/размеров: {skipped}"] if skipped else []
    return [ImportedObject(path.stem, "vector", contours, warnings=warnings)]


# --------------------------------------------------------------------------- растр

def import_raster(path: Path, opts: ImportOptions) -> ImportedObject:
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ImportError_(f"Не удалось открыть изображение: {exc}") from exc
    dpi = opts.raster_dpi
    if dpi is None:
        info_dpi = img.info.get("dpi")
        dpi = float(info_dpi[0]) if info_dpi and info_dpi[0] > 1 else 96.0
    img = _flatten_alpha(img)
    w_mm = img.width / dpi * MM_PER_INCH * opts.scale
    h_mm = img.height / dpi * MM_PER_INCH * opts.scale
    return ImportedObject(path.stem, "raster", image=img, width_mm=w_mm, height_mm=h_mm)


def _flatten_alpha(img: Image.Image) -> Image.Image:
    """Прозрачность -> белый фон, результат в оттенках серого."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    return img.convert("L")


# --------------------------------------------------------------------------- PDF / AI

def find_inkscape() -> str | None:
    exe = shutil.which("inkscape")
    if exe:
        return exe
    for candidate in (r"C:\Program Files\Inkscape\bin\inkscape.exe", r"C:\Program Files\Inkscape\inkscape.exe"):
        if Path(candidate).exists():
            return candidate
    return None


def import_pdf(path: Path, opts: ImportOptions) -> list[ImportedObject]:
    """PDF/AI: через Inkscape -> SVG (вектор), иначе растеризация первой страницы через QtPdf."""
    inkscape = find_inkscape()
    if inkscape:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / (path.stem + ".svg")
            try:
                subprocess.run([inkscape, str(path), "--pdf-poppler", "--export-type=svg",
                                f"--export-filename={out}"], check=True, timeout=120,
                               capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                objs = import_svg(out, ImportOptions(svg_dpi=96.0, scale=opts.scale))
                for o in objs:
                    o.name = path.stem
                return objs
            except (subprocess.SubprocessError, OSError, ImportError_):
                pass
    return [_rasterize_pdf(path, opts)]


def _rasterize_pdf(path: Path, opts: ImportOptions, dpi: float = 300.0) -> ImportedObject:
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    doc = QPdfDocument()
    doc.load(str(path))
    if doc.pageCount() < 1:
        raise ImportError_("Не удалось открыть PDF/AI (установите Inkscape для векторного импорта)")
    size_pt = doc.pagePointSize(0)
    px = QSize(int(size_pt.width() / 72 * dpi), int(size_pt.height() / 72 * dpi))
    qimg = doc.render(0, px)
    qimg = qimg.convertToFormat(qimg.Format.Format_RGBA8888)
    buf = bytes(qimg.constBits())
    img = Image.frombuffer("RGBA", (qimg.width(), qimg.height()), buf, "raw", "RGBA", qimg.bytesPerLine(), 1)
    img = _flatten_alpha(img.copy())
    obj = ImportedObject(path.stem, "raster", image=img,
                         width_mm=size_pt.width() / 72 * MM_PER_INCH * opts.scale,
                         height_mm=size_pt.height() / 72 * MM_PER_INCH * opts.scale)
    obj.warnings.append("PDF/AI импортирован как растр. Для векторного импорта установите Inkscape.")
    return obj
