"""纯图像处理函数：不打开摄像头、不创建窗口、不写文件。"""

import cv2
import numpy as np

from config import DEFAULT_MIN_AREA, HSV_RANGES, MORPH_KERNEL_SIZE
from display import draw_detections


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
            objects.append({
                "id": len(objects) + 1,
                "color": color,
                "center_px": {"x": cx, "y": cy},
                "bbox_xywh": {"x": x, "y": y, "w": w, "h": h},
                "contour_area_px2": area,
            })
    return objects, masks


def annotate_frame(frame: np.ndarray, objects: list[dict], fps: float | None = None,
                   paused: bool = False, calibration_status: str | None = None) -> np.ndarray:
    """原尺寸导出图只画框、中心和短编号；状态一次显示，坐标见工作台列表/原 JSON。

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
