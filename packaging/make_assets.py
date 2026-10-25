"""Генерирует n40.ico и version_info.txt для PyInstaller из исходников (версия — из n40/__init__.py)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # CI-сборка без дисплея

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from n40 import __version__  # noqa: E402
from n40.gui.style import app_icon  # noqa: E402

app = QApplication([])
app_icon().pixmap(256, 256).save(str(ROOT / "n40.png"))
from PIL import Image  # noqa: E402

Image.open(ROOT / "n40.png").save(ROOT / "n40.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

nums = ([int(x) for x in __version__.split(".")] + [0, 0, 0, 0])[:4]
(ROOT / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(nums)}, prodvers={tuple(nums)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041904B0', [
      StringStruct('CompanyName', 'N40'),
      StringStruct('FileDescription', 'N40 — управление лазером K40'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductName', 'N40'),
      StringStruct('ProductVersion', '{__version__}')])]),
        VarFileInfo([VarStruct('Translation', [1049, 1200])])]
)
""", encoding="utf-8")
print("assets ok", __version__)
