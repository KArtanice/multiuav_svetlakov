"""Эксперимент оператора: параметры из меню -> прогон сценария -> папка попытки.

Окно меню (menu.py) только собирает ExperimentConfig и вызывает run_experiment, поэтому всю
логику можно проверять без окна. Каждая попытка пишется в свою подпапку run_<дата_время>:
experiment.json (параметры попытки) и то, что сохраняет сам прогон (track.csv, summary.json).

Сейчас попытка запускается прямо в этом процессе. Когда появится скрипт автозапуска Unreal
(`python -m multiuav launch <файл параметров>`), он вызывается вместо SwarmManager в
run_experiment, а experiment.json уже лежит в папке попытки как раз для него.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .manager import SwarmManager
from .scenario import AlgorithmSpec, Scenario
from .types import MODES

ROOT = Path(__file__).resolve().parents[1]

END_MODES = ("time", "finish")  # по времени / когда дошли до финиша сценария
WIND_LAWS = ("constant", "sine", "gusts")  # постоянный / синус / порывы
BACKENDS = ("kinematic", "cosys")

#: Параметры, которые меню уже принимает и пишет в experiment.json, но которые пока не влияют
#: на полёт: для них нет реализации (затемнение — карта Виталия, ветер, камеры, помощь).
NOT_APPLIED_YET = ("blackout_ms", "wind_speed", "wind_direction_deg", "wind_law",
                   "follower_cameras", "assist")


@dataclass
class ExperimentConfig:
    scenario: str = str(ROOT / "scenarios" / "corner.yaml")
    backend: str = "kinematic"  # kinematic — упрощённый, для проверки; cosys — Unreal
    host: str = "127.0.0.1"  # адрес машины с Cosys-AirSim
    drones: int = 5  # всего, вместе с ведущим
    end_on: str = "time"
    duration_s: float = 120.0  # при «на финише» — предельное время
    log_dir: str = str(ROOT / "runs")
    blackout_ms: int = 500
    wind_speed: float = 0.0  # м/с
    wind_direction_deg: float = 0.0  # откуда дует, градусы от севера
    wind_law: str = "constant"
    flight_mode: str = "althold"  # режим пульта ведущего: althold или acro
    follower_cameras: bool = False
    assist: bool = False

    def validate(self) -> list[str]:
        """Список понятных человеку ошибок; пустой — параметры годятся."""
        errors = []
        if not 1 <= self.drones <= 20:
            errors.append("Количество дронов должно быть от 1 до 20.")
        if self.duration_s <= 0:
            errors.append("Длительность должна быть больше нуля.")
        if not 0 <= self.blackout_ms <= 60_000:
            errors.append("Длительность затемнения: от 0 до 60000 мс.")
        if self.wind_speed < 0:
            errors.append("Скорость ветра не может быть отрицательной.")
        if self.wind_law not in WIND_LAWS:
            errors.append("Неизвестный закон изменения ветра.")
        if self.flight_mode not in MODES:
            errors.append("Неизвестный режим полёта.")
        if self.end_on not in END_MODES:
            errors.append("Неизвестное условие окончания.")
        if self.backend not in BACKENDS:
            errors.append("Неизвестный симулятор.")
        if not self.log_dir.strip():
            errors.append("Укажи папку для журнала.")
        if not Path(self.scenario).is_file():
            errors.append(f"Не найден файл сценария: {self.scenario}")
            return errors
        try:
            sc = Scenario.load(self.scenario)
        except Exception as exc:  # битый YAML и т. п.
            errors.append(f"Не удалось прочитать сценарий: {exc}")
            return errors
        if self.backend == "kinematic" and sc.leader.name == "gamepad":
            errors.append("Ведение с пульта работает только в Cosys-AirSim: в упрощённом "
                          "симуляторе время идёт не в реальном темпе. Выбери сценарий с "
                          "автопилотом (например, corner.yaml) или симулятор Cosys-AirSim.")
        if self.end_on == "finish" and sc.finish is None:
            errors.append("В сценарии нет финишной зоны (finish), а окончание выбрано «на финише».")
        return errors


@dataclass
class ExperimentOutcome:
    run_dir: Path
    summary: dict


def build_scenario(config: ExperimentConfig) -> Scenario:
    """Сценарий из файла с поправками из меню (так же, как делает `run --drones --mode`)."""
    sc = Scenario.load(config.scenario)
    sc.drones = config.drones
    sc.duration_s = float(config.duration_s)
    if config.end_on == "time":
        sc.finish = None  # без финиша прогон идёт ровно duration_s
    if sc.leader.name == "gamepad":
        # Если в сценарии задан тумблер режима (mode_switch), решает он, как и в `run --mode`.
        sc.leader = AlgorithmSpec("gamepad", {**sc.leader.params, "mode": config.flight_mode})
    return sc


def make_backend(name: str, host: str):
    if name == "kinematic":
        from .backends.kinematic import KinematicBackend

        return KinematicBackend()
    if name == "cosys":
        from .backends.cosys import CosysBackend

        return CosysBackend(host=host)
    raise ValueError(f"Неизвестный симулятор: {name}")


def make_run_dir(base: str | Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = Path(base) / f"run_{stamp}"
    n = 2
    while run_dir.exists():
        run_dir = Path(base) / f"run_{stamp}_{n}"
        n += 1
    return run_dir


def run_experiment(config: ExperimentConfig) -> ExperimentOutcome:
    """Одна попытка: прогон сценария и запись всего в новую подпапку."""
    errors = config.validate()
    if errors:
        raise ValueError("\n".join(errors))
    sc = build_scenario(config)

    run_dir = make_run_dir(config.log_dir)
    run_dir.mkdir(parents=True)
    (run_dir / "experiment.json").write_text(json.dumps(
        {**asdict(config), "started": datetime.now().isoformat(timespec="seconds"),
         "not_applied_yet": list(NOT_APPLIED_YET)}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    result = SwarmManager(sc, make_backend(config.backend, config.host)).run()
    result.save(run_dir)  # track.csv и summary.json, как у `run --out`
    return ExperimentOutcome(run_dir, result.summary())


_pygame_ready = False


def gamepad_status() -> tuple[bool, str]:
    """(подключён ли пульт, пояснение). Пульт RadioMaster по USB виден как геймпад."""
    global _pygame_ready
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    try:
        import pygame
    except ImportError:
        return False, "не установлен pygame (pip install -e .[gamepad])"
    if not _pygame_ready:
        pygame.init()
        pygame.joystick.init()
        _pygame_ready = True
    pygame.event.pump()
    if pygame.joystick.get_count() == 0:
        return False, "пульт не найден"
    return True, pygame.joystick.Joystick(0).get_name()
