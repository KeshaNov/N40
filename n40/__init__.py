"""N40 — управление CO2-лазерным гравером K40 (контроллер M2 Nano / LHYMICRO-GL)."""

__version__ = "0.1.1"
APP_NAME = "N40"
GITHUB_REPO = "KeshaNov/N40"

# Qt 6 (PySide6) для разработки, Qt 5 (PySide2) в сборке под Windows 7 — см. qtcompat
from .qtcompat import install as _install_qt  # noqa: E402

_install_qt()
