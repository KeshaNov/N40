# PyInstaller: папка dist\N40 с N40.exe (onedir).
# Сборка: pyinstaller packaging/n40.spec --noconfirm   (Python 3.8 + packaging/requirements-release.txt)
#
# Почему папка, а не один exe: однофайловый exe при каждом запуске распаковывает себя во временную
# папку — так же ведут себя многие вредоносные программы, и антивирусы чаще дают ложные срабатывания.
# Папку ставит установщик (Inno Setup), для переносной версии она упаковывается в zip.
import glob
import os

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None


def ucrt_binaries():
    """Universal CRT для Windows 7 без обновления KB2999226 (app-local из Windows SDK)."""
    roots = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Redist\*\ucrt\DLLs\x64") + \
        glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Redist\ucrt\DLLs\x64")
    if not roots:
        if os.environ.get("N40_REQUIRE_UCRT"):
            raise SystemExit("Не найдены DLL Universal CRT (Windows SDK) — сборка для Windows 7 невозможна")
        print("ВНИМАНИЕ: DLL Universal CRT не найдены, N40 не запустится на Windows 7 без обновлений")
        return []
    root = sorted(roots)[-1]
    return [(path, ".") for path in glob.glob(os.path.join(root, "*.dll"))]


a = Analysis(
    ["../run_n40.py"],
    pathex=[".."],
    binaries=collect_dynamic_libs("libusb_package") + ucrt_binaries(),
    datas=[],
    hiddenimports=["usb.backend.libusb1", "usb.backend.libusb0"],
    excludes=[
        "tkinter", "matplotlib", "torch", "scipy", "sympy", "pandas", "IPython", "jupyter", "numba",
        "tensorflow", "sklearn", "PySide6",
        "PySide2.QtWebEngine", "PySide2.QtWebEngineCore", "PySide2.QtWebEngineWidgets", "PySide2.Qt3DCore",
        "PySide2.Qt3DRender", "PySide2.QtQuick", "PySide2.QtQml", "PySide2.QtMultimedia", "PySide2.QtCharts",
        "PySide2.QtDataVisualization", "PySide2.QtLocation", "PySide2.QtPositioning", "PySide2.QtBluetooth",
        "PySide2.QtSql", "PySide2.QtXmlPatterns", "PySide2.QtScxml", "PySide2.QtSensors",
    ],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="N40",
    icon="n40.ico",
    console=False,
    upx=False,
    version="version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="N40", upx=False)
