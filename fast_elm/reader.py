from __future__ import annotations

import asyncio
import multiprocessing

import os
import time
from itertools import cycle
from pathlib import Path
from typing import NoReturn, AsyncIterator, cast, Any

from loguru import logger
from serial import Serial
from serial.tools.list_ports import comports

from fast_elm.responses import ObdResponseBase

WRITE_PIPE_BUFFER_SIZE = 2048 * 1024  # way more than enough but we don't want to block
READ_PIPE_BUFFER_SIZE = 2048 * 1024


def elm_reader(write_pipe: int, read_pipe: int, port: str, baudrate: int) -> NoReturn:
    writer = os.fdopen(write_pipe, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)
    reader = os.fdopen(read_pipe, "rb", buffering=READ_PIPE_BUFFER_SIZE)

    # _serial = Serial(port=port, baudrate=baudrate)
    _serial = Serial(port=port, baudrate=38400)

    # Reset the buffer and discard any ongoing commands, then wait for the prompt
    _serial.reset_output_buffer()
    _serial.reset_input_buffer()
    _serial.write(b"\r")

    # Perform the initialization sequence and wait for the prompt
    initialization_sequence = (
        b"atz",  # reset
        b"ate0",  # echo off
        # b"ats0",  # spaces off
        b"atsp6",  # protocol 6
    )
    _serial.write(b"\r".join(initialization_sequence) + b"\r")
    _serial.read_until(b">")
    print("ELM327 initialized")

    # Start the main loop
    # remaining = b""
    commands = cycle(
        (b"010C", b"010D", b"014C", b"0111") * 10
        + (b"0105",),  # get RPM, speed, throttle more frequently than coolant temp
    )
    for next_command in commands:
        _serial.write(next_command + b"\r")
        data = _serial.read_until(b">")
        writer.write(data + b"\n")
        writer.flush()

    assert False, "Should never reach this point"


class ElmProtocol:
    def __init__(self, device: str, baudrate: int = 38400) -> None:

        self.elm_read, self.elm_write = os.pipe()
        self.main_read, self.main_write = os.pipe()

        os.set_inheritable(self.elm_read, True)
        os.set_inheritable(self.main_read, True)
        elm_reader_process = multiprocessing.Process(
            target=elm_reader,
            kwargs=dict(
                write_pipe=self.elm_write,
                read_pipe=self.main_read,
                port=device,
                baudrate=baudrate,
            ),
        )
        elm_reader_process.start()

        self.at_prompt = asyncio.Event()
        self.has_message = asyncio.Event()

    async def raw_stream(self) -> AsyncIterator[tuple[float, bytes]]:

        loop = asyncio.get_event_loop()
        stream_reader = asyncio.StreamReader()

        def protocol_factory():
            return asyncio.StreamReaderProtocol(stream_reader)

        transport, _ = await loop.connect_read_pipe(
            protocol_factory=protocol_factory,
            pipe=os.fdopen(self.elm_read, "rb"),
        )

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
