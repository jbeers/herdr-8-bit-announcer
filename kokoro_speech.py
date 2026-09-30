#!/usr/bin/env python3
"""Isolated Kokoro worker: JSON on stdin, output WAV path as its argument."""

import json
from pathlib import Path
import sys
import wave


def main():
    import numpy as np
    import onnxruntime as rt
    from kokoro_onnx import Kokoro

    assets = Path(__file__).resolve().parent / ".kokoro"
    request = json.load(sys.stdin)
    options = rt.SessionOptions()
    options.intra_op_num_threads = 4  # Don't compete with agents for all CPU cores.
    session = rt.InferenceSession(str(assets / "kokoro-v1.0.onnx"), sess_options=options,
                                  providers=["CPUExecutionProvider"])
    kokoro = Kokoro.from_session(session, str(assets / "voices-v1.0.bin"))
    voices = [name for name in kokoro.get_voices() if name.startswith(("af_", "am_", "bf_", "bm_"))]
    voice = request["voice"]
    if voice not in voices:
        raise ValueError("Choose an English Kokoro voice: " + ", ".join(voices))
    samples, rate = kokoro.create(request["text"], voice=voice, speed=request["speed"],
                                  lang="en-gb" if voice.startswith("b") else "en-us")
    pcm = np.rint(np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(sys.argv[1], "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(pcm)


if __name__ == "__main__":
    try:
        main()
    except (ImportError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"kokoro: {error}", file=sys.stderr)
        sys.exit(1)
