"""settings.json для Cosys-AirSim, собранный из сценария."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .backends.cosys import vehicle_name
from .scenario import Scenario

DEFAULT_PATH = Path.home() / "Documents" / "AirSim" / "settings.json"


def build_settings(scenario: Scenario) -> dict:
    vehicles = {}
    for i, p in enumerate(scenario.start_positions()):
        vehicles[vehicle_name(i)] = {
            "VehicleType": "SimpleFlight",
            "X": round(float(p[0]), 2),
            "Y": round(float(p[1]), 2),
            "Z": 0,  # на земле под точкой старта; высоту набирает менеджер
            "Yaw": round(math.degrees(scenario.heading), 1),
        }
    return {
        "SettingsVersion": 2.0,
        "SimMode": "Multirotor",
        "ClockSpeed": 1,
        "ViewMode": "FlyWithMe",
        "Vehicles": vehicles,
    }


def write_settings(scenario: Scenario, path: Path = DEFAULT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_settings(scenario), indent=2), encoding="utf-8")
    return path
