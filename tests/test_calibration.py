"""C01~C10：可重复合成数据上的 H、区域、配置与坐标空间约束。"""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from calibration import (add_workplane_coordinates, check_frame_context, create_plane_calibration,
                         intrinsics_reference, load_calibration, pixel_to_workplane, save_calibration,
                         undistort_frame, validate_intrinsics, validate_plane_calibration)
from config import PROJECT_DIR
from io_utils import build_result, read_image, save_results
from scripts.make_calibration_demo import make_demo_calibration
from scripts.make_demo import make_demo
from tests.calibration_fixtures import synthetic_intrinsics
from vision import annotate_frame, detect_objects


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.plane = make_demo_calibration()
        self.size = {"width": 640, "height": 480}

    def test_c01_four_corner_mapping_and_axes(self):
        expected = [[0, 0], [290, 0], [290, 195], [0, 195]]
        for point, true_point in zip(self.plane["corners_px"], expected):
            converted, status = pixel_to_workplane(point, self.plane)
            self.assertEqual(status, "valid")
            np.testing.assert_allclose([converted["x"], converted["y"]], true_point, atol=1e-6)
        self.assertEqual(self.plane["origin"], "TL")
        self.assertEqual(self.plane["axes"], {"x": "TL_to_TR", "y": "TL_to_BL"})

    def test_c02_perspective_independent_internal_points(self):
        quad = np.float32([[90, 60], [520, 100], [570, 420], [50, 380]])
        world = np.float32([[0, 0], [300, 0], [300, 200], [0, 200]])
        plane = create_plane_calibration(quad, 300, 200, self.size)
        world_to_pixel = cv2.getPerspectiveTransform(world, quad)
        # 这些内部点没有用于求解 plane.H，误差允许 0.0001 mm（只限合成数学数据）。
        internal = np.float64([[[40, 30], [120, 80], [260, 170], [180, 120]]])
        pixels = cv2.perspectiveTransform(internal, world_to_pixel)[0]
        for point, expected in zip(pixels, internal[0]):
            converted, status = pixel_to_workplane(point, plane)
            self.assertEqual(status, "valid")
            np.testing.assert_allclose([converted["x"], converted["y"]], expected, atol=1e-4)

    def test_c03_invalid_quadrilaterals(self):
        valid = np.array(self.plane["corners_px"])
        cases = [valid[[0, 2, 1, 3]], valid[::-1], valid[[1, 2, 3, 0]],
                 [[20, 20], [30, 30], [40, 40], [50, 50]],
                 [[20, 20], [20, 20], [400, 400], [20, 400]],
                 [[20, 20], [30, 20], [30, 30], [20, 30]],
                 [[-1, 20], [300, 20], [300, 300], [20, 300]],
                 [[20, 20], [float("nan"), 20], [300, 300], [20, 300]],
                 [[20, 20], [300, 20], [400, 20.00001], [20, 300]]]
        for points in cases:
            with self.subTest(points=points), self.assertRaises(ValueError):
                create_plane_calibration(points, 210, 297, self.size)

    def test_c03_invalid_dimensions_and_types(self):
        for value in (0, -1, float("nan"), float("inf"), True, "210", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                create_plane_calibration(self.plane["corners_px"], value, 297, self.size)
        for size in ({"width": True, "height": 480}, {"width": 640.0, "height": 480}, {}):
            with self.subTest(size=size), self.assertRaises(ValueError):
                create_plane_calibration(self.plane["corners_px"], 210, 297, size)

    def test_c04_roundtrip_raw_and_undistorted(self):
        intrinsics = synthetic_intrinsics()
        corrected = create_plane_calibration(self.plane["corners_px"], 290, 195, self.size, "synthetic", intrinsics)
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            for index, data in enumerate((self.plane, corrected, intrinsics)):
                path = Path(directory) / "中文标定" / f"{index}.json"
                save_calibration(path, data)
                kind = data["calibration_type"]
                self.assertEqual(load_calibration(path, kind), data)
                with self.assertRaises(FileExistsError):
                    save_calibration(path, data)
                save_calibration(path, data, overwrite=True)
        self.assertEqual(corrected["intrinsics_reference"], intrinsics_reference(intrinsics))

    def test_c05_missing_required_plane_fields(self):
        for field in ("schema_version", "calibration_type", "id", "created_at", "image_size", "width_mm", "height_mm",
                      "corners_px", "H", "origin", "axes", "corner_order", "matrix_direction", "pixel_frame", "undistorted", "intrinsics_reference"):
            broken = deepcopy(self.plane)
            del broken[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_plane_calibration(broken)

    def test_c05_corrupt_matrices_versions_and_units(self):
        cases = {"schema_version": "0.1", "H": [[0] * 3] * 3, "axes": {"x": "robot_x", "y": "robot_y"},
                 "matrix_direction": "mm_to_pixel", "pixel_frame": "other", "undistorted": True, "created_at": "yesterday"}
        for field, value in cases.items():
            broken = deepcopy(self.plane)
            broken[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_plane_calibration(broken)
        for matrix in (np.eye(3).tolist(), [[1, 0, 0], [0, 1, 0], [0, 0, float("nan")]], [[1, 0], [0, 1]]):
            broken = deepcopy(self.plane)
            broken["H"] = matrix
            with self.assertRaises(ValueError):
                validate_plane_calibration(broken)

    def test_c05_corrupt_json_has_clear_error(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            path = Path(directory) / "bad.json"
            for text in ("not JSON", "[]", "{}", "null"):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(ValueError):
                    load_calibration(path)
            path.write_text(json.dumps(self.plane), encoding="utf-8-sig")
            self.assertEqual(load_calibration(path), self.plane)

    def test_c06_resolution_mismatch_is_rejected_even_with_no_objects(self):
        for size in ({"width": 320, "height": 240}, {"width": 640, "height": 481}):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "分辨率"):
                add_workplane_coordinates([], self.plane, size)

    def test_c07_no_plane_preserves_pixel_fields(self):
        frame = make_demo()
        objects, _ = detect_objects(frame)
        converted = add_workplane_coordinates(objects, None, self.size)
        for original, actual in zip(objects, converted):
            self.assertEqual({key: actual[key] for key in original}, original)
            self.assertEqual(actual["mm_status"], "uncalibrated")
            self.assertNotIn("center_mm", actual)
        self.assertNotIn("mm_status", objects[0])
        self.assertEqual(add_workplane_coordinates([], None, self.size), [])

    def test_c08_outside_roi_has_no_mm_and_boundary_is_valid(self):
        for point in ([0, 0], [610, 300], [100, 450]):
            with self.subTest(point=point):
                self.assertEqual(pixel_to_workplane(point, self.plane), (None, "outside_roi"))
        self.assertEqual(pixel_to_workplane([20, 200], self.plane)[1], "valid")

    def test_c09_detection_export_same_pixel_and_mm_frame(self):
        frame = make_demo()
        objects, _ = detect_objects(frame)
        converted = add_workplane_coordinates(objects, self.plane, self.size)
        self.assertEqual(converted[0]["center_px"], {"x": 110, "y": 130})
        np.testing.assert_allclose(list(converted[0]["center_mm"].values()), [45, 40], atol=1e-6)
        result = build_result(frame, converted, "synthetic:demo", plane=self.plane)
        self.assertEqual(result["schema_version"], "0.2")
        self.assertEqual(result["coordinate_system"], "image_pixel")
        self.assertEqual(result["workplane_coordinate_system"], "workplane_mm")
        self.assertEqual(result["pixel_frame"], "raw")
        self.assertEqual(result["calibration"]["id"], self.plane["id"])
        self.assertIsNotNone(datetime.fromisoformat(result["timestamp"]).tzinfo)
        annotated = annotate_frame(frame, converted)
        with tempfile.TemporaryDirectory(dir=PROJECT_DIR / "outputs") as directory:
            png, metadata = save_results(annotated, result, Path(directory))
            np.testing.assert_array_equal(read_image(png), annotated)
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8")), result)

    def test_c10_zero_distortion_preserves_frame_and_raw_mode(self):
        frame = make_demo()
        self.assertIs(undistort_frame(frame), frame)
        np.testing.assert_allclose(undistort_frame(frame, synthetic_intrinsics()), frame, atol=1)

    def test_c10_wrong_intrinsic_resolution_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "分辨率"):
            undistort_frame(np.zeros((240, 320, 3), np.uint8), synthetic_intrinsics())

    def test_c10_raw_and_undistorted_cannot_mix(self):
        intrinsics = synthetic_intrinsics()
        with self.assertRaisesRegex(ValueError, "去畸变"):
            check_frame_context(self.plane, self.size, intrinsics)
        plane = create_plane_calibration(self.plane["corners_px"], 290, 195, self.size, intrinsics=intrinsics)
        check_frame_context(plane, self.size, intrinsics)
        with self.assertRaises(ValueError):
            check_frame_context(plane, self.size)
        changed = deepcopy(intrinsics)
        changed["distortion_coefficients"][0] = 0.01
        with self.assertRaises(ValueError):
            check_frame_context(plane, self.size, changed)

    def test_c10_invalid_intrinsic_fields(self):
        source = synthetic_intrinsics()
        for field in ("camera_matrix", "distortion_coefficients", "image_size", "undistort_method", "created_at", "id"):
            broken = deepcopy(source)
            del broken[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_intrinsics(broken)
        for field, value in (("distortion_coefficients", [0, 0, 0]), ("camera_matrix", np.zeros((3, 3)).tolist()),
                             ("distortion_coefficients", [float("inf")] * 5), ("reprojection_rmse_px", -1),
                             ("valid_views", True), ("per_view_rmse_px", [1])):
            broken = deepcopy(source)
            broken[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_intrinsics(broken)

    def test_invalid_runtime_point_never_produces_mm(self):
        with self.assertRaises(ValueError):
            pixel_to_workplane([float("nan"), 100], self.plane)


if __name__ == "__main__":
    unittest.main()
