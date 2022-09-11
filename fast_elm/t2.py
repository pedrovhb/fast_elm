import asyncio
import multiprocessing
import os
import time
from collections import defaultdict
from itertools import cycle
from typing import NoReturn, cast, AsyncIterator
from serial import Serial

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
    _serial.read_until(b">")

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


class ElmProtocol:
    def __init__(self, write_pipe: int, read_pipe: int):
        self.elm_read = os.fdopen(read_pipe, "rb", buffering=READ_PIPE_BUFFER_SIZE)
        self.elm_write = os.fdopen(write_pipe, "wb", buffering=WRITE_PIPE_BUFFER_SIZE)

        self.at_prompt = asyncio.Event()
        self.has_message = asyncio.Event()

    async def raw_stream(self) -> AsyncIterator[bytes]:

        loop = asyncio.get_event_loop()
        stream_reader = asyncio.StreamReader()

        def protocol_factory():
            return asyncio.StreamReaderProtocol(stream_reader)

        transport, _ = await loop.connect_read_pipe(protocol_factory, self.elm_read)

        async for raw_line in stream_reader:
            line = cast(bytes, raw_line)  # type: ignore
            data = line.replace(b"\r", b"").replace(b">", b"").strip()
            yield data

    async def __aiter__(self) -> AsyncIterator[tuple[str, int]]:
        async for raw_line in self.raw_stream():
            raw_line = raw_line.replace(b" ", b"")
            if raw_line.startswith(b"4105"):
                yield "coolant_temp", int(raw_line[4:6], 16) - 40
            elif raw_line.startswith(b"410C"):
                yield "rpm", int(raw_line[4:8], 16) // 4
            elif raw_line.startswith(b"410D"):
                yield "speed", int(raw_line[4:6], 16)


async def main() -> None:
    device = "/dev/pts/3"
    baudrate = 38400

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

    c: dict[int, int] = defaultdict(int)
    async for line in prot:
        print(line)
        c[crt_second := int(time.time())] += 1
        mps = c[crt_second - 1]
        print(f"Messages per second: {mps} ({1000 / (mps or 1):.3f} ms/message)")
        # With ELM327-emulator: `Messages per second: 3056 (0.327 ms/message)`


if __name__ == "__main__":
    asyncio.run(main())
