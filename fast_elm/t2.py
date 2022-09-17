from __future__ import annotations

import asyncio
import atexit
import multiprocessing
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import cast, AsyncIterator, Any

import serial
import typer
import zstandard
from loguru import logger

from fast_elm import utils
from fast_elm.reader import (
    WRITE_PIPE_BUFFER_SIZE,
    READ_PIPE_BUFFER_SIZE,
    elm_reader,
    ElmReaderMessage,
)
from fast_elm.responses import ObdResponseBase
from fast_elm.utils import run_sync, StatusItem
from serial.tools.list_ports import comports

current_status = StatusItem("Current status", "Initializing.")


class ElmManager:
    def __init__(self, device: str, baudrate: int):

        main_reads_from, elm_writes_to = os.pipe()
        elm_reads_from, main_writes_to = os.pipe()

        self.main_reads_from = os.fdopen(main_reads_from, "rb", buffering=READ_PIPE_BUFFER_SIZE)
        self.main_writes_to = os.fdopen(main_writes_to, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)

        os.set_inheritable(elm_writes_to, True)
        os.set_inheritable(elm_reads_from, True)
        self.elm_reader_process = multiprocessing.Process(
            target=elm_reader,
            kwargs=dict(
                write_pipe=elm_writes_to,
                read_pipe=elm_reads_from,
                port=device,
                baudrate=baudrate,
            ),
        )
        self.elm_reader_process.start()

        self.at_prompt = asyncio.Event()
        # self.has_message = asyncio.Event()

    async def raw_stream(self) -> AsyncIterator[ElmReaderMessage]:

        loop = asyncio.get_event_loop()
        stream_reader = asyncio.StreamReader()

        def protocol_factory():
            return asyncio.StreamReaderProtocol(stream_reader)

        transport, _ = await loop.connect_read_pipe(protocol_factory, self.main_reads_from)

        async for raw_line in stream_reader:
            print(f"Got line {raw_line}")
            line = cast(ElmReaderMessage, raw_line)
            for elm_reader_message in line.splitlines():
                if elm_reader_message == b">":
                    self.at_prompt.set()
                else:
                    yield elm_reader_message
            # for elm_line in line.split(b"\r"):
            #     elm_line = elm_line.strip()
            #     if not elm_line:
            #         continue
            #     if elm_line == b">":
            #         self.at_prompt.set()
            #         continue
            #     # data = elm_line.replace(b"\r", b"").replace(b">", b"").strip()
            #     yield time.time(), elm_line

    async def __aiter__(self) -> AsyncIterator[ObdResponseBase[Any]]:
        async for raw_line in self.raw_stream():
            try:
                yield ObdResponseBase(raw_line)
            except Exception as e:
                print(f"Failed to parse {raw_line!r} -- {e}")
            # if raw_line.startswith(b"4105"):
            #     yield "coolant_temp", int(raw_line[4:6], 16) - 40
            # elif raw_line.startswith(b"410C"):
            #     yield "rpm", int(raw_line[4:8], 16) // 4
            # elif raw_line.startswith(b"410D"):
            #     yield "speed", int(raw_line[4:6], 16)


app = typer.Typer()


# @current_status.update_on_fun_entry("Initializing.")
def pick_auto_port():
    ports = comports()

    if not ports:
        logger.error("No serial ports found")
        raise typer.Exit(1)

    logger.info(f"Found {len(ports)} serial ports - {','.join(map(str, ports))}")
    device = next((d.device for d in iter(ports) if "USB" in d.description), "")
    if device:
        logger.info(f"Using {device}")
    else:
        device = ports[0].device
        logger.info(f"No USB serial ports found. Using first port found: {device}")


class ObdDataRecorder:
    def __init__(self):
        self.write_buf = bytearray()
        self._file = None

    def write(self, data: ObdResponseBase):
        self.write_buf += data.data
        if len(self.write_buf) > 1000:
            self.flush()

    def flush(self):
        if self._file is None:
            raise RuntimeError("ObdDataRecorder is not open")

        self._file.write(self.write_buf)
        self.write_buf.clear()

    def __enter__(self):
        dt_fmt = "obd_data__%Y_%m_%d__%H_%M_%S.zst"
        self._file = zstandard.open(datetime.now().strftime(dt_fmt), "wb")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.flush()
        self._file.close()
        self._file = None


@app.command("fast-elm")
@run_sync
@utils.my_main
async def main(
    device: str = typer.Argument("auto"),
    baudrate: int = typer.Option(38400, "--baudrate", "-b", "-r", help="Baudrate to use"),
    try_fast: bool = typer.Option(False, "--try-fast", "-f", help="Try fast baudrates"),
    to_fast_baudrates: list[int] = typer.Option(
        [500000, 115200, 38400], "--fast-baudrates", "-fb", help="Baudrates to try in fast mode"
    ),
) -> None:

    if device == "auto":
        device = pick_auto_port()
    logger.info(f"Using {device}")

    elm_manager = ElmManager(device, baudrate)

    latest: dict[type, Any] = {}
    messages_per_second = StatusItem("Messages per second", 0)

    c = 0

    async def log_messages_per_second():
        nonlocal c
        while True:
            await asyncio.sleep(1)
            messages_per_second.value = c
            c = 0

    asyncio.create_task(log_messages_per_second())

    current_status.value = "Gathering data in main loop"
    with ObdDataRecorder() as recorder:
        async for line in elm_manager:
            print(line)
            if (t := type(line)) not in latest:
                latest[t] = StatusItem(t.__name__, line)
            latest[type(line)].value = line
            c += 1
            if line is not None:
                recorder.write(line)

        # pass
        # With ELM327-emulator: `Messages per second: 3056 (0.327 ms/message)`


if __name__ == "__main__":
    app()
