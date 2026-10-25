"""Точка входа N40."""

from __future__ import annotations

import sys


def main() -> None:
    for arg in sys.argv[1:]:
        if arg.startswith("--self-test"):
            from .selftest import run
            sys.exit(run(arg.partition("=")[2] or "n40-selftest.txt"))

    from PySide6.QtCore import QLocale, QTranslator, QLibraryInfo
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__
    from .gui import style
    from .gui.mainwindow import MainWindow

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"N40.Laser.{__version__}")
        except Exception:  # noqa: BLE001
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("N40")
    QLocale.setDefault(QLocale(QLocale.Language.Russian, QLocale.Country.Russia))
    # русские подписи стандартных диалогов Qt
    translator = QTranslator(app)
    if translator.load(QLocale(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    app.setStyle("Fusion")
    app.setStyleSheet(style.QSS)
    app.setFont(style.ui_font())
    app.setWindowIcon(style.app_icon())

    win = MainWindow()
    win.show()
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    if files:
        from pathlib import Path
        projects = [f for f in files if f.lower().endswith(".n40")]
        if projects:
            win.load_project(Path(projects[0]))
        else:
            win.import_files(files)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
