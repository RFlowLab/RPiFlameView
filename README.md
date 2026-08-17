[README.md](https://github.com/user-attachments/files/31137845/README.md)
# RPiFlameView

A Tkinter control panel for flame-imaging experiments on a Raspberry Pi camera.
It drives `rpicam-still` and `rpicam-vid`, organises the output into a folder
tree keyed by experiment conditions, and writes a metadata file next to every
capture so a recording can be traced back to the settings that produced it.

Built for the ReactingFlow Lab.

## Requirements

| | |
|---|---|
| Hardware | Raspberry Pi with a CSI camera module (autofocus supported) |
| OS | Raspberry Pi OS **Bookworm** or later |
| Camera stack | `rpicam-apps` (`rpicam-still`, `rpicam-vid`, `rpicam-hello`) |
| Python | 3.9+ with Tkinter (`sudo apt install python3-tk`) |

Only the standard library is used — there is nothing to `pip install`.

The program shells out to `rpicam-*`, so it must run on the Pi itself, on a
desktop session (locally or over VNC/X11). It will not work on the older
`libcamera-*` or `raspistill` tooling.

Check the camera stack first:

```bash
rpicam-hello --list-cameras
```

## Running

```bash
python3 GUI_12.py
```

That is the whole setup — `GUI_12.py` on its own is enough to start the program
and capture images. No image asset, parameter file, or config is needed up
front.

`ReFlowLab_signature.gif` is purely decorative. If you drop it next to
`GUI_12.py` (or in the directory you launch from) the lab logo appears in the
title bar; if it is absent the program shows a text label instead and behaves
identically.

## Parameter files

The top-left `file.txt` button lists every `.txt` file in the working
directory. A parameter file describes one experiment run:

```
CH4
Photos 11000 32000 1000
Videos 8000 4000 30
Photos 11000 32000 1000
```

- **Line 1** — the fuel name, used as a folder level in the output path.
- **Each following line** — one capture set, four whitespace-separated fields:

| Field | Meaning |
|---|---|
| `Photos` / `Videos` | capture mode for this set |
| `t` | capture duration, milliseconds |
| `shutter` | exposure time, microseconds |
| `timelapse` / `framerate` | photos: interval between frames in ms · videos: frames per second |

Entering a name that does not exist offers to create the file. Rows can be
added and removed in the GUI, and `Save` writes the table back to the `.txt`.

## Workflow

1. **Pick a parameter file**, then set concentration (`pc`), equivalence ratio
   (`eq`), power (`kW`), focus mode, lens position, gain and monitor shutter.
   The buttons above each field offer the usual preset values.
2. **`Test Camera`** opens a live preview at the current focus/gain/shutter
   settings without saving anything. `STOP` closes it.
3. **`Next`** loads the parameter file into an editable table.
4. **`Next`** again generates an output folder name for every row.
5. **`Create folder`** creates them on disk and reveals `Start`.
6. **`Start`** runs each set in order, then begins the end-of-run monitor
   recording, which continues until you press `STOP`.

`Monitor` records an ad-hoc clip at any time, filed separately under
`temp_monitor` and tagged with the optional *monitor name* field.

`STOP` terminates the running camera process and cancels the rest of the
sequence.

## Output

Everything lands under `~/Desktop/<YYYYMMDD>/`:

```
20260817/
├── CH4/
│   ├── 25ms/50pc/0.85eq/3kW/32000_1/   photos   image00.jpg, image01.jpg, …
│   ├── record/50pc/0.85eq/3kW/4000_1/  videos   record.h264
│   └── exp/50pc/0.85eq/3kW/test1_25000/  end monitor  record.h264
└── temp_monitor/3kW/test1_25000_<name>/  ad-hoc   record.h264
```

The trailing `<shutter>_<n>` counter increments so repeat runs at the same
shutter never overwrite each other.

Every capture folder also gets an `experiment_info.json`:

```json
{
  "created_at": "2026-08-17T14:32:05",
  "mode": "photo",
  "fuel": "CH4",
  "concentration_pc": "50",
  "eq": "0.85",
  "power_kw": "3",
  "focus_mode": "manual",
  "lens_position": "1.25",
  "gain": "10",
  "monitor_shutter_us": "25000",
  "camera_command": "rpicam-still -t 11000 …",
  "duration_ms": 11000,
  "shutter_us": 32000,
  "timelapse_ms": 1000,
  "resolution": "4608x2592"
}
```

## Fixed camera settings

These are hardcoded and require a code change to alter:

- Rotation `180`
- AWB gains `2.0,2.3`
- Photos `4608x2592`, JPEG quality `100`, `-r` (raw metadata)
- Videos `1920x1080`; monitor recordings at `30` fps
- Monitor recordings run untimed (`-t 0`) until stopped

Videos are written as raw `.h264`. Wrap them for playback with:

```bash
ffmpeg -framerate 30 -i record.h264 -c copy record.mp4
```

## Checking a change without a Pi

`mock_run.py` drives the GUI through the whole workflow with the `rpicam`
subprocess stubbed and `~` redirected into a temporary sandbox, so it runs on
any machine with Python and Tkinter and touches nothing outside `/tmp`:

```bash
python3 mock_run.py -v
```

It checks folder naming, the repeated-shutter counter, metadata, `STOP`
handling and input validation, and exits non-zero on failure. Drop `-v` for
quiet output.

It cannot check that `rpicam-*` accepts the flags or that the camera behaves —
those still need a run on the Pi. Treat a pass as "the plumbing is intact", not
"this is ready to ship".

## Known quirks

- The photo output path contains a literal `25ms` segment that predates the
  configurable monitor shutter. It is a naming convention, not a setting.
- `Pi 5` does not support `--save-pts`, so frame timestamps are not recorded.
- The parameter table's file-name column stays editable until `Create folder`.
  Empty or duplicate names are rejected at that point.

## Troubleshooting

**"Camera command not found"** — `rpicam-apps` is missing, or the OS is older
than Bookworm and still ships `libcamera-*`.

**"Camera process exited with code N"** — run the command printed in the status
line by hand to see the error from `rpicam-*`. The most common causes are a
shutter longer than the frame interval, or another process holding the camera.

**"Camera busy"** — a previous capture is still running. Press `STOP`.

**Preview does not appear over SSH** — `rpicam-hello` needs a display. Use a
local session or VNC, not a plain SSH terminal.
