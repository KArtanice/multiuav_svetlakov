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


def test_gamepad_indicator_shows_connected_and_not_connected(tmp_path):
    menu, root, _ = make_menu(tmp_path, gamepad_probe=lambda: (True, "RadioMaster Pocket"))
    assert "подключён" in menu.gamepad_text.get() and "RadioMaster" in menu.gamepad_text.get()
    assert menu.gamepad_label.kw["fg"] == "#1b7f3b"

    menu2, _, _ = make_menu(tmp_path)
    assert "не подключён" in menu2.gamepad_text.get()
    assert menu2.gamepad_label.kw["fg"] == "#b3261e"


def test_gamepad_is_polled_repeatedly(tmp_path):
    menu, root, _ = make_menu(tmp_path)
    assert root.scheduled  # опрос пульта запланирован
    before = len(root.scheduled)
    root.scheduled[-1][1]()  # сработал таймер
    assert len(root.scheduled) == before + 1  # ровно одна следующая отметка, не две


def test_start_runs_an_attempt_and_returns_to_the_menu(tmp_path):
    menu, root, shown = make_menu(tmp_path)
    menu.end.set("на финише")
    menu.start()
    assert menu.start_button.kw["state"] == "disabled"
    menu._thread.join(timeout=60)
    menu.poll()
    assert menu.start_button.kw["state"] == "normal"
    assert "КОНЕЦ ЭКСПЕРИМЕНТА" in menu.status.get()
    runs = list(tmp_path.glob("run_*"))
    assert len(runs) == 1
    assert sorted(p.name for p in runs[0].iterdir()) == ["experiment.json", "summary.json", "track.csv"]
    assert not shown.get("errors")


def test_second_start_after_the_end_makes_a_second_attempt(tmp_path):
    menu, _, _ = make_menu(tmp_path)
    menu.end.set("на финише")
    for _ in range(2):
        menu.start()
        menu._thread.join(timeout=60)
        menu.poll()
    assert len(list(tmp_path.glob("run_*"))) == 2


def test_parameters_from_the_fields_reach_the_run(tmp_path):
    seen = []
    menu, _, _ = make_menu(tmp_path, runner=lambda cfg: seen.append(cfg) or type(
        "O", (), {"summary": {"finished": 0, "drones": cfg.drones, "collided": 0}, "run_dir": tmp_path})())
    menu.drones.set(4)
    menu.end.set("на финише")
    menu.mode.set("Acro")
    menu.wind_law.set("порывы")
    menu.blackout.set(800)
    menu.assist.set(True)
    menu.start()
    menu._thread.join(timeout=10)
    cfg = seen[0]
    assert (cfg.drones, cfg.end_on, cfg.flight_mode, cfg.wind_law) == (4, "finish", "acro", "gusts")
    assert cfg.blackout_ms == 800 and cfg.assist is True
    assert cfg.backend == "kinematic"


def test_cosys_choice_and_default_flight_mode(tmp_path):
    menu, _, _ = make_menu(tmp_path)
    assert menu.read_config().flight_mode == "althold"
    menu.backend.set("Cosys-AirSim (Unreal)")
    assert menu.read_config().backend == "cosys"


def test_invalid_parameters_show_a_message_and_do_not_start(tmp_path):
    menu, _, shown = make_menu(tmp_path)
    menu.drones.set(0)
    menu.start()
    assert menu._thread is None
    assert shown["errors"] and "дронов" in shown["errors"][0]
    assert menu.start_button.kw.get("state") != "disabled"


def test_not_a_number_in_a_field_is_reported_not_crashed(tmp_path):
    menu, _, shown = make_menu(tmp_path)
    menu.drones.set("abc")
    menu.start()
    assert menu._thread is None
    assert "числа" in shown["errors"][0]


def test_error_inside_the_run_is_shown_in_the_window(tmp_path):
    def broken(cfg):
        raise RuntimeError("Cosys не отвечает")

    menu, _, _ = make_menu(tmp_path, runner=broken)
    menu.start()
    menu._thread.join(timeout=10)
    menu.poll()
    assert "Cosys не отвечает" in menu.status.get()
    assert menu.start_button.kw["state"] == "normal"


def test_start_pressed_twice_while_running_is_ignored(tmp_path):
    import threading

    gate = threading.Event()
    calls = []

    def slow(cfg):
        calls.append(1)
        gate.wait(10)
        return type("O", (), {"summary": {"finished": 0, "drones": 3, "collided": 0}, "run_dir": tmp_path})()

    menu, _, _ = make_menu(tmp_path, runner=slow)
    menu.start()
    menu.start()  # второй щелчок
    gate.set()
    menu._thread.join(timeout=10)
    assert len(calls) == 1
