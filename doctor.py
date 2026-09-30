#!/usr/bin/env python3
"""Check setup without playing audio, contacting speech services, or exposing keys."""

import argparse
import os
from pathlib import Path
import shutil
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        print("FAIL Python: install Python 3.11+ and put python3 on Herdr's PATH")
        return 1

    import announcer as audio
    import configure as ui

    failures = 0

    def report(ok, label, detail):
        nonlocal failures
        failures += not ok
        print(f"{'OK' if ok else 'FAIL'} {label}: {detail}")

    def tool(label, names, hint):
        found = next((shutil.which(name) for name in names if shutil.which(name)), None)
        report(bool(found), label, found or hint)
        return found

    report(True, "Python", sys.version.split()[0])
    tool("Herdr", [os.environ.get("HERDR_BIN_PATH", "herdr")], "install Herdr 0.9.2+ on the server's PATH")
    ffmpeg = tool("FFmpeg", ["ffmpeg"], "install ffmpeg using your system package manager")
    file = audio.config_path(args.config)
    config = None
    try:
        if args.config and not file.is_file():
            raise FileNotFoundError(f"config not found: {file}")
        config = audio.load_config(file)
        ui.validate(config)
        report(True, "Config", str(file))
        if not file.exists():
            print("WARN Config: missing; runtime uses defaults. Open Configure to save your settings.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        report(False, "Config", f"{file}: {error}")
        config = None

    if config is not None:
        settings = audio.audio_settings(config)
        backend = settings["backend"]
        if ffmpeg:
            try:
                filters = audio.run([ffmpeg, "-hide_banner", "-filters"]).decode()
                needed = {"aresample", "alimiter"}
                if settings["eight_bit_crunch"]:
                    needed.update(("asoftclip", "acrusher", "highpass", "lowpass"))
                if settings["grit"]:
                    needed.add("acrusher")
                if settings["echo"]:
                    needed.add("aecho")
                missing = sorted(needed - {line.split()[1] for line in filters.splitlines() if len(line.split()) >= 2})
                report(not missing, "Audio filters", "missing: " + ", ".join(missing) if missing else "available")
            except (OSError, audio.subprocess.SubprocessError) as error:
                report(False, "Audio filters", str(error))
        if backend == "local":
            tool("Local speech", ["say"] if sys.platform == "darwin" else ["espeak-ng", "espeak"],
                 "install espeak-ng (macOS uses built-in say)")
        elif backend == "kokoro":
            assets = Path(audio.__file__).resolve().parent / ".kokoro"
            missing = [name for name in ("venv/bin/python", "kokoro-v1.0.onnx", "voices-v1.0.bin")
                       if not (assets / name).is_file()]
            report(not missing, "Kokoro assets", "missing: " + ", ".join(missing) + "; follow README setup" if missing else str(assets))
            if not missing:
                try:
                    audio.run([str(assets / "venv/bin/python"), "-c", "import kokoro_onnx, numpy, onnxruntime"])
                    report(True, "Kokoro runtime", "imports work; use Say something to test the model/voice")
                except (OSError, audio.subprocess.SubprocessError):
                    report(False, "Kokoro runtime", "imports failed; reinstall the isolated runtime per README")
        else:
            key_file = file.parent / "openai-api-key"
            try:
                key = os.environ.get("OPENAI_API_KEY", "").strip() or (key_file.read_text().strip() if key_file.exists() else "")
                report(bool(key), "OpenAI credentials", "present (not tested online)" if key else
                       "set OPENAI_API_KEY in Herdr's server environment or create openai-api-key beside config.toml")
                if key_file.exists() and key_file.stat().st_mode & 0o077:
                    report(False, "API key permissions", f"run chmod 600 '{key_file}'")
            except OSError:
                report(False, "OpenAI credentials", "cannot read key file; check its permissions")
            print("WARN Privacy: OpenAI receives spoken text, including workspace/agent names; cache misses incur charges.")
        if config.get("only_matched") or any(rule.get("mute") for rule in config.get("rules", [])):
            print("WARN Rules: some previews/completions may be muted; Say something bypasses rules.")

    tool("Playback", ["afplay"] if sys.platform == "darwin" else ["paplay", "aplay", "ffplay"],
         "install pulseaudio-utils, alsa-utils, or ffplay")
    if not shutil.which("dialog"):
        print("WARN Settings UI: install dialog to use Configure and Say something popups")
    else:
        print("OK Settings UI: dialog available")
    state = audio.state_path()
    parent = state
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    report(parent.is_dir() and os.access(parent, os.W_OK | os.X_OK), "State directory", str(state))
    print("Audio runs on Herdr's server machine. This check does not test the audio device or make paid requests.")
    print(f"{'Setup checks failed' if failures else 'Setup checks passed'} ({failures} failures).")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
