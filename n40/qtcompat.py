"""Совместимость с Qt 5 (PySide2) для сборки под Windows 7.

Код N40 написан под PySide6 (Qt 6), но Qt 6 работает только на Windows 10+. Релизная сборка
использует PySide2 (Qt 5.15, поддерживает Windows 7). Если PySide6 не установлен, этот модуль
подставляет PySide2 под именем PySide6 и закрывает различия API, которые встречаются в N40:
  * exec() вместо exec_();
  * QAction / QActionGroup / QShortcut в QtGui (в Qt 5 они в QtWidgets);
  * QMouseEvent.position() / QDropEvent.position() (в Qt 5 — localPos() / posF());
  * QLibraryInfo.path(LibraryPath.…) (в Qt 5 — location(LibraryLocation.…)).
Модуля QtPdf в PySide2 нет — места, где он нужен, проверяют это сами.
"""

from __future__ import annotations

import sys

QT6 = True


def install() -> None:
    global QT6
    try:
        import PySide6  # noqa: F401
        return
    except ImportError:
        pass
    try:
        import PySide2
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:  # Qt не установлен вовсе (например, CI до установки зависимостей) — ядру он не нужен
        return

    QT6 = False
    sys.modules["PySide6"] = PySide2
    for name, module in (("QtCore", QtCore), ("QtGui", QtGui), ("QtWidgets", QtWidgets)):
        sys.modules[f"PySide6.{name}"] = module
    try:
        from PySide2 import QtTest
        sys.modules["PySide6.QtTest"] = QtTest
    except ImportError:
        pass

    for name in ("QAction", "QActionGroup", "QShortcut"):
        setattr(QtGui, name, getattr(QtWidgets, name))
    # Обёртка, а не псевдоним exec = exec_: у QMenu.exec_ есть ещё статическая перегрузка, и голый
    # псевдоним теряет привязку к экземпляру — menu.exec(pos) падает с access violation.
    def _exec(self, *args, **kwargs):
        return self.exec_(*args, **kwargs)

    for cls in (QtCore.QEventLoop, QtWidgets.QDialog, QtWidgets.QMenu):
        cls.exec = _exec
    QtCore.QCoreApplication.exec = staticmethod(QtCore.QCoreApplication.exec_)
    QtGui.QMouseEvent.position = QtGui.QMouseEvent.localPos
    QtGui.QDropEvent.position = QtGui.QDropEvent.posF
    QtCore.QLibraryInfo.LibraryPath = QtCore.QLibraryInfo.LibraryLocation
    QtCore.QLibraryInfo.path = staticmethod(QtCore.QLibraryInfo.location)
