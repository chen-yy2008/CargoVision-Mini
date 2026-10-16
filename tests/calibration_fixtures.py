"""固定合成标定参数；不含任何真实摄像头测量数据。"""

import cv2
import numpy as np

from calibrate_camera import board_object_points


def synthetic_intrinsics():
    return {
        "schema_version": "0.2", "calibration_type": "camera_intrinsics", "id": "synthetic-camera",
        "created_at": "2026-10-16T00:00:00+08:00", "image_size": {"width": 640, "height": 480},
        "camera_matrix": [[600.0, 0.0, 320.0], [0.0, 610.0, 240.0], [0.0, 0.0, 1.0]],
        "distortion_coefficients": [0.0] * 5,
        "undistort_method": "opencv_undistort_same_K_no_crop", "synthetic": True,
    }


def projected_chessboards():
    """使用已知针孔模型从 8 个不同姿态投影角点；只能验证软件数学流程。"""
    camera = np.array(synthetic_intrinsics()["camera_matrix"])
    points = board_object_points((7, 5), 20)
    observations = []
    for index in range(8):
        rotation = np.array([0.12 + index * 0.04, -0.25 + index * 0.07, -0.08 + index * 0.025])
        translation = np.array([-65 + index * 5.0, -45 + index * 3.0, 550 + index * 30.0])
        projected, _ = cv2.projectPoints(points, rotation, translation, camera, np.zeros(5))
        observations.append(projected.reshape(-1, 2))
    return observations
