"""Run with: python3 -m unittest -v"""

import contextlib
from datetime import date, datetime, time, timezone
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
from types import SimpleNamespace
import tomllib
import unittest
from unittest.mock import patch
import wave

import announcer as audio
import configure as ui

CONTEXT = {"workspace_label": "my project", "focused_pane_agent": "pi", "focused_pane_id": "w1:p1"}
AGENT = {
    "agent": "pi", "agent_status": "idle", "pane_id": "w1:p1", "workspace_id": "w1",
    "terminal_id": "term_1", "state_change_seq": 10, "completion_seq": 10,
}
EVENT = {"event": "pane_agent_status_changed", "data": {
    "type": "pane_agent_status_changed", "pane_id": "w1:p1", "workspace_id": "w1",
    "agent": "pi", "agent_status": "idle",
}}


class AnnouncerCheck(unittest.TestCase):
    def test_completion_is_not_startup_idle_or_stale_state(self):
        def lookup(agent):
            response = {"result": {"agent": agent}}
            with patch.object(audio, "run", return_value=json.dumps(response).encode()) as command:
                result = audio.completed_agent(EVENT)
                self.assertEqual(command.call_args.args[0][-3:], ["agent", "get", "w1:p1"])
                return result

        self.assertEqual(lookup(AGENT), AGENT)
        self.assertEqual(lookup(dict(AGENT, focused=True)), dict(AGENT, focused=True))
        self.assertIsNone(lookup(dict(AGENT, completion_seq=None)))
        self.assertIsNone(lookup(dict(AGENT, state_change_seq=11)))
        self.assertIsNone(lookup(dict(AGENT, agent_status="working")))
        self.assertIsNone(lookup(dict(AGENT, agent="claude")))
        with patch.object(audio, "run") as command:
            self.assertIsNone(audio.completed_agent({"data": {"agent_status": "working"}}))
            command.assert_not_called()

    def test_specific_agent_rules_and_custom_templates(self):
        kind, values = audio.labels(CONTEXT, AGENT)
        config = {"only_matched": True, "rules": [{
            "agent": "pi", "workspace": "my project",
            "templates": ["{agent} agent in {workspace} needs food badly!"],
        }]}
        self.assertEqual(audio.phrase(config, values, kind), "Pi agent in my project needs food badly!")
        self.assertIsNone(audio.phrase(config, values, "claude"))
        self.assertIsNone(audio.phrase({"rules": [{"mute": True}]}, values, kind))
        self.assertIn(audio.phrase({"templates": ["global"], "rules": [{"preset": "snark"}]}, values, kind),
                      [text.format_map(values) for text in audio.PRESETS["snark"]])
        _, renamed = audio.labels(CONTEXT, dict(AGENT, name="reviewer"))
        self.assertEqual(renamed["agent"], "reviewer")
        self.assertEqual(audio.phrase({}, values, kind, "{{loot}} for {agent}"), "{loot} for Pi")
        for bad in ("{agent.__class__}", "{workspace[0]}", "{unknown}", "{agent!r}", "{agent:>10}", "{", "\x00"):
            with self.subTest(template=bad), self.assertRaises(ValueError):
                audio.phrase({"templates": [bad]}, values, kind)
        for bad in ({"rules": [{"typo": "pi"}]}, {"templates": []}, {"only_matched": "false"}):
            with self.assertRaises(ValueError):
                audio.phrase(bad, values, kind)
        for bad in (float("nan"), float("inf"), -1, "0.9", True):
            with self.assertRaises(ValueError):
                audio.audio_settings({"effects": {"pitch": bad}})

    @unittest.skipUnless(shutil.which("ffmpeg"), "audio processing check needs ffmpeg")
    def test_generate_process_and_cache_a_real_wav(self):
        def speech(text, settings, path, config_file):
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                wav.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(i * 2 * math.pi * 220 / 22050)))
                                         for i in range(11025)))

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            self.assertTrue(audio.audio_settings({})["eight_bit_crunch"])
            settings = audio.audio_settings({"effects": {"eight_bit_crunch": False}})
            self.assertEqual((settings["pitch"], settings["grit"], settings["echo"]), (1.0, 0.0, 0.0))
            text = "Pi agent in a '; $(touch /tmp/not-executed)' workspace needs food badly!"
            old_key = audio.hashlib.sha256(json.dumps([1, text, settings], sort_keys=True).encode()).hexdigest()
            old_clip = state / "clips" / f"{old_key}.wav"
            old_clip.parent.mkdir()
            old_clip.write_bytes(b"obsolete rough audio" * 4)
            with patch.object(audio, "synthesize", side_effect=speech) as synthesis, \
                    patch.object(audio, "run", wraps=audio.run) as processing:
                path = audio.clip(text, settings, state, state / "config.toml")
                self.assertEqual(audio.clip(text, settings, state, state / "config.toml"), path)
                synthesis.assert_called_once()
                self.assertEqual(synthesis.call_args.args[0], text)
                self.assertNotEqual(path, old_clip)
                argv = processing.call_args.args[0]
                filters = argv[argv.index("-af") + 1]
                for effect in ("acrusher", "aecho", "asetrate", "highpass", "lowpass"):
                    self.assertNotIn(effect, filters)
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertEqual(wav.getframerate(), 22050)
                    self.assertEqual(wav.getnframes(), 11025)
                crunchy = dict(settings, eight_bit_crunch=True)
                crunch_path = audio.clip(text, crunchy, state, state / "config.toml")
                self.assertNotEqual(crunch_path, path)
                self.assertEqual(audio.clip(text, crunchy, state, state / "config.toml"), crunch_path)
                self.assertEqual(synthesis.call_count, 2)
                argv = processing.call_args.args[0]
                self.assertEqual(argv[argv.index("-af") + 1], audio.CRUNCH_FILTER)
                with wave.open(str(crunch_path), "rb") as wav:
                    self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 1, 8000))
                    self.assertEqual(wav.getnframes(), 4000)
                    pcm = wav.readframes(wav.getnframes())
                    self.assertTrue(any(value != 128 for value in pcm))
                    self.assertLessEqual(max(abs(value - 128) for value in pcm), 81)
                retro = dict(settings, pitch=0.9, grit=0.12, echo=0.12)
                self.assertNotEqual(audio.clip(text, retro, state, state / "config.toml"), path)
                argv = processing.call_args.args[0]
                filters = argv[argv.index("-af") + 1]
                for effect in ("acrusher", "aecho", "asetrate"):
                    self.assertIn(effect, filters)

    @unittest.skipUnless(shutil.which("ffmpeg") and Path("preview.wav").is_file()
                         and Path("samples/08-sampled-medium.wav").is_file(), "sample comparison needs local WAVs")
    def test_crunch_matches_approved_medium_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, output = Path(directory) / "raw.wav", Path(directory) / "out.wav"
            audio.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "preview.wav",
                       "-af", audio.CRUNCH_FILTER, "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(raw)])
            audio.quantize_wav(raw, output)
            with wave.open(str(output), "rb") as wav, wave.open("samples/08-sampled-medium.wav", "rb") as approved:
                self.assertEqual(wav.getparams(), approved.getparams())
                self.assertEqual(wav.readframes(wav.getnframes()), approved.readframes(approved.getnframes()))

    def test_crunch_validation_quantization_and_silence(self):
        for bad in ("true", 1, None, []):
            with self.assertRaises(ValueError):
                audio.audio_settings({"effects": {"eight_bit_crunch": bad}})
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "in.wav", Path(directory) / "out.wav"
            for values in ([0, 0, 0], [-32768, -1000, 0, 1000, 32767]):
                with wave.open(str(source), "wb") as wav:
                    wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                    wav.writeframes(struct.pack(f"<{len(values)}h", *values))
                for volume in (0, 0.5, 1):
                    audio.quantize_wav(source, output, volume=volume)
                    with wave.open(str(output), "rb") as wav:
                        self.assertEqual((wav.getsampwidth(), wav.getframerate()), (1, 8000))
                        pcm = wav.readframes(wav.getnframes())
                        self.assertEqual(len(pcm), len(values))
                        self.assertLessEqual(max(abs(value - 128) for value in pcm), 115 * volume + 1)
                        if not volume or not any(values):
                            self.assertEqual(pcm, bytes([128] * len(values)))

    def test_duplicate_hooks_do_not_replay_and_failed_playback_can_retry(self):
        args = SimpleNamespace(mode="event", agent=None, workspace=None, template="{agent} agent in {workspace} needs food badly!",
                               text_only=False, output=None, no_play=False)
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            state = Path(directory)
            socket = state / "socket"
            socket.write_text("first server")
            with patch.dict(os.environ, {"HERDR_SOCKET_PATH": str(socket)}), \
                    patch.object(audio, "clip", return_value=state / "clip.wav") as generation, \
                    patch.object(audio, "play") as playback:
                audio.announce({}, CONTEXT, AGENT, state, state / "config.toml", args)
                audio.announce({}, CONTEXT, AGENT, state, state / "config.toml", args)
                generation.assert_called_once()
                playback.assert_called_once()
                next_task = dict(AGENT, completion_seq=11, state_change_seq=11)
                playback.side_effect = RuntimeError("no audio device")
                with self.assertRaises(RuntimeError):
                    audio.announce({}, CONTEXT, next_task, state, state / "config.toml", args)
                playback.side_effect = None
                audio.announce({}, CONTEXT, next_task, state, state / "config.toml", args)
                self.assertEqual(playback.call_count, 3)
                self.assertEqual(next(state.glob("completion-*")).read_text(), "11")
                socket.write_text("new server; completion counter reset")
                audio.announce({}, CONTEXT, dict(AGENT, completion_seq=1, state_change_seq=1), state, state / "config.toml", args)
                self.assertEqual(playback.call_count, 4)

    def test_herdr_preview_uses_the_named_agent_and_does_not_consume_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            config = state / "config.toml"
            config.write_text('only_matched = true\n[[rules]]\nname = "reviewer"\n'
                              'templates = ["{agent} in {workspace} needs coffee!"]\n')
            agent = dict(AGENT, name="reviewer")
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONTEXT_JSON": json.dumps(CONTEXT),
                                         "HERDR_PLUGIN_STATE_DIR": str(state)}), \
                    patch.object(audio, "get_agent", return_value=agent), \
                    patch.object(audio, "clip", return_value=state / "clip.wav"), \
                    patch.object(audio, "play") as playback, contextlib.redirect_stdout(io.StringIO()) as output:
                audio.main(["preview", "--config", str(config)])
                self.assertIn("reviewer in my project needs coffee!", output.getvalue())
                playback.assert_called_once()
                self.assertFalse(list(state.glob("completion-*")))

    def test_speech_inputs_without_network_or_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            text = "Pi in a '; $(echo nope)' workspace!"
            settings = audio.audio_settings({})
            with patch.object(audio.sys, "platform", "linux"), \
                    patch.object(audio.shutil, "which", return_value="espeak-ng"), \
                    patch.object(audio, "run") as command:
                audio.synthesize(text, settings, state / "speech.wav", state / "config.toml")
                self.assertEqual(command.call_args.kwargs["input"], text.encode())
                self.assertIn("--stdin", command.call_args.args[0])
                self.assertNotIn("-p", command.call_args.args[0])  # Use the voice's natural pitch.
            with patch.object(audio.sys, "platform", "darwin"), patch.object(audio, "run") as command:
                audio.synthesize(text, settings, state / "speech.aiff", state / "config.toml")
                self.assertEqual(command.call_args.args[0][-2:], ["--", text])
                self.assertNotIn("-v", command.call_args.args[0])

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            state = Path(directory)
            settings = audio.audio_settings({"voice": {"backend": "openai"}})
            with patch.object(audio.urllib.request, "urlopen", return_value=io.BytesIO(b"fake wav")) as request:
                audio.synthesize("Pi needs food badly!", settings, state / "speech.wav", state / "config.toml")
                sent = request.call_args.args[0]
                body = json.loads(sent.data)
                self.assertEqual(sent.full_url, "https://api.openai.com/v1/audio/speech")
                self.assertEqual(sent.get_header("Authorization"), "Bearer test-key")
                self.assertEqual(body["input"], "Pi needs food badly!")
                self.assertEqual(body["voice"], "onyx")
                self.assertEqual(body["response_format"], "wav")
                self.assertEqual((state / "speech.wav").read_bytes(), b"fake wav")

    def test_kokoro_uses_isolated_runtime_and_stdin(self):
        root = Path(audio.__file__).resolve().parent
        for rate in (80, 140, 250):
            config = {"voice": {"backend": "kokoro", "rate": rate}}
            ui.validate(config)
            settings = audio.audio_settings(config)
            text = "Pi in a '; $(echo nope)' workspace needs food badly!"
            with patch.object(Path, "is_file", return_value=True), patch.object(audio, "run") as command:
                audio.synthesize(text, settings, Path("/tmp/speech.wav"), Path("/tmp/config.toml"))
                argv = command.call_args.args[0]
                self.assertEqual(argv, [str(root / ".kokoro/venv/bin/python"),
                                        str(root / "kokoro_speech.py"), "/tmp/speech.wav"])
                payload = json.loads(command.call_args.kwargs["input"])
                self.assertEqual(payload["text"], text)
                self.assertEqual(payload["voice"], "am_michael")
                self.assertEqual(payload["speed"], rate / 140)
                self.assertTrue(0.5 <= payload["speed"] <= 2)
                self.assertNotIn(text, argv)
        with patch.object(Path, "is_file", return_value=True), patch.object(audio, "run") as command:
            settings = audio.audio_settings({"voice": {"backend": "kokoro", "name": "bm_george"}})
            audio.synthesize("Victory!", settings, Path("/tmp/speech.wav"), Path("/tmp/config.toml"))
            self.assertEqual(json.loads(command.call_args.kwargs["input"])["voice"], "bm_george")
        with patch.object(Path, "is_file", return_value=False), patch.object(audio, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "Kokoro is not installed"):
                audio.synthesize("Victory!", settings, Path("/tmp/speech.wav"), Path("/tmp/config.toml"))
            command.assert_not_called()
        with self.assertRaises(ValueError):
            audio.audio_settings({"voice": {"backend": "typo"}})

    @unittest.skipUnless(all((Path(audio.__file__).resolve().parent / ".kokoro" / name).is_file()
                             for name in ("venv/bin/python", "kokoro-v1.0.onnx", "voices-v1.0.bin")),
                         "optional Kokoro runtime/model is not installed")
    def test_kokoro_worker_generates_a_real_wav_and_rejects_unknown_voices(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            settings = audio.audio_settings({"voice": {"backend": "kokoro", "name": "bm_george"}})
            path = state / "speech.wav"
            audio.synthesize("Victory!", settings, path, state / "config.toml")
            with wave.open(str(path), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 24000))
                self.assertGreater(wav.getnframes(), 1000)
                samples = wav.readframes(wav.getnframes())
                self.assertTrue(any(struct.unpack(f"<{len(samples) // 2}h", samples)))
            with self.assertRaises(audio.subprocess.CalledProcessError) as failure:
                audio.synthesize("Victory!", dict(settings, voice="not_a_voice"), path, state / "config.toml")
            self.assertIn(b"Choose an English Kokoro voice", failure.exception.stderr)

    def test_settings_save_roundtrips_values_and_protects_existing_files(self):
        config = {"preset": "gauntlet", "effects": {"volume": 0.5}, "rules": [{"agent": "pi", "mute": False}],
                  "other": {"text": 'Dungeon 🔥 "loot"\\backslash\n\x7f',
                            "date": date(2026, 9, 30), "time": time(12, 30),
                            "stamp": datetime(2026, 9, 30, tzinfo=timezone.utc), "values": [1, True, {"x": 0.1}]}}
        self.assertIn("[effects]", ui.document(config).decode())
        self.assertIn("[[rules]]", ui.document(config).decode())
        self.assertEqual(tomllib.loads(ui.document(config).decode()), config)
        self.assertEqual(tomllib.loads(ui.document({"rules": []}).decode()), {"rules": []})
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "config.toml"
            original = b'# keep these comments in the backup\npreset = "gauntlet"\n'
            file.write_bytes(original)
            ui.save_config(file, config, original)
            saved = file.read_bytes()
            backup = file.with_suffix(".toml.bak")
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(audio.load_config(file), config)
            for invalid in ({"effects": {"volume": 3}},
                            {"rules": [{}, {"agent": "other", "mute": True, "templates": ["{unknown}"]}]},
                            {"rules": [{}, {"mute": "false"}]}, {"rules": [{}, 123]}):
                with self.assertRaises(ValueError):
                    ui.save_config(file, invalid, saved)
                self.assertEqual(file.read_bytes(), saved)
                self.assertEqual(backup.read_bytes(), original)
            external_edit = b'preset = "victory"\n'
            file.write_bytes(external_edit)
            with self.assertRaisesRegex(RuntimeError, "outside"):
                ui.save_config(file, config, saved)
            self.assertEqual(file.read_bytes(), external_edit)
            self.assertEqual(backup.read_bytes(), original)
            with patch.object(Path, "replace", side_effect=OSError("disk error")), self.assertRaises(OSError):
                ui.atomic_write(file, b"replacement")
            self.assertEqual(file.read_bytes(), external_edit)
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()),
                             ["config.lock", "config.toml", "config.toml.bak"])

    def test_settings_menu_edits_drafts_previews_and_saves(self):
        choices = ["5", "6", "c", "1", "snark", "3", "add", "3", "1", "phrases", "4", "7", "8"]
        forms = [["local", "", "130", "gpt-4o-mini-tts", "Booming dungeon announcer"],
                 ["0.8", "0.1", "0", "0.5"], ["pi", "my project", "", "", "false"]]
        def ask(title, widget, *values, **kwargs):
            return "{agent} agent in {workspace} needs food badly!\n" if widget == "--editbox" else ""

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            file = state / "config.toml"
            original = b'# original comments\npreset = "gauntlet"\n'
            file.write_bytes(original)
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONTEXT_JSON": "{}", "HERDR_PLUGIN_STATE_DIR": str(state)}), \
                    patch.object(ui, "menu", side_effect=choices), patch.object(ui, "form", side_effect=forms), \
                    patch.object(ui, "dialog", side_effect=ask), patch.object(ui, "message") as notice, \
                    patch.object(audio, "clip", return_value=state / "clip.wav"), patch.object(audio, "play") as playback:
                ui.settings(file)
                notice.assert_called_once_with("Pi agent in my project needs food badly!")
                playback.assert_called_once()
            saved = audio.load_config(file)
            self.assertEqual(saved["preset"], "snark")
            self.assertTrue(saved["only_matched"])
            self.assertEqual(saved["voice"]["rate"], 130)
            self.assertEqual(saved["effects"]["volume"], 0.5)
            self.assertFalse(saved["effects"]["eight_bit_crunch"])
            self.assertEqual(saved["rules"][0]["workspace"], "my project")
            self.assertEqual(saved["rules"][0]["templates"], ["{agent} agent in {workspace} needs food badly!"])
            self.assertFalse(list(state.glob("completion-*")))
            self.assertEqual(file.with_suffix(".toml.bak").read_bytes(), original)

    def test_cancel_and_rejected_form_do_not_change_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "config.toml"
            original = b'# untouched\npreset = "gauntlet"\n'
            file.write_bytes(original)
            with patch.object(ui, "menu", side_effect=["3", None, "9"]), patch.object(ui, "dialog") as ask:
                ui.settings(file)
                ask.assert_not_called()  # Cancelling a rule menu must not create an empty rules array.
            with patch.object(ui, "menu", side_effect=["6", "8"]), \
                    patch.object(ui, "form", return_value=["0.9", "0.12", "0.12", "99"]), \
                    patch.object(ui, "message") as notice:
                ui.settings(file)
                self.assertIn("volume", notice.call_args.args[0])
            with patch.object(ui, "menu", side_effect=["4", None, "9"]), \
                    patch.object(ui, "dialog", side_effect=[None, ""]):
                ui.settings(file)  # Refuse the first discard prompt, then explicitly discard.
            self.assertEqual(file.read_bytes(), original)
            self.assertFalse(file.with_suffix(".toml.bak").exists())

    def test_dialog_data_cannot_be_interpreted_as_command_options(self):
        def invoke(argv, **kwargs):
            descriptor = int(argv[argv.index("--output-fd") + 1])
            os.write(descriptor, b"selected\n")
            return SimpleNamespace(returncode=0)
        with patch.object(ui.subprocess, "run", side_effect=invoke) as command:
            self.assertEqual(ui.dialog("--title", "--inputbox", "--prgbox", 0, 0, "--file"), "selected")
            args = command.call_args.args[0]
            self.assertEqual(args[args.index("--inputbox") + 1:], ["--", "--prgbox", "0", "0", "--", "--file"])
        with patch.object(ui.subprocess, "run", return_value=SimpleNamespace(returncode=255)):
            self.assertIsNone(ui.dialog("Cancel", "--menu", "Pick", 0, 0, 0, "1", "One"))


if __name__ == "__main__":
    unittest.main()
