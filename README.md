# Dungeon Announcer for Herdr

A Gauntlet-inspired voice announces which agent finished in which workspace:

> “Pi agent in my project needs food badly!”

Uses Herdr's native completion events: no Pi extension, polling loop, or daemon.
Choose lightweight system speech, **Kokoro's offline neural voices**, or OpenAI
speech for a theatrical narrator. **8-bit crunch defaults to on**, using the
medium sampled-dialogue sound; switch it off for clean speech. None is a clone
of the original actor.

## Install

Requires **Herdr 0.9.2+**, **Python 3.11+**, **FFmpeg**, and a speech engine.
The settings UI also uses the system **dialog** utility (no Python UI packages):

```sh
# openSUSE
sudo zypper install python311 espeak-ng ffmpeg dialog
# Debian/Ubuntu
sudo apt install python3 espeak-ng ffmpeg pulseaudio-utils dialog
# Fedora
sudo dnf install python3 espeak-ng ffmpeg-free pulseaudio-utils dialog
# macOS: built-in say/afplay; add Python and FFmpeg
brew install python ffmpeg dialog
```

Linux playback uses the first installed tool among `paplay`, `aplay`, and
`ffplay`. Check that `python3 --version` is at least 3.11; on distributions with
multiple Python versions, use a compatible `python3` on Herdr's PATH.

From this checkout:

```sh
herdr plugin link . --disabled
CONFIG_DIR="$(herdr plugin config-dir jbeers.herdr-audio)"
cp config.example.toml "$CONFIG_DIR/config.toml"
# Edit config.toml (or run python3 configure.py), then:
herdr plugin enable jbeers.herdr-audio
herdr plugin action invoke jbeers.herdr-audio.preview
```

Config is reread each time. Edit the copy in the plugin config directory, not
inside an installed plugin's source checkout. Disable with
`herdr plugin disable jbeers.herdr-audio`; unlink with
`herdr plugin unlink jbeers.herdr-audio`.

To avoid also hearing Herdr's built-in completion chime, optionally set
`[ui.sound] enabled = false` in your Herdr `config.toml`, then run
`herdr server reload-config`. This also disables Herdr's built-in attention
sounds; this plugin only announces completions.

## Settings popup

```sh
herdr plugin action invoke jbeers.herdr-audio.configure
# Or open the declared popup directly:
herdr plugin pane open --plugin jbeers.herdr-audio --entrypoint settings
```

Use arrows/Enter to select menus, Up/Down to move between form fields, and Tab
to reach buttons. Escape goes back; closing with unsaved changes asks before
discarding. The popup provides phrase packs, custom phrases (one per line),
agent/workspace/name/pane rules with mute and ordering, speech settings, an
**8-bit crunch** on/off toggle, retro effects, and a preview using the **draft**
settings and underlying agent/workspace.
Previews respect selection rules; OpenAI previews can incur API charges.

**Save and close** validates every rule and writes `config.toml` atomically.
Unknown settings are retained; formatting/comments are regenerated. The prior
file is kept as `config.toml.bak`, with private permissions. External edits made
while the popup is open are not overwritten: reopen it to pick up those changes.
Changes apply to the next completion without a server restart.

Standalone terminal UI (also works before the plugin is enabled):

```sh
python3 configure.py
python3 configure.py --config /path/to/config.toml
```

Optional binding in Herdr's own `config.toml`, followed by
`herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+alt+a"
type = "plugin_action"
command = "jbeers.herdr-audio.configure"
description = "configure dungeon announcer"
```

## Phrases and specific agents

Built-in random phrase packs: **gauntlet**, **victory**, **snark**. Set `preset`
or supply a `templates` array. Available placeholders:

- `{agent}` / `{name}`: custom agent name if present, otherwise “Pi”, “Claude”, etc.
- `{workspace}`: Herdr workspace label, not its directory name.
- `{tab}`, `{pane}`: tab label and pane ID.

To announce only Pi in “my project”, put this in `config.toml` **before** the
`[voice]` and `[effects]` sections, and place the rule at the end:

```toml
only_matched = true

[[rules]]
agent = "pi"
workspace = "my project"
templates = [
  "{agent} agent in {workspace} needs food badly!",
  "{agent} agent in {workspace} has slain the TODO dragon!",
]
```

Rules match exactly and are case-sensitive; all specified fields must match.
The first matching rule wins. Match `name = "reviewer"` for a named agent or
`pane = "w7:p1"` for a particular instance. Set `mute = true` to silence a match.
A rule can override `preset` or `templates`; other agents use the global phrases
unless `only_matched = true`. See [`config.example.toml`](config.example.toml).

## Preview or save a clip

No Herdr session is needed for standalone previews:

```sh
python3 announcer.py preview --agent pi --workspace "my project" \
  --template '{agent} agent in {workspace} needs food badly!' --text-only

python3 announcer.py preview --agent pi --workspace "my project" \
  --template '{agent} agent in {workspace} needs food badly!' \
  --output preview.wav --no-play

python3 announcer.py preview --config /path/to/config.toml
```

Herdr's preview action uses the focused agent/workspace. Standalone preview uses
`config.example.toml` unless `--config` or `HERDR_PLUGIN_CONFIG_DIR` is supplied;
run outside a Herdr plugin invocation and it defaults to Pi / “my project”.
Previews respect selection/mute rules, just like completions.

## Voice tuning / AI speech

`[voice] rate` controls delivery. **8-bit crunch** defaults to on and uses the
approved `samples/08-sampled-medium.wav` processing: mild tanh saturation,
6-bit crunch at 25% mix, roughly 300–3,400 Hz, and mono 8 kHz/8-bit PCM.
It peak-normalizes with about 1 dB of headroom, then applies playback volume.
No echo, reverb, or background noise is added by this preset.

Toggle **8-bit crunch** in the popup, or change the existing effects section:

```toml
[effects]
eight_bit_crunch = false # true is the default, including when omitted
```

Off restores full-bandwidth speech. `[effects] pitch`, `grit`, and `echo` are
additional independent effects; defaults retain natural pitch (`1.0`) and disable
extra grit/echo (`0.0`). Volume controls playback in both modes. Switching crunch
on/off generates distinct cached clips, so old clean audio is not reused as crunch.
Local defaults are eSpeak NG's `en-us` voice on Linux and the system voice on
macOS; change `voice.name` to an installed voice if desired. For smoother speech
without sending text to a service, use Kokoro.

### Kokoro (local neural speech)

From this checkout, install [uv](https://docs.astral.sh/uv/getting-started/installation/)
if needed, then run:

```sh
uv venv .kokoro/venv --python 3.11
uv pip install --python .kokoro/venv/bin/python 'kokoro-onnx==0.6.1'
curl -fL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx \
  -o .kokoro/kokoro-v1.0.onnx.part && mv .kokoro/kokoro-v1.0.onnx.part .kokoro/kokoro-v1.0.onnx
curl -fL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin \
  -o .kokoro/voices-v1.0.bin.part && mv .kokoro/voices-v1.0.bin.part .kokoro/voices-v1.0.bin
```

Change the existing `[voice]` section in your plugin config (or the popup):

```toml
[voice]
backend = "kokoro"
name = "am_michael"
rate = 140
```

`am_michael` is an American male voice; try `bm_george` for British male or
`af_heart` for American female. Blank uses `am_michael`. This integration
supports English voices (`af_`, `am_`, `bf_`, `bm_`) and selects US/UK
pronunciation automatically. Rate 140 is natural speed; smaller/larger values
slow/speed delivery. OpenAI model/direction fields do not affect Kokoro.

The isolated CPU runtime uses four inference threads: no PyTorch, CUDA, API key,
or GPU needed. Downloads are approximately 337 MiB plus Python packages, with
Apache-2.0 model weights and an MIT runtime. After setup, synthesis stays offline
(including pronunciation; eSpeak is used internally, not as the audible voice).
A new clip loads the model in a short-lived worker; repeat clips use the existing
WAV cache. Keep `.kokoro/` beside the plugin source when moving/installing it.

### OpenAI

For OpenAI, change the existing `[voice]` section:

```toml
[voice]
backend = "openai"
name = "onyx"
model = "gpt-4o-mini-tts"
rate = 140
# Optional: override the default deep, theatrical fantasy-announcer direction.
# instructions = "A booming dungeon master. Dramatic, gravelly, urgent. Speak only the text."
```

Supply `OPENAI_API_KEY` in **the Herdr server's environment**, or save the key in
`openai-api-key` beside the plugin's `config.toml` (permission `600`). Exporting
a key inside a pane does not change an already-running server's environment.
Never commit a key. The AI backend sends the rendered phrase (including agent
and workspace names) to OpenAI and incurs API charges on cache misses. Cached
clips work without another API call.

## Behavior and checks

- Announces completions in both focused and background workspaces.
- Uses Herdr's `completion_seq`, not just “idle”; startup idle isn't a completion.
- Suppresses duplicate notifications for the same completed task, including when
  its result is viewed. Failed synthesis/playback is logged, not marked delivered;
  a later hook can retry (there is no automatic retry worker).
- WAVs are cached by phrase, voice, and effects under `HERDR_PLUGIN_STATE_DIR/clips`.
  Standalone runs use `~/.cache/herdr-audio` (or `$XDG_CACHE_HOME/herdr-audio`).
- One file lock prevents clips overlapping. A cold clip must finish generating
  before queued announcements play. The cache has no eviction; remove its
  `clips` directory to reclaim space.
- Runs on the Herdr **server's machine**, using that machine's audio device.
  Remote-server audio forwarding is not included.
- Hooks resolve the live agent state. A new task started before a completion
  hook runs can make that announcement stale, so it is skipped.

```sh
python3 -m unittest -v
herdr plugin log list --plugin jbeers.herdr-audio
```

The checks cover agent selection, completion semantics, deduplication/retry,
Kokoro subprocess inputs/setup errors, OpenAI requests without network calls,
real FFmpeg WAV processing, crunch toggling/cache separation/volume/silence,
settings drafts/cancellation, previews, TOML
roundtrips, backups, and save conflicts. With Kokoro installed, they also generate
a real British-voice WAV and verify invalid voices fail; otherwise that check skips.
