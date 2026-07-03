# Lamuel

A voice-driven robot for the NVIDIA Jetson. You speak to Lamuel; it thinks with
a local LLM, talks back, and moves its head. Its camera continuously tracks
faces (and, failing that, motion), and on request it looks through the camera
and describes what it sees.

This is a clean-room rewrite of the original prototype. It keeps the same
observable behaviour but fixes the architecture: one process, one owner of the
serial port, in-memory image capture instead of temp-file semaphores, and
graceful degradation when hardware is missing.

## How it works

```
        mic ──▶ hearing (Vosk STT)
                     │ transcript
                     ▼
                  brain ──▶ ollama "lamuel" persona ──▶ reply
                     │
        parse reply into actions:
             ├─ speak      ─▶ voice (flite ─▶ mpv)
             ├─ HEAD-YAW/PITCH ─▶ head (serial X:/Y:)   [overrides tracking]
             └─ CAPTURE    ─▶ sight.snapshot ─▶ ollama vision model
                                   │ description
                                   └─▶ fed back into brain as a sensor reading

        camera ──▶ sight (background thread)
                     ├─ face detection (Haar) ─┐
                     └─ motion detection ──────┴▶ head (serial X:/Y:)  [tracking]
```

The vision thread runs continuously, so the head keeps following you while the
brain is busy. When the LLM issues a deliberate `HEAD-YAW` / `HEAD-PITCH` (or
takes a picture), that briefly overrides autonomous tracking so the intentional
motion is visible, then tracking resumes.

### Serial protocol (unchanged)

    X:<int>\n\r    yaw    (+ = left)
    Y:<int>\n\r    pitch  (+ = up)

Steps are treated as relative increments; the software keeps an estimate of the
current angle to clamp within the mechanical limits. If your firmware expects
absolute positions instead, set `HeadConfig.relative = False`.

## Layout

```
run.py                  entry point (python run.py)
Modelfile               the "lamuel" Ollama persona + command grammar
requirements.txt
assets/                 startup + shutter sounds
lamuel/
  config.py             all tunables (env-overridable)
  hearing.py            Vosk speech-to-text (falls back to typed input)
  brain.py              Ollama chat, action dispatch, capture->describe loop
  commands.py           parse LLM text into Say / Look / Capture actions
  voice.py              flite text-to-speech
  sight.py              camera loop: faces, motion, tracking, snapshots
  head.py               sole serial owner: servo moves, arbitration, clamping
  app.py                wiring + lifecycle
  tools/devices.py      list mic indices (python -m lamuel.tools.devices)
```

## Setup

Run the setup script from the repo root:

```bash
./setup.sh
```

It creates a virtual environment with `--system-site-packages` (so it reuses
the Jetson's CUDA-built OpenCV and numpy instead of pulling slower PyPI builds),
installs the system packages (`flite`, `mpv`, `portaudio19-dev`), installs the
Python dependencies — skipping `opencv-python` when the system already provides
`cv2` — downloads the small Vosk model, and prepares the Ollama models. Steps
that are already done are detected and skipped, so it's safe to re-run.

If you'd rather do it by hand, the equivalent steps are:

1. `sudo apt install flite mpv portaudio19-dev`
2. `python -m venv --system-site-packages venv && source venv/bin/activate`
3. `pip install -r requirements.txt -c constraints.txt` (drop `opencv-python`
   if `import cv2` already works). The `-c constraints.txt` cap keeps NumPy on
   the 1.x ABI so it doesn't shadow and break the system's OpenCV.
4. Unpack a Vosk model (e.g. `vosk-model-small-en-us-0.15`) into the repo root
5. `ollama create lamuel -f Modelfile && ollama pull llava-phi3:3.8b`

## Running

```bash
source venv/bin/activate
python -m lamuel.tools.devices     # find your mic index
export LAMUEL_MIC_INDEX=<index>
python run.py
```

Then talk. Say hello, ask it to look left, or ask what it can see.

### Web control panel

Lamuel serves a browser console at `http://<the-Jetson's-IP>:8080/` (find the
IP with `hostname -I`). Open it from any machine on the same network to:

- **watch the live camera feed** as Lamuel sees it,
- **follow a running log** of what Lamuel hears and says,
- **toggle conversation** (listening and speaking together) **and head tracking** on and off, and
- **shut the whole box down.**

The panel is optional — if Flask isn't installed it's skipped and the robot
runs as normal. It's on by default; set `LAMUEL_WEB=0` to disable it, or
`LAMUEL_WEB_PORT` to move it.

The **Shut down** button runs `sudo shutdown -h now`, which needs privileges.
If Lamuel runs as a normal user, grant passwordless permission for just that
command (replace `lamuel` with the account it runs as):

```
# /etc/sudoers.d/lamuel-poweroff  (edit with: sudo visudo -f ...)
lamuel ALL=(root) NOPASSWD: /sbin/shutdown
```

Or point `LAMUEL_POWEROFF_CMD` at whatever your system uses (e.g.
`systemctl poweroff`).

> **Note:** the portal has no authentication and binds to all interfaces, so
> keep it on a trusted LAN — anyone who can reach the IP can move the head and
> power the box off.

### Off-robot / development

Every hardware-touching subsystem degrades gracefully when
`graceful_degradation` is on (the default): no serial port → head runs in
dry-run and logs its moves; no camera → tracking and capture are skipped; no
microphone → you get a `you>` prompt and can **type** what you'd say. That lets
you exercise the whole brain-and-voice pipeline on a laptop.

## Configuration

Everything is in `lamuel/config.py`, and the common knobs can be set with
environment variables so you don't touch source on the robot:

| Variable                | Meaning                              | Default                      |
|-------------------------|--------------------------------------|------------------------------|
| `LAMUEL_MIC_INDEX`      | audio input device index             | `1`                          |
| `LAMUEL_CAMERA`         | camera index (`/dev/video<N>`)       | `0`                          |
| `LAMUEL_SERIAL`         | servo serial port                    | `/dev/ttyACM0`               |
| `LAMUEL_BAUD`           | serial baud rate                     | `9600`                       |
| `LAMUEL_MODEL`          | Ollama persona model                 | `lamuel`                     |
| `LAMUEL_VISION_MODEL`   | image-description model              | `llava-phi3:3.8b`            |
| `LAMUEL_VOSK_MODEL`     | path to the Vosk model directory     | `vosk-model-small-en-us-0.15`|
| `LAMUEL_WEB`            | enable the browser control panel     | `1`                          |
| `LAMUEL_WEB_HOST`       | address the panel binds to           | `0.0.0.0`                    |
| `LAMUEL_WEB_PORT`       | port the panel listens on            | `8080`                       |
| `LAMUEL_POWEROFF_CMD`   | command run by the shutdown button   | `sudo shutdown -h now`       |

## Notes on the rewrite

- **One process, one serial owner.** Previously `main.py` and `new_vision.py`
  each opened `/dev/ttyACM0` and both drove the servos; they could fight over
  the head. Now all motion goes through a single locked `HeadController`.
- **In-memory capture.** The old `/tmp/GETIMG` + `/tmp/image.jpg` handshake and
  polling loop between two processes is gone. The vision thread keeps the latest
  frame in memory, so a capture is just a copy.
- **Dropped scaffolding.** `super_main.py`, `vision.py`'s CSI/GStreamer path,
  `device_test.py`, and `serial_test.py` were experiments or throwaway probes
  and aren't carried over. Device listing lives in `lamuel/tools/devices.py`.
- **Safety + robustness.** Servo positions are clamped to configurable limits;
  the capture→describe→reply loop has a depth guard; failures are logged rather
  than fatal.

