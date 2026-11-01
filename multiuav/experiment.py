"""Эксперимент оператора: параметры из меню -> попытка -> папка runs/<код участника>/<дата_время>/.

Попытка запускается отдельным процессом: `python -m multiuav run ...`, ровно так же, как из
терминала. Окно меню при этом не делит процесс с полётом (не мешает ему и не зависает),
а кнопка «Стоп» посылает процессу Ctrl+C, после которого менеджер штатно сохраняет журнал.

В папке попытки:
  experiment.json  параметры из меню (для скрипта автозапуска и для анализа);
  scenario.yaml    сценарий, как он был на самом деле запущен (с поправками из меню);
  drone0.csv ...   журнал по дрону (flightlog.py);
  track.csv, summary.json  то, что сохраняет сам `run --out`;
  run.log          вывод процесса (по нему разбирают ошибки).

Когда появится скрипт автозапуска Unreal (`python -m multiuav launch <файл параметров>`),
команда в start_attempt заменяется его вызовом: experiment.json уже лежит в папке попытки.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import yaml

from .scenario import Scenario
from .types import MODES

ROOT = Path(__file__).resolve().parents[1]

END_MODES = ("time", "finish")  # по времени / когда дошли до финиша сценария
WIND_LAWS = ("constant", "sine", "gusts")  # постоянный / синус / порывы
BACKENDS = ("kinematic", "cosys")
PARTICIPANT_RE = re.compile(r"^[\w.\-]{1,40}$")  # буквы, цифры, _ - . — чтобы имя папки было безопасным

#: Параметры, которые меню уже принимает и пишет в experiment.json, но которые пока не влияют
#: на полёт: для них нет реализации (затемнение — карта Виталия, ветер, камеры, помощь).
NOT_APPLIED_YET = ("blackout_ms", "wind_speed", "wind_direction_deg", "wind_law",
                   "follower_cameras", "assist")


@dataclass
class ExperimentConfig:
    participant: str = "test"  # код участника: имя папки runs/<код>/...
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
        if not PARTICIPANT_RE.match(self.participant.strip()):
            errors.append("Код участника: от 1 до 40 символов, только буквы, цифры, «_», «-», «.».")
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


def scenario_dict(config: ExperimentConfig) -> dict:
    """Сценарий из файла с поправками из меню (так же, как делает `run --followers --mode`)."""
    data = yaml.safe_load(Path(config.scenario).read_text(encoding="utf-8")) or {}
    data["drones"] = config.drones
    data["duration_s"] = float(config.duration_s)
    if config.end_on == "time":
        data.pop("finish", None)  # без финиша прогон идёт ровно duration_s
    leader = data.get("leader", "gamepad")
    spec = {"algorithm": leader} if isinstance(leader, str) else dict(leader)
    if spec.get("algorithm", "gamepad") == "gamepad":
        # Если в сценарии задан тумблер режима (mode_switch), решает он, как и в `run --mode`.
        spec["params"] = {**(spec.get("params") or {}), "mode": config.flight_mode}
        data["leader"] = spec
    return data


def build_scenario(config: ExperimentConfig) -> Scenario:
    return Scenario.from_dict(scenario_dict(config), default_name=Path(config.scenario).stem)


def make_run_dir(base: str | Path, participant: str, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = Path(base) / participant.strip() / stamp
    n = 2
    while run_dir.exists():
        run_dir = Path(base) / participant.strip() / f"{stamp}_{n}"
        n += 1
    return run_dir


@dataclass
class AttemptResult:
    run_dir: Path
    ok: bool  # процесс завершился штатно (в том числе по кнопке «Стоп»)
    stopped: bool  # попытку остановили кнопкой «Стоп»
    summary: dict | None
    message: str  # при ошибке — хвост run.log


class Attempt:
    """Запущенная попытка: процесс `run` и папка, в которую он пишет."""

    def __init__(self, run_dir: Path, process: subprocess.Popen, log_file) -> None:
        self.run_dir = run_dir
        self.process = process
        self._log_file = log_file
        self.stopped = False

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def stop(self) -> None:
        """Остановить попытку: процесс получает Ctrl+C и штатно сохраняет журнал."""
        if not self.running:
            return
        self.stopped = True
        if os.name == "nt":  # на Windows Ctrl+C процессу не послать; журнал по дронам уже на диске
            self.process.terminate()
        else:
            self.process.send_signal(signal.SIGINT)

    def wait(self, timeout: float | None = None) -> None:
        self.process.wait(timeout)

    def result(self) -> AttemptResult:
        self.process.wait()
        if not self._log_file.closed:
            self._log_file.close()
        summary_path = self.run_dir / "summary.json"
        summary = (json.loads(summary_path.read_text(encoding="utf-8"))
                   if summary_path.is_file() else None)
        ok = self.process.returncode == 0 and summary is not None
        message = ""
        if not ok:
            tail = (self.run_dir / "run.log").read_text(encoding="utf-8", errors="replace")
            message = "\n".join(tail.strip().splitlines()[-6:]) or f"код выхода {self.process.returncode}"
            if self.stopped and summary is None:
                message = "Остановлено до начала полёта. " + message
        return AttemptResult(self.run_dir, ok or (self.stopped and summary is not None),
                             self.stopped, summary, message)


def start_attempt(config: ExperimentConfig) -> Attempt:
    """Создать папку попытки, записать параметры и запустить `python -m multiuav run`."""
    errors = config.validate()
    if errors:
        raise ValueError("\n".join(errors))
    run_dir = make_run_dir(config.log_dir, config.participant)
    run_dir.mkdir(parents=True)
    (run_dir / "experiment.json").write_text(json.dumps(
        {**asdict(config), "started": datetime.now().isoformat(timespec="seconds"),
         "not_applied_yet": list(NOT_APPLIED_YET)}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (run_dir / "scenario.yaml").write_text(
        yaml.safe_dump(scenario_dict(config), allow_unicode=True, sort_keys=False), encoding="utf-8")

    command = [sys.executable, "-m", "multiuav", "run", str(run_dir / "scenario.yaml"),
               "--backend", config.backend, "--host", config.host,
               "--out", str(run_dir), "--flight-log", str(run_dir)]
    log_file = open(run_dir / "run.log", "w", encoding="utf-8")
    process = subprocess.Popen(command, cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT,
                               env={**os.environ, "PYTHONUNBUFFERED": "1"})
    return Attempt(run_dir, process, log_file)


def run_experiment(config: ExperimentConfig) -> AttemptResult:
    """Попытка целиком, с ожиданием конца (для тестов и скриптов)."""
    attempt = start_attempt(config)
    attempt.wait()
    return attempt.result()


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
