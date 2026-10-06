import dataclasses
from pathlib import Path

import pytest

from multiuav.backends.kinematic import KinematicBackend
from multiuav.cosys_settings import build_settings
from multiuav.manager import SwarmManager
from multiuav.scenario import AlgorithmSpec, Scenario

ROOT = Path(__file__).resolve().parents[1]
CORNER = ROOT / "scenarios" / "corner.yaml"


def run(algorithm: str, drones: int):
    base = Scenario.load(CORNER)
    sc = dataclasses.replace(base, drones=drones,
                             followers=AlgorithmSpec(algorithm, base.followers.params))
    return SwarmManager(sc, KinematicBackend()).run()


def test_leader_alone_reaches_finish():
    result = run("single_file", 1)
    assert result.finished.keys() == {0}
    assert not result.collided


def test_single_file_cuts_the_corner_with_long_column():
    # Ровно то, что видно на практике: хвост длинной колонны срезает угол.
    result = run("single_file", 10)
    assert result.collided
    assert 0 not in result.collided


@pytest.mark.parametrize("drones", [3, 5, 10])
def test_leader_path_passes_the_corner(drones):
    result = run("leader_path", drones)
    assert not result.collided
    assert len(result.finished) == drones


def test_custom_algorithm_from_file():
    result = run(f"{ROOT / 'examples' / 'my_algorithm.py'}:Cautious", 3)
    assert 0 in result.finished


def test_cosys_settings_match_start_positions():
    sc = Scenario.load(CORNER)
    vehicles = build_settings(sc)["Vehicles"]
    assert list(vehicles) == [f"Drone{i}" for i in range(sc.drones)]
    assert vehicles["Drone2"]["X"] == -12.0  # колонна выстроена позади ведущего
