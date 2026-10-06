"""Менеджер группы: цикл «прочитать состояния -> спросить алгоритмы -> отправить команды»."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .algorithms import FollowerAlgorithm, load_algorithm
from .backends.base import SimBackend
from .scenario import Scenario
from .types import DroneState


@dataclass
class RunResult:
    scenario: str
    leader: str
    followers: str
    drones: int
    sim_time: float = 0.0
    finished: dict[int, float] = field(default_factory=dict)  # номер дрона -> время финиша, с
    collided: dict[int, float] = field(default_factory=dict)  # номер дрона -> время столкновения
    track: list[tuple[float, int, float, float, float, float, bool]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return len(self.finished) / self.drones if self.drones else 0.0

    @property
    def group_time(self) -> float | None:
        """Время, за которое финишировал последний дошедший дрон."""
        return max(self.finished.values()) if self.finished else None

    def summary(self) -> dict:
        return {
            "scenario": self.scenario,
            "leader": self.leader,
            "followers": self.followers,
            "drones": self.drones,
            "finished": len(self.finished),
            "collided": len(self.collided),
            "success_rate": round(self.success_rate, 3),
            "group_time_s": None if self.group_time is None else round(self.group_time, 2),
            "sim_time_s": round(self.sim_time, 2),
            "collisions": {str(k): round(v, 2) for k, v in sorted(self.collided.items())},
        }

    def save(self, directory: str | Path) -> Path:
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "track.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["t", "drone", "north", "east", "altitude", "yaw", "collided"])
            writer.writerows(self.track)
        with open(out / "summary.json", "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, ensure_ascii=False, indent=2)
        return out


class SwarmManager:
    def __init__(self, scenario: Scenario, backend: SimBackend) -> None:
        self.scenario = scenario
        self.backend = backend
        leader_cls = load_algorithm(scenario.leader.name)
        follower_cls = load_algorithm(scenario.followers.name)
        self.algorithms: list[FollowerAlgorithm] = [
            leader_cls(0, scenario.leader.params, scenario.limits)]
        self.algorithms += [follower_cls(i, scenario.followers.params, scenario.limits)
                            for i in range(1, scenario.drones)]

    def run(self) -> RunResult:
        sc = self.scenario
        result = RunResult(sc.name, sc.leader.name, sc.followers.name, sc.drones)
        dt = 1.0 / sc.rate_hz
        t = 0.0
        self.backend.start(sc)
        next_tick = time.monotonic()
        try:
            while t <= sc.duration_s:
                states = self.backend.states()
                self._record(result, states, t)
                if len(result.finished) + len(result.collided) >= sc.drones:
                    break
                leader = states[0]
                for state in states:
                    if state.collided:
                        continue
                    others = [s for s in states if s.id != state.id]
                    rc = self.algorithms[state.id].step(state, others, leader, t)
                    self.backend.send(state.id, rc)
                self.backend.advance(dt)
                t += dt
                if self.backend.realtime:
                    next_tick += dt
                    time.sleep(max(0.0, next_tick - time.monotonic()))
        finally:
            self.backend.close()
        result.sim_time = t
        return result

    def _record(self, result: RunResult, states: list[DroneState], t: float) -> None:
        finish = self.scenario.finish
        for s in states:
            result.track.append((round(t, 3), s.id, round(float(s.position[0]), 3),
                                 round(float(s.position[1]), 3), round(s.altitude, 3),
                                 round(s.yaw, 4), s.collided))
            if s.collided and s.id not in result.collided and s.id not in result.finished:
                result.collided[s.id] = t
            if (finish and not s.collided and s.id not in result.finished
                    and finish.reached(s.position)):
                result.finished[s.id] = t
