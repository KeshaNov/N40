"""Камера над рабочим полем: захват (USB UVC или сетевой поток), калибровка, перспектива.

Цепочка: кадр -> undistort (матрица камеры и коэффициенты искажений) ->
warpPerspective по гомографии (неискажённый кадр, px -> поле, мм) -> изображение поля
в масштабе px_per_mm, совмещённое с координатами рабочей области.
"""

from __future__ import annotations

import os

import cv2
import numpy as np

from .settings import CameraCalibration


def open_capture(source: str, index: int, url: str) -> cv2.VideoCapture:
    if source == "url":
        if not url:
            raise RuntimeError("Не задан URL камеры")
        # FFmpeg-бэкенд OpenCV понимает RTSP, HTTP-FLV и MJPEG
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(int(index), cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(int(index))
    if not cap.isOpened():
        raise RuntimeError("Не удалось открыть камеру")
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def list_usb_cameras(max_index: int = 6) -> list[int]:
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


# --------------------------------------------------------------------------- калибровка объектива

def find_chessboard(frame: np.ndarray, cols: int, rows: int) -> np.ndarray | None:
    """Ищет внутренние углы шахматной доски (cols × rows). Возвращает (N,1,2) float32 или None."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    ok, corners = cv2.findChessboardCorners(gray, (cols, rows), flags)
    if not ok:
        return None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    return cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)


def calibrate_lens(corner_sets: list[np.ndarray], cols: int, rows: int, square_mm: float,
                   image_size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, float]:
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_mm
    rms, mtx, dist, _r, _t = cv2.calibrateCamera([objp] * len(corner_sets), corner_sets, image_size, None, None)
    return mtx, dist, float(rms)


def compute_homography(image_pts: list[tuple[float, float]], field_pts: list[tuple[float, float]]) -> np.ndarray:
    """Гомография неискажённого кадра (px) -> поле (мм) по ≥4 парам точек."""
    src = np.array(image_pts, dtype=np.float32)
    dst = np.array(field_pts, dtype=np.float32)
    if len(src) == 4:
        return cv2.getPerspectiveTransform(src, dst)
    h, _ = cv2.findHomography(src, dst, cv2.RANSAC)
    return h


class FieldProjector:
    """Превращает сырые кадры в изображение рабочего поля (мм -> px_per_mm)."""

    def __init__(self, cal: CameraCalibration, bed_w: float, bed_h: float, px_per_mm: float = 2.0):
        self.cal = cal
        self.bed_w, self.bed_h, self.ppm = bed_w, bed_h, px_per_mm
        self._maps = None
        self._maps_size = None

    @property
    def has_lens(self) -> bool:
        return self.cal.camera_matrix is not None and self.cal.dist_coeffs is not None

    @property
    def has_perspective(self) -> bool:
        return self.cal.homography is not None

    def undistort(self, frame: np.ndarray) -> np.ndarray:
        if not self.has_lens:
            return frame
        h, w = frame.shape[:2]
        if self._maps is None or self._maps_size != (w, h):
            mtx = np.array(self.cal.camera_matrix, dtype=np.float64)
            dist = np.array(self.cal.dist_coeffs, dtype=np.float64)
            new_mtx, _ = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 0)
            self._maps = cv2.initUndistortRectifyMap(mtx, dist, None, new_mtx, (w, h), cv2.CV_16SC2)
            self._maps_size = (w, h)
        return cv2.remap(frame, self._maps[0], self._maps[1], cv2.INTER_LINEAR)

    def project(self, frame: np.ndarray) -> np.ndarray | None:
        """Кадр -> изображение поля размером (bed_h·ppm, bed_w·ppm). None без калибровки перспективы."""
        if not self.has_perspective:
            return None
        und = self.undistort(frame)
        h = np.array(self.cal.homography, dtype=np.float64)
        scale = np.diag([self.ppm, self.ppm, 1.0])
        size = (int(round(self.bed_w * self.ppm)), int(round(self.bed_h * self.ppm)))
        return cv2.warpPerspective(und, scale @ h, size, flags=cv2.INTER_LINEAR)
