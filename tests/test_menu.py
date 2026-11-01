"""Окно меню. Настоящее окно в тестах не открывается: подставляется «пустой» tkinter,
поэтому проверяется логика (сбор параметров, проверка, запуск, итог), а не вёрстка."""

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class _Widget:
    def __init__(self, *args, **kwargs):
        self.kw = dict(kwargs)

    def configure(self, **kwargs):
        self.kw.update(kwargs)

    config = configure

    def __getattr__(self, name):  # grid, pack, bind, columnconfigure, ...
        return lambda *a, **k: None


class _Var:
    def __init__(self, master=None, value=None):
        self.value = value

    def get(self):
        if isinstance(self.value, str) and self.kind != "str":
            raise _TclError("не число")
        return self.value

    def set(self, value):
        self.value = value


class _TclError(Exception):
    pass


class _Root(_Widget):
    def __init__(self):
        super().__init__()
        self.scheduled = []

    def after(self, ms, callback=None):
        self.scheduled.append((ms, callback))

    def title(self, text):
        self.kw["title"] = text


def _fake_tkinter(shown):
    def var(kind):
        return type(f"{kind}Var", (_Var,), {"kind": kind})

    tk = types.ModuleType("tkinter")
    tk.Tk, tk.Label, tk.TclError = _Root, _Widget, _TclError
    tk.IntVar, tk.DoubleVar, tk.BooleanVar, tk.StringVar = (var("int"), var("float"), var("bool"), var("str"))
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "LabelFrame", "Label", "Entry", "Spinbox", "Combobox", "Button", "Checkbutton"):
        setattr(ttk, name, _Widget)
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askdirectory = lambda **kw: shown.setdefault("folder", "")
    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showerror = lambda title, text: shown.setdefault("errors", []).append(text)
    tk.ttk, tk.filedialog, tk.messagebox = ttk, filedialog, messagebox
    return {"tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": filedialog,
            "tkinter.messagebox": messagebox}


def make_menu(tmp_path, **kwargs):
    """Импортировать multiuav.menu с подменным tkinter и вернуть (Menu, root, shown)."""
    shown = {}
    saved = {k: sys.modules.get(k) for k in [*_fake_tkinter({}), "multiuav.menu"]}
    sys.modules.update(_fake_tkinter(shown))
    sys.modules.pop("multiuav.menu", None)
    try:
        menu_module = importlib.import_module("multiuav.menu")
    finally:
        for key, module in saved.items():
            if module is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = module
    root = _Root()
    kwargs.setdefault("gamepad_probe", lambda: (False, "пульт не найден"))
    menu = menu_module.Menu(root, **kwargs)
    menu.log_dir.set(str(tmp_path))
    menu.drones.set(3)
    menu.duration.set(60.0)
    return menu, root, shown


class FakeAttempt:
    """Попытка без процесса: ею управляет тест."""

    def __init__(self, run_dir, summary=None, ok=True, message=""):
        self.run_dir = run_dir
        self.running = True
        self.stop_calls = 0
        self._result = (summary or {"finished": 3, "drones": 3, "collided": 0}, ok, message)

    def stop(self):
        self.stop_calls += 1
        self.running = False
        self.stopped = True

    stopped = False

    def finish(self):
        self.running = False

    def result(self):
        from multiuav.experiment import AttemptResult

        summary, ok, message = self._result
        return AttemptResult(self.run_dir, ok, self.stopped, summary, message)


def fake_launcher(tmp_path, calls, **attempt_kwargs):
    def launch(config):
        calls.append(config)
        attempt = FakeAttempt(tmp_path / "run", **attempt_kwargs)
        calls.append(attempt)
        return attempt
    return launch


def test_gamepad_indicator_shows_connected_and_not_connected(tmp_path):
    menu, _, _ = make_menu(tmp_path, gamepad_probe=lambda: (True, "RadioMaster Pocket"))
    assert "подключён" in menu.gamepad_text.get() and "RadioMaster" in menu.gamepad_text.get()
    assert menu.gamepad_label.kw["fg"] == "#1b7f3b"
    menu2, _, _ = make_menu(tmp_path)
    assert "не подключён" in menu2.gamepad_text.get()
    assert menu2.gamepad_label.kw["fg"] == "#b3261e"


def test_gamepad_is_polled_once_per_tick_and_not_during_the_flight(tmp_path):
    probes = []
    calls = []
    menu, root, _ = make_menu(tmp_path, gamepad_probe=lambda: probes.append(1) or (False, "нет"),
                              launcher=fake_launcher(tmp_path, calls))
    before = len(root.scheduled)
    root.scheduled[-1][1]()
    assert len(root.scheduled) == before + 1 and len(probes) == 2
    menu.start()  # попытка идёт: пульт читает процесс полёта, окно его не трогает
    probes.clear()
    refresh = [cb for _, cb in root.scheduled if cb.__name__ == "refresh_gamepad"][-1]
    refresh()
    assert probes == []


def test_start_launches_the_attempt_with_the_menu_values(tmp_path):
    calls = []
    menu, root, _ = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.participant.set("P07")
    menu.drones.set(4)
    menu.end.set("на финише")
    menu.mode.set("Acro")
    menu.wind_law.set("порывы")
    menu.blackout.set(800)
    menu.assist.set(True)
    menu.start()
    cfg = calls[0]
    assert (cfg.participant, cfg.drones, cfg.end_on) == ("P07", 4, "finish")
    assert (cfg.flight_mode, cfg.wind_law, cfg.blackout_ms, cfg.assist) == ("acro", "gusts", 800, True)
    assert cfg.backend == "kinematic" and cfg.log_dir == str(tmp_path)
    assert menu.start_button.kw["state"] == "disabled" and menu.stop_button.kw["state"] == "normal"
    assert "Идёт эксперимент" in menu.status.get() and "run" in menu.status.get()


def test_normal_end_returns_to_the_menu(tmp_path):
    calls = []
    menu, _, _ = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.start()
    calls[1].finish()
    menu.poll()
    assert "КОНЕЦ ЭКСПЕРИМЕНТА" in menu.status.get() and "3 из 3" in menu.status.get()
    assert menu.start_button.kw["state"] == "normal" and menu.stop_button.kw["state"] == "disabled"


def test_still_running_poll_schedules_the_next_check(tmp_path):
    calls = []
    menu, root, _ = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.start()
    before = len(root.scheduled)
    menu.poll()
    assert len(root.scheduled) == before + 1
    assert menu.start_button.kw["state"] == "disabled"


def test_stop_button_stops_the_attempt_and_saves(tmp_path):
    calls = []
    menu, _, _ = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.start()
    menu.stop()
    assert calls[1].stop_calls == 1 and "сохраняю" in menu.status.get()
    menu.poll()
    assert "ОСТАНОВЛЕНА" in menu.status.get() and "Журнал сохранён" in menu.status.get()
    assert menu.start_button.kw["state"] == "normal" and menu.stop_button.kw["state"] == "disabled"
    menu.stop()  # повторное нажатие без попытки ничего не ломает
    assert calls[1].stop_calls == 1


def test_failed_attempt_is_explained_in_the_window(tmp_path):
    calls = []
    menu, _, _ = make_menu(tmp_path, launcher=fake_launcher(
        tmp_path, calls, summary=None, ok=False, message="Не удалось подключиться к симулятору"))
    menu.start()
    calls[1].finish()
    menu.poll()
    assert "Ошибка" in menu.status.get() and "подключиться" in menu.status.get()
    assert menu.start_button.kw["state"] == "normal"


def test_invalid_parameters_show_a_message_and_do_not_start(tmp_path):
    calls = []
    menu, _, shown = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.drones.set(0)
    menu.start()
    assert calls == [] and "дронов" in shown["errors"][0]
    menu.drones.set(3)
    menu.participant.set("../evil")
    menu.start()
    assert calls == [] and "участник" in shown["errors"][1]


def test_not_a_number_in_a_field_is_reported_not_crashed(tmp_path):
    calls = []
    menu, _, shown = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.drones.set("abc")
    menu.start()
    assert calls == [] and "числа" in shown["errors"][0]


def test_start_pressed_twice_while_running_is_ignored(tmp_path):
    calls = []
    menu, _, _ = make_menu(tmp_path, launcher=fake_launcher(tmp_path, calls))
    menu.start()
    menu.start()
    assert len([c for c in calls if hasattr(c, "participant")]) == 1


def test_launcher_error_is_shown_and_buttons_stay_usable(tmp_path):
    def broken(config):
        raise OSError("папка недоступна")

    menu, _, shown = make_menu(tmp_path, launcher=broken)
    menu.start()
    assert "папка недоступна" in menu.status.get() and shown["errors"]
    assert menu.start_button.kw.get("state") != "disabled"


def test_cosys_choice_and_default_flight_mode(tmp_path):
    menu, _, _ = make_menu(tmp_path)
    assert menu.read_config().flight_mode == "althold"
    menu.backend.set("Cosys-AirSim (Unreal)")
    assert menu.read_config().backend == "cosys"


def test_real_attempt_through_the_window(tmp_path):
    """Без подмены попытки: окно запускает настоящий процесс и показывает итог."""
    menu, _, _ = make_menu(tmp_path)  # launcher по умолчанию — настоящий
    menu.participant.set("P09")
    menu.end.set("на финише")
    menu.start()
    menu.attempt.wait(timeout=60)
    menu.poll()
    assert "КОНЕЦ ЭКСПЕРИМЕНТА" in menu.status.get()
    runs = list((tmp_path / "P09").iterdir())
    assert len(runs) == 1
    assert sorted(p.name for p in runs[0].glob("drone*.csv")) == ["drone0.csv", "drone1.csv", "drone2.csv"]
