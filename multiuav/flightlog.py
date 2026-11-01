"""Журнал полёта: свой CSV-файл на каждого дрона (drone0.csv — ведущий, drone1.csv, ...).

Одна строка — один шаг управления. Столбцы:
  pc_time_ms — время компьютера, мс от 1970 года (то же, чем пользуются часы айтрекера), по ним
               журнал склеивается с датчиками когнитивистов; считается по часам, а не «шаг × dt»,
               поэтому не отстаёт, даже если симулятор тормозил;
  t          — время симуляции, с, как в track.csv (шаг × dt);
  north, east, altitude — положение, м (NED, высота вверх); yaw_deg — курс, градусы
               (0 — север, по часовой стрелке положительный);
  collided   — 1, если дрон столкнулся (в сценариях с ручным полётом полёт продолжается);
  rc_roll, rc_pitch, rc_throttle, rc_yaw — каналы пульта 1000..2000, rc_mode — режим пульта.
               Пусто, если на этом шаге дрону команда не отправлялась;
  blackout   — 1, если экран оператора чёрный (источник — SimBackend.blackout()).

Файлы сбрасываются на диск на каждом шаге: при аварийном выходе записанное сохраняется.
Формат: стандартный CSV (разделитель «,», дробная часть через «.», UTF-8).
"""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path

from .types import DroneState, RcOverride

COLUMNS = ["pc_time_ms", "t", "north", "east", "altitude", "yaw_deg", "collided",
           "rc_roll", "rc_pitch", "rc_throttle", "rc_yaw", "rc_mode", "blackout"]


class FlightLog:
    def __init__(self, directory: str | Path, drones: int) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._files = []
        self._writers = []
        for i in range(drones):
            f = open(self.directory / f"drone{i}.csv", "w", newline="", encoding="utf-8")
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(COLUMNS)
            f.flush()
            self._files.append(f)
            self._writers.append(writer)

    def write_step(self, t: float, states: list[DroneState], sent: dict[int, RcOverride],
                   blackout: bool = False, pc_time_ms: int | None = None) -> None:
        """Записать один шаг для всех дронов.

        sent — команды, отправленные дронам на этом шаге (как в track.csv); у дрона без команды
        каналы пустые, а не «1500»: настоящие стики после столкновения ведущего пишутся, если
        сценарий не останавливает дрон при столкновении (stop_on_collision: false).
        """
        now = pc_time_ms if pc_time_ms is not None else time.time_ns() // 1_000_000
        for s in states:
            rc = sent.get(s.id)
            channels = (rc.roll, rc.pitch, rc.throttle, rc.yaw, rc.mode) if rc else ("",) * 5
            self._writers[s.id].writerow([
                now, round(t, 3), round(float(s.position[0]), 3), round(float(s.position[1]), 3),
                round(s.altitude, 3), round(math.degrees(s.yaw), 2), int(s.collided),
                *channels, int(bool(blackout))])
            self._files[s.id].flush()

    def close(self) -> None:
        for f in self._files:
            if not f.closed:
                f.close()

    def __enter__(self) -> "FlightLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
