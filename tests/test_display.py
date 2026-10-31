"""显示几何与拥挤标注测试；验证显示缩放不改变检测/毫米/JSON 数据。"""

from copy import deepcopy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from display import draw_detections, fit_image_rect, initial_preview_size, label_layout, render_workbench
import main
from scripts.make_calibration_demo import make_demo_calibration
from scripts.make_demo import make_demo


class DisplayTests(unittest.TestCase):
    def test_letterbox_preserves_full_image_and_aspect(self):
        for size in ((640, 480), (1920, 1080), (480, 1920)):
            for bounds in ((0, 0, 960, 720), (8, 82, 674, 576), (0, 0, 320, 180)):
                x, y, width, height = fit_image_rect(size, bounds)
                self.assertGreaterEqual(x, bounds[0])
                self.assertGreaterEqual(y, bounds[1])
                self.assertLessEqual(x + width, bounds[0] + bounds[2])
                self.assertLessEqual(y + height, bounds[1] + bounds[3])
                self.assertLessEqual(abs(width - height * size[0] / size[1]), 2)

    def test_initial_size_fits_normal_laptop_work_area(self):
        self.assertEqual(initial_preview_size((1920, 1040)), (960, 720))
        width, height = initial_preview_size((1366, 728))
        self.assertLessEqual(width + 80, 1366)
        self.assertLessEqual(height + 180, 728)

    def test_window_initialized_once_and_small_area_range(self):
        with patch("main.cv2.namedWindow"), patch("main.cv2.createTrackbar") as trackbar, \
                patch("main.cv2.resizeWindow") as resize, patch("main.initial_preview_size", return_value=(960, 720)):
            main.create_window(300)
        resize.assert_called_once_with(main.WINDOW_NAME, 960, 720)
        self.assertEqual(trackbar.call_args_list[0].args[3], 5000)
        with patch("main.cv2.namedWindow"), patch("main.cv2.createTrackbar") as trackbar, patch("main.cv2.resizeWindow"):
            main.create_window(11000)
        self.assertEqual(trackbar.call_args_list[0].args[3], 11000)

    def test_dense_labels_stay_inside_and_never_overlap_each_other(self):
        objects = []
        for index in range(60):
            x, y = 50 + (index % 10) * 8, 50 + (index // 10) * 8
            objects.append({"id": index + 1, "color": "red", "center_px": {"x": x + 4, "y": y + 4},
                            "bbox_xywh": {"x": x, "y": y, "w": 8, "h": 8}, "contour_area_px2": 49.0})
        layouts = label_layout(objects, (200, 150))
        placed = [rect for rect in layouts if rect is not None]
        self.assertGreater(len(placed), 0)
        self.assertLess(len(placed), len(objects))
        for index, (x, y, w, h) in enumerate(placed):
            self.assertTrue(0 <= x <= 200 - w and 0 <= y <= 150 - h)
            for sx, sy, sw, sh in placed[index + 1:]:
                self.assertFalse(x < sx + sw and sx < x + w and y < sy + sh and sy < y + h)
        original = deepcopy(objects)
        frame = np.full((150, 200, 3), 255, np.uint8)
        annotated = draw_detections(frame, objects)
        self.assertEqual(objects, original)
        self.assertTrue((frame == 255).all())
        self.assertEqual(annotated.shape, frame.shape)

    def test_workbench_resizes_without_mutating_pixels_mm_or_json(self):
        args = main.parse_args(["--image", "demo.png"])
        args.plane_data = make_demo_calibration()
        frame = make_demo()
        original_frame = frame.copy()
        annotated, _, result = main.analyze_frame(frame, args, "synthetic", "2026-10-31T10:00:00+08:00")
        before = deepcopy(result)
        for width, height in ((960, 720), (1280, 600), (800, 900), (400, 300)):
            canvas = render_workbench(frame, result["objects"], result, {"detail": True}, (width, height))
            self.assertEqual(canvas.shape, (height, width, 3))
        self.assertEqual(result, before)
        np.testing.assert_array_equal(frame, original_frame)
        self.assertEqual(annotated.shape, frame.shape)
        self.assertEqual(result["schema_version"], "0.2")
        np.testing.assert_allclose(list(result["objects"][0]["center_mm"].values()), [45, 40], atol=1e-6)

    def test_uncalibrated_appears_only_once_in_workbench(self):
        args = main.parse_args(["--image", "demo.png"])
        frame = make_demo()
        _, _, result = main.analyze_frame(frame, args, "synthetic", "2026-10-31T10:00:00+08:00")
        with patch("display.cv2.putText", wraps=cv2.putText) as put:
            render_workbench(frame, result["objects"], result, {}, (960, 720))
        strings = [call.args[1] for call in put.call_args_list]
        self.assertEqual(sum(text.count("UNCALIBRATED") for text in strings), 1)

    def test_detailed_list_contains_real_px_mm_and_outside_status(self):
        args = main.parse_args(["--image", "demo.png"])
        args.plane_data = make_demo_calibration()
        frame = make_demo()
        _, _, result = main.analyze_frame(frame, args, "synthetic", "2026-10-31T10:00:00+08:00")
        result["objects"][1].pop("center_mm")
        result["objects"][1]["mm_status"] = "outside_roi"
        result["objects"][2].pop("center_mm")
        result["objects"][2]["mm_status"] = "invalid_transform"
        with patch("display.cv2.putText", wraps=cv2.putText) as put:
            render_workbench(frame, result["objects"], result, {"detail": True}, (960, 720))
        strings = [call.args[1] for call in put.call_args_list]
        self.assertIn("R#1  px (110, 130)", strings)
        self.assertIn("mm (45.00, 40.00)", strings)
        self.assertIn("OUTSIDE ROI", strings)
        self.assertIn("INVALID MM", strings)

    def test_target_list_pagination_reaches_every_object_and_clamps(self):
        args = main.parse_args(["--image", "demo.png"])
        frame = make_demo()
        _, _, result = main.analyze_frame(frame, args, "synthetic", "2026-10-31T10:00:00+08:00")
        result["objects"] = [{**result["objects"][0], "id": index + 1} for index in range(40)]
        seen = set()
        for page in range(20):
            ui = {"page": page}
            with patch("display.cv2.putText", wraps=cv2.putText) as put:
                render_workbench(frame, result["objects"], result, ui, (960, 720))
            for call in put.call_args_list:
                if call.args[1].startswith("R#") and "px (" in call.args[1]:
                    seen.add(int(call.args[1].split()[0][2:]))
        self.assertEqual(seen, set(range(1, 41)))
        self.assertLess(ui["page"], 20)

    def test_keyboard_detail_paging_and_one_pixel_area_steps(self):
        args = main.parse_args(["--image", "demo.png", "--min-area", "300"])
        with patch("main.cv2.setTrackbarPos") as slider:
            main.handle_view_key(ord("+"), args)
            slider.assert_called_with("Min area", main.WINDOW_NAME, 301)
            main.handle_view_key(ord("-"), args)
            slider.assert_called_with("Min area", main.WINDOW_NAME, 299)
        main.handle_view_key(ord("D"), args)
        self.assertTrue(args.ui["detail"])
        main.handle_view_key(ord("]"), args)
        self.assertEqual(args.ui["page"], 1)
        main.handle_view_key(ord("["), args)
        self.assertEqual(args.ui["page"], 0)
        self.assertEqual(main.parse_args(["--min-area", "11000"]).area_max, 11000)

    def test_preview_obeys_current_window_size_and_never_resizes_window(self):
        frame = make_demo()
        args = main.parse_args(["--image", "demo.png"])
        annotated, masks, result = main.analyze_frame(frame, args, "synthetic", "2026-10-31T10:00:00+08:00")
        with patch("main.cv2.getTrackbarPos", return_value=0), \
                patch("main.cv2.getWindowImageRect", return_value=(0, 0, 800, 500)), \
                patch("main.cv2.imshow") as show, patch("main.cv2.resizeWindow") as resize:
            main.show_preview(annotated, masks, result, args.ui, frame)
        self.assertEqual(show.call_args.args[1].shape, (500, 800, 3))
        resize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
