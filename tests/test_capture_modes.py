"""采集参数及限时检测回归；只用模拟帧/临时文件，不访问真实设备或本机偏好。"""

from contextlib import redirect_stdout, redirect_stderr
import io
import itertools
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tests.camera_fixtures import make_camera

import cv2
import numpy as np

import camera_utils
import main
import calibrate_plane
from config import OUTPUT_DIR
from scripts import probe_camera


class CaptureModeTests(unittest.TestCase):
    def test_new_settings_roundtrip_and_cli_precedence(self):
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory:
            path = Path(directory) / "偏好.json"
            info = {"width": 1280, "height": 720, "backend": "DSHOW",
                    "requested_fourcc": "MJPG", "requested_fps": 30}
            camera_utils.save_camera_preference(path, 2, info)
            preference = camera_utils.load_camera_preference(path)
            restored = camera_utils.choose_camera(None, preference)
            self.assertEqual(restored["requested_fourcc"], "MJPG")
            self.assertEqual(restored["requested_fps"], 30)
            override = camera_utils.choose_camera(None, preference, fourcc="YUY2", fps=15)
            self.assertEqual((override["requested_fourcc"], override["requested_fps"]), ("YUY2", 15))
            self.assertNotIn("requested_fourcc", camera_utils.choose_camera(1, preference))
            self.assertNotIn("requested_fps", camera_utils.choose_camera(1, preference))

    def test_invalid_saved_mode_is_rejected(self):
        base = {"version": 1, "camera_index": 2, "backend": "DSHOW", "capture_size": {"width": 640, "height": 480}}
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory:
            path = Path(directory) / "pref.json"
            for key, value in (("requested_fourcc", "ABCD"), ("requested_fourcc", []),
                               ("requested_fps", True), ("requested_fps", "30"), ("requested_fps", float("inf"))):
                path.write_text(json.dumps({**base, key: value}), encoding="utf-8")
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "偏好损坏"):
                    camera_utils.load_camera_preference(path)

    def test_invalid_request_does_not_set_any_property(self):
        for options in ({"fourcc": "H264"}, {"fps": float("nan")}, {"fps": 0}, {"fps": True}):
            cap = make_camera()
            with self.subTest(options=options), self.assertRaises(ValueError):
                camera_utils.configure_capture(cap, **options)
            cap.set.assert_not_called()

    def test_calibration_conflict_blocks_format_and_fps_too(self):
        cap = make_camera()
        with self.assertRaisesRegex(ValueError, "未更改设备"):
            camera_utils.configure_capture(cap, {"width": 1280, "height": 720},
                plane={"image_size": {"width": 640, "height": 480}}, fourcc="MJPG", fps=30)
        cap.set.assert_not_called()

    def test_properties_and_real_frame_are_separate(self):
        cap = make_camera()
        props = {cv2.CAP_PROP_FRAME_WIDTH: 1920, cv2.CAP_PROP_FRAME_HEIGHT: 1080,
                 cv2.CAP_PROP_FPS: 30, cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"YUY2")}
        cap.get.side_effect = props.__getitem__
        info = camera_utils.capture_info(cap, np.zeros((480, 640, 3), np.uint8))
        self.assertEqual((info["width"], info["height"]), (640, 480))
        self.assertEqual(info["properties"]["width"], 1920)
        self.assertEqual(info["properties"]["fourcc"], "YUY2")
        text = camera_utils.describe_capture(info, {"size": {"width": 1920, "height": 1080}, "requested_fourcc": "MJPG"})
        self.assertIn("真实帧：640×480", text)
        self.assertIn("不证明", text)

    def test_unknown_properties_are_json_safe(self):
        cap = make_camera()
        for value in (float("nan"), float("inf"), 0, -1, None):
            cap.get.side_effect = lambda prop: value
            props = camera_utils.capture_properties(cap)
            self.assertTrue(all(value is None for value in props.values()))
            json.dumps(props, allow_nan=False)
        cap.get.side_effect = cv2.error("unsupported")
        self.assertIsNone(camera_utils.capture_properties(cap)["fourcc"])

    def test_auto_format_explicitly_clears_saved_request(self):
        preference = {"camera_index": 2, "backend": "DSHOW", "capture_size": {"width": 640, "height": 480},
                      "requested_fourcc": "MJPG", "requested_fps": 30}
        args = main.parse_args(["--fourcc", "auto"])
        with patch("main.load_camera_preference", return_value=preference), redirect_stdout(io.StringIO()):
            main.prepare_camera_choice(args)
        self.assertNotIn("requested_fourcc", args.camera_choice)
        self.assertEqual(args.camera_choice["requested_fps"], 30)

    def test_invalid_cli_fps_and_image_mode_options(self):
        for argv in (["--fps", "nan"], ["--fps", "inf"], ["--fps", "241"],
                     ["--image", "demo.png", "--fourcc", "mjpg"], ["--image", "demo.png", "--fps", "30"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main.parse_args(argv)

    def test_plane_tool_rejects_capture_options_for_image(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            calibrate_plane.main(["--image", "demo.png", "--width-mm", "210", "--height-mm", "297", "--fourcc", "mjpg"])

    def test_plane_tool_passes_same_mode_to_capture_and_releases(self):
        cap = make_camera()
        cap.read.return_value = (True, np.zeros((720, 1280, 3), np.uint8))
        with patch("calibrate_plane.open_camera", return_value=cap), patch("calibrate_plane.cv2.namedWindow"), \
                patch("calibrate_plane.cv2.setMouseCallback"), patch("calibrate_plane.cv2.destroyAllWindows"), \
                patch("calibrate_plane.window_is_open", return_value=False), redirect_stdout(io.StringIO()):
            code = calibrate_plane.main(["--camera", "2", "--backend", "dshow", "--width", "1280", "--height", "720",
                                         "--fourcc", "mjpg", "--fps", "30", "--width-mm", "210", "--height-mm", "297"])
        self.assertEqual(code, 0)
        cap.set.assert_any_call(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set.assert_any_call(cv2.CAP_PROP_FPS, 30)
        cap.release.assert_called_once()


class ProbeTests(unittest.TestCase):
    def spec(self):
        return {"index": 2, "backend": "DSHOW", "size": {"width": 1280, "height": 720},
                "fourcc": "MJPG", "fps": 30, "warmup": 1, "seconds": 2}

    def measure(self, frames, spec=None, property_size=(1280, 720), accepted=True):
        cap = make_camera()
        cap.read.side_effect = frames
        cap.set.return_value = accepted
        props = {cv2.CAP_PROP_FRAME_WIDTH: property_size[0], cv2.CAP_PROP_FRAME_HEIGHT: property_size[1],
                 cv2.CAP_PROP_FPS: 30, cv2.CAP_PROP_FOURCC: cv2.VideoWriter_fourcc(*"MJPG")}
        cap.get.side_effect = props.__getitem__
        with patch("scripts.probe_camera.open_camera", return_value=cap), \
                patch("scripts.probe_camera.perf_counter", side_effect=itertools.count(0, 0.25)), redirect_stdout(io.StringIO()):
            result = probe_camera.measure_mode(spec or self.spec())
        cap.release.assert_called_once()
        return result

    def test_warmup_excluded_and_throughput_measured(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        result = self.measure([(True, frame)] * 5)
        self.assertEqual(result["frames"], 4)
        self.assertEqual(result["measured_read_fps"], 2)
        self.assertEqual(result["actual"]["reported_fps"], 30)
        self.assertEqual(result["size_counts"], {"1280x720": 4})
        self.assertTrue(result["exact_resolution"])

    def test_set_success_and_property_size_do_not_prove_real_size(self):
        frame = np.zeros((480, 640, 3), np.uint8)
        result = self.measure([(True, frame)] * 5)
        self.assertEqual(result["status"], "size_mismatch")
        self.assertFalse(result["exact_resolution"])
        self.assertEqual(result["actual"]["properties"]["width"], 1280)
        self.assertEqual(result["actual"]["width"], 640)

    def test_set_false_but_real_frame_matches_is_recorded(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        result = self.measure([(True, frame)] * 5, accepted=False)
        self.assertEqual(result["status"], "read_ok")
        self.assertFalse(any(result["set_results"].values()))

    def test_midstream_size_change_is_not_exact_mode(self):
        first = np.zeros((720, 1280, 3), np.uint8)
        other = np.zeros((480, 640, 3), np.uint8)
        result = self.measure([(True, first)] * 3 + [(True, other)] * 2)
        self.assertEqual(result["status"], "size_mismatch")
        self.assertEqual(len(result["size_counts"]), 2)

    def test_read_failure_releases_and_preserves_partial_evidence(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        result = self.measure([(True, frame)] * 2 + [(False, None)])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["frames"], 1)
        self.assertIsNone(result["measured_read_fps"])
        self.assertFalse(result["exact_resolution"])

    def test_unavailable_device_has_no_fabricated_measurement(self):
        with patch("scripts.probe_camera.open_camera", side_effect=RuntimeError("unavailable")):
            result = probe_camera.measure_mode(self.spec())
        self.assertEqual(result["frames"], 0)
        self.assertNotIn("actual", result)
        self.assertIsNone(result["measured_read_fps"])

    def test_timeout_and_worker_error_are_distinct(self):
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory:
            with patch("scripts.probe_camera.subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 3)):
                self.assertEqual(probe_camera.run_isolated(self.spec(), 3, directory)["status"], "timeout")
            with patch("scripts.probe_camera.subprocess.run", return_value=MagicMock(returncode=1)):
                self.assertEqual(probe_camera.run_isolated(self.spec(), 3, directory)["status"], "worker_error")

    def test_worker_driver_stdout_does_not_corrupt_result(self):
        def worker(command, **kwargs):
            Path(command[-1]).write_text('{"status":"read_ok"}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=b"driver chatter")
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory, patch("scripts.probe_camera.subprocess.run", side_effect=worker):
            self.assertEqual(probe_camera.run_isolated(self.spec(), 3, directory)["status"], "read_ok")

    def test_malformed_worker_report_is_reported_without_crashing_scan(self):
        def worker(command, **kwargs):
            Path(command[-1]).write_text("bad JSON", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory, patch("scripts.probe_camera.subprocess.run", side_effect=worker):
            self.assertEqual(probe_camera.run_isolated(self.spec(), 3, directory)["status"], "worker_error")

    def test_invalid_probe_ranges(self):
        for argv in (["--sizes", "bad"], ["--sizes", "0x480"], ["--seconds", "nan"], ["--fps", "0"],
                     ["--timeout", "2"], ["--seconds", "15", "--timeout", "10"], ["--warmup", "-1"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                probe_camera.parse_args(argv)

    def test_probe_saves_numeric_report_without_changing_preference(self):
        preference = {"camera_index": 2, "backend": "DSHOW"}
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as directory:
            output = Path(directory) / "report.json"
            argv = ["--backends", "dshow", "--formats", "mjpg", "--sizes", "1280x720", "--output", str(output)]
            def measured(spec, timeout, directory):
                return {"requested": spec, "status": "read_ok", "frames": 60, "measured_read_fps": 30}
            with patch("scripts.probe_camera.load_camera_preference", return_value=preference), \
                    patch("scripts.probe_camera.run_isolated", side_effect=measured) as worker, redirect_stdout(io.StringIO()):
                self.assertEqual(probe_camera.main(argv), 0)
            self.assertEqual(worker.call_args.args[0]["index"], 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["complete"])
            self.assertEqual(len(report["results"]), 1)
            with patch("scripts.probe_camera.run_isolated") as worker, redirect_stderr(io.StringIO()):
                self.assertEqual(probe_camera.main([*argv, "--camera", "2"]), 1)
            worker.assert_not_called()

    def test_probe_without_saved_or_explicit_device_refuses_guessing(self):
        with patch("scripts.probe_camera.load_camera_preference", return_value=None), \
                patch("scripts.probe_camera.run_isolated") as worker, redirect_stderr(io.StringIO()):
            self.assertEqual(probe_camera.main([]), 1)
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
