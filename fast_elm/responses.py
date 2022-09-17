from __future__ import annotations

import time
from abc import ABC
from datetime import datetime
from enum import Enum

from typing import TypeVar, Generic, ClassVar, Type

from fast_elm.reader import ElmReaderMessage

# from loguru import logger


T = TypeVar("T")


# class ElmResponseType(bytes, Enum):
#
#     CoolantTemperature = b"4105"
#     EngineRPM = b"410C"
#     VehicleSpeed = b"410D"
#
#     def __eq__(self, other: object) -> bool:
#         if isinstance(other, bytes):
#             return self.value == other.replace(b" ", b"")
#         return super().__eq__(other)

_command_subclasses: dict[bytes | None, Type[ObdResponseBase]] = {}


class ObdResponseBase(Generic[T], ABC):
    data: bytes
    timestamp: float

    response_prefix: ClassVar[bytes]
    unit: ClassVar[str]

    __slots__ = ("data", "timestamp")

    # def __init_subclass__(cls) -> None:
    #     if cls.response_prefix in _command_subclasses:
    # raise ValueError(f"Duplicate response prefix: {response_prefix!r}")
    # print(f"Duplicate response prefix: {cls.response_prefix!r}")
    # _command_subclasses[cls.response_prefix] = cls

    def __new__(cls, data: ElmReaderMessage) -> ObdResponseBase[T]:
        if cls is ObdResponseBase:
            timestamp, data = data.split(b" ", maxsplit=1)
            timestamp = float(timestamp.decode())

            data = data.replace(b" ", b"")
            prefix = data[:4]

            if prefix in _command_subclasses:
                obj_cls = _command_subclasses[prefix]
                obj = super().__new__(obj_cls)
                obj.data = data
                obj.timestamp = timestamp
                # return _command_subclasses[prefix](timestamp, data)
                return obj
            else:
                obj_cls = ObdResponse
                obj = super().__new__(obj_cls)
                obj.data = data
                obj.timestamp = timestamp
                return obj

        return super().__new__(cls)

    # def __init__(self, timestamp: float, data: bytes) -> None:
    #     self.data = data
    #     self.timestamp = timestamp

    # @property
    # def response_type(self) -> ElmResponseType:
    #     todo [:4] probably not applicable for all responses
    # return ElmResponseType(self.data[:4])

    @property
    def value(self) -> T:
        raise NotImplementedError

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.value} {self.unit}, {self.dt.isoformat()})>"

    # def as_bytes(self) -> bytes:
    #     return self.timestamp).decode() self.data


class ObdResponse(ObdResponseBase[bytes]):
    unit: ClassVar[str] = "bytes"

    @property
    def value(self) -> bytes:
        return self.data


class ResponseCoolantTemperature(ObdResponseBase[int]):
    response_prefix: ClassVar[bytes] = b"4105"
    unit: ClassVar[str] = "°C"

    @property
    def value(self) -> int:
        return int(self.data[4:], 16) - 40


class ResponseEngineRPM(ObdResponseBase[float]):
    response_prefix: ClassVar[bytes] = b"410C"
    unit = "rpm"

    @property
    def value(self) -> float:
        return int(self.data[4:], 16) / 4


class ResponseVehicleSpeed(ObdResponseBase[int]):
    response_prefix: ClassVar[bytes] = b"410D"
    unit = "km/h"

    @property
    def value(self) -> int:
        return int(self.data[4:], 16)


_command_subclasses[ResponseCoolantTemperature.response_prefix] = ResponseCoolantTemperature
_command_subclasses[ResponseEngineRPM.response_prefix] = ResponseEngineRPM
_command_subclasses[ResponseVehicleSpeed.response_prefix] = ResponseVehicleSpeed
"""
if __name__ == "__main__":
RESPONSE_PREFIXES = {
    b"4105": ResponseCoolantTemperature,
    b"410C": ResponseEngineRPM,
    b"410D": ResponseVehicleSpeed,
    b"": ObdResponse,
}

r = None
t = time.perf_counter_ns()
for _ in range(1000000):
    ResponseCoolantTemperature(b"4105 00", 0)
    ResponseEngineRPM(b"410C 0000", 0)
    r = ResponseVehicleSpeed(b"410D 00", 0)
    ObdResponse(b"4105 00", 0)
print(time.perf_counter_ns() - t)
print(r)
"""
