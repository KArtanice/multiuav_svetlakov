"""Базовые типы: состояние дрона и команда в стиле RC Override.

Мировая система координат везде NED, как в AirSim и ArduPilot:
x — на север, y — на восток, z — вниз (высота = -z). Метры, секунды, радианы.
Курс (yaw): 0 — север, положительный — поворот по часовой стрелке (вправо).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000
RC_HALF = (RC_MAX - RC_MIN) / 2


@dataclass(frozen=True)
class DroneState:
    """Объективное состояние дрона, которое получают алгоритмы."""

    id: int
    position: np.ndarray  # м, NED
    velocity: np.ndarray  # м/с, NED
    yaw: float  # рад
    collided: bool = False

    @property
    def altitude(self) -> float:
        return -float(self.position[2])

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.velocity[:2]))


def _to_pwm(value: float) -> int:
    value = max(-1.0, min(1.0, float(value)))
    return int(round(RC_MID + value * RC_HALF))


def _from_pwm(pwm: int) -> float:
    return max(-1.0, min(1.0, (pwm - RC_MID) / RC_HALF))


@dataclass(frozen=True)
class RcOverride:
    """Команда управления как с пульта: четыре канала по 1000..2000, 1500 — центр.

    Режим полёта с удержанием высоты (как AltHold в ArduPilot):
      roll     > 1500 — крен вправо, дрон смещается вправо;
      pitch    > 1500 — наклон вперёд, дрон летит вперёд (стик от себя);
      throttle > 1500 — набор высоты, 1500 — держать высоту;
      yaw      > 1500 — поворот вправо (по часовой стрелке).
    """

    roll: int = RC_MID
    pitch: int = RC_MID
    throttle: int = RC_MID
    yaw: int = RC_MID

    @classmethod
    def from_normalized(cls, roll: float = 0.0, pitch: float = 0.0,
                        throttle: float = 0.0, yaw: float = 0.0) -> RcOverride:
        """Собрать команду из значений -1..1 по каждому каналу."""
        return cls(_to_pwm(roll), _to_pwm(pitch), _to_pwm(throttle), _to_pwm(yaw))

    def normalized(self) -> tuple[float, float, float, float]:
        """Каналы в виде -1..1: (roll, pitch, throttle, yaw)."""
        return (_from_pwm(self.roll), _from_pwm(self.pitch),
                _from_pwm(self.throttle), _from_pwm(self.yaw))


def wrap_angle(angle: float) -> float:
    """Привести угол к диапазону -pi..pi."""
    return (angle + math.pi) % (2 * math.pi) - math.pi
