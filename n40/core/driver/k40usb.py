"""USB-транспорт для платы M2 Nano (чип CH341, VID 0x1A86 / PID 0x5512) через pyusb + libusb.

На Windows контроллеру нужен драйвер WinUSB/libusb-win32 (ставится через Zadig, как для K40 Whisperer).

Пакет: 0xA6 0x00 <30 байт данных, дополненных 'F'> 0xA6 <CRC-8 Dallas/Maxim от 30 байт>.
После каждого пакета читается статус (запрос 0xA0, ответ 6 байт, статус в байте [1]).
"""

from __future__ import annotations

import time
from typing import Callable

VID, PID = 0x1A86, 0x5512
EP_OUT, EP_IN = 0x02, 0x82
PAYLOAD = 30

STATUS_OK = 206
STATUS_BUSY = 238
STATUS_CRC = 207
STATUS_COMPLETE = 236
STATUS_POWER = 239

STATUS_TEXT = {
    STATUS_OK: "Готов",
    STATUS_BUSY: "Занят",
    STATUS_CRC: "Ошибка CRC",
    STATUS_COMPLETE: "Задание выполнено",
    STATUS_POWER: "Нет питания / неизвестно",
}


class K40Error(Exception):
    pass


def crc8_maxim(data: bytes) -> int:
    crc = 0
    for byte in data:
        for _ in range(8):
            mix = (crc ^ byte) & 0x01
            crc >>= 1
            if mix:
                crc ^= 0x8C
            byte >>= 1
    return crc


def make_packets(command: str) -> list[bytes]:
    """Режет команду на пакеты по 30 байт. '\\n' завершает пакет (дополняется 'F')."""
    packets = []
    for line in command.split("\n"):
        data = line.encode("ascii")
        if not data:
            continue
        for i in range(0, len(data), PAYLOAD):
            chunk = data[i:i + PAYLOAD].ljust(PAYLOAD, b"F")
            packets.append(bytes([0xA6, 0x00]) + chunk + bytes([0xA6, crc8_maxim(chunk)]))
    return packets


class K40Usb:
    def __init__(self, timeout_ms: int = 2000):
        self.dev = None
        self.timeout = timeout_ms

    # ------------------------------------------------------------------ соединение
    @property
    def connected(self) -> bool:
        return self.dev is not None

    def connect(self) -> None:
        try:
            import usb.core
            import usb.util
        except ImportError as exc:
            raise K40Error("Не установлен pyusb") from exc
        backend = None
        try:
            import libusb_package
            backend = libusb_package.get_libusb1_backend()
        except Exception:  # noqa: BLE001 — пакет необязателен, pyusb найдёт системный libusb
            backend = None
        try:
            dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
        except usb.core.NoBackendError as exc:
            raise K40Error("Не найдена библиотека libusb") from exc
        if dev is None:
            raise K40Error("Лазер не найден. Проверьте кабель, питание и драйвер (Zadig → WinUSB).")
        try:
            dev.set_configuration()
        except usb.core.USBError as exc:
            raise K40Error(f"Не удалось открыть устройство: {exc}") from exc
        self.dev = dev
        self.status()

    def disconnect(self) -> None:
        if self.dev is not None:
            try:
                import usb.util
                usb.util.dispose_resources(self.dev)
            finally:
                self.dev = None

    # ------------------------------------------------------------------ обмен
    def status(self) -> int:
        if self.dev is None:
            raise K40Error("Нет соединения")
        try:
            self.dev.write(EP_OUT, bytes([0xA0]), self.timeout)
            resp = self.dev.read(EP_IN, 6, self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise K40Error(f"Ошибка USB: {exc}") from exc
        return int(resp[1]) if len(resp) > 1 else 0

    def _wait_ready(self, should_stop: Callable[[], bool] | None) -> None:
        while True:
            st = self.status()
            if st != STATUS_BUSY:
                return
            if should_stop and should_stop():
                return
            time.sleep(0.01)

    def send(self, command: str, should_stop: Callable[[], bool] | None = None,
             progress: Callable[[int, int], None] | None = None, retries: int = 10) -> None:
        packets = make_packets(command)
        for i, pkt in enumerate(packets):
            if should_stop and should_stop():
                return
            for _attempt in range(retries):
                self._wait_ready(should_stop)
                try:
                    self.dev.write(EP_OUT, pkt, self.timeout)
                except Exception as exc:  # noqa: BLE001
                    raise K40Error(f"Ошибка передачи: {exc}") from exc
                st = self.status()
                if st != STATUS_CRC:
                    break
            else:
                raise K40Error("Контроллер постоянно сообщает об ошибке CRC")
            if progress:
                progress(i + 1, len(packets))

    def send_realtime(self, command: str) -> None:
        """Команда вне очереди (стоп/пауза) — без ожидания готовности."""
        for pkt in make_packets(command):
            self.dev.write(EP_OUT, pkt, self.timeout)

    def wait_complete(self, should_stop: Callable[[], bool] | None = None, timeout_s: float = 3600) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if should_stop and should_stop():
                return
            st = self.status()
            if st == STATUS_COMPLETE:
                return
            time.sleep(0.1)
