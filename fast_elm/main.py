from __future__ import annotations

import asyncio
import atexit
from typing import Any, Iterator

import typer
import zstandard
from loguru import logger

from fast_elm import utils
from fast_elm.reader import ElmProtocol
from fast_elm.utils import run_sync, StatusItem
from serial.tools.list_ports import comports


class DataRecorder:
    def __init__(self, buffer_size: int = 1000) -> None:
        self._buffer: bytearray = bytearray()
        self.buffer_size = buffer_size
        self._fd = zstandard.open("data.obd", "wb")
        atexit.register(self.close)

    def add_to_buffer(self, message: bytes):
        self._buffer += message
        if len(self._buffer) > self.buffer_size:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        self._fd.write(self._buffer)
        self._fd.flush()
        self._buffer.clear()

    def close(self):
        self.flush()
        self._fd.close()

    @classmethod
    def iter_messages(cls) -> Iterator[bytes]:
        print("Reading messages")
        read_chunk_size = 1000
        buf = bytearray()
        with zstandard.open("data.obd", "rb") as fd:
            while True:
                read = fd.read(read_chunk_size)
                buf += read
                *crt, nxt = buf.split(b"\x00")
                yield from map(bytes, crt)
                buf = nxt

                if not read:
                    yield bytes(buf)
                    break

            # todo - check for off-by-one error


app = typer.Typer()


@app.command("run")
@run_sync
@utils.my_main
async def main(
    device: str = typer.Argument("auto"),
    baudrate: int = typer.Option(38400, "--baudrate", "-b", "-r", help="Baudrate to use"),
) -> None:

    current_status = StatusItem("Current status", "Initializing.")
    if device == "auto":
        ports = comports()

        if not ports:
            logger.error("No serial ports found")
            raise typer.Exit(1)
        logger.info(f"Found {len(ports)} serial ports - {','.join(map(str,ports))}")
        device = next((d.device for d in iter(ports) if "USB" in d.description), "")
        if device:
            logger.info(f"Using {device}")
        else:
            device = ports[0].device
            logger.info(f"No USB serial ports found. Using first port found: {device}")
    else:
        logger.info(f"Using {device}")

    current_status.value = "Connecting to ELM327"

    prot = ElmProtocol(device=device, baudrate=baudrate)

    current_status.value = "Waiting for ELM327 to be ready"
    c = 0
    latest: dict[str, Any] = {
        "message": StatusItem("Latest message", "<none>"),
        "coolant_temp": StatusItem("Coolant temp", 0),
        "rpm": StatusItem("RPM", 0),
        "speed": StatusItem("Speed", 0),
        "throttle position": StatusItem("Throttle", 0),
        "commanded throttle actuation": StatusItem("Commanded Throttle", 0),
    }

    messages_per_second = StatusItem("Messages per second", 0)

    async def log_messages_per_second():
        nonlocal c
        while True:
            await asyncio.sleep(1)
            messages_per_second.value = c
            c = 0

    asyncio.create_task(log_messages_per_second())

    data_recorder = DataRecorder()
    current_status.value = "Gathering data in main loop"
    async for timestamp, raw_line in prot.raw_stream():
        c += 1
        recorded_bytes = b"\x00" + f"{timestamp:.3f}".encode("utf-8") + b" " + raw_line
        data_recorder.add_to_buffer(recorded_bytes)
        latest["message"].value = raw_line
        raw_line = raw_line.replace(b" ", b"")

        if raw_line.startswith(b"4105"):
            latest["coolant_temp"].value = int(raw_line[4:6], 16) - 40
        elif raw_line.startswith(b"410C"):
            latest["rpm"].value = int(raw_line[4:8], 16) // 4
        elif raw_line.startswith(b"410D"):
            latest["speed"].value = int(raw_line[4:6], 16)
        elif raw_line.startswith(b"4111"):
            latest["throttle position"].value = int(raw_line[4:6], 16) * 100 / 255
        elif raw_line.startswith(b"414C"):
            latest["commanded throttle actuation"].value = int(raw_line[4:6], 16) * 100 / 255


@app.command("replay-messages")
def replay_messages():
    for message in DataRecorder.iter_messages():
        print(message)


if __name__ == "__main__":
    app()
