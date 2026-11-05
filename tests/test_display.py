"""显示几何与拥挤标注测试；验证显示缩放不改变检测/毫米/JSON 数据。"""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from display import (DETAIL_ROW_STRIDE, LONG_AXIS_COLOR, RECT_CENTER_COLOR, ROTATED_RECT_COLOR,
                     draw_detections, fit_image_rect, initial_preview_size, label_layout, render_workbench)
from config import PROJECT_DIR
from io_utils import read_image, save_results
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


class GeometryDisplayTests(unittest.TestCase):
    """A2 离线绘图测试；合成几何是确定的源坐标，显示不应改写任何原数据。"""

    def target(self, angle=30, valid=True):
        center = np.array([160.0, 120.0])
        theta = math.radians(angle)
        along = np.array([math.cos(theta), math.sin(theta)]) * 60
        across = np.array([-math.sin(theta), math.cos(theta)]) * 20
        corners = [center - along - across, center + along - across,
                   center + along + across, center - along + across]
        low, high = np.floor(np.min(corners, axis=0)).astype(int), np.ceil(np.max(corners, axis=0)).astype(int)
        return {"id": 1, "color": "red", "center_px": {"x": 145, "y": 130},
                "bbox_xywh": {"x": int(low[0]), "y": int(low[1]), "w": int(high[0] - low[0] + 1), "h": int(high[1] - low[1] + 1)},
                "contour_area_px2": 4800.0, "center_mm": {"x": 62.5, "y": 40.0}, "mm_status": "valid",
                "geometry": {"rotated_rect_px": {"center_px": {"x": 160.0, "y": 120.0},
                    "long_side_px": 120.0, "short_side_px": 40.0, "aspect_ratio": 3.0,
                    "angle_deg": angle if valid else None, "orientation_valid": valid,
                    "corners_px": [{"x": float(x), "y": float(y)} for x, y in corners]}}}

    def frame(self):
        return np.zeros((240, 320, 3), np.uint8)

    def result(self, objects):
        return {"objects": objects, "image_size": {"width": 320, "height": 240}, "calibration": {"status": "valid"}}

    def test_rotated_horizontal_and_near_vertical_geometry_is_drawn(self):
        for angle in (0, 30, 89.5, -89.5):
            with self.subTest(angle=angle), patch("display.cv2.polylines", wraps=cv2.polylines) as poly, \
                    patch("display.cv2.line", wraps=cv2.line) as line, patch("display.cv2.circle", wraps=cv2.circle) as circle, \
                    patch("display.cv2.arrowedLine") as arrow:
                obj = self.target(angle)
                output = draw_detections(self.frame(), [obj])
                poly.assert_called_once()
                self.assertTrue(poly.call_args.args[2])
                self.assertEqual(poly.call_args.args[3], ROTATED_RECT_COLOR)
                line.assert_called_once()
                self.assertEqual(line.call_args.args[3], LONG_AXIS_COLOR)
                self.assertEqual(circle.call_args_list[-1].args[1:4], ((160, 120), 7, RECT_CENTER_COLOR))
                arrow.assert_not_called()
                self.assertEqual(tuple(output[130, 145]), (255, 255, 255))  # 原质心仍是白色十字中心。

    def test_axis_endpoints_are_symmetric_and_follow_source_angle(self):
        for angle in (0, 30, 89.5):
            with self.subTest(angle=angle), patch("display.cv2.line", wraps=cv2.line) as line:
                draw_detections(self.frame(), [self.target(angle)])
                first, second = np.array(line.call_args.args[1]), np.array(line.call_args.args[2])
                np.testing.assert_array_equal(first + second, [320, 240])
                expected_vector = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))]) * 120
                np.testing.assert_allclose(second - first, expected_vector, atol=1.1)

    def test_invalid_direction_or_null_angle_keeps_box_and_center_but_no_axis(self):
        for flag, angle in ((False, 30), (True, None), (False, None)):
            obj = self.target()
            obj["geometry"]["rotated_rect_px"].update(orientation_valid=flag, angle_deg=angle)
            with self.subTest(flag=flag, angle=angle), patch("display.cv2.line") as line, \
                    patch("display.cv2.polylines", wraps=cv2.polylines) as poly, patch("display.cv2.circle", wraps=cv2.circle) as circle, \
                    patch("display.cv2.putText", wraps=cv2.putText) as text:
                render_workbench(self.frame(), [obj], self.result([obj]), {"detail": True}, (960, 720))
                line.assert_not_called()
                poly.assert_called_once()
                self.assertGreater(circle.call_count, 0)
                strings = [c.args[1] for c in text.call_args_list]
                self.assertIn("Axis N/A | NO VALID DIRECTION", strings)
                self.assertFalse(any("Axis 30" in value for value in strings))

    def test_actual_corners_order_is_used_without_assuming_tl(self):
        obj = self.target()
        corners = obj["geometry"]["rotated_rect_px"]["corners_px"]
        obj["geometry"]["rotated_rect_px"]["corners_px"] = corners[2:] + corners[:2]
        expected = np.rint([[p["x"], p["y"]] for p in corners[2:] + corners[:2]]).astype(np.int32)
        with patch("display.cv2.polylines", wraps=cv2.polylines) as poly:
            draw_detections(self.frame(), [obj])
        np.testing.assert_array_equal(poly.call_args.args[1][0], expected)

    def test_legacy_targets_without_geometry_still_draw_and_show_details(self):
        obj = self.target()
        obj.pop("geometry")
        with patch("display.cv2.polylines") as poly, patch("display.cv2.line") as line, \
                patch("display.cv2.putText", wraps=cv2.putText) as text:
            canvas = render_workbench(self.frame(), [obj], self.result([obj]), {"detail": True}, (960, 720))
        poly.assert_not_called()
        line.assert_not_called()
        self.assertEqual(canvas.shape, (720, 960, 3))
        self.assertIn("Rect Cpx N/A", [c.args[1] for c in text.call_args_list])

    def test_malformed_optional_geometry_never_crashes_rendering(self):
        variants = [None, [], "bad", {}, {"rotated_rect_px": None}, {"rotated_rect_px": []}]
        original = self.target()["geometry"]["rotated_rect_px"]
        for field, value in (("corners_px", None), ("corners_px", []), ("corners_px", [{"x": 1, "y": 2}] * 4),
                             ("corners_px", [{"x": float("nan"), "y": 2}] * 4),
                             ("center_px", {"x": float("inf"), "y": 1}), ("center_px", {"x": 10**400, "y": 0}),
                             ("long_side_px", float("inf")), ("short_side_px", -1), ("aspect_ratio", None),
                             ("angle_deg", float("nan")), ("angle_deg", "30"), ("orientation_valid", "true")):
            variants.append({"rotated_rect_px": {**original, field: value}})
        for geometry in variants:
            with self.subTest(geometry=repr(geometry)[:60]):
                obj = self.target()
                obj["geometry"] = geometry
                before = repr(obj)
                canvas = render_workbench(self.frame(), [obj], self.result([obj]), {"detail": True}, (960, 720))
                self.assertEqual(canvas.dtype, np.uint8)
                self.assertEqual(repr(obj), before)

    def test_crossed_or_incomplete_corners_skip_polygon_and_axis(self):
        for corners in ([{"x": 10, "y": 10}, {"x": 30, "y": 30}, {"x": 30, "y": 10}, {"x": 10, "y": 30}],
                        [{"x": 10}, None, {}, {"x": 20, "y": 30}]):
            obj = self.target()
            obj["geometry"]["rotated_rect_px"]["corners_px"] = corners
            with patch("display.cv2.polylines") as poly, patch("display.cv2.line") as line, \
                    patch("display.cv2.circle", wraps=cv2.circle) as circle:
                draw_detections(self.frame(), [obj])
            poly.assert_not_called()
            line.assert_not_called()
            self.assertEqual(circle.call_count, 2)  # 有效中心仍可显示。

    def test_preview_scales_corners_center_and_axis_by_same_resize(self):
        obj = self.target(30)
        raw_corners = np.array([[p["x"], p["y"]] for p in obj["geometry"]["rotated_rect_px"]["corners_px"]])
        # 960×720 时图像区实际为674×506；800×500时为475×356，均有独立黑边偏移。
        for size, image_size, origin in (((960, 720), (674, 506), (8, 117)), ((800, 500), (475, 356), (27, 82))):
            with self.subTest(size=size), patch("display.cv2.polylines", wraps=cv2.polylines) as poly, \
                    patch("display.cv2.circle", wraps=cv2.circle) as circle, patch("display.cv2.line", wraps=cv2.line) as line:
                canvas = render_workbench(self.frame(), [obj], self.result([obj]), {}, size)
                scale = np.array(image_size) / [320, 240]
                np.testing.assert_array_equal(poly.call_args.args[1][0], np.rint(raw_corners * scale).astype(np.int32))
                expected_center = tuple(np.rint(np.array([160, 120]) * scale).astype(int))
                self.assertEqual(circle.call_args_list[-1].args[1], expected_center)
                along = np.array([math.cos(math.pi / 6), math.sin(math.pi / 6)]) * 60
                np.testing.assert_array_equal(line.call_args.args[1], np.rint((np.array([160, 120]) - along) * scale).astype(int))
                point = np.rint((np.array([160, 120]) + along * 0.6) * scale).astype(int) + origin
                patch_pixels = canvas[point[1] - 2:point[1] + 3, point[0] - 2:point[0] + 3]
                self.assertTrue(np.any(np.all(patch_pixels == LONG_AXIS_COLOR, axis=2)))

    def test_direct_draw_scaling_uses_only_drawing_copies(self):
        obj = self.target()
        before = deepcopy(obj)
        frame = np.full((120, 160, 3), 255, np.uint8)
        source = frame.copy()
        with patch("display.cv2.circle", wraps=cv2.circle) as circle:
            output = draw_detections(frame, [obj], source_size=(320, 240))
        self.assertEqual(circle.call_args_list[-1].args[1], (80, 60))
        self.assertEqual(obj, before)
        np.testing.assert_array_equal(frame, source)
        self.assertEqual(output.shape, source.shape)

    def test_all_fields_and_input_pixels_remain_identical_after_many_views(self):
        objects = [self.target(), self.target(-60, False)]
        result = self.result(objects)
        before = json.dumps(result, allow_nan=False, sort_keys=True)
        frame = self.frame()
        original = frame.copy()
        for size in ((960, 720), (800, 900), (400, 300), (960, 240)):
            for detail in (True, False):
                render_workbench(frame, objects, result, {"detail": detail}, size)
        self.assertEqual(json.dumps(result, allow_nan=False, sort_keys=True), before)
        np.testing.assert_array_equal(frame, original)

    def test_detail_displays_source_values_not_resized_values(self):
        obj = self.target()
        with patch("display.cv2.putText", wraps=cv2.putText) as text:
            render_workbench(self.frame(), [obj], self.result([obj]), {"detail": True}, (960, 720))
        strings = [c.args[1] for c in text.call_args_list]
        for expected in ("R#1  px (145, 130)", "mm (62.50, 40.00)", "Rect Cpx (160.0, 120.0)",
                         "Long 120.0 px | Short 40.0 px", "Aspect 3.000", "Axis 30.00 deg | VALID"):
            self.assertIn(expected, strings)

    def test_compact_mode_keeps_geometry_numbers_out_of_target_list(self):
        obj = self.target()
        with patch("display.cv2.putText", wraps=cv2.putText) as text:
            render_workbench(self.frame(), [obj], self.result([obj]), {"detail": False}, (960, 720))
        strings = [c.args[1] for c in text.call_args_list]
        self.assertFalse(any(s.startswith(("Rect Cpx", "Long ", "Aspect ", "Axis ")) for s in strings))
        self.assertIn("R#1  px (145, 130)", strings)

    def test_detail_pagination_has_nonoverlapping_rows_and_reaches_all_targets(self):
        objects = [{**self.target(), "id": i + 1} for i in range(13)]
        seen = set()
        for page in range(4):
            with patch("display.cv2.putText", wraps=cv2.putText) as text:
                render_workbench(self.frame(), objects, self.result(objects), {"detail": True, "page": page}, (960, 720))
            calls = [c for c in text.call_args_list if c.args[2][0] == 700]
            targets = [c for c in calls if c.args[1].startswith("R#")]
            self.assertLessEqual(len(targets), 4)
            for call in targets:
                seen.add(int(call.args[1].split()[0][2:]))
            y_positions = [call.args[2][1] for call in targets]
            self.assertTrue(all(b - a == DETAIL_ROW_STRIDE for a, b in zip(y_positions, y_positions[1:])))
            detail_lines = [c for c in calls if not c.args[1].startswith("TARGETS")]
            self.assertTrue(all(82 < c.args[2][1] < 720 - 62 for c in detail_lines))
            all_y = [c.args[2][1] for c in detail_lines]
            self.assertTrue(all(b - a >= 17 for a, b in zip(all_y, all_y[1:])))
        self.assertEqual(seen, set(range(1, 14)))

    def test_small_detail_window_prompts_enlarge_instead_of_clipping_rows(self):
        obj = self.target()
        with patch("display.cv2.putText", wraps=cv2.putText) as text:
            render_workbench(self.frame(), [obj], self.result([obj]), {"detail": True, "page": 99}, (960, 240))
        strings = [c.args[1] for c in text.call_args_list]
        self.assertIn("Enlarge height for target details", strings)
        self.assertFalse(any(s.startswith("Rect Cpx") or (s.startswith("R#") and "px (" in s) for s in strings))

    def test_mask_image_region_has_no_annotations(self):
        obj = self.target()
        frame = np.full((240, 320, 3), 255, np.uint8)
        with patch("display.draw_detections") as draw:
            canvas = render_workbench(frame, [obj], self.result([obj]), {"view": "red", "detail": True}, (960, 720))
        draw.assert_not_called()
        np.testing.assert_array_equal(canvas[117:117 + 506, 8:8 + 674], np.full((506, 674, 3), 255, np.uint8))

    def test_png_export_keeps_capture_size_and_json_geometry_exact(self):
        frame = make_demo()
        args = main.parse_args(["--image", "demo.png"])
        args.plane_data = make_demo_calibration()
        annotated, masks, result = main.analyze_frame(frame, args, "synthetic", "2026-11-05T10:00:00+08:00")
        before = deepcopy(result)
        render_workbench(frame, result["objects"], result, {"detail": True}, (960, 720))
        render_workbench(cv2.cvtColor(masks["red"], cv2.COLOR_GRAY2BGR), result["objects"], result,
                         {"detail": True, "view": "red"}, (800, 500))
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            image, data = save_results(annotated, result, Path(directory))
            self.assertEqual(read_image(image).shape, (480, 640, 3))
            np.testing.assert_array_equal(read_image(image), annotated)
            self.assertEqual(json.loads(data.read_text(encoding="utf-8")), before)
        self.assertEqual(result, before)
        self.assertEqual(result["schema_version"], "0.2")


if __name__ == "__main__":
    unittest.main()
