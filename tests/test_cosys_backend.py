"""Cosys-AirSim здесь не запускается, поэтому проверяем перевод команд и координат на подделке клиента."""

import math
import sys
import types
from types import SimpleNamespace as NS

import pytest

from multiuav.backends.cosys import CosysBackend
from multiuav.scenario import AlgorithmSpec, Scenario
from multiuav.types import RcOverride


class Done:
    def join(self):
        pass


class FakeClient:
    def __init__(self, ip=""):
        self.calls = []
        self.vehicles = [f"Drone{i}" for i in range(3)]

    def confirmConnection(self):
        pass

    def listVehicles(self):
        return self.vehicles

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return Done()
        return record

    def simGetCollisionInfo(self, name):
        return NS(has_collided=True, time_stamp=100)

    def simGetGroundTruthKinematics(self, name):
        v = lambda x, y, z: NS(x_val=x, y_val=y, z_val=z)  # noqa: E731
        yaw = math.radians(90)
        q = NS(w_val=math.cos(yaw / 2), x_val=0.0, y_val=0.0, z_val=math.sin(yaw / 2))
        return NS(position=v(1.0, 2.0, -10.0), linear_velocity=v(0.5, 0.0, 0.0), orientation=q)


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setitem(sys.modules, "cosysairsim", types.SimpleNamespace(MultirotorClient=FakeClient))
    sc = Scenario(name="t", drones=3, leader=AlgorithmSpec("waypoints"),
                  followers=AlgorithmSpec("single_file"), spacing=5.0, altitude=10.0)
    b = CosysBackend()
    b.start(sc)
    return b


def test_positions_are_shifted_to_common_frame(backend):
    states = backend.states()
    assert states[0].position.tolist() == [1.0, 2.0, -10.0]
    assert states[2].position.tolist() == [1.0 - 10.0, 2.0, -10.0]  # третий стартовал в 10 м позади
    assert math.isclose(states[0].yaw, math.radians(90))
    assert not states[0].collided  # касание при взлёте не считается


def test_yaw_right_is_negative_rate_for_cosys_client(backend):
    backend.send(1, RcOverride(roll=1500, pitch=2000, throttle=1500, yaw=2000))
    name, args, kwargs = backend.client.calls[-1]
    assert name == "moveByRollPitchYawrateZAsync"
    roll, pitch, yaw_rate, z, _ = args
    assert roll == 0 and pitch > 0 and yaw_rate < 0
    assert math.isclose(z, -10.0, abs_tol=1e-6)
    assert kwargs["vehicle_name"] == "Drone1"


def test_missing_vehicles_are_reported(monkeypatch):
    class Few(FakeClient):
        def listVehicles(self):
            return ["Drone0"]

    monkeypatch.setitem(sys.modules, "cosysairsim", types.SimpleNamespace(MultirotorClient=Few))
    sc = Scenario(name="t", drones=2, leader=AlgorithmSpec("waypoints"),
                  followers=AlgorithmSpec("single_file"))
    with pytest.raises(RuntimeError, match="Drone1"):
        CosysBackend().start(sc)
