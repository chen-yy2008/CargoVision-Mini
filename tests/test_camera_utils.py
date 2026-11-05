"""设备选择和设置回归：全部使用模拟摄像头，不操作用户真实设备偏好。"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.camera_fixtures import make_camera

import cv2
import numpy as np

import camera_utils
from config import PROJECT_DIR
import main
from scripts.make_demo import make_demo


class CameraPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.preference = {"version": 1, "camera_index": 2, "backend": "DSHOW",
                           "capture_size": {"width": 640, "height": 480}}

    def test_explicit_choice_overrides_saved_index_and_settings(self):
        selected = camera_utils.choose_camera(1, self.preference)
        self.assertEqual(selected, {"index": 1, "backend": None, "size": None, "from_preference": False})
        self.assertEqual(camera_utils.choose_camera(None, self.preference)["index"], 2)
        self.assertEqual(camera_utils.choose_camera(None)["index"], 0)

    def test_explicit_backend_and_size_override_preference(self):
        selected = camera_utils.choose_camera(None, self.preference, "MSMF", {"width": 1280, "height": 720})
        self.assertEqual(selected["backend"], "MSMF")
        self.assertEqual(selected["size"], {"width": 1280, "height": 720})

    def test_unicode_preference_roundtrip_and_replace(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "本机设置" / "camera.json"
            self.assertIsNone(camera_utils.load_camera_preference(path))
            info = {"backend": "DSHOW", "width": 640, "height": 480}
            camera_utils.save_camera_preference(path, 2, info)
            data = camera_utils.load_camera_preference(path)
            self.assertEqual(data["camera_index"], 2)
            self.assertEqual(data["identity_kind"], "opencv_index_only")
            camera_utils.save_camera_preference(path, 1, info)
            self.assertEqual(camera_utils.load_camera_preference(path)["camera_index"], 1)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_corrupt_preferences_fail_instead_of_defaulting(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "bad.json"
            broken = []
            for key, value in (("version", True), ("version", 99), ("camera_index", -1), ("camera_index", True),
                               ("backend", "invalid"), ("capture_size", {"width": 0, "height": 480})):
                data = deepcopy(self.preference)
                data[key] = value
                broken.append(json.dumps(data))
            for payload in ["not json", "[]", "null", *broken]:
                path.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "显式重新选择"):
                    camera_utils.load_camera_preference(path)

    def test_missing_backend_is_a_clear_configuration_error(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "camera.json"
            data = dict(self.preference)
            del data["backend"]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "偏好损坏"):
                camera_utils.load_camera_preference(path)

    def test_failed_atomic_replace_keeps_previous_preference(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "camera.json"
            path.write_text(json.dumps(self.preference), encoding="utf-8")
            before = path.read_bytes()
            with patch.object(Path, "replace", side_effect=PermissionError("read only")), self.assertRaises(PermissionError):
                camera_utils.save_camera_preference(path, 1, {"backend": "DSHOW", "width": 640, "height": 480})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_saved_backend_does_not_fall_back_to_other_backends(self):
        cap = make_camera()
        cap.open.return_value = False
        with patch("camera_utils.cv2.VideoCapture", return_value=cap), self.assertRaises(RuntimeError):
            camera_utils.open_camera(2, "MSMF")
        cap.open.assert_called_once_with(2, cv2.CAP_MSMF)
        cap.release.assert_called_once()

    def test_enumeration_requires_readable_frame_and_releases_all(self):
        first, third = make_camera(), make_camera()
        first.read.return_value = (True, np.zeros((480, 640, 3), np.uint8))
        third.read.return_value = (False, None)
        with patch("camera_utils.open_camera", side_effect=[first, RuntimeError("unavailable"), third]):
            devices = camera_utils.list_cameras(3, "DSHOW")
        self.assertEqual([device["index"] for device in devices], [0])
        first.release.assert_called_once()
        third.release.assert_called_once()

    def test_enumeration_tries_readable_backend_at_same_index(self):
        bad, good = make_camera(), make_camera()
        bad.read.return_value = (False, None)
        good.read.return_value = (True, make_demo())
        with patch("camera_utils.os.name", "nt"), patch("camera_utils.open_camera", side_effect=[bad, good]) as opened:
            devices = camera_utils.list_cameras(1)
        self.assertEqual(opened.call_args_list[0].args, (0, "DSHOW"))
        self.assertEqual(opened.call_args_list[1].args, (0, "MSMF"))
        self.assertEqual(devices[0]["backend"], "MOCK")
        bad.release.assert_called_once()
        good.release.assert_called_once()

    def test_reported_fps_unknown_and_size_comes_from_actual_frame(self):
        cap = make_camera()
        for fps in (0, -1, float("nan"), float("inf")):
            cap.get.side_effect = lambda prop: fps
            info = camera_utils.capture_info(cap, np.zeros((720, 1280, 3), np.uint8))
            self.assertIsNone(info["reported_fps"])
            self.assertEqual((info["width"], info["height"]), (1280, 720))

    def test_resolution_changes_rejected_before_device_set_when_calibrated(self):
        cap = make_camera()
        calibration = {"image_size": {"width": 640, "height": 480}}
        for keyword in ("plane", "intrinsics"):
            with self.subTest(keyword=keyword), self.assertRaisesRegex(ValueError, "未更改设备"):
                camera_utils.configure_capture(cap, {"width": 1280, "height": 720}, **{keyword: calibration})
        cap.set.assert_not_called()

    def test_no_resolution_setting_unless_requested(self):
        cap = make_camera()
        camera_utils.configure_capture(cap)
        cap.set.assert_not_called()
        cap.set.return_value = False
        with redirect_stdout(io.StringIO()) as output:
            camera_utils.configure_capture(cap, {"width": 1280, "height": 720})
        self.assertEqual(cap.set.call_count, 2)
        self.assertIn("实际返回", output.getvalue())


class CameraMainTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "camera.json"
        patcher = patch("main.CAMERA_PREFERENCE_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_camera(self, argv, keys=None, frame=None, save_error=False):
        cap = make_camera(make_demo() if frame is None else frame)
        cap.set.return_value = True
        with ExitStack() as stack:
            opened = stack.enter_context(patch("main.open_camera", return_value=cap))
            stack.enter_context(patch("main.create_window"))
            preview = stack.enter_context(patch("main.show_preview"))
            stack.enter_context(patch("main.cv2.getTrackbarPos", return_value=300))
            stack.enter_context(patch("main.cv2.getWindowProperty", return_value=1))
            stack.enter_context(patch("main.cv2.waitKey", side_effect=keys or [ord("q")]))
            stack.enter_context(patch("main.cv2.destroyAllWindows"))
            if save_error:
                stack.enter_context(patch("main.save_camera_preference", side_effect=PermissionError("read only")))
            stdout = stack.enter_context(redirect_stdout(io.StringIO()))
            stderr = stack.enter_context(redirect_stderr(io.StringIO()))
            status = main.main(argv)
        cap.release.assert_called_once()
        return status, cap, opened, preview, stdout.getvalue(), stderr.getvalue()

    def test_first_explicit_selection_is_reused_on_next_plain_run(self):
        status, _, first, _, _, _ = self.run_camera(["--camera", "2"])
        self.assertEqual(status, 0)
        first.assert_called_once_with(2)
        self.assertEqual(camera_utils.load_camera_preference(self.path)["camera_index"], 2)
        status, cap, second, _, output, _ = self.run_camera([])
        self.assertEqual(status, 0)
        second.assert_called_once_with(2)
        self.assertEqual(cap.set.call_count, 2)
        self.assertIn("本机偏好", output)

    def test_explicit_index_overrides_saved_selection_and_corrupt_file(self):
        self.path.write_text("broken", encoding="utf-8")
        status, _, opened, _, _, _ = self.run_camera(["--camera", "1", "--backend", "msmf"])
        self.assertEqual(status, 0)
        opened.assert_called_once_with(1, "MSMF")
        self.assertEqual(camera_utils.load_camera_preference(self.path)["camera_index"], 1)

    def test_corrupt_implicit_preference_does_not_open_any_camera(self):
        self.path.write_text("broken", encoding="utf-8")
        with patch("main.open_camera") as opened, patch("main.cv2.destroyAllWindows"), redirect_stderr(io.StringIO()):
            self.assertEqual(main.main([]), 1)
        opened.assert_not_called()

    def test_unavailable_saved_camera_is_not_replaced_with_zero(self):
        camera_utils.save_camera_preference(self.path, 2, {"backend": "DSHOW", "width": 640, "height": 480})
        with patch("main.open_camera", side_effect=RuntimeError("saved device unavailable")) as opened, \
                patch("main.cv2.destroyAllWindows"), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main.main([]), 1)
        opened.assert_called_once_with(2, "DSHOW")

    def test_requested_size_is_checked_against_actual_frame_and_saved(self):
        status, _, _, _, output, _ = self.run_camera(["--camera", "1", "--width", "1280", "--height", "720"])
        self.assertEqual(status, 0)
        self.assertIn("实际分辨率与请求不同", output)
        self.assertEqual(camera_utils.load_camera_preference(self.path)["capture_size"], {"width": 640, "height": 480})

    def test_requested_format_and_fps_restore_without_reselecting_device(self):
        status, cap, _, _, output, _ = self.run_camera(["--camera", "2", "--fourcc", "mjpg", "--fps", "30"])
        self.assertEqual(status, 0)
        cap.set.assert_any_call(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set.assert_any_call(cv2.CAP_PROP_FPS, 30)
        self.assertIn("属性读回", output)
        status, cap, opened, _, _, _ = self.run_camera([])
        self.assertEqual(status, 0)
        opened.assert_called_once_with(2)
        self.assertEqual(cap.set.call_count, 4)
        saved = camera_utils.load_camera_preference(self.path)
        self.assertEqual((saved["requested_fourcc"], saved["requested_fps"]), ("MJPG", 30))

    def test_calibration_resolution_conflict_releases_without_saving(self):
        status, cap, _, preview, _, error = self.run_camera(["--camera", "1", "--width", "1280", "--height", "720",
            "--calibration", str(PROJECT_DIR / "samples" / "workplane_demo.json")])
        self.assertEqual(status, 1)
        self.assertIn("标定不一致", error)
        cap.set.assert_not_called()
        preview.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_preference_write_failure_keeps_session_usable(self):
        status, _, _, _, _, error = self.run_camera(["--camera", "1"], save_error=True)
        self.assertEqual(status, 0)
        self.assertIn("偏好保存失败", error)

    def test_list_command_does_not_load_or_save_preference(self):
        self.path.write_text("broken", encoding="utf-8")
        device = {"index": 1, "width": 640, "height": 480, "backend": "MOCK", "reported_fps": None}
        with patch("main.list_cameras", return_value=[device]), patch("main.open_camera") as opened, \
                patch("main.cv2.destroyAllWindows"), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main.main(["--list-cameras"]), 0)
        opened.assert_not_called()
        self.assertIn("--camera 1:", output.getvalue())
        self.assertIn("MOCK", output.getvalue())
        self.assertNotIn("--backend", output.getvalue())
        self.assertEqual(self.path.read_text(encoding="utf-8"), "broken")

    def test_list_empty_has_actionable_error(self):
        with patch("main.list_cameras", return_value=[]), patch("main.cv2.destroyAllWindows"), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main.main(["--list-cameras"]), 1)
        self.assertIn("--scan-limit", error.getvalue())

    def test_invalid_capture_options(self):
        for arguments in (["--width", "640"], ["--width", "0", "--height", "480"], ["--scan-limit", "0"],
                          ["--area-max", "0"], ["--image", "test.png", "--width", "640", "--height", "480"]):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main.parse_args(arguments)


if __name__ == "__main__":
    unittest.main()
