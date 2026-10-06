"""Ручное управление ведущим с геймпада (раскладка Mode 2, как на пульте)."""

from __future__ import annotations

import os

from ..types import DroneState, RcOverride
from .base import FollowerAlgorithm

# Оси по умолчанию для геймпада Xbox под Linux. Свои номера осей
# можно узнать командой `python -m multiuav gamepad` и задать в params.
DEFAULT_AXES = {"yaw": 0, "throttle": 1, "roll": 3, "pitch": 4}


class GamepadPilot(FollowerAlgorithm):
    """Левый стик: вверх-вниз — высота, влево-вправо — поворот.
    Правый стик: вверх-вниз — вперёд-назад, влево-вправо — крен.

    Параметры: axes — номера осей {roll, pitch, throttle, yaw};
    invert — оси, которые надо перевернуть (по умолчанию pitch и throttle,
    потому что у геймпадов «вверх» — это минус); deadzone — мёртвая зона (0.08);
    joystick — номер геймпада (0).
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        self._pygame = pygame
        pygame.init()
        pygame.joystick.init()
        index = int(self.param("joystick", 0))
        if pygame.joystick.get_count() <= index:
            raise RuntimeError("Геймпад не найден. Подключи его и проверь: python -m multiuav gamepad")
        self.joystick = pygame.joystick.Joystick(index)
        self.joystick.init()
        self.axes = {**DEFAULT_AXES, **self.param("axes", {})}
        self.invert = set(self.param("invert", ["pitch", "throttle"]))
        self.deadzone = float(self.param("deadzone", 0.08))

    def _axis(self, name: str) -> float:
        value = self.joystick.get_axis(int(self.axes[name]))
        if abs(value) < self.deadzone:
            value = 0.0
        return -value if name in self.invert else value

    def step(self, me: DroneState, others: list[DroneState], leader: DroneState,
             t: float) -> RcOverride:
        self._pygame.event.pump()
        return RcOverride.from_normalized(
            roll=self._axis("roll"), pitch=self._axis("pitch"),
            throttle=self._axis("throttle"), yaw=self._axis("yaw"))
