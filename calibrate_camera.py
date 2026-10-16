"""独立棋盘格相机内参工具；不是四点平面标定的必需前置步骤。"""

import argparse
import hashlib
from datetime import datetime
from pathlib import Path
import sys
from uuid import uuid4

import cv2
import numpy as np

from calibration import (MIN_VIEWS, SCHEMA_VERSION, finite_array, positive_number,
                         save_calibration, validate_image_size, validate_intrinsics)
from config import PROJECT_DIR
from io_utils import read_image


def board_object_points(board_size, square_mm):
    """返回棋盘格内角点的 (N,3) 毫米坐标；board_size 为（列数,行数），不是方格数。

    棋盘格是 Z=0 的平面。格子尺寸只决定平移尺度，不表示已获得机械坐标。
    参数不合法时抛 ValueError；输出为 OpenCV 要求的 float32。
    """
    if not isinstance(board_size, (tuple, list)) or len(board_size) != 2 or any(type(n) is not int or n < 2 for n in board_size):
        raise ValueError("内角点列数/行数必须是大于等于 2 的整数。")
    square_mm = positive_number(square_mm, "square_mm（单格实测毫米边长）")
    columns, rows = board_size
    points = np.zeros((columns * rows, 3), dtype=np.float32)
    points[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2)
    points *= square_mm
    return points


def calibrate_from_points(image_points, image_size, board_size, square_mm):
    """由多幅图的亚像素内角点求 K、畸变和实际重投影 RMSE，输出标定字典。

    image_points 中每幅为 (N,2) pixel 数组；至少 5 幅不同角点集合。
    断点看 object_points、camera_matrix、projected、squared_errors。
    照片数量不足、重复观测、非法数组或求解失败会抛 ValueError。
    """
    size = validate_image_size(image_size)
    board_points = board_object_points(board_size, square_mm)
    if len(image_points) < MIN_VIEWS:
        raise ValueError(f"至少需要 {MIN_VIEWS} 幅不同视角的有效棋盘格照片，建议 15~25 幅。")
    observations, fingerprints = [], set()
    for points in image_points:
        array = finite_array(points, (len(board_points), 2), "棋盘格角点")
        if (array < 0).any() or (array[:, 0] >= size["width"]).any() or (array[:, 1] >= size["height"]).any():
            raise ValueError("棋盘格角点超出图像范围。")
        fingerprint = hashlib.sha256(np.round(array, 3).tobytes()).hexdigest()
        if fingerprint in fingerprints:
            raise ValueError("检测到重复棋盘格观测，请拍摄不同角度和位置的照片。")
        fingerprints.add(fingerprint)
        observations.append(array.astype(np.float32).reshape(-1, 1, 2))
    object_points = [board_points.copy() for _ in observations]
    try:
        rms, camera_matrix, coefficients, rvecs, tvecs = cv2.calibrateCamera(
            object_points, observations, (size["width"], size["height"]), None, None)
    except cv2.error as exc:
        raise ValueError("相机内参求解失败，请检查内角点规格、清晰度与视角多样性。") from exc
    if not np.isfinite(rms) or rms < 0:
        raise ValueError("相机内参求解得到无效的重投影误差。")
    squared_errors, per_view_rmse = [], []
    for observed, rotation, translation in zip(observations, rvecs, tvecs):
        projected, _ = cv2.projectPoints(board_points, rotation, translation, camera_matrix, coefficients)
        # 每个角点的二维误差平方 dx²+dy²；先对所有点平均，再开方，单位 pixel。
        squared = np.sum((observed.reshape(-1, 2) - projected.reshape(-1, 2)) ** 2, axis=1)
        squared_errors.extend(squared.tolist())
        per_view_rmse.append(float(np.sqrt(np.mean(squared))))
    data = {
        "schema_version": SCHEMA_VERSION, "calibration_type": "camera_intrinsics", "id": uuid4().hex,
        "created_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "image_size": size, "camera_matrix": camera_matrix.tolist(),
        "distortion_coefficients": coefficients.reshape(-1).tolist(),
        "undistort_method": "opencv_undistort_same_K_no_crop",
        "board_inner_corners": {"columns": board_size[0], "rows": board_size[1]},
        "square_mm": float(square_mm), "valid_views": len(observations),
        "opencv_rms_px": float(rms), "reprojection_rmse_px": float(np.sqrt(np.mean(squared_errors))),
        "per_view_rmse_px": per_view_rmse,
    }
    return validate_intrinsics(data)


def calibrate_images(image_paths, board_size, square_mm):
    """读取等尺寸真实照片，检测并精修内角点后求解；返回配置及逐文件识别记录。

    角点失败照片会明确记录并跳过；尺寸不符、无法解码或有效照片不足则拒绝保存。
    """
    board_object_points(board_size, square_mm)
    if len(image_paths) < MIN_VIEWS:
        raise ValueError(f"照片不足，至少需要 {MIN_VIEWS} 幅，建议 15~25 幅。")
    observations, accepted, rejected = [], [], []
    size = None
    for path in image_paths:
        frame = read_image(Path(path))
        height, width = frame.shape[:2]
        current_size = {"width": width, "height": height}
        if size is not None and size != current_size:
            raise ValueError(f"棋盘格照片分辨率不一致：{path}")
        size = current_size
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(
            gray, tuple(board_size), cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not found:
            rejected.append(str(path))
            continue
        # 5 是搜索半径（对应 11×11 pixel 邻域），沿用官方 calibrate.py 的较小窗口。
        # 邻域过大可能跨到相邻角点并把位置拉偏；仍需清晰、多视角、角点间距足够的照片。
        refined = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1),
                                  (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
        observations.append(refined.reshape(-1, 2))
        accepted.append(str(path))
    if len(observations) < MIN_VIEWS:
        raise ValueError(f"有效照片不足：成功 {len(accepted)}，失败 {len(rejected)}；至少需要 {MIN_VIEWS} 幅。")
    data = calibrate_from_points(observations, size, board_size, square_mm)
    data["accepted_images"] = accepted
    data["rejected_images"] = rejected
    return data


def main(argv=None):
    """内参工具 CLI：读取照片目录并保存 JSON，参数/照片/输出失败打印中文原因。"""
    parser = argparse.ArgumentParser(description="棋盘格相机内参标定（独立进阶工具）")
    parser.add_argument("--images", type=Path, required=True, help="只含该相机棋盘格照片的目录")
    parser.add_argument("--cols", type=int, required=True, help="内角点列数，不是方格数")
    parser.add_argument("--rows", type=int, required=True, help="内角点行数")
    parser.add_argument("--square-mm", type=float, required=True, help="单格实测边长，毫米")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "calibrations" / "camera.json")
    parser.add_argument("--overwrite", action="store_true", help="明确允许覆盖指定的旧配置")
    args = parser.parse_args(argv)
    try:
        if not args.images.is_dir():
            raise ValueError("--images 必须是存在的棋盘格照片目录。")
        paths = sorted(p for p in args.images.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
        data = calibrate_images(paths, (args.cols, args.rows), args.square_mm)
        save_calibration(args.output, data, args.overwrite)
        print(f'有效照片 {data["valid_views"]} 幅，失败 {len(data["rejected_images"])} 幅。')
        print(f'重投影 RMSE：{data["reprojection_rmse_px"]:.6f} pixel（不代表桌面毫米精度）。')
        for path, error in zip(data["accepted_images"], data["per_view_rmse_px"]):
            print(f"逐图重投影 RMSE：{path} = {error:.6f} pixel")
        for path in data["rejected_images"]:
            print(f"未识别棋盘格：{path}")
        print(f"已保存内参：{args.output}")
        return 0
    except (OSError, ValueError, cv2.error) as exc:
        print(f"内参标定失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
