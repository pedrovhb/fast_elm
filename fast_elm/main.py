import atexit
import os
import time
from datetime import datetime
from functools import partial, partialmethod
from pathlib import Path
from typing import NoReturn, AsyncIterator

import zstandard
from serial import Serial

from fast_elm import utils
import asyncio
import serial_asyncio
import serial.tools.list_ports
import typer as typer
from loguru import logger

from fast_elm.utils import run_sync, StatusItem


class ElmProtocol(asyncio.Protocol):
    transport: serial_asyncio.SerialTransport
    _buffer: bytes = b""
    _messages: list[bytes] = []
    _timestamps: list[float] = []

    at_prompt = asyncio.Event()
    has_message = asyncio.Event()

    def connection_made(self, transport: serial_asyncio.SerialTransport) -> None:
        self.transport = transport
        logger.info(f"Port {transport.serial.port} opened")
        transport.write(b"\ratz\r")

    def data_received(self, data: bytes) -> None:
        logger.debug(f"Received {data!r}")
        self._buffer += data
        self.at_prompt.clear()
        self._process_buffer()

    def _process_buffer(self) -> None:
        while b"\r" in self._buffer:
            index = self._buffer.index(b"\r")
            if message := self._buffer[:index]:
                self._messages.append(message.strip(b"\r>"))
                self._timestamps.append(time.time())
                print(message)
            self._buffer = self._buffer[index + 1 :]

        if self._buffer == b">":
            logger.trace("Got prompt from ELM327")
            self.at_prompt.set()
            self._buffer = b""

        print(f"Setting messages to {self._messages}")
        if self._messages:
            self.has_message.set()

    async def write(
        self,
        *messages: bytes,
        wait_prompt_before_send: bool = False,
        wait_prompt_after_send: bool = False,
    ) -> None:

        if wait_prompt_before_send and not self.at_prompt.is_set():
            logger.trace(f"Waiting for prompt before sending {messages}")
            await self.at_prompt.wait()

        message_bytes = b"\r".join(m.strip(b"\r") for m in messages) + b"\r"
        self.at_prompt.clear()
        logger.debug(f"Sending {message_bytes!r}")
        self.transport.write(message_bytes)
        if wait_prompt_after_send:
            logger.trace(f"Waiting for prompt after sending {messages}")
            await self.at_prompt.wait()

    # async def __aiter__(self) -> AsyncIterator[tuple[bytes]]:
    #     while True:
    #         logger.trace("Waiting for message")
    #         await self.has_message.wait()
    #         self.has_message.clear()
    #         logger.trace(f"Yielding {len(self._messages)} messages")
    #         for message in self._messages:
    #             yield message
    #         self._messages = []

    async def aiter_messages_timestamps(self) -> AsyncIterator[tuple[list[bytes], list[float]]]:
        while True:
            logger.trace("Waiting for message")
            await self.has_message.wait()
            print("mmm", self._messages)
            msgs = self._messages
            self.has_message.clear()
            logger.trace(f"Yielding {len(self._messages)} messages")
            yield self._messages, self._timestamps
            self._messages = []
            self._timestamps = []

    def connection_lost(self, exc: Exception | None) -> None:
        print("port closed")
        self.transport.loop.stop()

    def pause_writing(self) -> None:
        print("pause writing")
        print("out_waiting", self.transport.serial.out_waiting)
        print("in_waiting", self.transport.serial.in_waiting)
        print(self.transport.get_write_buffer_size())

    def resume_writing(self) -> None:
        print(self.transport.get_write_buffer_size())
        print("out_waiting", self.transport.serial.out_waiting)
        print("in_waiting", self.transport.serial.in_waiting)
        print("resume writing")


app = typer.Typer()


async def reader(read):
    pipe = os.fdopen(read, mode="r")

    loop = asyncio.get_event_loop()
    stream_reader = asyncio.StreamReader()

    def protocol_factory():
        return asyncio.StreamReaderProtocol(stream_reader)

    transport, _ = await loop.connect_read_pipe(protocol_factory, pipe)
    print(await stream_reader.readline())
    transport.close()


def writer(write):
    os.write(write, b"Hello World\n")


if __name__ == "__main__":
    main()


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
        ports = serial.tools.list_ports.comports()
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

    current_status.value = f"Connecting to ELM327 using device {device} and baudrate {baudrate}"

    loop = asyncio.get_running_loop()
    _, protocol = await serial_asyncio.create_serial_connection(
        loop,
        ElmProtocol,
        device,
        baudrate=baudrate,
        # timeout=0,
        # write_timeout=0,
    )

    current_status.value = f"Connected to ELM327. Waiting for prompt."
    await protocol.at_prompt.wait()

    current_status.value = f"Connected to ELM327, waiting for messages after sending 0100."
    await protocol.write(b"atsp6", b"ate0", b"ats0", b"0100", wait_prompt_before_send=True)

    latest_message = StatusItem("Latest message", "No messages received")
    current_status.value = f"Connected to ELM327, running main loop."

    coolant_temp = StatusItem("Coolant temp".ljust(14), "N/A")
    rpm = StatusItem("RPM".ljust(14), "N/A")
    speed = StatusItem("Speed".ljust(14), "N/A")
    time_taken_status = StatusItem("Time taken".ljust(14), "N/A")
    message_buf: list[bytes] = []
    timestamp_buf: list[float] = []

    def message_buf_watcher() -> NoReturn:
        filename = datetime.now().strftime("elm_%Y-%m-%d__%H-%M-%S")
        f = zstandard.open(filename + ".obd.zst", "ab")
        f_timestamps = zstandard.open(filename + ".timestamps.zst", "ab")

        def dump_file() -> None:
            print(f"Message buffer has {len(message_buf)} messages. Clearing.")
            t0 = time.perf_counter_ns()
            f.write(b":".join(message_buf))
            f_timestamps.write(b":".join(str(t).encode("utf-8") for t in timestamp_buf))
            message_buf.clear()
            timestamp_buf.clear()
            print(
                f"Message buffer written to file "
                f"in {(time.perf_counter_ns() - t0) / 1_000_000:.4f} ms"
            )

        atexit.register(dump_file)
        while True:
            time.sleep(10)
            if len(message_buf) > 1000:
                dump_file()
                message_buf.clear()

    t = asyncio.create_task(asyncio.to_thread(message_buf_watcher))
    t0 = time.perf_counter_ns()
    max_time: float = 0
    async for messages, timestamps in protocol.aiter_messages_timestamps():
        # timestamp, message_bytes = message
        print(f"Received {len(messages)} messages, {len(timestamps)} timestamps")
        message_buf.extend(messages)
        timestamp_buf.extend(timestamps)

        for message_bytes, timestamp in zip(messages, timestamps):
            print(f"{timestamp:.4f} {message_bytes}")
            t1 = time.perf_counter_ns()
            time_taken = (t1 - t0) / 1_000_000

            if time_taken > 2:
                time_taken_status.value = f"{time_taken:.4f} ms"
            if time_taken > max_time:
                max_time = time_taken
                print(f"Max time taken: {max_time:.4f} ms")

            latest_message.value = message_bytes.decode("ascii")
            if message_bytes.startswith(b"4105"):
                coolant_temp.value = f"{int(message_bytes[4:6], 16) - 40:>3}   °C".rjust(12)
            elif message_bytes.startswith(b"410C"):
                rpm.value = f"{int(message_bytes[4:8], 16) / 4:>4.0f}  RPM".rjust(12)
            elif message_bytes.startswith(b"410D"):
                speed.value = f"{int(message_bytes[4:6], 16):>3} km/h".rjust(12)

        t0 = time.perf_counter_ns()
        await protocol.write(b"0105", b"010C", b"010D", wait_prompt_before_send=True)


if __name__ == "__main__":
    # logger = logger.bind(level="INFO")
    # logger.remove()
    app()
