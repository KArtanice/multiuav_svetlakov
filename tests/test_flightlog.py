"""Журнал по дронам: файл на дрона, время компьютера, курс в градусах, режим пульта, blackout."""

import csv
import dataclasses
import time
from pathlib import Path

from multiuav.backends.kinematic import KinematicBackend
from multiuav.flightlog import COLUMNS, FlightLog
from multiuav.manager import SwarmManager
from multiuav.scenario import AlgorithmSpec, Scenario

ROOT = Path(__file__).resolve().parents[1]
CORNER = ROOT / "scenarios" / "corner.yaml"


def make(drones=3, algorithm=None, **kwargs):
    base = Scenario.load(CORNER)
    followers = AlgorithmSpec(algorithm, base.followers.params) if algorithm else base.followers
    return dataclasses.replace(base, drones=drones, followers=followers, **kwargs)


def read(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def test_one_file_per_drone_with_the_agreed_columns(tmp_path):
    SwarmManager(make(drones=3), KinematicBackend(), log_dir=tmp_path).run()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["drone0.csv", "drone1.csv", "drone2.csv"]
    for i in range(3):
        header, rows = read(tmp_path / f"drone{i}.csv")
        assert header == COLUMNS == ["pc_time_ms", "t", "north", "east", "altitude", "yaw_deg",
                                     "collided", "rc_roll", "rc_pitch", "rc_throttle", "rc_yaw",
                                     "rc_mode", "blackout"]
        assert len(rows) > 100 and all(len(r) == len(COLUMNS) for r in rows)


def test_pc_time_is_the_computer_clock_in_milliseconds(tmp_path):
    before = time.time() * 1000
    SwarmManager(make(drones=2), KinematicBackend(), log_dir=tmp_path).run()
    after = time.time() * 1000
    times0 = [int(r[0]) for r in read(tmp_path / "drone0.csv")[1]]
    times1 = [int(r[0]) for r in read(tmp_path / "drone1.csv")[1]]
    assert before - 5 <= times0[0] <= times0[-1] <= after + 5
    assert times0 == sorted(times0)
    assert times0 == times1  # на одном шаге у всех дронов одно и то же время компьютера


def test_pc_time_follows_the_clock_not_the_step_count(tmp_path):
    """Если симулятор тормозит, время симуляции t отстаёт от часов, а pc_time_ms — нет."""

    class Slow(KinematicBackend):
        def advance(self, dt):
            time.sleep(0.02)  # шаг в 0,05 с симуляции стоит 0,02 с по часам
            super().advance(dt)

    sc = make(drones=2, duration_s=2.0, finish=None)
    SwarmManager(sc, Slow(), log_dir=tmp_path).run()
    rows = read(tmp_path / "drone0.csv")[1]
    sim_span = float(rows[-1][1]) - float(rows[0][1])
    wall_span = (int(rows[-1][0]) - int(rows[0][0])) / 1000
    assert abs(sim_span - 2.0) < 0.06
    assert 0.6 < wall_span < 1.6  # около 40 шагов × 0,02 с, а не 2 с


def test_yaw_is_in_degrees_and_collided_is_0_or_1(tmp_path):
    SwarmManager(make(drones=2), KinematicBackend(), log_dir=tmp_path).run()
    rows = read(tmp_path / "drone0.csv")[1]
    yaws = [float(r[5]) for r in rows]
    assert min(yaws) >= -180 and max(yaws) <= 180
    assert max(yaws) > 80  # ведущий сворачивает на восток (около 90°)
    assert {r[6] for r in rows} <= {"0", "1"}


def test_sticks_and_mode_match_the_track_csv(tmp_path):
    result = SwarmManager(make(drones=3), KinematicBackend(), log_dir=tmp_path).run()
    for drone in (0, 1, 2):
        _, rows = read(tmp_path / f"drone{drone}.csv")
        track = [r for r in result.track if r[1] == drone]
        assert len(rows) == len(track)
        for row, tr in zip(rows, track):
            assert row[7:12] == [str(v) for v in tr[7:12]]  # rc_roll..rc_mode
    assert {r[11] for r in rows[:-1]} == {"althold"}  # в последней строке команды уже нет, как в track.csv


def test_sticks_after_a_crash_are_real_when_the_flight_continues(tmp_path):
    crash = dict(drones=10, algorithm="single_file")
    SwarmManager(make(stop_on_collision=False, **crash), KinematicBackend(), log_dir=tmp_path / "go").run()
    SwarmManager(make(stop_on_collision=True, **crash), KinematicBackend(), log_dir=tmp_path / "stop").run()
    for name, expect_sticks in (("go", True), ("stop", False)):
        found = False
        for i in range(10):
            rows = read(tmp_path / name / f"drone{i}.csv")[1]
            after = [r for r in rows if r[6] == "1"]
            if after:
                found = True
                assert all((r[7] != "") == expect_sticks for r in after), (name, i)
        assert found, name  # в этом сценарии часть дронов действительно разбивается


def test_blackout_column_follows_the_backend_signal(tmp_path):
    class Dark(KinematicBackend):
        steps = 0

        def advance(self, dt):
            self.steps += 1
            super().advance(dt)

        def blackout(self):
            return 100 <= self.steps < 140

    SwarmManager(make(drones=2), Dark(), log_dir=tmp_path).run()
    for i in range(2):
        rows = read(tmp_path / f"drone{i}.csv")[1]
        assert [k for k, r in enumerate(rows) if r[12] == "1"] == list(range(100, 140))


def test_blackout_is_zero_without_a_signal_and_no_dir_means_no_files(tmp_path):
    SwarmManager(make(drones=2), KinematicBackend(), log_dir=tmp_path / "a").run()
    assert {r[12] for r in read(tmp_path / "a" / "drone0.csv")[1]} == {"0"}
    SwarmManager(make(drones=2), KinematicBackend()).run()
    assert not (tmp_path / "b").exists()


def test_rows_are_on_disk_before_the_log_is_closed(tmp_path):
    from multiuav.types import DroneState
    import numpy as np

    log = FlightLog(tmp_path, 1)
    state = DroneState(0, np.array([1.0, 2.0, -10.0]), np.zeros(3), 0.0)
    log.write_step(0.0, [state], {}, pc_time_ms=123)
    rows = read(tmp_path / "drone0.csv")[1]  # файл ещё не закрыт
    assert rows == [["123", "0.0", "1.0", "2.0", "10.0", "0.0", "0", "", "", "", "", "", "0"]]
    log.close()


def test_pc_time_is_taken_when_the_states_are_read_not_after_the_commands(tmp_path):
    """Отправка команд в Unreal занимает время (по запросу на каждого дрона). Время компьютера
    в журнале должно относиться к моменту, когда сняты состояния, иначе оно уедет вперёд и
    не совпадёт с датчиками когнитивистов."""

    class Rpc(KinematicBackend):
        def __init__(self):
            super().__init__()
            self.sampled = []  # настоящее время съёма состояний, мс

        def states(self):
            self.sampled.append(time.time_ns() // 1_000_000)
            return super().states()

        def send(self, drone_id, rc):
            time.sleep(0.01)  # как сетевой вызов в Cosys-AirSim
            super().send(drone_id, rc)

    backend = Rpc()
    SwarmManager(make(drones=4, duration_s=1.0, finish=None), backend, log_dir=tmp_path).run()
    rows = read(tmp_path / "drone0.csv")[1]
    assert len(rows) == len(backend.sampled)
    lag = [int(r[0]) - s for r, s in zip(rows, backend.sampled)]
    assert max(lag) < 8, f"время в журнале позже съёма состояний до {max(lag)} мс"
