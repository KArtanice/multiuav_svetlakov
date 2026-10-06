"""Cosys-AirSim (Unreal Engine 5): реальная картинка и физика.

Перед запуском симулятор должен быть открыт, а в ~/Documents/AirSim/settings.json
лежать файл, созданный командой `python -m multiuav settings <сценарий>`:
имена и стартовые точки дронов берутся оттуда.
"""

from __future__ import annotations

import math
import time

import numpy as np

from ..control import rc_to_setpoint
from ..scenario import Scenario
from ..types import DroneState, RcOverride
from .base import SimBackend


def vehicle_name(drone_id: int) -> str:
    return f"Drone{drone_id}"


def _yaw_from_quaternion(q) -> float:
    w, x, y, z = q.w_val, q.x_val, q.y_val, q.z_val
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class CosysBackend(SimBackend):
    realtime = True

    def __init__(self, host: str = "127.0.0.1", command_duration: float = 0.5) -> None:
        self.host = host
        # Сколько дрон выполняет последнюю команду, если новые перестали приходить.
        self.command_duration = command_duration

    def start(self, scenario: Scenario) -> None:
        import cosysairsim as airsim

        self.limits = scenario.limits
        self.client = airsim.MultirotorClient(ip=self.host)
        self.client.confirmConnection()
        self.names = [vehicle_name(i) for i in range(scenario.drones)]
        missing = set(self.names) - set(self.client.listVehicles())
        if missing:
            raise RuntimeError(
                f"В симуляторе нет дронов {sorted(missing)}. Создай settings.json командой "
                "`python -m multiuav settings <сценарий>` и перезапусти симулятор.")

        # Позиции в AirSim отсчитываются от точки старта каждого дрона,
        # поэтому храним эти точки, чтобы перевести всё в общую систему.
        self.origins = [np.array([p[0], p[1], 0.0]) for p in scenario.start_positions()]
        self.z_target = [-scenario.altitude for _ in self.names]
        self._last_send = [time.monotonic() for _ in self.names]

        for name in self.names:
            self.client.enableApiControl(True, name)
            self.client.armDisarm(True, name)
        for f in [self.client.takeoffAsync(vehicle_name=n) for n in self.names]:
            f.join()
        for f in [self.client.moveToZAsync(-scenario.altitude, 3.0, vehicle_name=n)
                  for n in self.names]:
            f.join()
        # Касания земли при взлёте не считаем столкновениями.
        self._collision_baseline = [self.client.simGetCollisionInfo(n).time_stamp
                                    for n in self.names]

    def states(self) -> list[DroneState]:
        result = []
        for i, name in enumerate(self.names):
            k = self.client.simGetGroundTruthKinematics(name)
            pos = self.origins[i] + np.array([k.position.x_val, k.position.y_val, k.position.z_val])
            vel = np.array([k.linear_velocity.x_val, k.linear_velocity.y_val,
                            k.linear_velocity.z_val])
            info = self.client.simGetCollisionInfo(name)
            collided = info.has_collided and info.time_stamp > self._collision_baseline[i]
            result.append(DroneState(i, pos, vel, _yaw_from_quaternion(k.orientation), collided))
        return result

    def send(self, drone_id: int, rc: RcOverride) -> None:
        now = time.monotonic()
        dt = min(now - self._last_send[drone_id], 0.5)
        self._last_send[drone_id] = now
        sp = rc_to_setpoint(rc, self.limits)
        # Режим удержания высоты: стик газа задаёт скорость набора, копим её в целевую высоту.
        self.z_target[drone_id] -= sp.climb_rate * dt
        # В клиенте Cosys положительный yaw_rate — поворот влево, у нас — вправо.
        self.client.moveByRollPitchYawrateZAsync(
            sp.roll, sp.pitch, -sp.yaw_rate, self.z_target[drone_id],
            self.command_duration, vehicle_name=self.names[drone_id])

    def advance(self, dt: float) -> None:
        pass  # Unreal живёт в реальном времени, менеджер сам выдерживает темп.

    def close(self) -> None:
        for name in getattr(self, "names", []):
            try:
                self.client.hoverAsync(vehicle_name=name)
            except Exception:
                pass
