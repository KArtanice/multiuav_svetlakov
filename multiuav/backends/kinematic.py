"""Упрощённый симулятор без графики: точечная модель квадрокоптера и здания-коробки.

Нужен, чтобы отлаживать алгоритмы и гонять серии прогонов на любой машине,
в том числе в автоматических тестах. Модель грубая: наклон -> ускорение,
линейное сопротивление воздуха, инерция наклона и вертикальной скорости.
Отлаженный здесь алгоритм потом проверяется в Cosys-AirSim.
"""

from __future__ import annotations

import math

import numpy as np

from ..control import G, rc_to_setpoint
from ..scenario import Scenario
from ..types import DroneState, RcOverride
from .base import SimBackend


class KinematicBackend(SimBackend):
    realtime = False

    def __init__(self, drone_radius: float = 0.4, drag: float = 0.35,
                 tilt_tau: float = 0.15, climb_tau: float = 0.3) -> None:
        self.drone_radius = drone_radius
        self.drag = drag
        self.tilt_tau = tilt_tau
        self.climb_tau = climb_tau

    def start(self, scenario: Scenario) -> None:
        n = scenario.drones
        self.limits = scenario.limits
        self.buildings = scenario.buildings
        self.pos = np.array(scenario.start_positions(), dtype=float)
        self.vel = np.zeros((n, 3))
        self.yaw = np.full(n, scenario.heading)
        self.tilt = np.zeros((n, 2))  # крен, тангаж
        self.collided = np.zeros(n, dtype=bool)
        self.commands = [RcOverride() for _ in range(n)]

    def states(self) -> list[DroneState]:
        return [DroneState(i, self.pos[i].copy(), self.vel[i].copy(), float(self.yaw[i]),
                           bool(self.collided[i])) for i in range(len(self.pos))]

    def send(self, drone_id: int, rc: RcOverride) -> None:
        self.commands[drone_id] = rc

    def advance(self, dt: float) -> None:
        k_tilt = min(1.0, dt / self.tilt_tau)
        k_climb = min(1.0, dt / self.climb_tau)
        for i, rc in enumerate(self.commands):
            if self.collided[i]:
                continue
            sp = rc_to_setpoint(rc, self.limits)
            self.tilt[i] += (np.array([sp.roll, sp.pitch]) - self.tilt[i]) * k_tilt
            self.yaw[i] = (self.yaw[i] + sp.yaw_rate * dt + math.pi) % (2 * math.pi) - math.pi
            roll, pitch = self.tilt[i]
            acc_forward, acc_right = G * math.tan(pitch), G * math.tan(roll)
            c, s = math.cos(self.yaw[i]), math.sin(self.yaw[i])
            acc = np.array([acc_forward * c - acc_right * s, acc_forward * s + acc_right * c])
            self.vel[i, :2] += (acc - self.drag * self.vel[i, :2]) * dt
            self.vel[i, 2] += (-sp.climb_rate - self.vel[i, 2]) * k_climb
            self.pos[i] += self.vel[i] * dt
        self._check_collisions()

    def _check_collisions(self) -> None:
        r = self.drone_radius
        for i, p in enumerate(self.pos):
            if self.collided[i]:
                continue
            altitude = -p[2]
            hit = altitude <= 0.0
            for b in self.buildings:
                if (b.north[0] - r <= p[0] <= b.north[1] + r
                        and b.east[0] - r <= p[1] <= b.east[1] + r and altitude < b.height):
                    hit = True
                    break
            if hit:
                self._crash(i)
        active = np.flatnonzero(~self.collided)
        for a_idx, i in enumerate(active):
            for j in active[a_idx + 1:]:
                if np.linalg.norm(self.pos[i] - self.pos[j]) < 2 * r:
                    self._crash(i)
                    self._crash(j)

    def _crash(self, i: int) -> None:
        self.collided[i] = True
        self.vel[i] = 0.0
