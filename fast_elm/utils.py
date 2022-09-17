from __future__ import annotations

import asyncio
import functools
from abc import ABC
from typing import (
    Any,
    Callable,
    ClassVar,
    Coroutine,
    Generic,
    ParamSpec,
    Type,
    TypeVar,
)

import loguru
from loguru import logger
from rich.console import Console as RichConsole
from rich.console import ConsoleRenderable, Group, RenderableType, RichCast
from rich.live import Live as RichLive
from rich.panel import Panel

T = TypeVar("T")
_U = TypeVar("_U")
_V = TypeVar("_V")
P = ParamSpec("P")


def run_sync(f: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, T]:
    """Given a function, return a new function that runs the original one with asyncio.

    This is useful for functions that need to be run in a synchronous manner,
    such as Typer commands.

    Args:
        f: The function to run synchronously.

    Returns:
        A new function that runs the original one with `asyncio.run`.
    """

    @functools.wraps(f)
    def decorated(*args: P.args, **kwargs: P.kwargs) -> T:
        return asyncio.run(f(*args, **kwargs))

    return decorated


class StatusItemBase(RichCast, Generic[T], ABC):
    _status_items: ClassVar[dict[str, StatusItemBase[Any]]] = {}
    _dirty: ClassVar[asyncio.Event] = asyncio.Event()
    _updater_running: ClassVar[bool] = False

    _value: T

    def __init_subclass__(cls: Type[StatusItemBase[T]], **kwargs: Any) -> None:
        cls._status_items = StatusItemBase._status_items
        super().__init_subclass__(**kwargs)
        # todo maybe move logic to __init__

    # def __init__(self) -> None:
    #     if not self._updater_running:
    #         asyncio.create_task(self.update_status_loop())

    def __rich__(self) -> ConsoleRenderable | RichCast | str:
        raise NotImplementedError

    @property
    def value(self) -> T:
        return self._value

    @value.setter
    def value(self, value: T) -> None:
        self._value = value
        StatusItemBase._dirty.set()

    @staticmethod
    async def update_status_loop() -> None:
        """Update the status panel."""
        try:
            if StatusItemBase._updater_running:
                # logger.error("Status updater already running - there should only be one. Exiting.")
                return
            StatusItemBase._updater_running = True
            while True:
                await StatusItemBase._dirty.wait()
                await asyncio.sleep(0.01)  # debounce
                status_panel = Panel(
                    Group(*StatusItemBase._status_items.values()),
                    title="Status",
                    title_align="left",
                    border_style="bright_blue",
                )
                live.update(status_panel, refresh=True)
                StatusItemBase._dirty.clear()
        finally:
            StatusItemBase._updater_running = False


class StatusItem(StatusItemBase[T]):
    def __init__(
        self,
        name: str,
        value: T,
        name_color: str = "green",
        value_color: str = "white",
    ) -> None:
        super().__init__()
        StatusItemBase._status_items[name] = self
        self.name = name
        self._value: T = value
        self.name_color = name_color
        self.value_color = value_color

    def __str__(self) -> str:
        return f"{self.name}: {self.value}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r}, {self.value!r})"

    def __rich__(self) -> ConsoleRenderable | RichCast | str:
        return (
            f"[bold {self.name_color}]{self.name}[/]"
            f"[bold white]:[/] [{self.value_color}]{self.value}[/]"
        )

    def update_on_fun_entry(
        self, fun: Callable[P, _U], message: str | None = None
    ) -> Callable[P, _U]:
        """Update the status item when the function is entered."""

        @functools.wraps(fun)
        def decorated(*args: P.args, **kwargs: P.kwargs) -> _U:
            self.value = f"Entering {fun.__name__}" if message is None else message
            return fun(*args, **kwargs)

        return decorated

    def update_on_fun_exit(
        self, fun: Callable[P, _U], message: str | None = None
    ) -> Callable[P, _U]:
        """Update the status item when the function exits."""

        @functools.wraps(fun)
        def decorated(*args: P.args, **kwargs: P.kwargs) -> _U:
            try:
                return fun(*args, **kwargs)
            finally:
                self.value = f"Exiting {fun.__name__}" if message is None else message

        return decorated


class PanStatusItem(StatusItem[str]):
    def __rich__(self) -> RenderableType:
        return Panel("[bold white]" + str(self) + "[/]", border_style="bright_blue")


cs = RichConsole()
live_obj = Panel("hello world!", title="Live", expand=True, height=10)
live = RichLive(live_obj, console=cs, auto_refresh=False)


async def alog(message: loguru.Message) -> None:
    """Custom logging function."""
    level_colors = {
        "DEBUG": "blue",
        "TRACE": "white",
        "INFO": "yellow",
        "IMPORTANT": "yellow",
        "WARNING": "orange",
        "ERROR": "red",
        "CRITICAL": "bold red",
    }
    level = message.record["level"].name
    color = level_colors.get(level, "purple")
    to_print = (
        f"{message.record['time'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} "
        f"| [{color}]{level:<9}[/] | "
        f"{message.record['message']}"
    )
    cs.print(to_print)


logger.configure(
    handlers=[
        {"sink": alog, "level": "TRACE"},
        {"sink": "file.log", "serialize": True},
    ]
)


def my_main(fn: Callable[P, Coroutine[_U, _V, T]]) -> Callable[P, Coroutine[_U, _V, T]]:
    @functools.wraps(fn)
    async def _main(*args: P.args, **kwargs: P.kwargs) -> T:
        with live:
            _ = asyncio.create_task(StatusItemBase.update_status_loop())
            result = await fn(*args, **kwargs)
            other_tasks = asyncio.all_tasks()
            if (crt_task := asyncio.current_task()) is not None:
                other_tasks.remove(crt_task)
            await asyncio.gather(*other_tasks)
        return result

    return _main


@my_main
async def main() -> None:
    logger.debug("hello world")
    await asyncio.sleep(0.1)
    logger.debug("hello world 2")
    i = 0
    i_status = StatusItem("i", "current mod: 0")
    power_status = PanStatusItem("power", "0")
    while True:
        await asyncio.sleep(0.1)
        logger.trace(f"hello world {i}")
        if i % 2 != 0:
            power_status.value = str(i**2)
        if i % 10 == 0:
            i_status.value = f"current mod: {i}"
        i += 1


if __name__ == "__main__":
    asyncio.run(main())
