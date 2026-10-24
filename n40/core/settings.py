"""Настройки приложения с сохранением в %APPDATA%\\N40\\settings.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / "N40"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class CameraCalibration:
    camera_matrix: list | None = None      # 3x3
    dist_coeffs: list | None = None        # 1xN
    image_size: list | None = None         # [w, h] кадра при калибровке
    homography: list | None = None         # 3x3: неискажённый кадр (px) -> поле (мм)
    rms: float | None = None


@dataclass
class Settings:
    # Рабочее поле, мм
    bed_width: float = 300.0
    bed_height: float = 200.0
    # Сетка и привязки
    grid_step: float = 5.0
    snap_grid: bool = True
    snap_nodes: bool = True
    # Авторасстановка
    arrange_rotate: bool = True
    arrange_gap: float = 2.0
    # Импорт
    svg_dpi: float = 96.0
    raster_default_dpi: float = 254.0
    # Лазер
    board: str = "M2"
    cut_speed: float = 10.0
    engrave_speed: float = 50.0
    raster_speed: float = 100.0
    raster_step: float = 0.1
    rapid_return_home: bool = True
    # Камера
    camera_source: str = "usb"            # "usb" | "url"
    camera_index: int = 0
    camera_url: str = ""
    camera_px_per_mm: float = 2.0
    camera_opacity: float = 0.6
    calibration: CameraCalibration = field(default_factory=CameraCalibration)
    # Обновления
    check_updates: bool = True

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return s
        names = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key == "calibration" and isinstance(value, dict):
                cal_names = {f.name for f in fields(CameraCalibration)}
                s.calibration = CameraCalibration(**{k: v for k, v in value.items() if k in cal_names})
            elif key in names:
                setattr(s, key, value)
        return s

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
