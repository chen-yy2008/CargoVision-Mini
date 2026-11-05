"""纯图像处理函数：不打开摄像头、不创建窗口、不写文件。"""

import cv2
import numpy as np

from config import DEFAULT_MIN_AREA, HSV_RANGES, MORPH_KERNEL_SIZE
from display import draw_detections

# 无单位：只有长边/短边 >= 1.10 才报告长轴方向；不是物体类别或定位精度置信度。
ORIENTATION_MIN_ASPECT_RATIO = 1.10


def create_masks(frame: np.ndarray) -> dict[str, np.ndarray]:
    """输入 uint8 BGR 图像，返回每种颜色的单通道二值 Mask。"""
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0):
        raise ValueError("图像必须为非空的 uint8 BGR 三通道数组。")
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    kernel = np.ones((MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE), dtype=np.uint8)
    masks = {}
    for color, ranges in HSV_RANGES.items():
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        for lower, upper in ranges:
            part = cv2.inRange(hsv, np.array(lower, dtype=np.uint8),
                               np.array(upper, dtype=np.uint8))
            mask = cv2.bitwise_or(mask, part)
        # 开运算去除孤立小点，闭运算填补小缝隙；面积筛选在后面执行。
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        masks[color] = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return masks


def contour_center(contour: np.ndarray) -> tuple[int, int]:
    """通过轮廓矩计算质心；退化轮廓回退到边界框中心。"""
    moments = cv2.moments(contour)
    if moments["m00"] != 0:
        return (int(round(moments["m10"] / moments["m00"])),
                int(round(moments["m01"] / moments["m00"])))
    x, y, w, h = cv2.boundingRect(contour)
    return int(round(x + (w - 1) / 2)), int(round(y + (h - 1) / 2))


def rotated_rect_geometry(contour: np.ndarray) -> dict | None:
    """轮廓 → 最小面积旋转矩形的纯 Python 字典；无效/退化轮廓返回 None。

    输入为 OpenCV 的 N×1×2 或 N×2 轮廓；输出中心、边长、四角均为浮点 pixel，
    aspect_ratio 无单位。矩形中心不替代原 contour_center 的轮廓矩质心。
    X 向右、Y 向下；角度参考 +X，正值在图像中顺时针，长轴无头尾，范围 [-90,90)。
    四角按图像顺时针排列，起点为 (y,x) 字典序最小顶点（最上，同高取最左）。
    orientation_valid=False 时 angle_deg=None；近方形/圆形不暴露不稳定的伪方向。
    断点观察 rect、corners、edges、long_axis 和 aspect_ratio；不改输入、检测筛选或 H。
    """
    points = np.asarray(contour, dtype=np.float32)
    if not ((points.ndim == 2 and points.shape[1:] == (2,)) or
            (points.ndim == 3 and points.shape[1:] == (1, 2))):
        return None
    if len(points) < 3 or not np.isfinite(points).all():
        return None
    rect = cv2.minAreaRect(np.ascontiguousarray(points))
    (cx, cy), (width, height), _ = rect
    if not np.isfinite((cx, cy, width, height)).all() or min(width, height) <= 0:
        return None  # 线/点没有短边，不能除以零或导出 Infinity。
    long_side, short_side = float(max(width, height)), float(min(width, height))
    aspect_ratio = long_side / short_side
    corners = cv2.boxPoints(rect).astype(np.float64)
    if not np.isfinite(corners).all() or not np.isfinite(aspect_ratio):
        return None

    # 图像 Y 朝下，atan2(dy,dx) 递增对应画面顺时针。重排起点，避免依赖 OpenCV
    # 不同宽高/角度表达方式自带的顶点起点；这里不是跨帧角点跟踪或标定 TL 点序。
    relative = corners - np.array((cx, cy))
    corners = corners[np.argsort(np.arctan2(relative[:, 1], relative[:, 0]))]
    start = int(np.lexsort((corners[:, 0], corners[:, 1]))[0])
    corners = np.roll(corners, -start, axis=0)
    edges = np.roll(corners, -1, axis=0) - corners
    long_axis = edges[int(np.argmax(np.linalg.norm(edges, axis=1)))]
    orientation_valid = bool(aspect_ratio >= ORIENTATION_MIN_ASPECT_RATIO)
    # 不直接输出 minAreaRect.angle：它随宽高交换而改变。由真实长边求角，再去掉
    # 180° 的头尾差别；竖直长轴为 -90°，+30° 与 -150° 表示同一无向长轴。
    angle = float((np.degrees(np.arctan2(long_axis[1], long_axis[0])) + 90) % 180 - 90)
    return {"center_px": {"x": float(cx), "y": float(cy)},
            "long_side_px": long_side, "short_side_px": short_side,
            "aspect_ratio": aspect_ratio, "angle_deg": angle if orientation_valid else None,
            "orientation_valid": orientation_valid,
            "corners_px": [{"x": float(x), "y": float(y)} for x, y in corners]}


def detect_objects(frame: np.ndarray, min_area: float = DEFAULT_MIN_AREA
                   ) -> tuple[list[dict], dict[str, np.ndarray]]:
    """返回普通字典目标列表与 Mask；ID 仅在当前帧内唯一。"""
    if not np.isfinite(min_area) or min_area < 1:
        raise ValueError("最小轮廓面积必须是大于等于 1 的有限数值。")
    masks = create_masks(frame)
    objects = []
    for color, mask in masks.items():
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # 稳定排序便于重复测试，不代表跨帧跟踪。
        for contour in sorted(contours, key=lambda c: cv2.boundingRect(c)[:2]):
            area = float(cv2.contourArea(contour))
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            cx, cy = contour_center(contour)
            obj = {
                "id": len(objects) + 1,
                "color": color,
                "center_px": {"x": cx, "y": cy},
                "bbox_xywh": {"x": x, "y": y, "w": w, "h": h},
                "contour_area_px2": area,
            }
            geometry = rotated_rect_geometry(contour)
            if geometry is not None:
                obj["geometry"] = {"rotated_rect_px": geometry}
            objects.append(obj)
    return objects, masks


def annotate_frame(frame: np.ndarray, objects: list[dict], fps: float | None = None,
                   paused: bool = False, calibration_status: str | None = None) -> np.ndarray:
    """原尺寸导出图画旧框/质心/编号及可用旋转几何；坐标详情见工作台列表/原 JSON。

    所有绘制都在副本上进行，不改变源图、像素/毫米结果或导出图尺寸。
    """
    annotated = draw_detections(frame, objects, reserved_top=52)
    status = f"Objects: {len(objects)}"
    if fps is not None:
        status += f" | FPS: {fps:.1f}"
    if paused:
        status += " | PAUSED"
    cv2.putText(annotated, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(annotated, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (255, 255, 255), 2, cv2.LINE_AA)
    if calibration_status:
        cv2.putText(annotated, calibration_status, (10, 47), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(annotated, calibration_status, (10, 47), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return annotated
