"""C10~C12：棋盘格、点选工具、误差统计和命令行集成，不使用真实摄像头。"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

import calibrate_camera
import calibrate_plane
from calibration import create_plane_calibration, load_calibration, save_calibration
from config import PROJECT_DIR
import main
from scripts.evaluate_calibration import evaluate_measurements, main as evaluate_main, read_measurements
from scripts.make_calibration_demo import make_demo_calibration
from scripts.make_demo import make_demo
from tests.calibration_fixtures import projected_chessboards, synthetic_intrinsics


class CameraCalibrationTests(unittest.TestCase):
    def test_synthetic_projection_solver_and_reprojection(self):
        result = calibrate_camera.calibrate_from_points(projected_chessboards(), {"width": 640, "height": 480}, (7, 5), 20)
        self.assertLess(result["reprojection_rmse_px"], 0.001)
        np.testing.assert_allclose(result["camera_matrix"], synthetic_intrinsics()["camera_matrix"], atol=0.1)
        self.assertEqual(result["valid_views"], 8)
        self.assertEqual(len(result["per_view_rmse_px"]), 8)
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "camera.json"
            save_calibration(path, result)
            self.assertEqual(load_calibration(path, "camera_intrinsics"), result)

    def test_insufficient_and_duplicate_views_are_rejected(self):
        observations = projected_chessboards()
        for points in (observations[:4], [observations[0]] * 5):
            with self.subTest(count=len(points)), self.assertRaises(ValueError):
                calibrate_camera.calibrate_from_points(points, {"width": 640, "height": 480}, (7, 5), 20)

    def test_invalid_board_parameters(self):
        for board, square in (((1, 5), 20), ((7, True), 20), ((7, 5), 0), ((7, 5), float("nan")), ((7, 5), "20")):
            with self.subTest(board=board, square=square), self.assertRaises(ValueError):
                calibrate_camera.board_object_points(board, square)

    def test_missing_photos_and_failed_corner_detection(self):
        with self.assertRaisesRegex(ValueError, "照片不足"):
            calibrate_camera.calibrate_images([], (7, 5), 20)
        with patch("calibrate_camera.read_image", return_value=np.zeros((480, 640, 3), np.uint8)), \
                self.assertRaisesRegex(ValueError, "成功 0，失败 5"):
            calibrate_camera.calibrate_images([Path(f"{index}.png") for index in range(5)], (7, 5), 20)

    def test_mixed_photo_sizes_are_rejected(self):
        frames = [np.zeros((480, 640, 3), np.uint8), np.zeros((240, 320, 3), np.uint8)]
        with patch("calibrate_camera.read_image", side_effect=frames), \
                patch("calibrate_camera.cv2.findChessboardCorners", return_value=(False, None)), \
                self.assertRaisesRegex(ValueError, "分辨率"):
            calibrate_camera.calibrate_images([Path(str(index)) for index in range(5)], (7, 5), 20)

    def test_real_opencv_detects_rendered_board_but_rejects_repeated_photos(self):
        board = np.full((480, 640, 3), 255, dtype=np.uint8)
        for row in range(6):
            for col in range(8):
                if (row + col) % 2 == 0:
                    board[100 + row * 30:130 + row * 30, 100 + col * 30:130 + col * 30] = 0
        found, corners = cv2.findChessboardCorners(cv2.cvtColor(board, cv2.COLOR_BGR2GRAY), (7, 5))
        self.assertTrue(found)
        self.assertEqual(corners.shape, (35, 1, 2))
        with patch("calibrate_camera.read_image", return_value=board), self.assertRaisesRegex(ValueError, "重复"):
            calibrate_camera.calibrate_images([Path(f"synthetic{index}.png") for index in range(5)], (7, 5), 20)

    def test_camera_cli_failure_does_not_create_output(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            output = Path(directory) / "camera.json"
            with redirect_stderr(io.StringIO()):
                status = calibrate_camera.main(["--images", directory, "--cols", "7", "--rows", "5", "--square-mm", "20", "--output", str(output)])
            self.assertEqual(status, 1)
            self.assertFalse(output.exists())

    def test_small_rendered_chessboard_corners_do_not_drift_to_neighbors(self):
        # 合成视图角点间距约 14~20 pixel；过大的亚像素窗口会包含相邻角点。
        # 此上限只是确定合成图的回归阈值，不代表真实相机或毫米精度。
        camera = np.array(synthetic_intrinsics()["camera_matrix"])
        texture = np.full((480, 640), 255, np.uint8)
        for row in range(6):
            for col in range(8):
                if (row + col) % 2 == 0:
                    texture[row * 80:(row + 1) * 80, col * 80:(col + 1) * 80] = 0
        source = np.float32([[0, 0], [640, 0], [640, 480], [0, 480]])
        outer = np.float32([[-20, -20, 0], [140, -20, 0], [140, 100, 0], [-20, 100, 0]])
        frames = []
        for index in range(10):
            rotation = np.array([0.12 + index * 0.04, -0.25 + index * 0.07, -0.08 + index * 0.025])
            translation = np.array([-65 + index * 5.0, -45 + index * 3.0, 550 + index * 30.0])
            projected, _ = cv2.projectPoints(outer, rotation, translation, camera, np.zeros(5))
            homography = cv2.getPerspectiveTransform(source, projected.reshape(4, 2))
            gray = cv2.warpPerspective(texture, homography, (640, 480), borderValue=255)
            frames.append(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
        with patch("calibrate_camera.read_image", side_effect=frames):
            result = calibrate_camera.calibrate_images([Path(f"synthetic_{i}.png") for i in range(10)], (7, 5), 20)
        self.assertEqual(result["valid_views"], 10)
        self.assertLess(result["reprojection_rmse_px"], 0.6)
        self.assertLess(max(result["per_view_rmse_px"]), 0.6)


class PlaneToolTests(unittest.TestCase):
    def test_display_resize_coordinates_and_header_rejection(self):
        self.assertEqual(calibrate_plane.display_to_pixel(50, 100, (2000, 1000), (1000, 500)), [100.5, 200.5])
        self.assertEqual(calibrate_plane.display_to_pixel(50, 100, (640, 480), (640, 480)), [50.0, 100.0])
        self.assertIsNone(calibrate_plane.display_to_pixel(0, -1, (640, 480), (640, 480)))
        self.assertIsNone(calibrate_plane.display_to_pixel(640, 100, (640, 480), (640, 480)))

    def test_selection_drawing_does_not_change_raw_frame(self):
        frame = np.full((1500, 2000, 3), 100, np.uint8)
        original = frame.copy()
        canvas, display_size = calibrate_plane.draw_selection(frame, [[100, 100], [1800, 150]], True, False)
        self.assertLessEqual(display_size[0], 1100)
        self.assertLessEqual(display_size[1], 650)
        self.assertEqual(canvas.shape[0], display_size[1] + calibrate_plane.HEADER_HEIGHT)
        np.testing.assert_array_equal(frame, original)

    def _run_selection(self, output, steps, camera=False, intrinsics_path=None):
        callback = {}
        cap = MagicMock()
        cap.read.return_value = (True, make_demo())

        def register(window, handler):
            callback["mouse"] = handler

        def click_four():
            for x, y in make_demo_calibration()["corners_px"]:
                callback["mouse"](cv2.EVENT_LBUTTONDOWN, int(x), int(y) + calibrate_plane.HEADER_HEIGHT, 0, None)

        def advance(delay):
            action = steps.pop(0)
            if isinstance(action, tuple):
                if action[0] == "click":
                    click_four()
                return action[1]
            return action

        with ExitStack() as stack:
            stack.enter_context(patch("calibrate_plane.read_image", return_value=make_demo()))
            stack.enter_context(patch("calibrate_plane.open_camera", return_value=cap))
            stack.enter_context(patch("calibrate_plane.cv2.namedWindow"))
            stack.enter_context(patch("calibrate_plane.cv2.setMouseCallback", side_effect=register))
            stack.enter_context(patch("calibrate_plane.cv2.imshow"))
            stack.enter_context(patch("calibrate_plane.cv2.waitKey", side_effect=advance))
            stack.enter_context(patch("calibrate_plane.window_is_open", return_value=True))
            stack.enter_context(patch("calibrate_plane.cv2.destroyAllWindows"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            arguments = ["--width-mm", "290", "--height-mm", "195", "--output", str(output)]
            arguments += ["--camera", "0"] if camera else ["--image", "synthetic.png"]
            if intrinsics_path is not None:
                arguments += ["--intrinsics", str(intrinsics_path)]
            self.assertEqual(calibrate_plane.main(arguments), 0)
        if camera:
            cap.release.assert_called_once()
        return cap

    def test_image_clicks_save_matching_raw_configuration(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "中文平面.json"
            self._run_selection(path, [("click", ord("s"))])
            plane = load_calibration(path)
            self.assertEqual(plane["corners_px"], make_demo_calibration()["corners_px"])
            self.assertEqual(plane["pixel_frame"], "raw")

    def test_camera_requires_freeze_and_stops_reading_when_frozen(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "plane.json"
            cap = self._run_selection(path, [("click", ord("f")), ("click", ord("s"))], camera=True)
            self.assertTrue(path.exists())
            self.assertEqual(cap.read.call_count, 2)

    def test_intrinsic_corrected_selection_keeps_exact_reference(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            camera_path = Path(directory) / "camera.json"
            output = Path(directory) / "plane.json"
            camera = synthetic_intrinsics()
            save_calibration(camera_path, camera)
            self._run_selection(output, [("click", ord("s"))], intrinsics_path=camera_path)
            plane = load_calibration(output)
            self.assertEqual(plane["pixel_frame"], "undistorted")
            self.assertTrue(plane["undistorted"])
            self.assertEqual(plane["intrinsics_reference"]["id"], camera["id"])

    def test_camera_frame_failure_releases_resource(self):
        cap = MagicMock()
        cap.read.return_value = (False, None)
        with patch("calibrate_plane.open_camera", return_value=cap), \
                patch("calibrate_plane.cv2.destroyAllWindows"), redirect_stderr(io.StringIO()):
            self.assertEqual(calibrate_plane.main(["--camera", "0", "--width-mm", "210", "--height-mm", "297"]), 1)
        cap.release.assert_called_once()

    def test_existing_config_requires_y_and_cancel_preserves_bytes(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "plane.json"
            save_calibration(path, make_demo_calibration())
            before = path.read_bytes()
            self._run_selection(path, [("click", ord("s")), 27])
            self.assertEqual(path.read_bytes(), before)
            self._run_selection(path, [("click", ord("s")), ord("y")])
            self.assertNotEqual(load_calibration(path)["id"], "synthetic-demo-plane")

    def test_reset_invalidates_overwrite_confirmation(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "plane.json"
            save_calibration(path, make_demo_calibration())
            before = path.read_bytes()
            self._run_selection(path, [("click", ord("s")), ord("r"), ord("y"), 27])
            self.assertEqual(path.read_bytes(), before)

    def test_inspect_offline_and_bad_dimensions(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "plane.json"
            save_calibration(path, make_demo_calibration())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(calibrate_plane.main(["--inspect", str(path)]), 0)
            self.assertIn("pixel_to_workplane_mm", output.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(calibrate_plane.main(["--image", "demo.png", "--width-mm", "0", "--height-mm", "297"]), 1)


class ErrorEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.measurements = read_measurements(PROJECT_DIR / "samples" / "validation_example.csv")

    def test_c11_errors_match_manual_calculation(self):
        result = evaluate_measurements(self.measurements, make_demo_calibration())
        self.assertEqual(result["points"][0]["dx_mm"], 3)
        self.assertEqual(result["points"][0]["dy_mm"], 4)
        self.assertEqual(result["points"][0]["error_mm"], 5)
        self.assertAlmostEqual(result["summary"]["mean_error_mm"], 10 / 3)
        self.assertEqual(result["summary"]["max_error_mm"], 5)
        self.assertAlmostEqual(result["summary"]["rmse_mm"], np.sqrt(50 / 3))

    def test_c11_empty_invalid_duplicate_and_nan_data(self):
        for rows in ([], self.measurements[:2], [{}] * 3, [self.measurements[0]] * 3):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evaluate_measurements(rows)
        broken = deepcopy(self.measurements)
        broken[0]["predicted_x_mm"] = float("nan")
        with self.assertRaises(ValueError):
            evaluate_measurements(broken)

    def test_c11_fit_corners_and_outside_true_positions_rejected(self):
        for point in ((0, 0), (300, 100)):
            rows = deepcopy(self.measurements)
            rows[0]["true_x_mm"], rows[0]["true_y_mm"] = point
            with self.subTest(point=point), self.assertRaises(ValueError):
                evaluate_measurements(rows, make_demo_calibration())

    def test_json_and_csv_input_and_output_cli(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            source = Path(directory) / "验证.json"
            source.write_text(json.dumps(self.measurements), encoding="utf-8")
            self.assertEqual(read_measurements(source), self.measurements)
            output = Path(directory) / "report.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(evaluate_main(["--input", str(source), "--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["count"], 3)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(evaluate_main(["--input", str(source), "--output", str(output)]), 1)


class MetricIntegrationTests(unittest.TestCase):
    def test_c07_headless_original_command_has_no_mm(self):
        with patch("main.read_image", return_value=make_demo()), patch("main.export_current", return_value=True) as export, \
                patch("main.cv2.destroyAllWindows"), redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--image", "demo.png", "--no-display"]), 0)
        result = export.call_args.args[1]
        self.assertEqual(len(result["objects"]), 4)
        self.assertEqual(result["calibration"]["status"], "uncalibrated")
        self.assertTrue(all("center_mm" not in obj for obj in result["objects"]))

    def test_c09_cli_calibrated_export_and_context(self):
        with patch("main.read_image", return_value=make_demo()), patch("main.export_current", return_value=True) as export, \
                patch("main.cv2.destroyAllWindows"), redirect_stdout(io.StringIO()):
            status = main.main(["--image", "demo.png", "--calibration", str(PROJECT_DIR / "samples" / "workplane_demo.json"), "--no-display"])
        self.assertEqual(status, 0)
        result = export.call_args.args[1]
        self.assertTrue(all(obj["mm_status"] == "valid" for obj in result["objects"]))
        self.assertEqual(result["calibration"]["id"], "synthetic-demo-plane")

    def test_c06_cli_resolution_failure_writes_no_results(self):
        with patch("main.read_image", return_value=np.zeros((240, 320, 3), np.uint8)), \
                patch("main.export_current") as export, patch("main.cv2.destroyAllWindows"), redirect_stderr(io.StringIO()) as error:
            status = main.main(["--image", "small.png", "--calibration", str(PROJECT_DIR / "samples" / "workplane_demo.json"), "--no-display"])
        self.assertEqual(status, 1)
        self.assertIn("分辨率", error.getvalue())
        export.assert_not_called()

    def test_c10_cli_undistort_before_detection_and_export(self):
        intrinsics = synthetic_intrinsics()
        plane = create_plane_calibration(make_demo_calibration()["corners_px"], 290, 195,
                                         {"width": 640, "height": 480}, intrinsics=intrinsics)
        # 校正后目标故意与原图不同，证明检测/保存使用校正帧而不是原帧。
        corrected = np.zeros((480, 640, 3), np.uint8)
        cv2.rectangle(corrected, (250, 200), (350, 300), (0, 0, 255), -1)
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            camera_path, plane_path = Path(directory) / "camera.json", Path(directory) / "plane.json"
            save_calibration(camera_path, intrinsics)
            save_calibration(plane_path, plane)
            with patch("main.read_image", return_value=make_demo()), patch("main.undistort_frame", return_value=corrected), \
                    patch("main.export_current", return_value=True) as export, patch("main.cv2.destroyAllWindows"), redirect_stdout(io.StringIO()):
                status = main.main(["--image", "demo.png", "--no-display", "--intrinsics", str(camera_path), "--calibration", str(plane_path)])
        self.assertEqual(status, 0)
        annotated, result = export.call_args.args
        self.assertEqual(len(result["objects"]), 1)
        self.assertEqual(result["pixel_frame"], "undistorted")
        self.assertEqual(result["objects"][0]["center_px"], {"x": 300, "y": 250})
        np.testing.assert_allclose(list(result["objects"][0]["center_mm"].values()), [140, 100], atol=1e-6)
        self.assertEqual(tuple(annotated[250, 300]), (255, 255, 255))

    def test_c12_calibrated_camera_pause_save_release(self):
        cap = MagicMock()
        cap.read.return_value = (True, make_demo())
        with ExitStack() as stack:
            stack.enter_context(patch("main.open_camera", return_value=cap))
            stack.enter_context(patch("main.create_window"))
            stack.enter_context(patch("main.show_preview"))
            stack.enter_context(patch("main.cv2.getTrackbarPos", return_value=300))
            stack.enter_context(patch("main.cv2.getWindowProperty", return_value=1))
            stack.enter_context(patch("main.cv2.waitKey", side_effect=[ord("p"), ord("s"), ord("q")]))
            export = stack.enter_context(patch("main.export_current", return_value=True))
            stack.enter_context(patch("main.cv2.destroyAllWindows"))
            status = main.main(["--camera", "0", "--calibration", str(PROJECT_DIR / "samples" / "workplane_demo.json")])
        self.assertEqual(status, 0)
        self.assertEqual(cap.read.call_count, 1)
        cap.release.assert_called_once()
        self.assertEqual(export.call_args.args[1]["objects"][0]["mm_status"], "valid")


if __name__ == "__main__":
    unittest.main()
