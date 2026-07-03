#!/usr/bin/env bash
#
# Setup for Lamuel.
#
# Creates a virtual environment with --system-site-packages so it can reuse
# heavy packages already built for the system (notably the Jetson's CUDA/
# GStreamer OpenCV and its numpy) instead of pulling slower PyPI builds, then
# installs the remaining system and Python dependencies and prepares the models.
#
# Usage:
#   ./setup.sh
#
# Overridable via environment:
#   PYTHON=python3.10 VENV_DIR=venv LAMUEL_VOSK_MODEL=vosk-model-small-en-us-0.15

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${VENV_DIR:-venv}"
PYTHON="${PYTHON:-python3}"
VOSK_MODEL="${LAMUEL_VOSK_MODEL:-vosk-model-small-en-us-0.15}"
VOSK_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. System packages: flite (TTS), mpv (playback), portaudio (builds pyaudio)
# ---------------------------------------------------------------------------
info "Checking system packages..."
need_apt=()
command -v flite >/dev/null 2>&1 || need_apt+=("flite")
command -v mpv   >/dev/null 2>&1 || need_apt+=("mpv")
dpkg -s portaudio19-dev >/dev/null 2>&1 || need_apt+=("portaudio19-dev")

if [ "${#need_apt[@]}" -gt 0 ]; then
    if command -v apt-get >/dev/null 2>&1; then
        info "Installing: ${need_apt[*]}"
        sudo apt-get update && sudo apt-get install -y "${need_apt[@]}" \
            || warn "apt install failed; install these manually: ${need_apt[*]}"
    else
        warn "apt-get not found; install manually: ${need_apt[*]}"
    fi
else
    info "System packages already present."
fi

# ---------------------------------------------------------------------------
# 2. Virtual environment (reuses system packages)
# ---------------------------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    info "Creating venv at '$VENV_DIR' (--system-site-packages)..."
    "$PYTHON" -m venv --system-site-packages "$VENV_DIR" \
        || die "failed to create venv with '$PYTHON'"
else
    info "Reusing existing venv at '$VENV_DIR'."
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate" || die "could not activate venv"
python -m pip install --upgrade pip >/dev/null || warn "pip upgrade failed; continuing"

# ---------------------------------------------------------------------------
# 3. Python dependencies (skip opencv-python if the system already provides cv2)
# ---------------------------------------------------------------------------
info "Installing Python dependencies..."
tmp_req="$(mktemp)"
trap 'rm -f "$tmp_req"' EXIT

if python -c "import cv2" >/dev/null 2>&1; then
    info "System OpenCV detected (cv2 importable) - skipping opencv-python."
    grep -vE '^[[:space:]]*opencv-python' requirements.txt > "$tmp_req"
else
    info "No system OpenCV found - opencv-python will be installed from PyPI."
    cp requirements.txt "$tmp_req"
fi

pip install -r "$tmp_req" -c constraints.txt || die "pip install failed"

# The Jetson's OpenCV is built against NumPy 1.x. If a 2.x build slipped into
# the venv it would shadow the system copy and break cv2, so verify and, if
# needed, drop the venv-local numpy to fall back to the system's 1.x.
info "Verifying OpenCV / NumPy compatibility..."
if ! python -c "import cv2" >/dev/null 2>&1; then
    warn "cv2 failed to import - a NumPy 2.x build may be shadowing the system copy."
    info "Removing venv-local numpy so the system NumPy is used..."
    pip uninstall -y numpy >/dev/null 2>&1
fi
if python -c "import cv2, numpy; print('    cv2', cv2.__version__, '| numpy', numpy.__version__)"; then
    info "OpenCV/NumPy OK."
else
    warn "OpenCV still not importable; check the system OpenCV/NumPy install."
fi

# ---------------------------------------------------------------------------
# 4. Vosk speech model
# ---------------------------------------------------------------------------
if [ -d "$VOSK_MODEL" ]; then
    info "Vosk model '$VOSK_MODEL' already present."
elif [ "$VOSK_MODEL" = "vosk-model-small-en-us-0.15" ]; then
    info "Downloading Vosk model..."
    if command -v wget >/dev/null 2>&1; then
        wget -q --show-progress "$VOSK_URL" -O vosk-model.zip \
            && unzip -q vosk-model.zip && rm -f vosk-model.zip \
            || warn "Vosk download/unzip failed; fetch it manually from $VOSK_URL"
    else
        warn "wget not found; download the model manually from $VOSK_URL"
    fi
else
    warn "Custom Vosk model '$VOSK_MODEL' not found; place it in $REPO_ROOT."
fi

# ---------------------------------------------------------------------------
# 5. Ollama models (persona + vision)
# ---------------------------------------------------------------------------
if command -v ollama >/dev/null 2>&1; then
    info "Building the 'lamuel' persona (pulls base llava:7b if needed)..."
    ollama create lamuel -f Modelfile || warn "ollama create failed"
    info "Pulling the vision model (llava-phi3:3.8b)..."
    ollama pull llava-phi3:3.8b || warn "ollama pull failed"
else
    warn "ollama not found. After installing it, run:
    ollama create lamuel -f Modelfile
    ollama pull llava-phi3:3.8b"
fi

# ---------------------------------------------------------------------------
info "Setup complete."
cat <<'DONE'

To run Lamuel:
    source venv/bin/activate
    python -m lamuel.tools.devices      # find your microphone index
    export LAMUEL_MIC_INDEX=<index>
    python run.py
DONE
