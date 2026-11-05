"""测试环境自身的回归：严格 UTF-8、模拟属性与真实设备访问保护。"""

import codecs
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import camera_utils
import calibrate_plane
from config import OUTPUT_DIR, PROJECT_DIR
import launcher_worker
import main
from scripts import probe_camera
from tests import forbid_real_camera
from tests.camera_fixtures import make_camera, utf8_environment


class CameraMockTests(unittest.TestCase):
    def test_all_capture_methods_have_explicit_values(self):
        frame = np.zeros((360, 512, 3), np.uint8)
        cap = make_camera(frame)
        self.assertTrue(cap.open(99))
        self.assertIs(cap.isOpened(), True)
        ok, returned = cap.read()
        self.assertIs(ok, True)
        self.assertIs(returned, frame)
        self.assertIsNone(cap.release())
        cap.release.assert_called_once()
        self.assertEqual(cap.getBackendName(), "MOCK")
        self.assertEqual(cap.get(cv2.CAP_PROP_FRAME_WIDTH), 512)
        self.assertEqual(cap.get(cv2.CAP_PROP_FRAME_HEIGHT), 360)
        self.assertEqual(cap.get(cv2.CAP_PROP_FPS), 0)
        self.assertEqual(cap.get(cv2.CAP_PROP_FOURCC), 0)
        self.assertIs(cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920), True)
        self.assertEqual(cap.get(cv2.CAP_PROP_FRAME_WIDTH), 512)

    def test_missing_fps_and_fourcc_remain_unknown_in_diagnostic(self):
        frame = np.zeros((360, 512, 3), np.uint8)
        info = camera_utils.capture_info(make_camera(frame), frame)
        self.assertEqual(info["backend"], "MOCK")
        self.assertIsNone(info["reported_fps"])
        self.assertIsNone(info["properties"]["fourcc"])
        text = camera_utils.describe_capture(info, {})
        self.assertIn("512×360", text)
        self.assertIn("MOCK", text)
        self.assertNotIn("1.0", text)

    def test_explicit_simulated_fps_and_format_are_preserved(self):
        cap = make_camera(fps=25, fourcc="MJPG")
        info = camera_utils.capture_info(cap, cap.read()[1])
        self.assertEqual(info["reported_fps"], 25)
        self.assertEqual(info["properties"]["fourcc"], "MJPG")
        self.assertEqual(info["backend"], "MOCK")

    def test_unmocked_constructor_is_blocked_before_accessing_driver(self):
        self.assertIs(cv2.VideoCapture, forbid_real_camera)
        with self.assertRaisesRegex(AssertionError, "禁止真实摄像头"):
            cv2.VideoCapture(0)

    def test_every_camera_entry_is_protected_without_mock(self):
        # 验证实际入口的绑定，而非只测试某个替身函数；断言在驱动构造前失败。
        for opened in (camera_utils.open_camera, main.open_camera, calibrate_plane.open_camera,
                       launcher_worker.open_camera, probe_camera.open_camera):
            with self.subTest(entry=opened), self.assertRaisesRegex(AssertionError, "禁止真实摄像头"):
                opened(0)

    def test_explicit_mock_can_replace_guard_and_releases_normally(self):
        cap = make_camera()
        with patch("camera_utils.cv2.VideoCapture", return_value=cap) as constructor:
            returned = camera_utils.open_camera(0)
            returned.release()
        constructor.assert_called_once()
        cap.release.assert_called_once()
        self.assertIs(cv2.VideoCapture, forbid_real_camera)


class Utf8SubprocessTests(unittest.TestCase):
    stdout_text = "标准输出：摄像头 MOCK，尺寸 640×480。\n第二行中文。\n"
    stderr_text = "标准错误：模拟设备诊断，未访问真实相机。\n"

    def command(self, *, bootstrap=False):
        code = ("import tests;" if bootstrap else "") + "import sys;"
        # 字节回归逐字比较：关闭 Windows 文本流的 LF -> CRLF 转换。
        code += "sys.stdout.reconfigure(newline='');sys.stderr.reconfigure(newline='');"
        code += f"sys.stdout.write({self.stdout_text!r});sys.stderr.write({self.stderr_text!r})"
        return [sys.executable, "-X", "utf8", "-c", code]

    def test_stdout_stderr_strict_capture_save_and_readback(self):
        result = subprocess.run(self.command(), cwd=PROJECT_DIR, env=utf8_environment(),
                                capture_output=True, encoding="utf-8", errors="strict", check=True, timeout=10)
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory:
            for name, actual, expected in (("stdout", result.stdout, self.stdout_text),
                                           ("stderr", result.stderr, self.stderr_text)):
                with self.subTest(stream=name):
                    path = Path(directory) / f"{name}.log"
                    path.write_text(actual, encoding="utf-8", errors="strict", newline="")
                    self.assertEqual(actual, expected)
                    self.assertEqual(path.read_bytes().decode("utf-8", errors="strict"), expected)

    def test_both_raw_byte_streams_are_valid_utf8(self):
        result = subprocess.run(self.command(), cwd=PROJECT_DIR, env=utf8_environment(),
                                capture_output=True, check=True, timeout=10)
        self.assertEqual(result.stdout.decode("utf-8", errors="strict"), self.stdout_text)
        self.assertEqual(result.stderr.decode("utf-8", errors="strict"), self.stderr_text)

    def test_incremental_reader_preserves_chinese_at_every_byte_boundary(self):
        with subprocess.Popen(self.command(), cwd=PROJECT_DIR, env=utf8_environment(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            for stream, expected in ((process.stdout, self.stdout_text), (process.stderr, self.stderr_text)):
                decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
                chunks = [decoder.decode(part) for part in iter(lambda: stream.read(1), b"")]
                chunks.append(decoder.decode(b"", final=True))
                self.assertEqual("".join(chunks), expected)
            self.assertEqual(process.wait(timeout=10), 0)

    def test_test_bootstrap_overrides_host_gbk_for_both_streams(self):
        env = {**utf8_environment(), "PYTHONIOENCODING": "gbk"}
        result = subprocess.run(self.command(bootstrap=True), cwd=PROJECT_DIR, env=env,
                                capture_output=True, encoding="utf-8", errors="strict", check=True, timeout=10)
        self.assertEqual(result.stdout, self.stdout_text)
        self.assertEqual(result.stderr, self.stderr_text)
