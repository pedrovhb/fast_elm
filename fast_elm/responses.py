from __future__ import annotations

import struct
import time
from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from typing import TypeVar, Generic, ClassVar, Type, Callable, NamedTuple

# from loguru import logger


T = TypeVar("T")
_ObdValueT = TypeVar("_ObdValueT", int, float, bytes)


@dataclass(slots=True)
class ObdMessageType(Generic[_ObdValueT]):
    prefix: bytes
    name: str
    value_calculator: Callable[[bytes], _ObdValueT]
    unit: str
    bytes_length: int


def divide_a_by_4(data: bytes) -> float:
    return int(data, 16) / 4


def subtract_40_from_a(data: bytes) -> float:
    return int(data, 16) - 40


def return_a(data: bytes) -> float:
    return int(data, 16) / 2


obd_message_types: dict[bytes, ObdMessageType] = {
    b"4105": ObdMessageType(
        prefix=b"4105",
        name="Engine RPM",
        value_calculator=divide_a_by_4,
        unit="rpm",
        bytes_length=4,
    ),
    b"410C": ObdMessageType(
        prefix=b"410C",
        name="Engine coolant temperature",
        value_calculator=lambda x: int(x, 16) - 40,
        unit="°C",
        bytes_length=4,
    ),
    b"410D": ObdMessageType(
        prefix=b"410D",
        name="Vehicle speed",
        value_calculator=lambda x: int(x, 16),
        unit="km/h",
        bytes_length=4,
    ),
}

b = obd_message_types[b"4105"].value_calculator(b"0000")


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

_command_subclasses: dict[bytes, Type[ObdResponseBase]] = {}


class ObdResponseBase(Generic[_ObdValueT], ABC):
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

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.response_prefix is not None:
            _command_subclasses[cls.response_prefix] = cls

    def __new__(cls, data: bytes, timestamp: float) -> ObdResponseBase:
        print(data)
        data = data.lstrip(b"\x00")
        if cls is ObdResponseBase:
            data = data.replace(b" ", b"")
            prefix = data[:4]
            if prefix in _command_subclasses:
                return _command_subclasses[prefix](data, timestamp)
            # logger.warning(f"Unknown response prefix: {prefix!r}")
            else:
                return ObdResponse(data, timestamp)
            # return _command_subclasses[None](data, timestamp)

        return super().__new__(cls)

    def __init__(self, data: bytes, timestamp: float) -> None:
        self.data = data.replace(b" ", b"")
        self.timestamp = timestamp

    # @property
    # def response_type(self) -> ElmResponseType:
    #     todo [:4] probably not applicable for all responses
    # return ElmResponseType(self.data[:4])

    @classmethod
    def from_bin(cls, bin_data: bytes):
        timestamp, data = struct.unpack("f16s", bin_data)
        return cls(data, timestamp)

    @property
    def value(self) -> T:
        raise NotImplementedError

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)

    @property
    def bin(self) -> bytes:
        padded_data = self.data.rjust(16, b"\x00")
        return struct.pack(
            "f16s",
            self.timestamp,
            padded_data,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.value} {self.unit}, {self.dt.isoformat()})>"

    # def as_bytes(self) -> bytes:
    #     return self.timestamp).decode() self.data


class ObdResponse(ObdResponseBase[bytes]):
    unit: ClassVar[str] = "bytes"
    byte_count: ClassVar[int] = 4
    response_prefix = b""

    @property
    def value(self) -> bytes:
        return self.data


class ResponseCoolantTemperature(ObdResponseBase[int]):
    response_prefix: ClassVar[bytes] = b"4105"
    byte_count: ClassVar[int] = 4
    unit: ClassVar[str] = "°C"

    @property
    def value(self) -> int:
        return int(self.data[4:], 16) - 40


class ResponseEngineRPM(ObdResponseBase[float]):
    response_prefix: ClassVar[bytes] = b"410C"
    byte_count: ClassVar[int] = 4
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

RESPONSE_PREFIXES = {
    b"4105": ResponseCoolantTemperature,
    b"410C": ResponseEngineRPM,
    b"410D": ResponseVehicleSpeed,
    b"": ObdResponse,
}
