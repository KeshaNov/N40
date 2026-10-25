"""Самопроверка собранного приложения: N40.exe --self-test=<файл отчёта>.

Проверяет то, что PyInstaller может не упаковать (динамические импорты, DLL, плагины Qt):
импорт SVG/DXF/растра, нестинг, кодировщик лазера, PDF, libusb, OpenCV.
Код возврата 0 — всё в порядке. Используется в CI перед публикацией релиза.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def _checks(tmp: Path):
    def svg():
        from .core.importers import import_file
        p = tmp / "t.svg"
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 200 100">'
                     '<rect x="10" y="10" width="80" height="40"/><circle cx="150" cy="50" r="30"/></svg>',
                     encoding="utf-8")
        o = import_file(p)[0]
        assert len(o.contours) == 2, o.contours
        return f"{len(o.contours)} контура"

    def dxf():
        import ezdxf
        from .core.importers import import_file
        doc = ezdxf.new()
        doc.header["$INSUNITS"] = 1
        doc.header["$MEASUREMENT"] = 1  # как у КОМПАС-3D
        msp = doc.modelspace()
        for a, b in (((0, 0), (40, 0)), ((40, 0), (40, 20)), ((40, 20), (0, 20)), ((0, 20), (0, 0))):
            msp.add_line(a, b)
        msp.add_spline([(0, 30), (10, 40), (20, 30), (30, 40)])
        p = tmp / "t.dxf"
        doc.saveas(p)
        o = import_file(p)[0]
        assert any(c.closed for c in o.contours), "отрезки не сшились"
        return f"{len(o.contours)} контура, ezdxf {ezdxf.__version__}"

    def raster():
        from PIL import Image
        from .core.importers import import_file
        p = tmp / "t.png"
        Image.new("RGB", (300, 150), "white").save(p, dpi=(300, 300))
        o = import_file(p)[0]
        assert abs(o.width_mm - 25.4) < 0.01
        return "25.4 мм"

    def nesting():
        from .core import nesting, primitives
        r = nesting.nest([nesting.NestPart("a", primitives.rectangle(0, 0, 50, 30), 4)], nesting.NestParams())
        assert len(r.placements) == 4
        return f"K = {r.utilization:.1f} %"

    def laser():
        from .core import planner, primitives
        from .core.driver import k40usb, lhymicro
        cmds = lhymicro.encode_job(planner.plan([planner.Operation("cut", 10, 1, primitives.circle(20, 20, 10))]))
        assert k40usb.make_packets(cmds[0])
        return f"{len(cmds)} команд"

    def libusb():
        import libusb_package
        import usb.core
        backend = libusb_package.get_libusb1_backend()
        assert backend is not None, "libusb-1.0.dll не найдена"
        usb.core.find(idVendor=0x1A86, idProduct=0x5512, backend=backend)  # лазер может быть не подключён
        return "backend ok"

    def opencv():
        import cv2
        import numpy as np
        h = cv2.getPerspectiveTransform(np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]),
                                        np.float32([[0, 0], [2, 0], [2, 2], [0, 2]]))
        assert h.shape == (3, 3)
        return cv2.__version__

    def qt_pdf():
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from .gui.calibration import save_chessboard_pdf
        p = tmp / "board.pdf"
        save_chessboard_pdf(str(p), 9, 6, 20)
        assert p.read_bytes().startswith(b"%PDF") and p.stat().st_size > 1000
        del app
        return f"{p.stat().st_size} байт"

    def gui():
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from .core.settings import Settings
        from .gui import style
        from .gui.mainwindow import MainWindow
        Settings.save = lambda self: None  # не трогаем настройки пользователя
        app.setStyleSheet(style.QSS)
        w = MainWindow()
        w.laser.shutdown()
        w.deleteLater()
        return "главное окно создаётся"

    return [("SVG", svg), ("DXF", dxf), ("Растр", raster), ("Нестинг", nesting), ("Лазер", laser),
            ("libusb", libusb), ("OpenCV", opencv), ("PDF", qt_pdf), ("Интерфейс", gui)]


def run(report_path: str) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines, failed = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, check in _checks(Path(tmp)):
            try:
                lines.append(f"OK    {name}: {check()}")
            except Exception:  # noqa: BLE001 — собираем все ошибки в отчёт
                failed += 1
                lines.append(f"FAIL  {name}:\n" + traceback.format_exc())
    from . import __version__
    lines.insert(0, f"N40 {__version__} self-test, frozen={getattr(sys, 'frozen', False)}")
    lines.append("RESULT: " + ("OK" if not failed else f"{failed} FAILED"))
    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
