from __future__ import annotations

import os
import time
from itertools import cycle
from typing import NoReturn, NamedTuple, Iterator, NewType

import serial
from serial import Serial

WRITE_PIPE_BUFFER_SIZE = 2048 * 1024  # way more than enough but we don't want to block
READ_PIPE_BUFFER_SIZE = 2048 * 1024


class TimestampedLine(NamedTuple):
    timestamp: float
    line: bytes


# def _iterate_from_read_buf(_serial: serial.Serial) -> Iterator[TimestampedLine]:
#     # may be too complicated, but would allow for more precise timestamps
#     unfinished_line: TimestampedLine | None = None
#     while True:
#         timestamped_lines = []
#         c = _serial.read_all()
#         if c:
#
#             *lines, last_line = c.split(b"\r")
#             for line in lines[1:]:
#                 if line:
#                     timestamped_lines.append(TimestampedLine(time.time(), line))
#
#             if unfinished_line is not None:
#                 timestamped_lines.append(
#                     TimestampedLine(unfinished_line.timestamp, unfinished_line.line + lines[0])
#                 )
#
#             if last_line.endswith((b">", b"\r")):
#                 timestamped_lines.append(TimestampedLine(time.time(), last_line))
#                 unfinished_line = None
#             else:
#                 # Partially read line; save it for the next iteration
#                 unfinished_line = TimestampedLine(time.time(), last_line)
#
#             yield from timestamped_lines
#             timestamped_lines.clear()

ElmReaderMessage = NewType("ElmReaderMessage", bytes)


def elm_reader(write_pipe: int, read_pipe: int, port: str, baudrate: int) -> NoReturn:
    writer = os.fdopen(write_pipe, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)
    reader = os.fdopen(read_pipe, "rb", buffering=READ_PIPE_BUFFER_SIZE)

    _serial = Serial(port=port, baudrate=baudrate, write_timeout=0)

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
    to_write_out = bytearray()
    for next_command in commands:
        _serial.write(next_command + b"\r")
        data = _serial.read_until(b">")

        for line in data.split(b"\r"):
            if line := line.strip():
                to_write_out += ElmReaderMessage(str(time.time()).encode() + b" " + line + b"\n")

        # Use an outgoing buffer, so we don't block the serial port while we write to the pipe.
        # This ensures that the timestamps we attribute to read data are as accurate as possible.
        n_written = writer.write(data + b"\n")
        to_write_out = to_write_out[n_written:]

    assert False, "Should never reach this point"
