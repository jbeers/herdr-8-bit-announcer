#!/usr/bin/env python3
"""Herdr completion announcer. Python 3.11+, optional isolated Kokoro runtime."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import string
import struct
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import wave

PRESETS = {
    "gauntlet": [
        "{agent} agent in {workspace} needs food badly!",
        "{agent} agent in {workspace} has found the exit!",
        "{agent} agent in {workspace} has defeated the bug horde!",
        "{agent} agent in {workspace} awaits your next quest!",
    ],
    "victory": [
        "Victory! {agent} agent has conquered {workspace}!",
        "{agent} agent in {workspace} is victorious. Collect your loot!",
        "The dungeon of {workspace} is clear. Well done, {agent} agent!",
    ],
    "snark": [
        "{agent} agent in {workspace} needs coffee badly!",
        "{agent} agent in {workspace} has slain the TODO dragon!",
        "{agent} agent in {workspace} is done. Your move, human!",
    ],
}
INSTRUCTIONS = (
    "Speak as a booming, theatrical fantasy arcade dungeon announcer. "
    "Use a deep, gravelly voice, punchy diction, and exaggerated urgency. "
    "Keep it short and playful. Speak only the supplied text."
)
FIELDS = {"agent", "workspace", "name", "tab", "pane"}
MATCH_FIELDS = {"agent", "workspace", "name", "pane"}
CRUNCH_FILTER = ("volume=3,asoftclip=type=tanh:oversample=4,acrusher=bits=6:mix=0.25,"
                 "highpass=f=300,lowpass=f=3400,aresample=8000")


def config_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    directory = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    return Path(directory) / "config.toml" if directory else Path(__file__).with_name("config.example.toml")


def load_config(path):
    if not path.exists():
        return {}
    with path.open("rb") as file:
        return tomllib.load(file)


def state_path():
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or cache_home / "herdr-8-bit-announcer")


def number(table, key, default, low, high):
    value = table.get(key, default)
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"{key} must be a number between {low} and {high}")
    return value


def audio_settings(config):
    voice, effects = config.get("voice", {}), config.get("effects", {})
    if not isinstance(voice, dict) or not isinstance(effects, dict):
        raise ValueError("voice and effects must be TOML sections")
    backend = voice.get("backend", "local")
    if backend not in ("local", "kokoro", "openai"):
        raise ValueError("voice.backend must be 'local', 'kokoro', or 'openai'")
    settings = {
        "backend": backend,
        "voice": voice.get("name", ""),
        "rate": int(number(voice, "rate", 140, 80, 250)),
        "model": voice.get("model", "gpt-4o-mini-tts"),
        "instructions": voice.get("instructions", INSTRUCTIONS),
        "eight_bit_crunch": effects.get("eight_bit_crunch", True),
        "pitch": number(effects, "pitch", 1.0, 0.6, 1.3),
        "grit": number(effects, "grit", 0.0, 0, 1),
        "echo": number(effects, "echo", 0.0, 0, 0.4),
        "volume": number(effects, "volume", 0.7, 0, 1),
    }
    if type(settings["eight_bit_crunch"]) is not bool:
        raise ValueError("effects.eight_bit_crunch must be a boolean")
    for key, limit in (("voice", 80), ("model", 80), ("instructions", 2000)):
        if not isinstance(settings[key], str) or len(settings[key]) > limit:
            raise ValueError(f"voice {key} must be text of at most {limit} characters")
    return settings


def phrase(config, values, kind, template=None):
    rules = config.get("rules", [])
    if not isinstance(rules, list) or type(config.get("only_matched", False)) is not bool:
        raise ValueError("rules must be an array; only_matched must be a boolean")
    targets = dict(values, agent=kind)
    chosen = None
    for rule in rules:
        if not isinstance(rule, dict) or rule.keys() - (MATCH_FIELDS | {"preset", "templates", "mute"}):
            raise ValueError("unknown rule field; use agent, workspace, name, pane, preset, templates, or mute")
        if any(not isinstance(rule[key], str) for key in MATCH_FIELDS & rule.keys()):
            raise ValueError("rule match fields must be strings")
        if type(rule.get("mute", False)) is not bool:
            raise ValueError("rule mute must be a boolean")
        if all(targets[key] == rule[key] for key in MATCH_FIELDS & rule.keys()):
            chosen = rule
            break
    if (chosen is None and config.get("only_matched", False)) or (chosen and chosen.get("mute", False)):
        return None
    source = chosen if chosen and ("templates" in chosen or "preset" in chosen) else config
    if template is not None:
        templates = [template]
    elif "templates" in source:
        templates = source["templates"]
    else:
        preset = source.get("preset", "gauntlet")
        if not isinstance(preset, str) or preset not in PRESETS:
            raise ValueError(f"unknown preset: {preset!r}; choose gauntlet, victory, or snark")
        templates = PRESETS[preset]
    if not isinstance(templates, list) or not templates:
        raise ValueError("templates must be a nonempty array of strings")
    for item in templates:
        if not isinstance(item, str) or not item.strip() or len(item) > 500:
            raise ValueError("each template must contain 1–500 characters")
        for _, field, spec, conversion in string.Formatter().parse(item):
            if field is not None and (field not in FIELDS or spec or conversion):
                raise ValueError("templates only accept {agent}, {workspace}, {name}, {tab}, and {pane}")
    text = " ".join(random.choice(templates).format_map(values).split())
    if not text or len(text) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError("rendered phrase must be 1–500 characters without control characters")
    return text


def labels(context, agent=None):
    agent = agent or {}
    kind = agent.get("agent") or context.get("focused_pane_agent") or "pi"
    name = agent.get("name") or agent.get("display_agent") or kind[:1].upper() + kind[1:]
    return kind, {
        "agent": name,
        "name": name,
        "workspace": context.get("workspace_label") or agent.get("workspace_id") or "my project",
        "tab": context.get("tab_label") or agent.get("tab_id") or "main",
        "pane": agent.get("pane_id") or context.get("focused_pane_id") or "preview",
    }


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, timeout=90, **kwargs).stdout


def get_agent(pane_id):
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    response = json.loads(run([herdr, "agent", "get", pane_id]))
    if "error" in response:
        raise RuntimeError(response["error"].get("message", "Herdr agent lookup failed"))
    return response["result"]["agent"]


def completed_agent(event):
    data = event.get("data", {})
    if data.get("agent_status") not in ("idle", "done") or not data.get("pane_id"):
        return None
    # ponytail: live lookup can miss a completion followed immediately by a new task;
    # use event sequence IDs for exact replay if Herdr adds them to hook payloads.
    agent = get_agent(data["pane_id"])
    seq = agent.get("completion_seq")
    # 'done' is idle/unseen in Herdr. completion_seq distinguishes finished work
    # from startup idle and survives viewing the result; no Pi-specific hooks needed.
    if (agent.get("focused") or type(seq) is not int or seq <= 0
            or agent.get("agent_status") not in ("idle", "done")
            or seq != agent.get("state_change_seq")
            or agent.get("workspace_id") != data.get("workspace_id")
            or (data.get("agent") and data["agent"] != agent.get("agent"))):
        return None
    return agent


def synthesize(text, settings, path, config_file):
    if settings["backend"] == "kokoro":
        root = Path(__file__).resolve().parent
        assets = root / ".kokoro"
        python = assets / "venv" / "bin" / "python"
        if not all(file.is_file() for file in (python, assets / "kokoro-v1.0.onnx", assets / "voices-v1.0.bin")):
            raise RuntimeError("Kokoro is not installed; follow the Kokoro setup in README.md")
        run([str(python), str(root / "kokoro_speech.py"), str(path)], input=json.dumps({
            "text": text, "voice": settings["voice"] or "am_michael", "speed": settings["rate"] / 140,
        }).encode())
    elif settings["backend"] == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        key_file = config_file.parent / "openai-api-key"
        if not key and key_file.exists():
            key = key_file.read_text().strip()
        if not key:
            raise RuntimeError("set OPENAI_API_KEY in Herdr's server environment or create openai-api-key beside config.toml")
        request = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps({
                "model": settings["model"], "voice": settings["voice"] or "onyx",
                "input": text, "instructions": settings["instructions"],
                "speed": settings["rate"] / 175, "response_format": "wav",
            }).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    elif sys.platform == "darwin":
        argv = ["say", "-r", str(settings["rate"]), "-o", str(path)]
        if settings["voice"]:
            argv.extend(["-v", settings["voice"]])
        run([*argv, "--", text])
    else:
        executable = shutil.which("espeak-ng") or shutil.which("espeak")
        if not executable:
            raise RuntimeError("local speech needs espeak-ng; install it with your system package manager (or use voice.backend = 'openai')")
        run([executable, "-v", settings["voice"] or "en-us", "-s", str(settings["rate"]),
             "-w", str(path), "--stdin"], input=text.encode())


def quantize_wav(source, destination, bits=8, volume=1.0):
    """Peak-normalize PCM16, quantize without dither, then apply playback volume."""
    with wave.open(str(source), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth()) != (1, 2):
            raise ValueError("quantization requires mono 16-bit PCM")
        rate = audio.getframerate()
        data = audio.readframes(audio.getnframes())
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    peak = max((abs(value) for value in samples), default=0)
    gain = (128 * 10 ** (-1 / 20)) / peak if peak else 0
    step = 1 << (8 - bits)
    pcm = bytes(128 + round(round(value * gain / step) * step * volume) for value in samples)
    with wave.open(str(destination), "wb") as audio:
        audio.setparams((1, 1, rate, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)


def clip(text, settings, state, config_file):
    key = hashlib.sha256(json.dumps([2, text, settings], sort_keys=True).encode()).hexdigest()
    # ponytail: no cache eviction; cap by bytes if workspace/template churn makes it large.
    cache = state / "clips"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{key}.wav"
    if destination.exists() and destination.stat().st_size > 44:
        return destination
    if not shutil.which("ffmpeg"):
        raise RuntimeError("install ffmpeg to apply the retro announcer effects")
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        directory = Path(temporary)
        raw = directory / ("speech.aiff" if sys.platform == "darwin" and settings["backend"] == "local" else "speech.wav")
        synthesize(text, settings, raw, config_file)
        processed = directory / "clip.wav"
        filters = ["aresample=22050"]
        if settings["pitch"] != 1.0:
            filters.extend([f"asetrate=22050*{settings['pitch']}", "aresample=22050"])
        if settings["grit"]:
            filters.append(f"acrusher=bits=9:mix={settings['grit']}")
        if settings["echo"]:
            filters.append(f"aecho=0.8:0.7:70:{settings['echo']}")
        # Match sample 08's clean input level; playback volume belongs AFTER normalization.
        level = 0.7 if settings["eight_bit_crunch"] else settings["volume"]
        filters.extend(["alimiter=limit=0.95:level=false:latency=true", f"volume={level}"])
        run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
             "-af", ",".join(filters), "-ac", "1", "-c:a", "pcm_s16le", str(processed)])
        if settings["eight_bit_crunch"]:
            crunchy = directory / "crunch.wav"
            run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(processed),
                 "-af", CRUNCH_FILTER, "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(crunchy)])
            quantize_wav(crunchy, processed, volume=settings["volume"])
        processed.replace(destination)
    return destination


def play(path):
    if sys.platform == "darwin":
        argv = ["afplay", str(path)]
    elif shutil.which("paplay"):
        argv = ["paplay", str(path)]
    elif shutil.which("aplay"):
        argv = ["aplay", "-q", str(path)]
    elif shutil.which("ffplay"):
        argv = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(path)]
    else:
        raise RuntimeError("install paplay, aplay, or ffplay for audio playback")
    run(argv)


def announce(config, context, agent, state, config_file, args):
    kind, values = labels(context, agent)
    if args.agent:
        kind = args.agent
        values["agent"] = values["name"] = kind[:1].upper() + kind[1:]
    if args.workspace:
        values["workspace"] = args.workspace
    text = getattr(args, "say", None)
    if text is not None:
        if not text.strip() or len(text) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValueError("speech text must be 1–500 characters without control characters")
    else:
        text = phrase(config, values, kind, args.template)
    if text is None:
        return
    if args.text_only:
        print(text)
        return
    settings = audio_settings(config)
    state.mkdir(parents=True, exist_ok=True)
    # ponytail: one lock serializes synthesis and playback across sessions;
    # separate generation/playback locks if cold clips start delaying bursts.
    with (state / "audio.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = None
        if args.mode == "event" and agent is not None:
            socket = os.environ.get("HERDR_SOCKET_PATH", "")
            # Completion sequences are server-local; scope markers to the socket lifetime.
            epoch = Path(socket).stat().st_ctime_ns if socket else 0
            identity = [socket, epoch, agent["terminal_id"]]
            digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            marker = state / f"completion-{digest}"
            if marker.exists() and int(marker.read_text()) >= agent["completion_seq"]:
                return
        path = clip(text, settings, state, config_file)
        if args.output:
            shutil.copyfile(path, args.output.expanduser())
        if not args.no_play:
            play(path)
        if marker is not None:
            pending = marker.with_suffix(".tmp")
            pending.write_text(str(agent["completion_seq"]))
            pending.replace(marker)
        print(text)
        print(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["event", "preview"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--agent", help="agent kind for preview, e.g. pi")
    parser.add_argument("--workspace", help="workspace label for preview")
    parser.add_argument("--template", help="one custom phrase for preview")
    parser.add_argument("--say", help="speak literal text, bypassing phrase selection and mute rules")
    parser.add_argument("--text-only", action="store_true", help="print the phrase without generating audio")
    parser.add_argument("--no-play", action="store_true", help="generate a clip without playing it")
    parser.add_argument("--output", type=Path, help="also save the generated WAV at this path")
    args = parser.parse_args(argv)
    if args.mode == "event" and any((args.agent, args.workspace, args.template, args.say is not None, args.text_only, args.no_play, args.output)):
        parser.error("preview options cannot be used in event mode")
    if args.say is not None and args.template is not None:
        parser.error("--say cannot be combined with --template")
    context = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    agent = None
    if args.mode == "event":
        event = json.loads(os.environ.get("HERDR_PLUGIN_EVENT_JSON", "{}"))
        agent = completed_agent(event)
        if agent is None:
            return
    elif args.say is None and context.get("focused_pane_id") and context.get("focused_pane_agent"):
        agent = get_agent(context["focused_pane_id"])
    file = config_path(args.config)
    if args.config and not file.is_file():
        raise FileNotFoundError(f"config not found: {file}")
    config = load_config(file)
    announce(config, context, agent, state_path(), file, args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode(errors="replace").strip()
        print(f"herdr-8-bit-announcer: {error.cmd[0]} failed: {detail[:1000]}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"herdr-8-bit-announcer: {error}", file=sys.stderr)
        sys.exit(1)
