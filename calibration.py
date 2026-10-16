"""V0.2 标定数学与 JSON 校验；不创建窗口，不读取摄像头。

原图 raw 与校正图 undistorted 属于不同像素坐标系，不能共用同一份 H。
本模块只接受固定相机、同一平面的几何映射，不提供机器人机械坐标。
"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import uuid4

import cv2
import numpy as np

SCHEMA_VERSION = "0.2"
CORNER_ORDER = ["TL", "TR", "BR", "BL"]
AXES = {"x": "TL_to_TR", "y": "TL_to_BL"}
MIN_VIEWS = 5


def finite_array(value, shape, name):
    """将数值数组转为 float64；拒绝字符串、布尔值、形状不符和 NaN/Inf。"""
    try:
        array = np.asarray(value)
        if array.dtype.kind not in "iuf" or array.shape != shape:
            raise ValueError
        if any(isinstance(item, (bool, np.bool_)) for item in np.asarray(value, dtype=object).flat):
            raise ValueError
        array = array.astype(np.float64)
        if not np.isfinite(array).all():
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须是形状为 {shape} 的有限数值数组。") from exc
    return array


def positive_number(value, name):
    """校验正实数（例如毫米尺寸）；不将字符串或 True 当成测量值。"""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} 必须是大于零的有限数值。")
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是大于零的有限数值。")
    return float(value)


def validate_image_size(image_size):
    """校验图像宽高字典，单位 pixel；只接受正整数，不允许运行时静默缩放。"""
    if not isinstance(image_size, dict):
        raise ValueError("image_size 必须包含整数 width / height。")
    for name in ("width", "height"):
        value = image_size.get(name)
        if type(value) is not int or value < 2:
            raise ValueError("image_size 的 width / height 必须是大于等于 2 的整数。")
    return {"width": image_size["width"], "height": image_size["height"]}


def _validate_header(data, calibration_type):
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("标定配置 schema_version 必须为 0.2。")
    if data.get("calibration_type") != calibration_type:
        raise ValueError(f"标定配置类型必须为 {calibration_type}。")
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        raise ValueError("标定配置缺少有效 id。")
    try:
        timestamp = datetime.fromisoformat(data["created_at"])
        if timestamp.tzinfo is None:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("created_at 必须是带时区的 ISO 时间。") from exc
    validate_image_size(data.get("image_size"))


def validate_corners(corners_px, image_size):
    """校验 TL→TR→BR→BL 四角，输入/输出为 (4,2) pixel 数组。

    拒绝越界、重复、近共线、交叉、过小或方向颠倒的四边形，避免病态 H。
    使用图像中向右/向下的边中点方向辅助检查顺序；矩形应大致正向摆放。
    """
    size = validate_image_size(image_size)
    points = finite_array(corners_px, (4, 2), "corners_px")
    if (points < 0).any() or (points[:, 0] > size["width"] - 1).any() or (points[:, 1] > size["height"] - 1).any():
        raise ValueError("四角必须位于当前图像的有效像素范围内。")
    edges = np.roll(points, -1, axis=0) - points
    lengths = np.linalg.norm(edges, axis=1)
    if (lengths < 5).any():
        raise ValueError("四角重复或边长过小，至少需要 5 pixel。")
    following = np.roll(edges, -1, axis=0)
    crosses = edges[:, 0] * following[:, 1] - edges[:, 1] * following[:, 0]
    # 图像 y 向下，TL→TR→BR→BL 的每次转弯应为同向正叉积。
    # 归一化后是夹角的正弦；小于 0.01（约 0.57 度）视为近退化。
    if (crosses / (lengths * np.roll(lengths, -1)) <= 0.01).any():
        raise ValueError("四角近共线、交叉或顺序错误，请按 TL→TR→BR→BL 点选。")
    area = cv2.contourArea(points.astype(np.float32))
    # 100 px² 与整幅画面 0.1% 取较大者，防止在极小区域拟合不稳定的 H。
    if area < max(100.0, size["width"] * size["height"] * 0.001):
        raise ValueError("标定四边形面积过小，请扩大有效标定区域。")
    if points[[0, 1], 1].mean() >= points[[2, 3], 1].mean() or points[[0, 3], 0].mean() >= points[[1, 2], 0].mean():
        raise ValueError("四角轴方向不符，请使宽度边大致向右、高度边大致向下。")
    return points


def _rectangle_mm(width_mm, height_mm):
    return np.array([[0, 0], [width_mm, 0], [width_mm, height_mm], [0, height_mm]], dtype=np.float32)


def validate_plane_calibration(data):
    """校验工作平面字典并原样返回；损坏/不兼容配置抛 ValueError。

    同时校验 H 的数值、方向、非奇异性和四角映射，而不只检查 JSON 能否读取。
    """
    _validate_header(data, "workplane")
    width_mm = positive_number(data.get("width_mm"), "width_mm（毫米）")
    height_mm = positive_number(data.get("height_mm"), "height_mm（毫米）")
    corners = validate_corners(data.get("corners_px"), data["image_size"])
    if data.get("corner_order") != CORNER_ORDER or data.get("origin") != "TL" or data.get("axes") != AXES:
        raise ValueError("工作平面原点、四角顺序或轴方向不兼容。")
    if data.get("matrix_direction") != "pixel_to_workplane_mm":
        raise ValueError("H 的方向必须为 pixel_to_workplane_mm。")
    matrix = finite_array(data.get("H"), (3, 3), "H")
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    # 最小/最大奇异值比过小意味着接近不可逆，这是数值保护阈值而非测量精度。
    if singular_values[0] == 0 or singular_values[-1] / singular_values[0] < 1e-12:
        raise ValueError("H 为奇异或数值不稳定矩阵，请重新标定。")
    # 透视变换包含齐次坐标除法；四角的分母必须同号，防止 ROI 内穿越无穷远。
    denominators = np.column_stack((corners, np.ones(4))) @ matrix[2]
    if not ((denominators > 1e-10).all() or (denominators < -1e-10).all()):
        raise ValueError("H 在标定区域内存在无效透视除法。")
    mapped = cv2.perspectiveTransform(corners.reshape(1, 4, 2), matrix)[0]
    if not np.isfinite(mapped).all() or not np.allclose(mapped, _rectangle_mm(width_mm, height_mm), atol=0.01, rtol=1e-5):
        raise ValueError("H 与四角、实测毫米尺寸不一致。")
    pixel_frame = data.get("pixel_frame")
    if pixel_frame not in ("raw", "undistorted") or type(data.get("undistorted")) is not bool:
        raise ValueError("pixel_frame / undistorted 字段无效。")
    if data["undistorted"] != (pixel_frame == "undistorted"):
        raise ValueError("去畸变状态字段互相矛盾。")
    reference = data.get("intrinsics_reference")
    if "intrinsics_reference" not in data:
        raise ValueError("平面标定缺少 intrinsics_reference 字段。")
    if pixel_frame == "raw" and reference is not None:
        raise ValueError("原始像素标定不得关联去畸变内参。")
    if pixel_frame == "undistorted":
        if not isinstance(reference, dict) or not isinstance(reference.get("id"), str) or not reference["id"]:
            raise ValueError("去畸变平面标定缺少内参 id 关联。")
        fingerprint = reference.get("sha256")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise ValueError("去畸变平面标定缺少有效内参指纹。")
    if data.get("source") is not None and not isinstance(data["source"], str):
        raise ValueError("source 必须为字符串或 null。")
    return data


def intrinsics_reference(intrinsics):
    """返回内参 id 与内容指纹；相同 id 的参数被改写也不能混用平面 H。"""
    if intrinsics is None:
        return None
    validate_intrinsics(intrinsics)
    content = {name: intrinsics[name] for name in ("image_size", "camera_matrix", "distortion_coefficients")}
    content["method"] = "opencv_undistort_same_K_no_crop"
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"id": intrinsics["id"], "sha256": hashlib.sha256(encoded).hexdigest()}


def create_plane_calibration(corners_px, width_mm, height_mm, image_size, source=None, intrinsics=None):
    """从四对对应点创建 JSON 可序列化的平面标定；输入 px/mm，输出 H 字典。

    四角映射到实测矩形，而不是图像宽高。适合在 corners / H 处设断点。
    失败条件由四角、尺寸、内参和矩阵校验明确拒绝。
    """
    size = validate_image_size(image_size)
    corners = validate_corners(corners_px, size)
    width_mm = positive_number(width_mm, "width_mm（毫米）")
    height_mm = positive_number(height_mm, "height_mm（毫米）")
    reference = intrinsics_reference(intrinsics)
    if intrinsics is not None and intrinsics["image_size"] != size:
        raise ValueError("内参分辨率与平面标定图像不一致。")
    # 不自行实现单应性求解；OpenCV 解出 pixel→mm 的 3×3 H。
    matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), _rectangle_mm(width_mm, height_mm))
    data = {
        "schema_version": SCHEMA_VERSION, "calibration_type": "workplane", "id": uuid4().hex,
        "created_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "origin": "TL", "axes": AXES.copy(), "corner_order": CORNER_ORDER.copy(),
        "width_mm": width_mm, "height_mm": height_mm, "corners_px": corners.tolist(),
        "H": matrix.tolist(), "matrix_direction": "pixel_to_workplane_mm", "image_size": size,
        "source": source, "pixel_frame": "undistorted" if intrinsics else "raw",
        "undistorted": intrinsics is not None, "intrinsics_reference": reference,
    }
    return validate_plane_calibration(data)


def validate_intrinsics(data):
    """校验针孔相机内参/畸变字典；参数像素单位，畸变系数无量纲。"""
    _validate_header(data, "camera_intrinsics")
    matrix = finite_array(data.get("camera_matrix"), (3, 3), "camera_matrix")
    if matrix[0, 0] <= 0 or matrix[1, 1] <= 0 or not np.allclose(matrix[2], [0, 0, 1]):
        raise ValueError("内参矩阵焦距必须为正，末行必须为 [0,0,1]。")
    if not np.isclose(matrix[0, 1], 0) or not np.isclose(matrix[1, 0], 0):
        raise ValueError("仅支持 OpenCV 标准无倾斜针孔内参矩阵。")
    if np.linalg.cond(matrix) > 1e12:
        raise ValueError("内参矩阵近奇异，不能可靠去畸变。")
    coefficients = data.get("distortion_coefficients")
    if not isinstance(coefficients, list) or len(coefficients) not in (4, 5, 8, 12, 14):
        raise ValueError("畸变系数须为 4/5/8/12/14 个数值的列表。")
    finite_array(coefficients, (len(coefficients),), "distortion_coefficients")
    if data.get("undistort_method") != "opencv_undistort_same_K_no_crop":
        raise ValueError("内参去畸变方法不兼容（要求保持原 K、原尺寸、不裁剪）。")
    for name in ("opencv_rms_px", "reprojection_rmse_px"):
        if name in data:
            value = finite_array([data[name]], (1,), name)[0]
            if value < 0:
                raise ValueError("重投影误差不能为负数。")
    if "valid_views" in data and (type(data["valid_views"]) is not int or data["valid_views"] < MIN_VIEWS):
        raise ValueError("valid_views 必须是至少 5 的整数。")
    if "per_view_rmse_px" in data:
        if "valid_views" not in data:
            raise ValueError("逐图误差缺少 valid_views。")
        errors = finite_array(data["per_view_rmse_px"], (data["valid_views"],), "per_view_rmse_px")
        if (errors < 0).any():
            raise ValueError("逐图误差不能为负数。")
    return data


def load_calibration(path, calibration_type="workplane"):
    """安全读取 JSON 并验证预期类型；不存在、格式错误或字段损坏时明确失败。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"标定 JSON 无法解析：{path}") from exc
    if calibration_type == "workplane":
        return validate_plane_calibration(data)
    if calibration_type == "camera_intrinsics":
        return validate_intrinsics(data)
    raise ValueError("未知标定配置类型。")


def save_calibration(path, data, overwrite=False):
    """验证后写 JSON；默认拒绝覆盖，明确确认后才允许原子替换旧文件。"""
    if isinstance(data, dict) and data.get("calibration_type") == "camera_intrinsics":
        validate_intrinsics(data)
    else:
        validate_plane_calibration(data)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(payload)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return path


def check_frame_context(plane, image_size, intrinsics=None):
    """校验分辨率及 raw/undistorted 关联；不匹配就拒绝毫米定位，不缩放 H。"""
    size = validate_image_size(image_size)
    if intrinsics is not None:
        validate_intrinsics(intrinsics)
        if intrinsics["image_size"] != size:
            raise ValueError("当前图像与内参标定分辨率不一致，禁止去畸变。")
    if plane is not None:
        if plane["image_size"] != size:
            raise ValueError("当前图像与平面标定分辨率不一致，禁止输出毫米坐标。")
        if plane["intrinsics_reference"] != intrinsics_reference(intrinsics):
            raise ValueError("平面标定与当前去畸变内参不匹配：不能混用 raw / undistorted 坐标。")


def undistort_frame(frame, intrinsics=None):
    """输入 raw BGR 图像，输出相同尺寸的校正图；无内参时原样返回。

    必须先校正再检测/点选。不改变 K、不裁剪，保证本项目所有校正流程一致。
    """
    if intrinsics is None:
        return frame
    height, width = frame.shape[:2]
    check_frame_context(None, {"width": width, "height": height}, intrinsics)
    matrix = np.array(intrinsics["camera_matrix"], dtype=np.float64)
    coefficients = np.array(intrinsics["distortion_coefficients"], dtype=np.float64)
    return cv2.undistort(frame, matrix, coefficients, None, matrix)


def pixel_to_workplane(center_px, plane):
    """单个 (x,y) pixel → (毫米字典或 None, 状态)；只在四角 ROI 内有效。

    H·[x,y,1]^T 得到 [u,v,w]，实际毫米为 [u/w,v/w]；透视除法由 OpenCV 完成。
    断点观察 point、denominator、mapped。区域外绝不输出看似可靠的外推坐标。
    """
    validate_plane_calibration(plane)
    point = finite_array(center_px, (2,), "center_px")
    polygon = np.array(plane["corners_px"], dtype=np.float32)
    if cv2.pointPolygonTest(polygon, tuple(float(v) for v in point), False) < 0:
        return None, "outside_roi"
    matrix = np.array(plane["H"], dtype=np.float64)
    denominator = matrix[2] @ np.array([point[0], point[1], 1.0])
    if abs(denominator) < 1e-10:
        return None, "invalid_transform"
    mapped = cv2.perspectiveTransform(point.reshape(1, 1, 2), matrix)[0, 0]
    if not np.isfinite(mapped).all():
        return None, "invalid_transform"
    return {"x": float(mapped[0]), "y": float(mapped[1])}, "valid"


def add_workplane_coordinates(objects, plane, image_size, intrinsics=None):
    """保留像素结果并添加 mm_status；仅合法时添加 center_mm，不修改原列表。"""
    check_frame_context(plane, image_size, intrinsics)
    converted = []
    for original in objects:
        obj = {key: value for key, value in original.items() if key not in ("center_mm", "mm_status")}
        if plane is None:
            obj["mm_status"] = "uncalibrated"
        else:
            center = obj["center_px"]
            center_mm, status = pixel_to_workplane([center["x"], center["y"]], plane)
            obj["mm_status"] = status
            if center_mm is not None:
                obj["center_mm"] = center_mm
        converted.append(obj)
    return converted


def calibration_metadata(plane=None, intrinsics=None):
    """构造检测 JSON 的标定元信息；原点/轴/区域明确，不暗示机械坐标或测量精度。"""
    data = {"status": "valid" if plane else "uncalibrated", "id": plane["id"] if plane else None,
            "intrinsics_reference": intrinsics_reference(intrinsics)}
    if plane:
        data.update({key: plane[key] for key in ("origin", "axes", "width_mm", "height_mm", "image_size", "matrix_direction")})
        data["valid_region"] = "calibration_rectangle_only"
        data["synthetic"] = plane.get("synthetic", False)
    return data
