from __future__ import annotations

import os
from itertools import cycle
from pathlib import Path
from typing import NoReturn

from loguru import logger
from serial import Serial
from serial.tools.list_ports import comports

WRITE_PIPE_BUFFER_SIZE = 2048 * 1024  # way more than enough but we don't want to block
READ_PIPE_BUFFER_SIZE = 2048 * 1024


def elm_reader(write_pipe: int, read_pipe: int, port: str, baudrate: int) -> NoReturn:
    writer = os.fdopen(write_pipe, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)
    reader = os.fdopen(read_pipe, "rb", buffering=READ_PIPE_BUFFER_SIZE)

    _serial = Serial(port=port, baudrate=baudrate)

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
    commands = cycle((b"0105", b"010C", b"010D"))
    for next_command in commands:
        _serial.write(next_command + b"\r")
        data = _serial.read_until(b">")
        writer.write(data + b"\n")
        writer.flush()

    assert False, "Should never reach this point"


class ElmReader:
    initialization_sequence = (
        b"atz",  # reset
        b"ate0",  # echo off
        # b"ats0",  # spaces off
        b"atsp6",  # protocol 6
    )

    def __init__(self, port: str | Path, baudrate: int, write_pipe: int) -> None:

        self._original_port = port
        self._original_baudrate = baudrate
        self.writer = os.fdopen(write_pipe, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)

        self._serial = self._get_initialized_serial()
        self.commands = cycle((b"0105", b"010C", b"010D"))

    @property
    def port(self) -> str:
        return self._serial.port

    def _get_initialized_serial(self) -> Serial:

        port = self._original_port
        if port == "auto":
            port = self.find_port()

        port = port
        _serial = Serial(port, baudrate=self._original_baudrate)

        # Reset the buffer and discard any ongoing commands, then wait for the prompt
        _serial.reset_output_buffer()
        _serial.reset_input_buffer()
        _serial.write(b"\r")

        # Perform the initialization sequence and wait for the prompt
        _serial.write(b"\r".join(self.initialization_sequence) + b"\r")
        _serial.read_until(b">")
        logger.info(f"ELM327 at {port} initialized")
        return _serial

    @classmethod
    def find_port(cls) -> str:
        for port in comports():
            if "ELM327" in port.description:
                return port.device
        raise RuntimeError("No ELM327 device found")

    def run(self):
        for next_command in self.commands:
            self._serial.write(next_command + b"\r")
            data = self._serial.read_until(b">")
            self.writer.write(data + b"\n")
            self.writer.flush()
