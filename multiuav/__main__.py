"""Командная строка: python -m multiuav <команда> ...

  run       прогнать сценарий (в упрощённом симуляторе или в Cosys-AirSim)
  compare   сравнить алгоритмы и размеры группы на одном сценарии
  settings  создать settings.json для Cosys-AirSim из сценария
  gamepad   показать оси геймпада, чтобы настроить раскладку
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

from .scenario import AlgorithmSpec, Scenario


def _make_backend(name: str, host: str):
    if name == "kinematic":
        from .backends.kinematic import KinematicBackend

        return KinematicBackend()
    if name == "cosys":
        from .backends.cosys import CosysBackend

        return CosysBackend(host=host)
    raise SystemExit(f"Неизвестный симулятор: {name}")


def _load(args) -> Scenario:
    sc = Scenario.load(args.scenario)
    if getattr(args, "drones", None):
        sc.drones = args.drones
    if getattr(args, "algorithm", None):
        sc.followers = AlgorithmSpec(args.algorithm, sc.followers.params)
    if getattr(args, "leader", None):
        sc.leader = AlgorithmSpec(args.leader, sc.leader.params)
    return sc


def cmd_run(args) -> None:
    from .manager import SwarmManager

    sc = _load(args)
    result = SwarmManager(sc, _make_backend(args.backend, args.host)).run()
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))
    if args.out:
        out = result.save(args.out)
        print(f"Журнал прогона: {out}")
    if args.plot:
        from .plot import plot_run

        print(f"Картинка: {plot_run(sc, result, args.plot)}")


def cmd_compare(args) -> None:
    from .backends.kinematic import KinematicBackend
    from .manager import SwarmManager

    base = Scenario.load(args.scenario)
    sizes = [int(x) for x in args.drones.split(",")]
    biggest = []  # самая большая группа каждого алгоритма — для картинки
    print(f"{'алгоритм':<14}{'дронов':>7}{'дошли':>7}{'столкн.':>9}{'время, с':>10}")
    for algorithm in args.algorithms.split(","):
        for n in sizes:
            sc = dataclasses.replace(base, drones=n,
                                     followers=AlgorithmSpec(algorithm, base.followers.params))
            result = SwarmManager(sc, KinematicBackend()).run()
            r = result.summary()
            group_time = "-" if r["group_time_s"] is None else f"{r['group_time_s']:.1f}"
            print(f"{algorithm:<14}{n:>7}{r['finished']:>7}{r['collided']:>9}{group_time:>10}")
        biggest.append((sc, result))
    if args.plot:
        from .plot import plot_runs

        print(f"Картинка: {plot_runs(biggest, args.plot)}")


def cmd_settings(args) -> None:
    from .cosys_settings import DEFAULT_PATH, build_settings, write_settings

    sc = _load(args)
    if args.write:
        print(f"Записано: {write_settings(sc, Path(args.write) if args.write != '-' else DEFAULT_PATH)}")
    else:
        print(json.dumps(build_settings(sc), indent=2))


def cmd_gamepad(args) -> None:
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        raise SystemExit("Геймпад не найден")
    js = pygame.joystick.Joystick(args.index)
    js.init()
    print(f"{js.get_name()}: {js.get_numaxes()} осей. Подвигай стики, Ctrl+C — выход.")
    try:
        while True:
            pygame.event.pump()
            axes = " ".join(f"{i}:{js.get_axis(i):+.2f}" for i in range(js.get_numaxes()))
            print("\r" + axes, end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="multiuav", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="прогнать сценарий")
    run.add_argument("scenario")
    run.add_argument("--backend", choices=["kinematic", "cosys"], default="kinematic")
    run.add_argument("--host", default="127.0.0.1", help="адрес машины с Cosys-AirSim")
    run.add_argument("--drones", type=int, help="число дронов вместо указанного в сценарии")
    run.add_argument("--algorithm", help="алгоритм ведомых вместо указанного в сценарии")
    run.add_argument("--leader", help="кто ведёт: waypoints, gamepad или свой алгоритм")
    run.add_argument("--out", help="папка для журнала прогона")
    run.add_argument("--plot", help="сохранить картинку траекторий (PNG)")
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser("compare", help="сравнить алгоритмы в упрощённом симуляторе")
    compare.add_argument("scenario")
    compare.add_argument("--algorithms", default="single_file,leader_path")
    compare.add_argument("--drones", default="3,5,7,10")
    compare.add_argument("--plot", help="картинка самой большой группы каждого алгоритма (PNG)")
    compare.set_defaults(func=cmd_compare)

    settings = sub.add_parser("settings", help="settings.json для Cosys-AirSim")
    settings.add_argument("scenario")
    settings.add_argument("--drones", type=int)
    settings.add_argument("--write", nargs="?", const="-",
                          help="записать в файл (без пути — в ~/Documents/AirSim/settings.json)")
    settings.set_defaults(func=cmd_settings)

    gamepad = sub.add_parser("gamepad", help="показать оси геймпада")
    gamepad.add_argument("--index", type=int, default=0)
    gamepad.set_defaults(func=cmd_gamepad)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
