"""T06 和控制流程：用模拟摄像头验证失败提示、暂停、保存和资源释放。

这些测试验证程序分支，不等于测试实际 Windows 摄像头或窗口交互。
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import cv2

import main
from scripts.make_demo import make_demo


class MainTests(unittest.TestCase):
    def test_t06_missing_file_reports_error_and_closes_windows(self):
        error = io.StringIO()
        with patch("main.read_image", side_effect=FileNotFoundError("图片不存在：missing.png")), \
                patch("main.cv2.destroyAllWindows") as close, redirect_stderr(error):
            self.assertEqual(main.main(["--image", "missing.png", "--no-display"]), 1)
        self.assertIn("图片不存在", error.getvalue())
        close.assert_called_once()

    def test_t06_camera_unavailable_releases_all_attempts(self):
        cap = MagicMock()
        cap.open.return_value = False
        with patch("main.cv2.VideoCapture", return_value=cap), \
                self.assertRaisesRegex(RuntimeError, "无法打开摄像头 999"):
            main.open_camera(999)
        self.assertGreaterEqual(cap.release.call_count, 1)
        self.assertEqual(cap.open.call_count, cap.release.call_count)

    def test_camera_backend_fallback(self):
        first, second = MagicMock(), MagicMock()
        first.open.return_value = False
        second.open.return_value = second.isOpened.return_value = True
        with patch("main.os.name", "nt"), \
                patch("main.cv2.VideoCapture", side_effect=[first, second]):
            self.assertIs(main.open_camera(0), second)
        first.release.assert_called_once()
        second.release.assert_not_called()

    def test_t06_failed_read_releases_camera(self):
        cap = MagicMock()
        cap.read.return_value = (False, None)
        error = io.StringIO()
        with patch("main.open_camera", return_value=cap), patch("main.create_window"), \
                patch("main.cv2.destroyAllWindows") as close, redirect_stderr(error):
            self.assertEqual(main.main(["--camera", "0"]), 1)
        self.assertIn("帧读取失败", error.getvalue())
        cap.release.assert_called_once()
        close.assert_called_once()

    def test_window_creation_failure_releases_camera(self):
        cap = MagicMock()
        with patch("main.open_camera", return_value=cap), \
                patch("main.create_window", side_effect=cv2.error("GUI unavailable")), \
                patch("main.cv2.destroyAllWindows"), redirect_stderr(io.StringIO()):
            self.assertEqual(main.main([]), 1)
        cap.release.assert_called_once()

    def test_pause_save_resume_and_quit_use_same_frame(self):
        cap = MagicMock()
        frame = make_demo()
        cap.read.return_value = (True, frame)
        with ExitStack() as stack:
            stack.enter_context(patch("main.open_camera", return_value=cap))
            stack.enter_context(patch("main.create_window"))
            preview = stack.enter_context(patch("main.show_preview"))
            stack.enter_context(patch("main.cv2.getTrackbarPos", return_value=300))
            stack.enter_context(patch("main.cv2.getWindowProperty", return_value=1))
            stack.enter_context(patch("main.cv2.waitKey", side_effect=[ord("p"), ord("s"), ord("p"), ord("q")]))
            export = stack.enter_context(patch("main.export_current"))
            stack.enter_context(patch("main.cv2.destroyAllWindows"))
            self.assertEqual(main.main(["--camera", "0"]), 0)
        self.assertEqual(cap.read.call_count, 2)
        self.assertEqual(preview.call_count, 4)
        cap.release.assert_called_once()
        annotated, result = export.call_args.args
        self.assertEqual(annotated.shape, frame.shape)
        self.assertEqual(result["source"], "camera:0")
        self.assertEqual(len(result["objects"]), 4)

    def test_image_mode_can_adjust_threshold_and_save(self):
        with ExitStack() as stack:
            stack.enter_context(patch("main.read_image", return_value=make_demo()))
            stack.enter_context(patch("main.create_window"))
            stack.enter_context(patch("main.show_preview"))
            stack.enter_context(patch("main.cv2.getTrackbarPos", return_value=11000))
            stack.enter_context(patch("main.cv2.getWindowProperty", return_value=1))
            stack.enter_context(patch("main.cv2.waitKey", side_effect=[ord("s"), 27]))
            export = stack.enter_context(patch("main.export_current"))
            stack.enter_context(patch("main.cv2.destroyAllWindows"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            self.assertEqual(main.main(["--image", "demo.png"]), 0)
        self.assertEqual(len(export.call_args.args[1]["objects"]), 1)

    def test_mask_preview_selects_requested_color(self):
        frame = make_demo()
        masks = {color: frame[:, :, 0] * 0 for color in ("red", "green", "blue")}
        masks["green"][100:200, 100:200] = 255
        with patch("main.cv2.getTrackbarPos", return_value=2), patch("main.cv2.imshow") as show:
            main.show_preview(frame, masks)
        preview = show.call_args.args[1]
        self.assertEqual(tuple(preview[150, 150]), (255, 255, 255))
        self.assertEqual(tuple(preview[300, 300]), (0, 0, 0))

    def test_headless_export_failure_returns_nonzero(self):
        with patch("main.read_image", return_value=make_demo()), \
                patch("main.export_current", return_value=False), \
                patch("main.cv2.destroyAllWindows"), redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--image", "demo.png", "--no-display"]), 1)

    def test_invalid_arguments(self):
        for argv in (["--camera", "-1"], ["--min-area", "0"], ["--min-area", "100001"],
                     ["--no-display"], ["--save"], ["--camera", "0", "--image", "a.png"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                main.parse_args(argv)
            self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
