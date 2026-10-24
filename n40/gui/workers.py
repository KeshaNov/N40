"""Фоновые потоки: лазер, камера, нестинг, обновления. GUI не блокируется."""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..core import camera as cam
from ..core import nesting, updater
from ..core.driver import lhymicro
from ..core.driver.k40usb import STATUS_TEXT, K40Error, K40Usb


def bgr_to_qimage(frame: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


# --------------------------------------------------------------------------- лазер

class LaserWorker(QThread):
    """Владеет USB-устройством. Команды ставятся в очередь; стоп/пауза — через флаги."""

    status = Signal(str)
    connected_changed = Signal(bool)
    progress = Signal(int, int)       # отправлено команд / всего
    job_finished = Signal(bool, str)  # успех, сообщение
    position = Signal(int, int)       # текущие координаты головы, шаги

    def __init__(self, board: str = "M2"):
        super().__init__()
        self.board = board
        self.usb = K40Usb()
        self._queue: list[tuple[str, object]] = []
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._alive = True
        self.busy = False
        self.x = self.y = 0

    # ------------------------------------------------------------------ API из GUI
    def submit(self, kind: str, payload=None) -> None:
        with self._cv:
            self._queue.append((kind, payload))
            self._cv.notify()

    def request_stop(self) -> None:
        self._stop.set()
        self._pause.clear()
        with self._cv:
            self._queue = [q for q in self._queue if q[0] in ("disconnect",)]

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._pause.set()
        else:
            self._pause.clear()

    def shutdown(self) -> None:
        self._alive = False
        self.request_stop()
        with self._cv:
            self._cv.notify()
        self.wait(3000)

    # ------------------------------------------------------------------ поток
    def run(self) -> None:
        while self._alive:
            with self._cv:
                while not self._queue and self._alive:
                    self._cv.wait(0.5)
                if not self._alive:
                    break
                kind, payload = self._queue.pop(0)
            try:
                self._handle(kind, payload)
            except K40Error as exc:
                self.status.emit(str(exc))
                if kind == "job":
                    self.job_finished.emit(False, str(exc))
                if not self.usb.connected:
                    self.connected_changed.emit(False)
            except Exception as exc:  # noqa: BLE001 — поток не должен падать
                self.status.emit(f"Ошибка: {exc}")
                if kind == "job":
                    self.job_finished.emit(False, str(exc))
        self.usb.disconnect()

    def _should_stop(self) -> bool:
        if self._pause.is_set() and not self._stop.is_set():
            self.usb.send_realtime(lhymicro.CMD_PAUSE)
            self.status.emit("Пауза")
            while self._pause.is_set() and not self._stop.is_set():
                time.sleep(0.05)
            if not self._stop.is_set():
                self.usb.send_realtime(lhymicro.CMD_RESUME)
                self.status.emit("Продолжение")
        return self._stop.is_set()

    def _require(self) -> None:
        if not self.usb.connected:
            raise K40Error("Лазер не подключён")

    def _handle(self, kind: str, payload) -> None:
        if kind == "connect":
            self.usb.connect()
            self.connected_changed.emit(True)
            self.status.emit("Подключено: " + STATUS_TEXT.get(self.usb.status(), "?"))
            return
        if kind == "disconnect":
            self.usb.disconnect()
            self.connected_changed.emit(False)
            self.status.emit("Отключено")
            return
        self._require()
        self._stop.clear()
        self.busy = True
        try:
            if kind == "home":
                self.usb.send(lhymicro.CMD_HOME)
                self.x = self.y = 0
                self.position.emit(0, 0)
                self.status.emit("Домой")
            elif kind == "unlock":
                self.usb.send(lhymicro.CMD_UNLOCK)
                self.status.emit("Каретка разблокирована")
            elif kind == "move":
                dx, dy = payload
                self.usb.send(lhymicro.rapid_move(dx, dy))
                self.x += dx
                self.y += dy
                self.position.emit(self.x, self.y)
            elif kind == "moveto":
                tx, ty = payload
                self.usb.send(lhymicro.rapid_move(tx - self.x, ty - self.y))
                self.x, self.y = tx, ty
                self.position.emit(self.x, self.y)
            elif kind == "job":
                self._run_job(payload)
        finally:
            self.busy = False

    def _run_job(self, programs) -> None:
        """programs — список Program из планировщика; координаты абсолютные от дома."""
        total = len(programs)
        self.progress.emit(0, total)
        for i, prog in enumerate(programs):
            if self._should_stop():
                break
            text, self.x, self.y = lhymicro.encode_program(prog, self.x, self.y, self.board)
            if not text:
                continue
            self.usb.send(text, should_stop=self._should_stop)
            if self._stop.is_set():
                break
            self.usb.wait_complete(should_stop=self._should_stop)
            self.position.emit(self.x, self.y)
            self.progress.emit(i + 1, total)
        if self._stop.is_set():
            try:
                self.usb.send_realtime(lhymicro.CMD_STOP)
            finally:
                self.job_finished.emit(False, "Остановлено")
            return
        self.job_finished.emit(True, "Задание выполнено")


# --------------------------------------------------------------------------- камера

class CameraWorker(QThread):
    raw_frame = Signal(object)       # np.ndarray BGR
    field_image = Signal(QImage)     # изображение поля (после калибровки) или сырой кадр
    error = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._running = True
        self.projector: cam.FieldProjector | None = None
        self.reload_calibration()

    def reload_calibration(self) -> None:
        s = self.settings
        self.projector = cam.FieldProjector(s.calibration, s.bed_width, s.bed_height, s.camera_px_per_mm)

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    def run(self) -> None:
        s = self.settings
        try:
            cap = cam.open_capture(s.camera_source, s.camera_index, s.camera_url)
        except RuntimeError as exc:
            self.error.emit(str(exc))
            return
        last_emit = 0.0
        fails = 0
        while self._running:
            ok, frame = cap.read()
            if not ok:
                fails += 1
                if fails > 50:
                    self.error.emit("Поток камеры прерван")
                    break
                time.sleep(0.05)
                continue
            fails = 0
            self.raw_frame.emit(frame)
            now = time.time()
            if now - last_emit < 0.1:  # ≤10 к/с для подложки
                continue
            last_emit = now
            projected = self.projector.project(frame) if self.projector else None
            self.field_image.emit(bgr_to_qimage(projected if projected is not None else frame))
        cap.release()


# --------------------------------------------------------------------------- нестинг

class NestWorker(QThread):
    progress = Signal(int, int)
    done = Signal(object)          # NestResult
    failed = Signal(str)

    def __init__(self, parts, params):
        super().__init__()
        self.parts, self.params = parts, params
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = nesting.nest(self.parts, self.params, progress=self.progress.emit,
                                  is_cancelled=self._cancel.is_set)
            self.done.emit(result)
        except nesting.NestCancelled:
            self.failed.emit("Расчёт остановлен")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Ошибка нестинга: {exc}")


# --------------------------------------------------------------------------- обновления

class UpdateWorker(QThread):
    found = Signal(object)  # ReleaseInfo

    def run(self) -> None:
        info = updater.fetch_latest()
        if info and updater.is_newer(info.version):
            self.found.emit(info)
