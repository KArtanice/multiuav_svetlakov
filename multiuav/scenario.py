"""Сценарий эксперимента: сколько дронов, кто чем управляется, где здания и финиш."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .control import ControlLimits


@dataclass(frozen=True)
class AlgorithmSpec:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Building:
    """Здание-параллелепипед: границы в плане (север, восток) и высота, м."""

    north: tuple[float, float]
    east: tuple[float, float]
    height: float


@dataclass(frozen=True)
class Finish:
    """Финишная зона: прямоугольник в плане (север, восток), м."""

    north: tuple[float, float]
    east: tuple[float, float]

    def reached(self, position: np.ndarray) -> bool:
        return (self.north[0] <= position[0] <= self.north[1]
                and self.east[0] <= position[1] <= self.east[1])


@dataclass
class Scenario:
    name: str
    drones: int
    leader: AlgorithmSpec
    followers: AlgorithmSpec
    rate_hz: float = 20.0
    duration_s: float = 120.0
    start_north: float = 0.0
    start_east: float = 0.0
    altitude: float = 10.0
    heading: float = 0.0  # рад
    spacing: float = 6.0  # м между дронами на старте
    buildings: list[Building] = field(default_factory=list)
    finish: Finish | None = None
    limits: ControlLimits = ControlLimits()

    def start_positions(self) -> list[np.ndarray]:
        """Стартовые точки NED: ведущий впереди, остальные колонной позади него."""
        back = -np.array([math.cos(self.heading), math.sin(self.heading)])
        points = []
        for i in range(self.drones):
            ne = np.array([self.start_north, self.start_east]) + back * self.spacing * i
            points.append(np.array([ne[0], ne[1], -self.altitude]))
        return points

    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data, default_name=Path(path).stem)

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_name: str = "scenario") -> Scenario:
        start = data.get("start", {})
        world = data.get("world", {})
        limits = data.get("limits", {})
        finish = data.get("finish")

        def spec(key: str, default: str) -> AlgorithmSpec:
            raw = data.get(key, {})
            if isinstance(raw, str):
                return AlgorithmSpec(raw)
            return AlgorithmSpec(raw.get("algorithm", default), dict(raw.get("params") or {}))

        return cls(
            name=data.get("name", default_name),
            drones=int(data.get("drones", 5)),
            leader=spec("leader", "gamepad"),
            followers=spec("followers", "single_file"),
            rate_hz=float(data.get("rate_hz", 20.0)),
            duration_s=float(data.get("duration_s", 120.0)),
            start_north=float(start.get("north", 0.0)),
            start_east=float(start.get("east", 0.0)),
            altitude=float(start.get("altitude", 10.0)),
            heading=math.radians(float(start.get("heading_deg", 0.0))),
            spacing=float(start.get("spacing", 6.0)),
            buildings=[Building(tuple(b["north"]), tuple(b["east"]), float(b.get("height", 50.0)))
                       for b in world.get("buildings", [])],
            finish=Finish(tuple(finish["north"]), tuple(finish["east"])) if finish else None,
            limits=ControlLimits(
                max_tilt=math.radians(float(limits.get("max_tilt_deg", 30.0))),
                max_yaw_rate=math.radians(float(limits.get("max_yaw_rate_deg", 90.0))),
                max_climb=float(limits.get("max_climb", 3.0)),
            ),
        )
