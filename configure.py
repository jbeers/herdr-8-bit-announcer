#!/usr/bin/env python3
"""Terminal settings popup for Dungeon Announcer (uses the system dialog tool)."""

import argparse
import contextlib
import copy
from datetime import date, time
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import tomllib

import announcer as audio

ROOT = Path(__file__).resolve().parent


def dialog(title, widget, *values, default=None, help_text="", cancel="Back"):
    # dialog's '--' escapes ONE argument, unlike getopt's end-of-options marker.
    def escaped(value):
        text = str(value)
        return ["--", text] if text.startswith("--") else [text]

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        argv = ["dialog", "--output-fd", str(output.fileno()), "--no-nl-expand", "--scrollbar",
                "--title", *escaped(title), "--cancel-label", cancel]
        if default is not None:
            argv.extend(["--default-item", *escaped(default)])
        if help_text:
            argv.extend(["--hline", *escaped(help_text)])
        if widget == "--yesno":
            argv.append("--defaultno")
        argv.append(widget)
        for value in values:
            argv.extend(escaped(value))
        result = subprocess.run(argv, pass_fds=(output.fileno(),))
        if result.returncode in (1, 255):
            return None
        if result.returncode != 0:
            raise RuntimeError(f"dialog failed (exit {result.returncode})")
        output.seek(0)
        return output.read().removesuffix("\n")


def menu(title, text, items, default=None, cancel="Back"):
    return dialog(title, "--menu", text, 0, 0, 0,
                  *(value for pair in items for value in pair), default=default, cancel=cancel)


def message(text):
    dialog("Dungeon Announcer", "--msgbox", text, 0, 0)


def form(title, text, fields):
    args = []
    for row, (label, value, limit) in enumerate(fields, 1):
        args.extend([label, row, 1, str(value).replace("\n", " "), row, 20, 32, limit])
    result = dialog(title, "--form", text, 0, 0, 0, *args,
                    help_text="Up/Down: fields   Tab: buttons   Esc: cancel")
    if result is None:
        return None
    values = result.split("\n")
    if len(values) != len(fields):
        raise ValueError("dialog returned an incomplete form")
    return [value.strip() for value in values]


def choose_pack(target, inherit=False):
    items = [("gauntlet", "Food badly, bug hordes, and dungeon quests"),
             ("victory", "Victory, loot, and cleared dungeons"),
             ("snark", "Coffee badly, TODO dragons, and your move, human")]
    if inherit:
        items.insert(0, ("inherit", "Use the global phrases"))
    choice = menu("Phrase pack", "Choosing a pack replaces custom phrases.", items,
                  default=target.get("preset", "inherit" if inherit else "gauntlet"))
    if choice is not None:
        target.pop("templates", None)
        if choice == "inherit":
            target.pop("preset", None)
        else:
            target["preset"] = choice


def edit_phrases(target, fallback):
    templates = target.get("templates", audio.PRESETS.get(target.get("preset"), fallback))
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / "phrases.txt"
        file.write_text("\n".join(templates) + "\n", encoding="utf-8")
        result = dialog("Custom phrases — one per line", "--editbox", file, -1, -1,
                        help_text="{agent} {workspace} {name} {tab} {pane}; empty restores pack; Tab: buttons")
    if result is not None:
        templates = [line.strip() for line in result.splitlines() if line.strip()]
        if templates:
            target["templates"] = templates
        else:
            target.pop("templates", None)


def edit_rule(rule):
    keys = ("agent", "workspace", "name", "pane")
    fields = [("Agent kind" if key == "agent" else key.capitalize(), rule.get(key, ""), 80) for key in keys]
    fields.append(("Mute true/false", str(rule.get("mute", False)).lower(), 5))
    values = form("Rule target", "Agent kind: pi, claude, codex, etc. Empty fields match anything.\n"
                  "Exact, case-sensitive matches. The FIRST matching rule wins.", fields)
    if values is None:
        return False
    if values[-1] not in ("true", "false"):
        raise ValueError("Mute must be true or false")
    for key, value in zip(keys, values):
        if value:
            rule[key] = value
        else:
            rule.pop(key, None)
    rule["mute"] = values[-1] == "true"
    return True


def edit_rules(config):
    rules = config.get("rules", [])
    items = []
    for index, rule in enumerate(rules, 1):
        label = ", ".join(f"{key}={rule[key]}" for key in ("agent", "workspace", "name", "pane") if key in rule) or "Any agent / workspace"
        items.append((str(index), label + (" [muted]" if rule.get("mute", False) else "")))
    choice = menu("Agent/workspace rules", "Order matters: the first match wins.", [*items, ("add", "Add a rule")])
    if choice is None:
        return
    if choice == "add":
        rule = {}
        if edit_rule(rule):
            rules.append(rule)
            config["rules"] = rules
        return
    index = int(choice) - 1
    rule = rules[index]
    action = menu("Rule settings", items[index][1], [
        ("target", "Agent / workspace / name / pane / mute"),
        ("pack", "Phrase pack (or inherit global)"), ("phrases", "Custom phrases"),
        ("up", "Move earlier"), ("down", "Move later"), ("delete", "Delete rule"),
    ])
    if action == "target":
        edit_rule(rule)
    elif action == "pack":
        choose_pack(rule, inherit=True)
    elif action == "phrases":
        edit_phrases(rule, config.get("templates", audio.PRESETS.get(config.get("preset"), audio.PRESETS["gauntlet"])))
    elif action in ("up", "down"):
        destination = max(0, min(len(rules) - 1, index + (-1 if action == "up" else 1)))
        rules.insert(destination, rules.pop(index))
    elif action == "delete" and dialog("Delete rule?", "--yesno", items[index][1], 0, 0) is not None:
        rules.pop(index)


def edit_voice(config):
    settings = audio.audio_settings(config)
    fields = [("Backend", settings["backend"], 10), ("Voice name", settings["voice"], 80),
              ("Rate (80–250)", settings["rate"], 3), ("AI model", settings["model"], 80),
              ("AI direction", settings["instructions"], 2000)]
    values = form("Voice", "Backend: local, kokoro, or openai. Blank voice uses the default.\n"
                  "Kokoro: am_michael (US), bm_george (UK), af_heart (US female).\n"
                  "Kokoro rate 140 = natural speed. Requires setup in README.md.\n"
                  "AI model/direction apply only to OpenAI (sends text; charges apply).\n"
                  "API key: server environment or openai-api-key beside config.toml.", fields)
    if values is not None:
        backend, name, rate, model, instructions = values
        config.setdefault("voice", {}).update(backend=backend, name=name, rate=int(rate), model=model, instructions=instructions)


def edit_effects(config):
    settings = audio.audio_settings(config)
    keys = ("pitch", "grit", "echo", "volume")
    fields = [("Pitch (0.6–1.3)", settings["pitch"], 12), ("Grit (0–1)", settings["grit"], 12),
              ("Echo (0–0.4)", settings["echo"], 12), ("Volume (0–1)", settings["volume"], 12)]
    values = form("Retro effects", "Lower pitch deepens/slows the voice. Zero grit/echo disables that effect.", fields)
    if values is not None:
        config.setdefault("effects", {}).update(zip(keys, map(float, values)))


def validate(config):
    audio.audio_settings(config)
    kind, values = audio.labels({})
    audio.phrase(config, values, kind)  # Validate global selection flags and rule structure.
    audio.phrase(dict(config, rules=[], only_matched=False), values, kind)
    # Check every rule, including muted/unreachable rules, before saving a draft.
    for rule in config.get("rules", []):
        if not isinstance(rule, dict):
            raise ValueError("Each rule must be a TOML table")
        targets = dict(values, **{key: rule[key] for key in audio.MATCH_FIELDS if key in rule})
        single = dict(config, rules=[rule], only_matched=False)
        audio.phrase(single, targets, rule.get("agent", kind))
        audio.phrase(dict(single, rules=[dict(rule, mute=False)]), targets, rule.get("agent", kind))


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_value(key)} = {toml_value(item)}" for key, item in value.items()) + " }"
    raise ValueError(f"unsupported TOML value: {type(value).__name__}")


def document(config):
    # ponytail: this small TOML writer preserves values, not comments; .bak keeps prior text.
    # Use tomlkit if comment-preserving edits are needed.
    def assignments(table):
        return [f"{toml_value(key)} = {toml_value(value)}" for key, value in table.items()]

    root = {key: value for key, value in config.items() if key not in ("voice", "effects", "rules")}
    if "rules" in config and not config["rules"]:
        root["rules"] = []
    lines = ["# Saved by Dungeon Announcer settings.", *assignments(root)]
    for section in ("voice", "effects"):
        if section in config:
            lines.extend(["", f"[{section}]", *assignments(config[section])])
    for rule in config.get("rules", []):
        lines.extend(["", "[[rules]]", *assignments(rule)])
    text = "\n".join(lines) + "\n"
    tomllib.loads(text)  # Never replace a working file with malformed generated TOML.
    return text.encode("utf-8")


def atomic_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)  # Private 0600 file, including backups.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_config(path, config, original):
    validate(config)
    data = document(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise RuntimeError("Config changed outside this popup. Reopen settings to avoid overwriting those edits.")
        if current is not None:
            atomic_write(path.with_suffix(".toml.bak"), current)
        atomic_write(path, data)


def preview(config, path):
    context = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "{}"))
    agent = audio.get_agent(context["focused_pane_id"]) if context.get("focused_pane_id") and context.get("focused_pane_agent") else None
    args = SimpleNamespace(mode="preview", agent=None, workspace=None, template=None,
                           text_only=False, no_play=False, output=None)
    output = io.StringIO()
    dialog("Preview", "--infobox", "Generating/playing with draft settings…", 0, 0)
    with contextlib.redirect_stdout(output):
        audio.announce(config, context, agent, audio.state_path(), path, args)
    message(output.getvalue().splitlines()[0] if output.getvalue() else "This target is muted or not selected by your rules.")


def settings(path):
    original = path.read_bytes() if path.exists() else None
    config = tomllib.loads(original.decode("utf-8")) if original is not None else audio.load_config(ROOT / "config.example.toml")
    validate(config)
    initial = copy.deepcopy(config)
    while True:
        pack = "custom" if "templates" in config else config.get("preset", "gauntlet")
        choice = menu("Dungeon Announcer settings", f"{path}\nChanges are drafts until Save. Arrows/Enter: select; Esc: close.", [
            ("1", f"Phrase pack: {pack}"), ("2", "Custom phrases"),
            ("3", f"Agent/workspace rules ({len(config.get('rules', []))})"),
            ("4", f"Only matching rules: {'on' if config.get('only_matched', False) else 'off'}"),
            ("5", "Voice / speech backend"),
            ("c", f"8-bit crunch: {'on' if audio.audio_settings(config)['eight_bit_crunch'] else 'off'} (medium)"),
            ("6", "Retro effects / volume"),
            ("7", "Preview focused agent/workspace (uses draft settings)"),
            ("8", "Save and close"), ("9", "Discard and close"),
        ], cancel="Close")
        try:
            if choice in (None, "9"):
                if config == initial or dialog("Discard changes?", "--yesno", "Unsaved settings will be discarded.", 0, 0) is not None:
                    return
                continue
            if choice == "8":
                if config != initial or original is None:
                    save_config(path, config, original)
                return
            if choice == "7":
                preview(config, path)
                continue
            candidate = copy.deepcopy(config)
            if choice == "1":
                choose_pack(candidate)
            elif choice == "2":
                edit_phrases(candidate, audio.PRESETS.get(candidate.get("preset"), audio.PRESETS["gauntlet"]))
            elif choice == "3":
                edit_rules(candidate)
            elif choice == "4":
                candidate["only_matched"] = not candidate.get("only_matched", False)
            elif choice == "5":
                edit_voice(candidate)
            elif choice == "c":
                candidate.setdefault("effects", {})["eight_bit_crunch"] = not audio.audio_settings(candidate)["eight_bit_crunch"]
            elif choice == "6":
                edit_effects(candidate)
            validate(candidate)
            config = candidate
        except subprocess.CalledProcessError as error:
            message((error.stderr or b"").decode(errors="replace")[:1000] or str(error))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            message(str(error))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="open this plugin's Herdr settings popup")
    parser.add_argument("--config", type=Path, help="edit an explicit config file in a standalone terminal")
    args = parser.parse_args(argv)
    if args.open:
        if args.config:
            parser.error("--config cannot be combined with --open")
        herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
        audio.run([herdr, "plugin", "pane", "open", "--plugin", "jbeers.herdr-audio", "--entrypoint", "settings"])
        return
    if not sys.stdin.isatty():
        raise RuntimeError("Settings need an interactive terminal; use the Herdr configure action or a terminal.")
    if not shutil.which("dialog"):
        raise RuntimeError("Install dialog for the settings UI (zypper/apt/dnf install dialog; macOS: brew install dialog).")
    if args.config:
        path = args.config.expanduser().resolve()
    else:
        directory = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
        if not directory:
            directory = audio.run([os.environ.get("HERDR_BIN_PATH", "herdr"), "plugin", "config-dir", "jbeers.herdr-audio"]).decode().strip()
        path = (Path(directory) / "config.toml").resolve()
    settings(path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"herdr-audio settings: {error}", file=sys.stderr)
        if sys.stdin.isatty():
            input("Press Enter to close.")
        sys.exit(1)
