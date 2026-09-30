"""Generate/check the three sampled-dialogue WAVs; never modify preview.wav."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "preview.wav"
sys.path.insert(0, str(ROOT.parent))
import announcer


def main():
    original = hashlib.sha256(SOURCE.read_bytes()).digest()
    with wave.open(str(SOURCE), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    versions = [
        ("07-sampled-subtle.wav", 8000, 8, 2, 3400, ""),
        ("08-sampled-medium.wav", 8000, 8, 3, 3400, "acrusher=bits=6:mix=0.25,"),
        ("09-sampled-heavy.wav", 6000, 4, 4, 2700, ""),
    ]
    for name, rate, bits, drive, cutoff, crunch in versions:
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "processed.wav"
            filters = (f"volume={drive},asoftclip=type=tanh:oversample=4,{crunch}"
                       f"highpass=f=300,lowpass=f={cutoff},aresample={rate}")
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                            "-i", str(SOURCE), "-af", filters, "-ac", "1", "-ar", str(rate),
                            "-c:a", "pcm_s16le", str(raw)], check=True)
            output = ROOT / name
            announcer.quantize_wav(raw, output, bits=bits)
            step = 1 << (8 - bits)
            with wave.open(str(output), "rb") as audio:
                assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 1, rate)
                assert abs(audio.getnframes() / rate - duration) <= 1 / rate
                pcm = audio.readframes(audio.getnframes())
            assert 0 < max(abs(value - 128) for value in pcm) <= 115
            assert all((value - 128) % step == 0 for value in pcm)
            assert len(set(pcm)) <= 2 ** bits
            print(f"{output.name}: {rate} Hz, {bits}-bit quantization, "
                  f"{len(set(pcm))} amplitude levels, peak {max(abs(value - 128) for value in pcm) / 128:.3f}")
    assert hashlib.sha256(SOURCE.read_bytes()).digest() == original
    print("All WAV checks passed; source preserved.")


if __name__ == "__main__":
    main()
