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
from fast_elm.reader import WRITE_PIPE_BUFFER_SIZE, READ_PIPE_BUFFER_SIZE, elm_reader
from fast_elm.responses import ObdResponseBase
from fast_elm.utils import run_sync, StatusItem
from serial.tools.list_ports import comports


class ElmProtocol:
    def __init__(self, write_pipe: int, read_pipe: int):
        self.elm_read = os.fdopen(read_pipe, "rb", buffering=READ_PIPE_BUFFER_SIZE)
        self.elm_write = os.fdopen(write_pipe, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)

        self.at_prompt = asyncio.Event()
        self.has_message = asyncio.Event()

    async def raw_stream(self) -> AsyncIterator[tuple[float, bytes]]:

        loop = asyncio.get_event_loop()
        stream_reader = asyncio.StreamReader()

        def protocol_factory():
            return asyncio.StreamReaderProtocol(stream_reader)

        transport, _ = await loop.connect_read_pipe(protocol_factory, self.elm_read)

        async for raw_line in stream_reader:
            line = cast(bytes, raw_line)  # type: ignore
            for elm_line in line.split(b"\r"):
                elm_line = elm_line.strip()
                if not elm_line:
                    continue
                if elm_line == b">":
                    self.at_prompt.set()
                    continue
                # data = elm_line.replace(b"\r", b"").replace(b">", b"").strip()
                yield time.time(), elm_line

    async def __aiter__(self) -> AsyncIterator[ObdResponseBase[Any]]:
        async for timestamp, raw_line in self.raw_stream():
            yield ObdResponseBase(raw_line, timestamp)
            # if raw_line.startswith(b"4105"):
            #     yield "coolant_temp", int(raw_line[4:6], 16) - 40
            # elif raw_line.startswith(b"410C"):
            #     yield "rpm", int(raw_line[4:8], 16) // 4
            # elif raw_line.startswith(b"410D"):
            #     yield "speed", int(raw_line[4:6], 16)


app = typer.Typer()


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
            logger.info("No USB serial ports found. Using first port found: {device}")
    else:
        logger.info(f"Using {device}")

    current_status.value = "Connecting to ELM327"

    elm_read, elm_write = os.pipe()
    main_read, main_write = os.pipe()

    os.set_inheritable(elm_read, True)
    os.set_inheritable(main_read, True)
    elm_reader_process = multiprocessing.Process(
        target=elm_reader,
        kwargs=dict(
            write_pipe=elm_write,
            read_pipe=main_read,
            port=device,
            baudrate=baudrate,
        ),
    )
    elm_reader_process.start()
    prot = ElmProtocol(main_write, elm_read)

    current_status.value = "Waiting for ELM327 to be ready"

    dt_fmt = "%Y-%m-%d_%H:%M:%S.%f"
    _write_fd = zstandard.open(f"obd_data_{datetime.now().strftime(dt_fmt)}.zst", "wb")
    _write_buf = []

    def _dump_write_buf():
        _write_fd.write(b":".join(_write_buf))
        _write_buf.clear()

    def _dump_write_buf_and_close():
        _dump_write_buf()
        _write_fd.close()

    atexit.register(_dump_write_buf_and_close)

    c = 0

    latest: dict[type, Any] = {}

    messages_per_second = StatusItem("Messages per second", 0)

    async def log_messages_per_second():
        nonlocal c
        while True:
            await asyncio.sleep(1)
            messages_per_second.value = c
            c = 0

    asyncio.create_task(log_messages_per_second())

    current_status.value = "Gathering data in main loop"
    async for line in prot:
        if (t := type(line)) not in latest:
            latest[t] = StatusItem(t.__name__, line)
        latest[type(line)].value = line
        c += 1
        _write_buf.extend((str(line.timestamp).encode("utf-8"), line.data))
        if len(_write_buf) > 1000:
            _dump_write_buf()

        # pass
        # With ELM327-emulator: `Messages per second: 3056 (0.327 ms/message)`


if __name__ == "__main__":
    app()
