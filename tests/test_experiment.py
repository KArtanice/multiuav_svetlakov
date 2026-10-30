"""Параметры эксперимента из меню: проверка, сценарий, запуск попытки, папка попытки."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from multiuav.experiment import ExperimentConfig, build_scenario, make_run_dir, run_experiment

ROOT = Path(__file__).resolve().parents[1]
RC_GROUP = str(ROOT / "scenarios" / "rc_group.yaml")  # ведущий с пульта, финиша нет


def cfg(tmp_path, **kwargs):
    return ExperimentConfig(log_dir=str(tmp_path), drones=3, duration_s=60, **kwargs)


def test_default_config_is_valid(tmp_path):
    assert cfg(tmp_path).validate() == []


def test_bad_values_give_readable_errors(tmp_path):
    errors = cfg(tmp_path, wind_speed=-1, blackout_ms=-5).validate()
    assert any("ветра" in e for e in errors)
    assert any("затемнения" in e for e in errors)
    assert ExperimentConfig(log_dir=str(tmp_path), drones=0).validate()
    assert ExperimentConfig(log_dir="  ").validate()
    assert any("режим" in e.lower() for e in cfg(tmp_path, flight_mode="stabilize").validate())


def test_gamepad_scenario_needs_cosys(tmp_path):
    errors = cfg(tmp_path, scenario=RC_GROUP, backend="kinematic").validate()
    assert any("Cosys" in e for e in errors)
    assert cfg(tmp_path, scenario=RC_GROUP, backend="cosys").validate() == []


def test_finish_mode_needs_a_finish_zone_in_the_scenario(tmp_path):
    errors = cfg(tmp_path, scenario=RC_GROUP, backend="cosys", end_on="finish").validate()
    assert any("финиш" in e for e in errors)


def test_missing_scenario_is_reported(tmp_path):
    errors = cfg(tmp_path, scenario=str(tmp_path / "net.yaml")).validate()
    assert any("сценари" in e for e in errors)


def test_build_scenario_applies_menu_values(tmp_path):
    sc = build_scenario(cfg(tmp_path, scenario=RC_GROUP, backend="cosys", flight_mode="acro"))
    assert sc.drones == 3 and sc.duration_s == 60
    assert sc.leader.name == "gamepad" and sc.leader.params["mode"] == "acro"
    assert sc.leader.params["axes"]  # остальные параметры пульта из сценария сохранились


def test_build_scenario_keeps_autopilot_leader_untouched(tmp_path):
    sc = build_scenario(cfg(tmp_path, flight_mode="acro"))
    assert sc.leader.name != "gamepad" and "mode" not in sc.leader.params


def test_end_on_time_removes_finish_and_finish_mode_keeps_it(tmp_path):
    assert build_scenario(cfg(tmp_path, end_on="time")).finish is None
    assert build_scenario(cfg(tmp_path, end_on="finish")).finish is not None


def test_run_creates_attempt_folder_with_params_and_results(tmp_path):
    out = run_experiment(cfg(tmp_path, end_on="finish"))
    assert sorted(p.name for p in out.run_dir.iterdir()) == ["experiment.json", "summary.json", "track.csv"]
    assert out.run_dir.parent == tmp_path
    meta = json.loads((out.run_dir / "experiment.json").read_text(encoding="utf-8"))
    assert meta["drones"] == 3 and meta["end_on"] == "finish" and meta["flight_mode"] == "althold"
    assert "wind_speed" in meta["not_applied_yet"] and "flight_mode" not in meta["not_applied_yet"]
    assert out.summary["drones"] == 3 and out.summary["finished"] >= 1


def test_time_mode_runs_the_whole_duration(tmp_path):
    out = run_experiment(cfg(tmp_path, end_on="time"))
    assert out.summary["sim_time_s"] >= 60
    assert out.summary["finished"] == 0  # финиша в этом режиме нет


def test_second_attempt_does_not_overwrite_the_first(tmp_path):
    a = run_experiment(cfg(tmp_path, end_on="finish"))
    b = run_experiment(cfg(tmp_path, end_on="finish"))
    assert a.run_dir != b.run_dir
    assert (a.run_dir / "track.csv").exists() and (b.run_dir / "track.csv").exists()


def test_invalid_config_raises_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError):
        run_experiment(cfg(tmp_path, wind_speed=-3))
    assert list(tmp_path.iterdir()) == []


def test_run_dir_name_has_a_timestamp(tmp_path):
    d = make_run_dir(tmp_path, datetime(2026, 10, 26, 14, 5, 33))
    assert d.name == "run_2026-10-26_14-05-33"
