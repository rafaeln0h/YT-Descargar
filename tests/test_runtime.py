import unittest
from unittest.mock import patch

from ymd.runtime import (
    detect_js_runtime,
    normalize_player_client,
    youtube_extractor_args,
    yt_dlp_runtime_options,
)


class RuntimeConfigurationTests(unittest.TestCase):
    def test_legacy_web_music_default_migrates_to_auto(self):
        self.assertEqual(normalize_player_client("default,web_music"), "auto")
        self.assertEqual(normalize_player_client("web_music,default"), "auto")

    def test_auto_client_leaves_selection_to_yt_dlp(self):
        self.assertEqual(youtube_extractor_args({"youtube_player_client": "auto"}), {})

    def test_explicit_client_is_preserved_for_advanced_diagnostics(self):
        self.assertEqual(
            youtube_extractor_args({"youtube_player_client": "android_vr,web_embedded"}),
            {"youtube": {"player_client": ["android_vr", "web_embedded"]}},
        )

    @patch("ymd.runtime.executable_version", return_value="v24.18.1")
    @patch("ymd.runtime.find_executable")
    def test_auto_runtime_falls_back_from_deno_to_node(self, find_executable, _version):
        find_executable.side_effect = lambda name: "C:/Program Files/nodejs/node.exe" if name == "node" else ""

        detected = detect_js_runtime("auto")
        options = yt_dlp_runtime_options({"youtube_js_runtime": "auto"})

        self.assertEqual(detected["name"], "node")
        self.assertEqual(
            options,
            {"js_runtimes": {"node": {"path": "C:/Program Files/nodejs/node.exe"}}},
        )

    def test_disabled_runtime_does_not_enable_yt_dlp_default(self):
        self.assertEqual(
            yt_dlp_runtime_options({"youtube_js_runtime": "none"}),
            {"js_runtimes": {}},
        )


if __name__ == "__main__":
    unittest.main()
