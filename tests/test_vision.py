"""T01~T05：验证合成图、几何定位、噪点过滤与实际文件导出。"""

from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from config import PROJECT_DIR
from calibration import add_workplane_coordinates
from io_utils import build_result, read_image, save_results
from scripts.make_demo import make_demo
from scripts.make_calibration_demo import make_demo_calibration
from vision import annotate_frame, contour_center, create_masks, detect_objects, rotated_rect_geometry


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.frame = make_demo()
        self.objects, self.masks = detect_objects(self.frame)

    def test_t01_all_three_colors(self):
        self.assertEqual(set(obj["color"] for obj in self.objects), {"red", "green", "blue"})
        self.assertEqual(len(self.objects), 4)

    def test_t02_two_red_objects_and_unique_ids(self):
        self.assertEqual(Counter(obj["color"] for obj in self.objects)["red"], 2)
        self.assertEqual([obj["id"] for obj in self.objects], [1, 2, 3, 4])

    def test_t03_known_centers_with_one_pixel_tolerance(self):
        expected = [(110, 130), (290, 130), (480, 140), (180, 340)]
        for obj, (x, y) in zip(self.objects, expected):
            self.assertLessEqual(abs(obj["center_px"]["x"] - x), 1)
            self.assertLessEqual(abs(obj["center_px"]["y"] - y), 1)
        self.assertEqual(self.objects[0]["bbox_xywh"], {"x": 60, "y": 80, "w": 101, "h": 101})
        self.assertEqual(self.objects[0]["contour_area_px2"], 10000.0)

    def test_t04_blank_is_empty(self):
        objects, masks = detect_objects(np.zeros((120, 180, 3), dtype=np.uint8))
        self.assertEqual(objects, [])
        self.assertTrue(all(not mask.any() for mask in masks.values()))

    def test_t04_noise_is_filtered_by_area(self):
        # 5x5 噪点能通过 3x3 开运算，但轮廓面积仅 16，低于默认阈值。
        noise_only = self.frame[330:380, 430:540].copy()
        self.assertEqual(detect_objects(noise_only)[0], [])
        self.assertEqual(len(detect_objects(noise_only, 1)[0]), 3)

    def test_min_area_changes_detection(self):
        self.assertEqual(len(detect_objects(self.frame, 11000)[0]), 1)

    def test_red_wraps_both_hue_endpoints(self):
        hsv = np.zeros((100, 180, 3), dtype=np.uint8)
        hsv[20:70, 10:60] = (0, 255, 255)
        hsv[20:70, 100:150] = (179, 255, 255)
        objects, _ = detect_objects(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
        self.assertEqual([obj["color"] for obj in objects], ["red", "red"])

    def test_masks_are_binary_and_frame_sized(self):
        for mask in self.masks.values():
            self.assertEqual(mask.shape, self.frame.shape[:2])
            self.assertEqual(mask.dtype, np.uint8)
            self.assertTrue(set(np.unique(mask)).issubset({0, 255}))

    def test_zero_moment_falls_back(self):
        line = np.array([[[10, 20]], [[30, 20]]], dtype=np.int32)
        self.assertEqual(contour_center(line), (20, 20))

    def test_annotation_does_not_change_input(self):
        original = self.frame.copy()
        annotated = annotate_frame(self.frame, self.objects, fps=12.5, paused=True)
        np.testing.assert_array_equal(self.frame, original)
        self.assertFalse(np.array_equal(annotated, original))
        # 纯色目标内部也应清楚显示中心，避免同色标记融入目标。
        for obj in self.objects:
            center = obj["center_px"]
            self.assertEqual(tuple(annotated[center["y"], center["x"]]), (255, 255, 255))

    def test_invalid_images_and_areas(self):
        for invalid in (None, np.zeros((0, 0, 3), np.uint8),
                        np.zeros((10, 10), np.uint8), np.zeros((10, 10, 3), float)):
            with self.subTest(image=type(invalid)), self.assertRaises(ValueError):
                create_masks(invalid)
        for area in (0, -1, float("nan"), float("inf")):
            with self.subTest(area=area), self.assertRaises(ValueError):
                detect_objects(self.frame, area)

    def test_t05_png_json_fields_and_same_frame(self):
        annotated = annotate_frame(self.frame, self.objects)
        result = build_result(self.frame, self.objects, "image:demo.png")
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            image_path, json_path = save_results(annotated, result, Path(directory) / "中文路径")
            self.assertEqual(image_path.stem, json_path.stem)
            np.testing.assert_array_equal(read_image(image_path), annotated)
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, result)
            self.assertEqual(saved["schema_version"], "0.2")
            self.assertEqual(saved["coordinate_system"], "image_pixel")
            self.assertEqual(saved["image_size"], {"width": 640, "height": 480})
            self.assertIsNotNone(datetime.fromisoformat(saved["timestamp"]).tzinfo)
            self.assertNotIn("confidence", json.dumps(saved))
            for obj in saved["objects"]:
                self.assertEqual(set(obj), {"id", "color", "center_px", "bbox_xywh", "contour_area_px2", "geometry"})
            next_image, _ = save_results(annotated, result, Path(directory) / "中文路径")
            self.assertNotEqual(next_image, image_path)
            self.assertTrue(image_path.is_file())

    def test_export_rejects_mismatched_dimensions(self):
        result = build_result(self.frame, self.objects, "image:demo.png")
        with self.assertRaisesRegex(ValueError, "尺寸"):
            save_results(self.frame[:100], result)

    def test_export_failure_removes_partial_image(self):
        result = build_result(self.frame, self.objects, "image:demo.png")
        real_open = Path.open

        def fail_json(path, *args, **kwargs):
            if path.suffix == ".json":
                raise PermissionError("模拟 JSON 写入失败")
            return real_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            with patch.object(Path, "open", fail_json), self.assertRaises(PermissionError):
                save_results(self.frame, result, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bad_image_paths_and_content(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "bad.png"
            with self.assertRaisesRegex(FileNotFoundError, "图片不存在"):
                read_image(path)
            for contents in (b"", b"this is not an image"):
                path.write_bytes(contents)
                with self.assertRaisesRegex(ValueError, "无法解码"):
                    read_image(path)


class RotatedGeometryTests(unittest.TestCase):
    """尺寸/角度期望来自手工几何模型，不用 minAreaRect/boxPoints 构造期望。"""

    @staticmethod
    def rectangle_points(center=(160, 140), long_side=140, short_side=44, angle=30):
        theta = math.radians(angle)
        along = np.array([math.cos(theta), math.sin(theta)]) * (long_side / 2)
        across = np.array([-math.sin(theta), math.cos(theta)]) * (short_side / 2)
        return np.array([center - along - across, center + along - across,
                         center + along + across, center - along + across], dtype=np.float32)

    def rectangle_image(self, angle=30, long_side=140, short_side=44):
        image = np.zeros((320, 320, 3), np.uint8)
        points = np.rint(self.rectangle_points(angle=angle, long_side=long_side, short_side=short_side)).astype(np.int32)
        cv2.fillConvexPoly(image, points, (0, 0, 255))
        return image

    def single_geometry(self, image):
        objects, _ = detect_objects(image)
        self.assertEqual(len(objects), 1)
        return objects[0]["geometry"]["rotated_rect_px"]

    def test_horizontal_rectangle_lengths_center_and_angle(self):
        image = np.zeros((200, 260, 3), np.uint8)
        cv2.rectangle(image, (40, 70), (200, 130), (0, 0, 255), -1)
        geometry = self.single_geometry(image)
        self.assertAlmostEqual(geometry["long_side_px"], 160, places=4)
        self.assertAlmostEqual(geometry["short_side_px"], 60, places=4)
        self.assertAlmostEqual(geometry["aspect_ratio"], 160 / 60, places=6)
        self.assertEqual(geometry["center_px"], {"x": 120.0, "y": 100.0})
        self.assertAlmostEqual(geometry["angle_deg"], 0, places=4)
        self.assertTrue(geometry["orientation_valid"])
        self.assertEqual(geometry["corners_px"], [{"x": 40.0, "y": 70.0}, {"x": 200.0, "y": 70.0},
                                                  {"x": 200.0, "y": 130.0}, {"x": 40.0, "y": 130.0}])

    def test_rotated_rectangles_and_angle_normalization(self):
        for angle, expected in ((-80, -80), (-35, -35), (-5, -5), (25, 25), (60, 60),
                                (89, 89), (90, -90), (110, -70), (170, -10)):
            with self.subTest(angle=angle):
                geometry = self.single_geometry(self.rectangle_image(angle))
                self.assertAlmostEqual(geometry["long_side_px"], 140, delta=2)
                self.assertAlmostEqual(geometry["short_side_px"], 44, delta=2)
                self.assertAlmostEqual(geometry["center_px"]["x"], 160, delta=0.6)
                self.assertAlmostEqual(geometry["center_px"]["y"], 140, delta=0.6)
                self.assertAlmostEqual(geometry["angle_deg"], expected, delta=0.8)
                self.assertGreaterEqual(geometry["angle_deg"], -90)
                self.assertLess(geometry["angle_deg"], 90)

    def test_fractional_rotated_center_is_not_rounded_to_centroid(self):
        points = self.rectangle_points(center=(100.25, 75.5), long_side=110, short_side=40, angle=17)
        geometry = rotated_rect_geometry(points)
        self.assertIsInstance(geometry["center_px"]["x"], float)
        self.assertAlmostEqual(geometry["center_px"]["x"], 100.25, delta=1e-4)
        self.assertAlmostEqual(geometry["center_px"]["y"], 75.5, delta=1e-4)

    def test_circle_has_no_reliable_orientation(self):
        image = np.zeros((200, 200, 3), np.uint8)
        cv2.circle(image, (100, 100), 40, (255, 0, 0), -1)
        geometry = self.single_geometry(image)
        self.assertLess(geometry["aspect_ratio"], 1.10)
        self.assertFalse(geometry["orientation_valid"])
        self.assertIsNone(geometry["angle_deg"])

    def test_near_squares_including_rotated_square_have_no_angle(self):
        for angle in (0, 28, 45, 80):
            with self.subTest(angle=angle):
                geometry = self.single_geometry(self.rectangle_image(angle, 104, 100))
                self.assertLess(geometry["aspect_ratio"], 1.10)
                self.assertFalse(geometry["orientation_valid"])
                self.assertIsNone(geometry["angle_deg"])

    def test_reliability_threshold_is_inclusive_at_1_10(self):
        for long_side, expected in ((109, False), (110, True), (111, True)):
            with self.subTest(long_side=long_side):
                geometry = rotated_rect_geometry(self.rectangle_points(long_side=long_side, short_side=100, angle=0))
                self.assertEqual(geometry["orientation_valid"], expected)
                self.assertEqual(geometry["angle_deg"] is not None, expected)

    def test_corners_are_clockwise_with_stable_start_and_in_frame_for_interior_objects(self):
        for angle in (-70, -20, 0, 35, 45, 90):
            with self.subTest(angle=angle):
                image = self.rectangle_image(angle)
                corners = self.single_geometry(image)["corners_px"]
                points = np.array([[point["x"], point["y"]] for point in corners])
                self.assertEqual(len(points), 4)
                self.assertEqual((corners[0]["y"], corners[0]["x"]), min((p["y"], p["x"]) for p in corners))
                # 图像 Y 向下：鞋带公式有向面积为正，对应画面顺时针。
                signed_twice_area = np.sum(points[:, 0] * np.roll(points[:, 1], -1) - points[:, 1] * np.roll(points[:, 0], -1))
                self.assertGreater(signed_twice_area, 0)
                self.assertTrue((points >= 0).all())
                self.assertTrue((points[:, 0] < image.shape[1]).all())
                self.assertTrue((points[:, 1] < image.shape[0]).all())
                lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
                np.testing.assert_allclose(lengths, np.roll(lengths, 2), atol=1e-4)

    def test_corner_order_does_not_depend_on_input_vertex_start_or_direction(self):
        points = self.rectangle_points(angle=23)
        expected = rotated_rect_geometry(points)
        expected_corners = [[p["x"], p["y"]] for p in expected["corners_px"]]
        for shift in range(4):
            for direction in (1, -1):
                actual = rotated_rect_geometry(np.roll(points, shift, axis=0)[::direction])
                np.testing.assert_allclose([[p["x"], p["y"]] for p in actual["corners_px"]], expected_corners, atol=1e-4)
                self.assertAlmostEqual(actual["angle_deg"], expected["angle_deg"], delta=1e-4)

    def test_border_enclosing_rectangle_is_not_clipped_or_rescaled(self):
        points = np.array([[0, 50], [50, 0], [100, 100]], np.float32)
        geometry = rotated_rect_geometry(points)
        corners = np.array([[p["x"], p["y"]] for p in geometry["corners_px"]], np.float32)
        self.assertLess(corners.min(), 0)  # 最小外接矩形允许超出图像，不裁角破坏几何。
        for point in points:
            self.assertGreaterEqual(cv2.pointPolygonTest(corners, tuple(map(float, point)), True), -1e-4)

    def test_asymmetric_object_keeps_moment_centroid_separate_from_rect_center(self):
        image = np.zeros((200, 200, 3), np.uint8)
        polygon = np.array([[30, 30], [150, 30], [150, 60], [60, 60], [60, 150], [30, 150]], np.int32)
        cv2.fillPoly(image, [polygon], (0, 255, 0))
        objects, masks = detect_objects(image)
        contours, _ = cv2.findContours(masks["green"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        obj = objects[0]
        self.assertEqual(obj["center_px"], {"x": 71, "y": 71})
        self.assertEqual(tuple(obj["center_px"].values()), contour_center(contours[0]))
        self.assertEqual(obj["geometry"]["rotated_rect_px"]["center_px"], {"x": 90.0, "y": 90.0})
        self.assertEqual(obj["bbox_xywh"], {"x": 30, "y": 30, "w": 121, "h": 121})
        self.assertEqual(obj["contour_area_px2"], cv2.contourArea(contours[0]))

    def test_blank_and_small_noise_detection_is_unchanged(self):
        image = np.zeros((100, 100, 3), np.uint8)
        self.assertEqual(detect_objects(image)[0], [])
        cv2.rectangle(image, (20, 20), (24, 24), (0, 0, 255), -1)
        self.assertEqual(detect_objects(image)[0], [])
        objects, _ = detect_objects(image, 1)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["contour_area_px2"], 16)
        self.assertFalse(objects[0]["geometry"]["rotated_rect_px"]["orientation_valid"])

    def test_degenerate_and_nonfinite_contours_have_no_geometry(self):
        for points in (np.empty((0, 1, 2), np.int32), np.array([[1, 2]], np.float32),
                       np.array([[0, 0], [10, 0], [20, 0]], np.float32),
                       np.array([[0, 0], [1, 0], [0, float("nan")]], np.float32),
                       np.array([[0, 0], [1, 0], [0, float("inf")]], np.float32)):
            with self.subTest(points=points):
                self.assertIsNone(rotated_rect_geometry(points))

    def test_mm_mapping_preserves_geometry_and_existing_centroids(self):
        objects, _ = detect_objects(make_demo())
        before = deepcopy(objects)
        plane = make_demo_calibration()
        converted = add_workplane_coordinates(objects, plane, {"width": 640, "height": 480})
        self.assertEqual(objects, before)
        for obj, original, expected in zip(converted, before, ((45, 40), (135, 40), (230, 45), (80, 145))):
            for field in ("id", "color", "center_px", "bbox_xywh", "contour_area_px2", "geometry"):
                self.assertEqual(obj[field], original[field])
            self.assertEqual(obj["mm_status"], "valid")
            self.assertAlmostEqual(obj["center_mm"]["x"], expected[0], places=5)
            self.assertAlmostEqual(obj["center_mm"]["y"], expected[1], places=5)

    def test_actual_json_export_contains_finite_geometry_and_null_invalid_angle(self):
        frame = make_demo()
        objects, _ = detect_objects(frame)
        objects = add_workplane_coordinates(objects, make_demo_calibration(), {"width": 640, "height": 480})
        result = build_result(frame, objects, "synthetic", plane=make_demo_calibration())
        json.dumps(result, allow_nan=False)
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            _, path = save_results(annotate_frame(frame, objects), result, Path(directory))
            payload = path.read_text(encoding="utf-8")
            self.assertNotIn("NaN", payload)
            self.assertNotIn("Infinity", payload)
            saved = json.loads(payload)
            self.assertEqual(saved, result)
            self.assertEqual(saved["schema_version"], "0.2")
            self.assertIn("center_mm", saved["objects"][0])
            circle = next(obj for obj in saved["objects"] if obj["color"] == "blue")
            self.assertIsNone(circle["geometry"]["rotated_rect_px"]["angle_deg"])

    def test_legacy_objects_without_optional_geometry_still_export(self):
        frame = make_demo()
        objects, _ = detect_objects(frame)
        for obj in objects:
            obj.pop("geometry")
        result = build_result(frame, objects, "legacy")
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            _, path = save_results(frame, result, Path(directory))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(all("geometry" not in obj for obj in saved["objects"]))
            self.assertEqual(saved["objects"], objects)


if __name__ == "__main__":
    unittest.main()
