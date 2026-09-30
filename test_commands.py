"""User-facing speech and diagnostic commands: python3 -m unittest -v."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import announcer as audio
import configure as ui
import doctor


class CommandCheck(unittest.TestCase):
    def test_literal_speech_bypasses_rules_and_does_not_lookup_focused_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('only_matched = true\n[[rules]]\nmute = true\n')
            text = "Say {this}; $(not a command)!"
            context = {"focused_pane_id": "w1:p1", "focused_pane_agent": "pi"}
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONTEXT_JSON": json.dumps(context),
                                         "HERDR_PLUGIN_STATE_DIR": directory}), \
                    patch.object(audio, "get_agent") as lookup, \
                    patch.object(audio, "clip", return_value=Path(directory) / "clip.wav") as clip, \
                    patch.object(audio, "play") as play, contextlib.redirect_stdout(io.StringIO()) as output:
                audio.main(["preview", "--config", str(config), "--say", text])
                self.assertEqual(clip.call_args.args[0], text)
                play.assert_called_once()
                lookup.assert_not_called()
                self.assertIn(text, output.getvalue())
                self.assertFalse(list(Path(directory).glob("completion-*")))
                for bad in ("", "   ", "x" * 501, "hello\x00", "hello\nworld"):
                    with self.subTest(text=bad), self.assertRaises(ValueError):
                        audio.main(["preview", "--config", str(config), "--say", bad, "--text-only"])

    def test_explicit_missing_config_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                audio.main(["preview", "--config", str(Path(directory) / "missing.toml"), "--text-only"])

    def test_speech_popup_and_cancel(self):
        with patch.object(ui.sys.stdin, "isatty", return_value=True), \
                patch.object(ui.shutil, "which", return_value="dialog"), \
                patch.object(ui, "dialog", side_effect=["--help", None]), \
                patch.object(audio, "main") as command:
            ui.main(["--say", "--config", "/tmp/example.toml"])
            command.assert_called_once_with(["preview", "--say=--help", "--config", "/tmp/example.toml"])
            ui.main(["--say"])
            command.assert_called_once()

    def test_doctor_is_offline_reports_errors_and_never_prints_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[voice]\nbackend = "openai"\n')
            filters = b" TSC aresample A->A\n TSC alimiter A->A\n TSC asoftclip A->A\n TSC acrusher A->A\n TSC highpass A->A\n TSC lowpass A->A\n"
            with patch.dict(os.environ, {"HERDR_PLUGIN_STATE_DIR": directory,
                                         "OPENAI_API_KEY": "secret-never-print-this"}, clear=True), \
                    patch.object(doctor.shutil, "which", side_effect=lambda name: "/fake/" + name), \
                    patch.object(audio, "run", return_value=filters), \
                    patch.object(audio, "synthesize") as synthesis, \
                    patch.object(audio, "play") as play, \
                    patch.object(audio.urllib.request, "urlopen") as network, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(doctor.main(["--config", str(config)]), 0)
                self.assertIn("OpenAI credentials: present", output.getvalue())
                self.assertNotIn("secret-never-print-this", output.getvalue())
                os.environ["OPENAI_API_KEY"] = ""
                self.assertEqual(doctor.main(["--config", str(config)]), 1)
                self.assertIn("FAIL OpenAI credentials", output.getvalue())
                config.write_text('[effects]\nvolume = 3\n')
                self.assertEqual(doctor.main(["--config", str(config)]), 1)
                self.assertIn("FAIL Config", output.getvalue())
                self.assertEqual(doctor.main(["--config", str(config.with_name("missing.toml"))]), 1)
                synthesis.assert_not_called()
                play.assert_not_called()
                network.assert_not_called()

    def test_herdr_speech_action_uses_server_binary_and_popup(self):
        with patch.dict(os.environ, {"HERDR_BIN_PATH": "/custom/herdr"}), patch.object(audio, "run") as command:
            ui.main(["--open", "--say"])
            command.assert_called_once_with(["/custom/herdr", "plugin", "pane", "open", "--plugin",
                                             "jbeers.herdr-8-bit-announcer", "--entrypoint", "say"])

    def test_manifest_declares_new_actions_and_name(self):
        manifest = audio.load_config(Path(__file__).with_name("herdr-plugin.toml"))
        self.assertEqual(manifest["id"], "jbeers.herdr-8-bit-announcer")
        self.assertEqual({action["id"] for action in manifest["actions"]}, {"preview", "configure", "say", "doctor"})


if __name__ == "__main__":
    unittest.main()
