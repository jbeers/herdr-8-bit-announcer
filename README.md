# herdr-8-bit-announcer

8-bit-style speech when a Herdr agent finishes a task:

> “Pi agent in my project needs food badly!”

Gauntlet-inspired, not a clone of the original actor. Uses native completion
hooks: no polling loop, daemon, or agent extension. Choose system speech,
**offline Kokoro neural voices**, or **OpenAI speech**. Retro crunch is on by default.

## Quick start

Requires **Herdr 0.9.2+**, **Python 3.11+**, **FFmpeg**, and a speech engine.
The optional settings/text popups require **dialog**.

```sh
# Debian/Ubuntu
sudo apt install python3 espeak-ng ffmpeg pulseaudio-utils dialog
# Fedora
sudo dnf install python3 espeak-ng ffmpeg-free pulseaudio-utils dialog
# openSUSE (ensure python3 resolves to Python 3.11+)
sudo zypper install python311 espeak-ng ffmpeg dialog
# macOS (speech/playback are built in)
brew install python ffmpeg dialog
```

From a checkout:

```sh
git clone https://github.com/jbeers/herdr-8-bit-announcer.git
cd herdr-8-bit-announcer
herdr plugin link . --disabled
CONFIG_DIR="$(herdr plugin config-dir jbeers.herdr-8-bit-announcer)"
mkdir -p "$CONFIG_DIR"
# First install only: do not overwrite an existing config.
cp -n config.example.toml "$CONFIG_DIR/config.toml"
python3 doctor.py --config "$CONFIG_DIR/config.toml"
python3 announcer.py preview --config "$CONFIG_DIR/config.toml" --say "Your 8-bit announcer is ready!"
herdr plugin enable jbeers.herdr-8-bit-announcer
```

Once the GitHub repository is published, you can alternatively install with
`herdr plugin install jbeers/herdr-8-bit-announcer`, then use the Configure action
to save your settings. Herdr's actions run on the **server machine**, with its
environment and audio device—not necessarily the machine displaying a pane.

## Say something

Prompt for any text and hear it with the configured voice/effects:

```sh
herdr plugin action invoke jbeers.herdr-8-bit-announcer.say
```

Herdr 0.9.2 actions do not accept arbitrary text arguments. The action opens a
text-input popup instead. From a checkout, no Herdr session is needed:

```sh
python3 announcer.py preview --say "Say this"
# Use the installed plugin's settings:
python3 announcer.py preview --config "$(herdr plugin config-dir jbeers.herdr-8-bit-announcer)/config.toml" --say "Say this"
```

Text is literal (braces are not placeholders), limited to 500 characters, and
**bypasses mute/selection rules**. OpenAI tests send this text to OpenAI and can
incur charges. Canceling the popup does not generate audio.

## Doctor / troubleshooting

```sh
# Through Herdr; inspect action output in plugin logs:
herdr plugin action invoke jbeers.herdr-8-bit-announcer.doctor
herdr plugin log list --plugin jbeers.herdr-8-bit-announcer
# From a checkout, with readable output and a nonzero exit status on failure:
python3 doctor.py
python3 doctor.py --config "$(herdr plugin config-dir jbeers.herdr-8-bit-announcer)/config.toml"
```

For an agent helping with setup: run Doctor, fix each `FAIL`, review `WARN`
lines, then use **Say something** to verify actual sound. Doctor checks Python,
Herdr availability, config/rules, FFmpeg filters, the selected speech backend,
playback tools, dialog, and state-directory access. It **does not play audio,
make network requests, or print API keys**. Installed playback tools do not
prove an audio device works; credentials are not validated online.

If standalone speech works but hooks don't, check Herdr's **server PATH and
environment**, plugin enablement, and logs. An export inside a pane does not
change an already-running server's environment. Remote audio forwarding is
not included.

## Configure

```sh
herdr plugin action invoke jbeers.herdr-8-bit-announcer.configure
# Standalone terminal UI:
python3 configure.py
python3 configure.py --config /path/to/config.toml
```

Arrows/Enter select menus, Tab reaches buttons, Escape goes back. Settings are
**drafts until Save**; preview uses the draft and respects rules. The popup
provides phrase packs, custom phrases, ordered agent/workspace rules, voice
settings, crunch, effects, and volume.

Save validates all rules, writes atomically, retains unknown values, and keeps
the previous text as private `config.toml.bak`. Comments/formatting are regenerated.
External edits are not overwritten. Config is reread on the next completion;
no restart is required. Edit the installed plugin's config, not its source example.

Optional Herdr keybinding (then `herdr server reload-config`):

```toml
[[keys.command]]
key = "prefix+alt+a"
type = "plugin_action"
command = "jbeers.herdr-8-bit-announcer.configure"
description = "configure 8-bit announcer"
```

Disable/unlink with `herdr plugin disable jbeers.herdr-8-bit-announcer` and
`herdr plugin unlink jbeers.herdr-8-bit-announcer`. To avoid duplicate chimes,
optionally set `[ui.sound] enabled = false` in Herdr's config and reload it.
That also disables built-in attention sounds; this plugin announces completions only.

### Renaming an existing installation

The old plugin ID was `jbeers.herdr-audio`. Disable it before linking/installing
the new ID to avoid duplicate speech. Copy its `config.toml` (and, if used,
`openai-api-key`, with permission 600) to the new plugin config directory.
Update keybindings, then unlink/uninstall the old ID. No automatic migration is
performed. The standalone cache now lives at `~/.cache/herdr-8-bit-announcer`;
the old cache can be deleted. Keep `.kokoro/` beside the source if moving it.

## Phrases and rules

Built-in random packs: **gauntlet**, **victory**, **snark**. Set `preset` or a
`templates` array. Placeholders: `{agent}` / `{name}` (custom name, otherwise
“Pi”, “Claude”, etc.), `{workspace}` (workspace label), `{tab}`, and `{pane}`.
Use `{{` and `}}` for literal braces.

In `config.toml`, put global settings **before** `[voice]`/`[effects]` and
append rules at the end:

```toml
only_matched = true

[[rules]]
agent = "pi"
workspace = "my project"
templates = ["{agent} agent in {workspace} needs food badly!"]
```

Rules are exact, case-sensitive, and **first match wins**. All specified fields
must match. Use `name = "reviewer"`, `pane = "w7:p1"`, or `mute = true`.
Rules can override `preset` or `templates`; unmatched agents use global phrases
unless `only_matched = true`. See [config.example.toml](config.example.toml).

```sh
python3 announcer.py preview --agent pi --workspace "my project" --text-only
python3 announcer.py preview --say "Victory!" --output preview.wav --no-play
```

Standalone commands use `config.example.toml` unless `--config` or
`HERDR_PLUGIN_CONFIG_DIR` is supplied. Herdr's Preview action uses the focused
agent/workspace and respects rules.

## Voice and effects

Local speech uses eSpeak NG's `en-us` on Linux and the system voice on macOS.
Blank `voice.name` uses the backend default. Local `rate` is words/minute.

`effects.eight_bit_crunch = true` uses saturation, 6-bit crunch at 25% mix,
300–3,400 Hz band-limiting, and mono 8 kHz/8-bit PCM, based on
[sample 08](samples/08-sampled-medium.wav). It normalizes with about 1 dB
headroom before playback volume. Set it to `false` for clean speech.
`pitch`, `grit`, and `echo` are independent effects; defaults are natural pitch,
no extra grit/echo, and volume 0.7. Lower pitch also slows speech.

### Kokoro: offline neural speech

From the checkout, install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
uv venv .kokoro/venv --python 3.11
uv pip install --python .kokoro/venv/bin/python 'kokoro-onnx==0.6.1'
curl -fL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx \
  -o .kokoro/kokoro-v1.0.onnx.part && mv .kokoro/kokoro-v1.0.onnx.part .kokoro/kokoro-v1.0.onnx
curl -fL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin \
  -o .kokoro/voices-v1.0.bin.part && mv .kokoro/voices-v1.0.bin.part .kokoro/voices-v1.0.bin
```

Change the existing section in your plugin config:

```toml
[voice]
backend = "kokoro"
name = "am_michael"
rate = 140
```

Try `bm_george` (UK male) or `af_heart` (US female). English `af_`, `am_`,
`bf_`, and `bm_` voices are supported; pronunciation follows the voice region.
Rate 140 is natural speed. OpenAI model/direction settings do not affect Kokoro.

Downloads are approximately 337 MiB plus Python packages. The isolated CPU
runtime uses four inference threads: no PyTorch, CUDA, API key, or GPU.
After setup it stays offline, including pronunciation. Each uncached clip uses
a short-lived worker; repeat clips reuse cached WAVs. Model weights are
Apache-2.0; the runtime is MIT. Keep `.kokoro/` beside the plugin source.

### OpenAI

Change the existing section:

```toml
[voice]
backend = "openai"
name = "onyx"
model = "gpt-4o-mini-tts"
rate = 140
# instructions = "A booming fantasy announcer. Dramatic, urgent. Speak only the text."
```

Set `OPENAI_API_KEY` in **Herdr's server environment**, or create
`openai-api-key` beside its plugin `config.toml` with permission `600`.
Never commit the key. Rendered text, including agent/workspace names, goes to
OpenAI; cache misses incur charges. Cached clips require no additional API call.

## Behavior and development

- Completions use `completion_seq`, not just idle; startup idle is ignored.
  Announcements are suppressed while the completed agent is focused.
- Duplicate hooks do not replay delivered completions. Failed audio is logged
  without marking delivery; a later hook can retry. No automatic retry worker.
- Hooks resolve live state; a new task started before lookup can cause a stale
  completion to be skipped.
- One lock serializes synthesis/playback. Cold clips can delay queued speech.
- Cache: `HERDR_PLUGIN_STATE_DIR/clips`, or `$XDG_CACHE_HOME/herdr-8-bit-announcer/clips`
  (default `~/.cache/herdr-8-bit-announcer/clips`). No eviction; delete `clips` to reclaim space.

```sh
python3 -m unittest -v
```

Tests include completion/deduplication semantics, real FFmpeg processing,
backend requests, literal speech, diagnostics, and config saves/conflicts.
Optional installed Kokoro assets enable real synthesis tests; otherwise they skip.
