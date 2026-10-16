"""T01~T05：验证合成图、几何定位、噪点过滤与实际文件导出。"""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from config import PROJECT_DIR
from io_utils import build_result, read_image, save_results
from scripts.make_demo import make_demo
from vision import annotate_frame, contour_center, create_masks, detect_objects


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
                self.assertEqual(set(obj), {"id", "color", "center_px", "bbox_xywh", "contour_area_px2"})
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


if __name__ == "__main__":
    unittest.main()
