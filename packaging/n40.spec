# PyInstaller: один исполняемый файл N40.exe
# Сборка: pyinstaller packaging/n40.spec --noconfirm
from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

a = Analysis(
    ["../run_n40.py"],
    pathex=[".."],
    binaries=collect_dynamic_libs("libusb_package"),
    datas=[],
    hiddenimports=["usb.backend.libusb1", "usb.backend.libusb0", "PySide6.QtPdf"],
    excludes=[
        "tkinter", "matplotlib", "torch", "scipy", "sympy", "pandas", "IPython", "jupyter", "numba",
        "tensorflow", "sklearn","PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    ],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="N40",
    icon="n40.ico",
    console=False,
    upx=False,
    version="version_info.txt",
)
