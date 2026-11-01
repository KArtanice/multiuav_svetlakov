"""Окно эксперимента: параметры, значок «пульт подключён» и кнопка «Старт».

Запуск: python -m multiuav menu

Окно только собирает ExperimentConfig (experiment.py) и запускает попытку отдельным процессом
(`python -m multiuav run ...`), поэтому оно не зависает и не мешает полёту. «Стоп» завершает
попытку и сохраняет журнал. После конца окно показывает итог и остаётся открытым: можно менять
параметры и запускать следующую попытку.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .experiment import ROOT, ExperimentConfig, gamepad_status, start_attempt

END_LABELS = {"по времени": "time", "на финише": "finish"}
WIND_LABELS = {"постоянный": "constant", "синус": "sine", "порывы": "gusts"}
MODE_LABELS = {"AltHold": "althold", "Acro": "acro"}
BACKEND_LABELS = {"Упрощённый (для проверки)": "kinematic", "Cosys-AirSim (Unreal)": "cosys"}

GAMEPAD_POLL_MS = 1500
RESULT_POLL_MS = 200


class Menu:
    def __init__(self, root: tk.Tk, gamepad_probe=gamepad_status, launcher=start_attempt) -> None:
        self.root = root
        self.gamepad_probe = gamepad_probe
        self.launcher = launcher
        self.attempt = None  # идущая попытка (experiment.Attempt)
        root.title("Симулятор оператора роя")

        defaults = ExperimentConfig()
        self.participant = tk.StringVar(value=defaults.participant)
        self.drones = tk.IntVar(value=defaults.drones)
        self.end = tk.StringVar(value="по времени")
        self.duration = tk.DoubleVar(value=defaults.duration_s)
        self.mode = tk.StringVar(value="AltHold")
        self.assist = tk.BooleanVar(value=defaults.assist)
        self.cameras = tk.BooleanVar(value=defaults.follower_cameras)
        self.blackout = tk.IntVar(value=defaults.blackout_ms)
        self.wind_speed = tk.DoubleVar(value=defaults.wind_speed)
        self.wind_dir = tk.DoubleVar(value=defaults.wind_direction_deg)
        self.wind_law = tk.StringVar(value="постоянный")
        self.log_dir = tk.StringVar(value=defaults.log_dir)
        self.scenario = tk.StringVar(value=Path(defaults.scenario).name)
        self.backend = tk.StringVar(value="Упрощённый (для проверки)")
        self.host = tk.StringVar(value=defaults.host)
        self.status = tk.StringVar(value="Задай параметры и нажми «Старт».")
        self.gamepad_text = tk.StringVar(value="Пульт: проверяю…")

        self._build()
        self.refresh_gamepad()

    # ------------------------------------------------------------------ интерфейс
    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        self.gamepad_label = tk.Label(frame, textvariable=self.gamepad_text, anchor="w",
                                      font=("Segoe UI", 11, "bold"))
        self.gamepad_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        exp = ttk.LabelFrame(frame, text="Эксперимент", padding=8)
        exp.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=4)
        self._row(exp, 0, "Код участника", ttk.Entry(exp, width=16, textvariable=self.participant))
        self._row(exp, 1, "Дронов (с ведущим)", ttk.Spinbox(exp, from_=1, to=20, width=8,
                                                           textvariable=self.drones))
        self._row(exp, 2, "Когда конец", ttk.Combobox(exp, values=list(END_LABELS), width=14,
                                                      state="readonly", textvariable=self.end))
        self._row(exp, 3, "Длительность, с", ttk.Spinbox(exp, from_=10, to=3600, increment=10,
                                                         width=8, textvariable=self.duration))
        self._row(exp, 4, "Режим полёта", ttk.Combobox(exp, values=list(MODE_LABELS), width=14,
                                                       state="readonly", textvariable=self.mode))
        self._row(exp, 5, "Алгоритмы помощи", ttk.Checkbutton(exp, variable=self.assist))
        self._row(exp, 6, "Камеры ведомых", ttk.Checkbutton(exp, variable=self.cameras))

        env = ttk.LabelFrame(frame, text="Помехи", padding=8)
        env.grid(row=1, column=1, sticky="nsew", pady=4)
        self._row(env, 0, "Затемнение, мс", ttk.Spinbox(env, from_=0, to=60000, increment=100,
                                                        width=8, textvariable=self.blackout))
        self._row(env, 1, "Ветер, м/с", ttk.Spinbox(env, from_=0, to=30, increment=0.5, width=8,
                                                    textvariable=self.wind_speed))
        self._row(env, 2, "Ветер откуда, °", ttk.Spinbox(env, from_=0, to=359, increment=15,
                                                         width=8, textvariable=self.wind_dir))
        self._row(env, 3, "Закон ветра", ttk.Combobox(env, values=list(WIND_LABELS), width=14,
                                                      state="readonly",
                                                      textvariable=self.wind_law))

        log = ttk.LabelFrame(frame, text="Куда сохранять попытки (папка/код участника/дата_время)", padding=8)
        log.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Entry(log, textvariable=self.log_dir, width=52).grid(row=0, column=0, sticky="ew")
        ttk.Button(log, text="Обзор…", command=self.choose_folder).grid(row=0, column=1, padx=6)

        dbg = ttk.LabelFrame(frame, text="Отладка", padding=8)
        dbg.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        scenarios = sorted(p.name for p in (ROOT / "scenarios").glob("*.yaml"))
        self._row(dbg, 0, "Сценарий", ttk.Combobox(dbg, values=scenarios, width=24,
                                                   state="readonly", textvariable=self.scenario))
        self._row(dbg, 1, "Симулятор", ttk.Combobox(dbg, values=list(BACKEND_LABELS), width=24,
                                                    state="readonly", textvariable=self.backend))
        self._row(dbg, 2, "Адрес Cosys-AirSim", ttk.Entry(dbg, width=26, textvariable=self.host))

        self.start_button = ttk.Button(frame, text="Старт", command=self.start)
        self.start_button.grid(row=4, column=0, sticky="ew", pady=(10, 4), padx=(0, 4), ipady=6)
        self.stop_button = ttk.Button(frame, text="Стоп", command=self.stop, state="disabled")
        self.stop_button.grid(row=4, column=1, sticky="ew", pady=(10, 4), padx=(4, 0), ipady=6)
        ttk.Label(frame, textvariable=self.status, wraplength=520, justify="left").grid(
            row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(frame, foreground="#777777", wraplength=520, justify="left",
                  text="Пока не влияют на полёт, а только записываются в experiment.json: "
                       "затемнение, ветер, камеры ведомых, алгоритмы помощи. Режим полёта "
                       "действует, когда ведущего ведёт пульт (сценарий rc_*, Cosys-AirSim).").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    @staticmethod
    def _row(parent, row: int, label: str, widget) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="w", pady=2)

    # ------------------------------------------------------------------ действия
    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.log_dir.get() or None,
                                         title="Куда сохранить журнал")
        if folder:
            self.log_dir.set(folder)

    def read_config(self) -> ExperimentConfig:
        """Собрать параметры из полей. Бросает ValueError с понятным текстом."""
        try:
            backend = BACKEND_LABELS[self.backend.get()]
            return ExperimentConfig(
                participant=self.participant.get().strip(),
                scenario=str(ROOT / "scenarios" / self.scenario.get()),
                backend=backend,
                host=self.host.get().strip(),
                drones=int(self.drones.get()),
                end_on=END_LABELS[self.end.get()],
                duration_s=float(self.duration.get()),
                log_dir=self.log_dir.get(),
                blackout_ms=int(self.blackout.get()),
                wind_speed=float(self.wind_speed.get()),
                wind_direction_deg=float(self.wind_dir.get()),
                wind_law=WIND_LABELS[self.wind_law.get()],
                flight_mode=MODE_LABELS[self.mode.get()],
                follower_cameras=bool(self.cameras.get()),
                assist=bool(self.assist.get()),
            )
        except (tk.TclError, ValueError, KeyError) as exc:
            raise ValueError("Проверь числа в полях: там должны быть числа.") from exc

    @property
    def running(self) -> bool:
        return self.attempt is not None and self.attempt.running

    def start(self) -> None:
        if self.running:
            return
        try:
            config = self.read_config()
            errors = config.validate()
        except ValueError as exc:
            errors = [str(exc)]
        if errors:
            self.status.set("Не могу запустить:\n" + "\n".join(errors))
            messagebox.showerror("Параметры", "\n".join(errors))
            return
        try:
            self.attempt = self.launcher(config)
        except Exception as exc:  # не удалось создать папку, запустить процесс и т. п.
            self.status.set(f"Не удалось запустить: {exc}")
            messagebox.showerror("Запуск", str(exc))
            return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set(f"Идёт эксперимент…\nПапка попытки: {self.attempt.run_dir}")
        self.root.after(RESULT_POLL_MS, self.poll)

    def stop(self) -> None:
        if self.running:
            self.attempt.stop()
            self.status.set("Останавливаю попытку и сохраняю журнал…")

    def poll(self) -> None:
        if self.running:
            self.root.after(RESULT_POLL_MS, self.poll)
            return
        result = self.attempt.result()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        s = result.summary
        if result.stopped and result.ok:
            self.status.set(f"ПОПЫТКА ОСТАНОВЛЕНА. Журнал сохранён.\nПапка попытки: {result.run_dir}")
        elif result.ok:
            self.status.set(f"КОНЕЦ ЭКСПЕРИМЕНТА. Финишировали: {s['finished']} из {s['drones']}, "
                            f"разбились: {s['collided']}.\nПапка попытки: {result.run_dir}\n"
                            "Можно менять параметры и запускать следующую попытку.")
        else:
            self.status.set(f"Ошибка: попытка не удалась.\n{result.message}\n"
                            f"Подробности: {result.run_dir / 'run.log'}")
        # Опрос пульта сам перепланирует себя (refresh_gamepad), здесь его запускать не нужно.

    def refresh_gamepad(self) -> None:
        if self.running:
            self.root.after(GAMEPAD_POLL_MS, self.refresh_gamepad)  # во время полёта пульт не трогаем
            return
        ok, text = self.gamepad_probe()
        self.gamepad_text.set(("● Пульт подключён: " if ok else "○ Пульт не подключён: ") + text)
        self.gamepad_label.configure(fg="#1b7f3b" if ok else "#b3261e")
        self.root.after(GAMEPAD_POLL_MS, self.refresh_gamepad)


def main() -> None:
    root = tk.Tk()
    Menu(root)
    root.mainloop()


if __name__ == "__main__":
    main()
