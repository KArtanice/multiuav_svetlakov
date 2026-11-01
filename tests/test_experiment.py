"""Параметры эксперимента из меню: проверка, сценарий, папка попытки, запуск и остановка."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from multiuav.experiment import (Attempt, ExperimentConfig, build_scenario, make_run_dir,
                                 run_experiment, scenario_dict, start_attempt)

ROOT = Path(__file__).resolve().parents[1]
RC_GROUP = str(ROOT / "scenarios" / "rc_group.yaml")  # ведущий с пульта, финиша нет


def cfg(tmp_path, **kwargs):
    params = {"drones": 3, "duration_s": 60, **kwargs}
    return ExperimentConfig(log_dir=str(tmp_path), **params)


def test_default_config_is_valid(tmp_path):
    assert cfg(tmp_path).validate() == []


def test_participant_code_must_be_a_safe_folder_name(tmp_path):
    for bad in ("", "  ", "../x", "a/b", "a b", "x" * 41):
        assert any("участник" in e for e in cfg(tmp_path, participant=bad).validate()), bad
    for good in ("P01", "участник-7", "s.3_b"):
        assert cfg(tmp_path, participant=good).validate() == [], good


def test_bad_values_give_readable_errors(tmp_path):
    errors = cfg(tmp_path, wind_speed=-1, blackout_ms=-5).validate()
    assert any("ветра" in e for e in errors)
    assert any("затемнения" in e for e in errors)
    assert ExperimentConfig(log_dir=str(tmp_path), drones=0).validate()
    assert ExperimentConfig(log_dir="  ").validate()
    assert any("режим" in e.lower() for e in cfg(tmp_path, flight_mode="stabilize").validate())


def test_gamepad_scenario_needs_cosys_and_finish_needs_a_finish_zone(tmp_path):
    assert any("Cosys" in e for e in cfg(tmp_path, scenario=RC_GROUP).validate())
    assert cfg(tmp_path, scenario=RC_GROUP, backend="cosys").validate() == []
    errors = cfg(tmp_path, scenario=RC_GROUP, backend="cosys", end_on="finish").validate()
    assert any("финиш" in e for e in errors)


def test_missing_scenario_is_reported(tmp_path):
    assert any("сценари" in e for e in cfg(tmp_path, scenario=str(tmp_path / "net.yaml")).validate())


def test_scenario_gets_menu_values(tmp_path):
    data = scenario_dict(cfg(tmp_path, scenario=RC_GROUP, backend="cosys", flight_mode="acro"))
    assert data["drones"] == 3 and data["duration_s"] == 60
    assert data["leader"]["algorithm"] == "gamepad" and data["leader"]["params"]["mode"] == "acro"
    assert data["leader"]["params"]["axes"]  # остальные параметры пульта из сценария сохранились
    sc = build_scenario(cfg(tmp_path, scenario=RC_GROUP, backend="cosys", flight_mode="acro"))
    assert sc.leader.params["mode"] == "acro" and sc.drones == 3 and sc.stop_on_collision is False


def test_autopilot_leader_is_left_alone_and_end_mode_controls_finish(tmp_path):
    assert "mode" not in (scenario_dict(cfg(tmp_path))["leader"].get("params") or {})
    assert "finish" not in scenario_dict(cfg(tmp_path, end_on="time"))
    assert "finish" in scenario_dict(cfg(tmp_path, end_on="finish"))


def test_run_dir_is_participant_then_timestamp(tmp_path):
    now = datetime(2026, 10, 26, 14, 5, 33)
    d = make_run_dir(tmp_path, "P01", now)
    assert d == tmp_path / "P01" / "2026-10-26_14-05-33"
    d.mkdir(parents=True)
    assert make_run_dir(tmp_path, "P01", now).name == "2026-10-26_14-05-33_2"


def test_attempt_creates_the_folder_with_logs_params_and_results(tmp_path):
    result = run_experiment(cfg(tmp_path, participant="P01", end_on="finish"))
    assert result.ok and not result.stopped
    assert result.run_dir.parent == tmp_path / "P01"
    assert sorted(p.name for p in result.run_dir.iterdir()) == [
        "drone0.csv", "drone1.csv", "drone2.csv", "experiment.json", "run.log",
        "scenario.yaml", "summary.json", "track.csv"]
    meta = json.loads((result.run_dir / "experiment.json").read_text(encoding="utf-8"))
    assert meta["participant"] == "P01" and meta["end_on"] == "finish" and meta["drones"] == 3
    assert "wind_speed" in meta["not_applied_yet"] and "flight_mode" not in meta["not_applied_yet"]
    used = yaml.safe_load((result.run_dir / "scenario.yaml").read_text(encoding="utf-8"))
    assert used["drones"] == 3 and "finish" in used
    assert result.summary["drones"] == 3 and result.summary["finished"] >= 1


def test_time_mode_runs_the_whole_duration(tmp_path):
    result = run_experiment(cfg(tmp_path, end_on="time"))
    assert result.summary["sim_time_s"] >= 60 and result.summary["finished"] == 0


def test_second_attempt_does_not_overwrite_the_first(tmp_path):
    a = run_experiment(cfg(tmp_path, end_on="finish"))
    b = run_experiment(cfg(tmp_path, end_on="finish"))
    assert a.run_dir != b.run_dir
    assert (a.run_dir / "drone0.csv").exists() and (b.run_dir / "drone0.csv").exists()


def test_invalid_config_raises_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError):
        start_attempt(cfg(tmp_path, participant="../evil"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Ctrl+C процессу посылается только на Linux")
def test_stop_ends_the_attempt_and_keeps_the_log(tmp_path):
    attempt = start_attempt(cfg(tmp_path, end_on="time", duration_s=100_000))  # «бесконечный» прогон
    log = attempt.run_dir / "drone0.csv"
    deadline = time.time() + 30
    while time.time() < deadline and not (log.exists() and log.read_text(encoding="utf-8").count("\n") > 50):
        time.sleep(0.1)
    assert attempt.running, "прогон должен был ещё идти"
    attempt.stop()
    attempt.wait(timeout=30)
    result = attempt.result()
    assert result.stopped and result.ok and result.summary is not None
    text = log.read_text(encoding="utf-8")
    assert text.count("\n") > 50 and text.endswith("\n")  # последняя строка целая
    assert (attempt.run_dir / "track.csv").exists()


def test_failed_attempt_reports_the_reason(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    log_file = open(run_dir / "run.log", "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-c", "print('нет связи с Unreal'); raise SystemExit(3)"],
                               stdout=log_file, stderr=subprocess.STDOUT)
    result = Attempt(run_dir, process, log_file).result()
    assert not result.ok and "нет связи с Unreal" in result.message
