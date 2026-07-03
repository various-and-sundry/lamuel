"""List available audio input devices and their indices.

Run with:  python -m lamuel.tools.devices

Use the printed index for LAMUEL_MIC_INDEX (or AudioConfig.device_index).
"""

from __future__ import annotations


def main():
    try:
        import pyaudio
    except ImportError:
        raise SystemExit("pyaudio is not installed (pip install pyaudio)")

    pa = pyaudio.PyAudio()
    try:
        print("Audio input devices:")
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            channels = info["maxInputChannels"]
            if channels > 0:
                print(f"  [{i}] {info['name']}  (in={channels}, "
                      f"rate={int(info['defaultSampleRate'])})")
    finally:
        pa.terminate()


if __name__ == "__main__":
    main()
