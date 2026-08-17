"""Off-Pi smoke check for GUI_12.py.

Runs the real GUI through the full workflow -- load parameters, build the
form, generate folder names, create folders, run the capture sequence -- with
only the rpicam subprocess faked and ~ redirected into a temporary sandbox.

It verifies the plumbing: folder naming, metadata, threading, STOP handling and
input validation. It cannot verify that rpicam-* accepts the flags or that the
camera behaves; that still needs a run on the Pi.

    python3 mock_run.py           # quiet, exit 0 on success
    python3 mock_run.py -v        # show the commands and the folder tree
    python3 mock_run.py --gui     # open the real window to click through by hand

The scenario runs inside root.mainloop(): tkinter only permits cross-thread
root.after() calls while the interpreter is dispatching, so a harness driven by
root.update() alone would fail where the real program succeeds.
"""
import json
import os
import shutil
import subprocess as real_subprocess
import sys
import tempfile
import time
import traceback
import types
import tkinter as tk

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
GUI = "--gui" in sys.argv
REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

SANDBOX = tempfile.mkdtemp(prefix="rpiflame-mock-")
WORKDIR = os.path.join(SANDBOX, "work")
os.makedirs(os.path.join(SANDBOX, "Desktop"), exist_ok=True)
os.makedirs(WORKDIR, exist_ok=True)

# Keep every write inside the sandbox instead of the real ~/Desktop.
_real_expanduser = os.path.expanduser
def sandbox_expanduser(path):
    if path == "~":
        return SANDBOX
    if path.startswith("~/"):
        return os.path.join(SANDBOX, path[2:])
    return _real_expanduser(path)
os.path.expanduser = sandbox_expanduser

import GUI_12

COMMANDS = []
class FakeCameraProcess:
    """Stands in for rpicam-*: records the command, writes its output, exits 0."""
    def __init__(self, command):
        COMMANDS.append(list(command))
        self.returncode = None
        if "-o" in command:
            target = command[command.index("-o") + 1]
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if "%" in target:                      # timelapse writes a series
                for n in range(3):
                    with open(target.replace("image%02d", f"image{n:02d}"), "wb") as f:
                        f.write(b"\xff\xd8mock jpeg")
            else:
                with open(target, "wb") as f:
                    f.write(b"mock h264")
    def wait(self, timeout=None):
        self.returncode = 0
        return 0
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15
    def kill(self):
        self.returncode = -9

GUI_12.subprocess = types.SimpleNamespace(
    Popen=FakeCameraProcess, TimeoutExpired=real_subprocess.TimeoutExpired
)

DIALOGS = []
if not GUI:
    # Headless: dialogs would block, so record them instead. In --gui mode the
    # real messagebox stays in place so they can be seen and clicked.
    GUI_12.messagebox = types.SimpleNamespace(
        showinfo=lambda t, m: DIALOGS.append((t, m)),
        showerror=lambda t, m: DIALOGS.append((t, m)),
        askokcancel=lambda t, m: (DIALOGS.append((t, m)), True)[1],
    )

FAILURES = []
def check(label, condition, detail=""):
    (print if VERBOSE else lambda *a: None)(
        f"  {'PASS' if condition else 'FAIL'}  {label}{'  ' + detail if detail else ''}"
    )
    if not condition:
        FAILURES.append(f"{label} {detail}".strip())

def banner(text):
    if VERBOSE:
        print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")

os.chdir(WORKDIR)
with open("run_a.txt", "w") as f:
    f.write("CH4\n")
    f.write("Photos 11000 32000 1000\n")
    f.write("Videos 8000 4000 30\n")
    f.write("Photos 11000 32000 1000\n")   # same shutter as row 1 -> _2 suffix

root = tk.Tk()
if not GUI:
    root.withdraw()
app = GUI_12.RaspberryPiGUI(root)
STATUS = []
if not GUI:
    app.set_status = lambda m: STATUS.append(m)


def pump(limit=20.0):
    """Let the worker run; root.update() keeps after() callbacks flowing."""
    deadline = time.time() + limit
    while app.worker_thread and app.worker_thread.is_alive() and time.time() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()


def scenario():
    banner("1. STARTUP")
    check("starts with no signature image present", app.img is None)

    banner("2. LOAD PARAMETER FILE")
    app.filename.set("run_a")
    app.pc.set("50"); app.eqivalent.set("0.85"); app.kw.set("3")
    app.ms.set("25000"); app.gain.set("10")
    app.focus_mode.set("manual"); app.lens_position.set("1.25")
    app.parameter_form(True)
    check("fuel parsed", app.fuel == "CH4", f"got {app.fuel!r}")
    check("three sets loaded", app.set_number == 3, f"got {app.set_number}")

    banner("3. ROW EDITING REJECTS BAD INPUT")
    # Must run before create_folder(), which disables these controls by design.
    for text, add, label in (("x", True, "non-numeric"), ("99", False, "out of range")):
        rows = app.set_number
        app.change_row.delete(0, tk.END); app.change_row.insert(0, text)
        DIALOGS.clear()
        app.Add_remove_data(add)
        check(f"{label} row {text!r} refused",
              bool(DIALOGS) and app.set_number == rows,
              DIALOGS[0][1] if DIALOGS else "no dialog")
    app.change_row.delete(0, tk.END)

    banner("4. GENERATE FOLDER NAMES")
    app.decide_file_name()
    names = [app.file_name[i].get() for i in range(app.set_number)]
    if VERBOSE:
        for n, name in enumerate(names, 1):
            print(f"    row {n}: {name}")
    check("repeated shutter gets a fresh counter",
          names[0].endswith("32000_1") and names[2].endswith("32000_2"))
    check("photos and videos use separate trees",
          "/25ms/" in names[0] and "/record/" in names[1])
    check("folder names are unique", len(set(names)) == 3)

    banner("5. CREATE FOLDERS")
    DIALOGS.clear()
    app.create_folder()
    check("no dialog raised", not DIALOGS, str(DIALOGS))
    check("Start button revealed", hasattr(app, "button_start1"))
    check("row editing locked once folders exist",
          str(app.change_row.cget("state")) == tk.DISABLED,
          str(app.change_row.cget("state")))

    banner("6. RUN THE SEQUENCE")
    DIALOGS.clear(); STATUS.clear()
    app.take_photo()
    pump()
    if VERBOSE:
        for n, cmd in enumerate(COMMANDS, 1):
            print(f"\n    [{n}] {cmd[0]}\n        {' '.join(str(c) for c in cmd[1:])}")
        print()
    check("no dialog raised", not DIALOGS, str(DIALOGS))
    check("three sets plus end monitor ran", len(COMMANDS) == 4, f"got {len(COMMANDS)}")
    check("photo set uses rpicam-still", COMMANDS[0][0] == "rpicam-still")
    check("video set uses rpicam-vid", COMMANDS[1][0] == "rpicam-vid")
    check("end monitor runs untimed", COMMANDS[3][COMMANDS[3].index("-t") + 1] == "0")
    check("end monitor uses the monitor shutter",
          COMMANDS[3][COMMANDS[3].index("--shutter") + 1] == "25000")
    check("reports success", STATUS and STATUS[-1] == "Experiment sequence finished.",
          STATUS[-1] if STATUS else "(no status)")

    banner("7. OUTPUT LAYOUT")
    desktop = os.path.join(SANDBOX, "Desktop")
    if VERBOSE:
        for base, dirs, files in os.walk(desktop):
            dirs.sort(); files.sort()
            depth = base[len(desktop):].count(os.sep)
            print("    " + "   " * depth + os.path.basename(base) + "/")
            for fn in files:
                print("    " + "   " * (depth + 1) + fn)

    metas = []
    for base, _, files in os.walk(desktop):
        if "experiment_info.json" in files:
            metas.append(os.path.join(base, "experiment_info.json"))
    check("one metadata file per capture", len(metas) == 4, f"got {len(metas)}")

    # Two folders share shutter 32000, so a mix-up here would be plausible.
    consistent = True
    for meta in metas:
        with open(meta) as f:
            data = json.load(f)
        target = data["camera_command"].split(" -o ")[-1]
        consistent &= os.path.dirname(target) == os.path.dirname(meta)
    check("each metadata file describes its own folder", consistent)

    jpegs = [f for b, _, fs in os.walk(desktop) for f in fs if f.endswith(".jpg")]
    h264s = [f for b, _, fs in os.walk(desktop) for f in fs if f.endswith(".h264")]
    check("timelapse frames written", len(jpegs) == 6, f"got {len(jpegs)}")
    check("video files written", len(h264s) == 2, f"got {len(h264s)}")

    banner("8. STOP CANCELS THE REST OF A RUN")
    before = len(COMMANDS)
    STATUS.clear()
    app.stop_camera()
    app.worker_thread = None
    app._take_photo_worker(app.build_capture_plan())
    pump()
    check("no camera call while stopped", len(COMMANDS) == before,
          f"{len(COMMANDS) - before} extra")
    check("reports the stop", STATUS and STATUS[-1].startswith("Experiment stopped"),
          STATUS[-1] if STATUS else "(no status)")

    banner("9. BAD INPUT IS REFUSED, NOT PASSED TO THE CAMERA")
    app.stop_requested = False
    for field, values in (("shutter", app.shutter), ("t", app.t)):
        for bad in ("abc", "", "-5"):
            before = len(COMMANDS)
            good = values[0].get()
            values[0].set(bad)
            DIALOGS.clear()
            app.take_photo(); pump()
            check(f"{field}={bad!r} refused",
                  bool(DIALOGS) and len(COMMANDS) == before,
                  DIALOGS[0][1] if DIALOGS else "no dialog, camera ran")
            values[0].set(good)


if GUI:
    print(f"""
Mock GUI -- the camera is stubbed, so every capture succeeds instantly
and writes placeholder files. Nothing touches your real Desktop.

  parameter file : run_a  (already in the working directory)
  output goes to : {os.path.join(SANDBOX, 'Desktop')}

Click through: file.txt -> Next -> Next -> Create folder -> Start.
Camera commands are printed below as they are issued. Close the window
when done; the sandbox is left in place so you can inspect the output.
""")
    _real_popen = FakeCameraProcess
    class LoggingCameraProcess(_real_popen):
        def __init__(self, command):
            print(f"  [camera] {' '.join(str(c) for c in command)}\n", flush=True)
            super().__init__(command)
    GUI_12.subprocess.Popen = LoggingCameraProcess

    def on_close():
        app.stop_camera()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    print(f"Sandbox left at: {SANDBOX}")
    sys.exit(0)

try:
    root.after(0, lambda: (scenario(), root.quit()))
    root.mainloop()
except Exception:
    traceback.print_exc()
    FAILURES.append("scenario raised an exception")
finally:
    try:
        root.destroy()
    except tk.TclError:
        pass
    os.chdir(REPO)
    shutil.rmtree(SANDBOX, ignore_errors=True)

if FAILURES:
    print(f"\nFAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nmock_run: all checks passed "
      "(rpicam-* was stubbed; still verify on the Pi)")
