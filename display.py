"""只负责显示：等比例预览、简洁标注和信息区，不改变检测坐标或 JSON。"""

import os

import cv2
import numpy as np

from config import DRAW_COLORS, PREVIEW_SIZE

FONT = cv2.FONT_HERSHEY_SIMPLEX
ROTATED_RECT_COLOR = (255, 255, 0)  # BGR 青色
RECT_CENTER_COLOR = (255, 0, 255)  # 洋红色空心圆，区别于原轮廓质心十字
LONG_AXIS_COLOR = (0, 255, 255)
DETAIL_LINE_GAP = 17
DETAIL_ROW_STRIDE = 126
_DRAW_LIMIT = np.iinfo(np.int32).max // 4  # 仅防绘图整数溢出，不是有效工作区域。


def _finite_number(value):
    """显示层只接受有限数值；损坏的可选字段不影响旧目标显示。"""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        return None
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


def _geometry_point(value):
    if not isinstance(value, dict):
        return None
    x, y = _finite_number(value.get("x")), _finite_number(value.get("y"))
    if x is None or y is None or max(abs(x), abs(y)) > _DRAW_LIMIT:
        return None
    return x, y


def geometry_for_display(obj):
    """解析 A1 可选数据为显示副本，不重新拟合几何，也不写回对象。

    center/corners/边长均保持原采集 pixel，角度为原图 degree；缺失分量为 None。
    角点损坏时跳过多边形；可靠轴必须同时有合法几何、True 标志及有效角度。
    不重新计算长宽比门槛，方向判据仍由 A1 决定。
    """
    geometry = obj.get("geometry")
    rect = geometry.get("rotated_rect_px") if isinstance(geometry, dict) else None
    if not isinstance(rect, dict):
        return None
    center = _geometry_point(rect.get("center_px"))
    raw_corners = rect.get("corners_px")
    corners = None
    if isinstance(raw_corners, (list, tuple)) and len(raw_corners) == 4:
        points = [_geometry_point(point) for point in raw_corners]
        if all(point is not None for point in points):
            candidate = np.array(points, dtype=np.float64)
            if cv2.isContourConvex(candidate.astype(np.float32)):
                corners = candidate  # 沿用实际顺序，不把首点猜成 TL，也不重新排序。
    long_side = _finite_number(rect.get("long_side_px"))
    short_side = _finite_number(rect.get("short_side_px"))
    aspect = _finite_number(rect.get("aspect_ratio"))
    long_side = long_side if long_side is not None and long_side > 0 else None
    short_side = short_side if short_side is not None and short_side > 0 else None
    aspect = aspect if aspect is not None and aspect >= 1 else None
    angle = _finite_number(rect.get("angle_deg"))
    valid = (rect.get("orientation_valid") is True and angle is not None and -90 <= angle < 90
             and center is not None and corners is not None and long_side is not None
             and short_side is not None and long_side >= short_side and aspect is not None)
    return {"center": center, "corners": corners, "long_side": long_side, "short_side": short_side,
            "aspect": aspect, "angle": angle if valid else None, "orientation_valid": bool(valid)}


def _drawing_points(points, scale):
    """源坐标乘原图→预览的 sx/sy，仅生成绘图整数副本；越界由 OpenCV 裁画布。

    极端/非有限坐标安全忽略，不对 JSON 做 clamp；取整仅发生在最后一次绘图转换。
    """
    with np.errstate(over="ignore", invalid="ignore"):
        scaled = np.asarray(points, dtype=np.float64) * np.asarray(scale)
    if not np.isfinite(scaled).all() or np.any(np.abs(scaled) > _DRAW_LIMIT):
        return None
    return np.rint(scaled).astype(np.int32)


def draw_rotated_geometry(output, obj, scale=(1.0, 1.0)):
    """在调用方提供的显示副本上叠加 A1 几何；不修改 obj 或重算 minAreaRect。

    scale 是同一 resize 的 sx/sy；先在源空间求轴端点，再整体缩放，避免把预览边长
    写成采集边长，或忽略整数 resize 带来的 sx/sy 细小差异。无方向时仍画框和中心。
    """
    geometry = geometry_for_display(obj)
    if geometry is None:
        return
    if geometry["corners"] is not None:
        corners = _drawing_points(geometry["corners"], scale)
        if corners is not None:
            cv2.polylines(output, [corners], True, ROTATED_RECT_COLOR, 1, cv2.LINE_AA)
    if geometry["orientation_valid"]:
        theta = np.deg2rad(geometry["angle"])
        vector = np.array((np.cos(theta), np.sin(theta))) * (geometry["long_side"] / 2)
        center = np.array(geometry["center"])
        endpoints = _drawing_points([center - vector, center + vector], scale)
        if endpoints is not None:
            cv2.line(output, tuple(endpoints[0]), tuple(endpoints[1]), LONG_AXIS_COLOR, 2, cv2.LINE_AA)
    if geometry["center"] is not None:
        point = _drawing_points([geometry["center"]], scale)
        if point is not None:
            x, y = map(int, point[0])
            if -7 <= x < output.shape[1] + 7 and -7 <= y < output.shape[0] + 7:
                cv2.circle(output, (x, y), 7, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.circle(output, (x, y), 7, RECT_CENTER_COLOR, 1, cv2.LINE_AA)


def initial_preview_size(screen_size=None):
    """初次窗口最大 960×720，普通小屏预留标题、任务栏和滑条空间；后续不主动改尺寸。

    Windows 工作区通过标准库 ctypes 查询，不新增 GUI 依赖；不可查询时用默认尺寸。
    screen_size 参数用于可重复测试，单位为屏幕 pixel。
    """
    if screen_size is None and os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            rectangle = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rectangle), 0):
                screen_size = (rectangle.right - rectangle.left, rectangle.bottom - rectangle.top)
        except (AttributeError, OSError):
            pass
    if screen_size is None:
        return PREVIEW_SIZE
    return min(PREVIEW_SIZE[0], max(320, screen_size[0] - 80)), min(PREVIEW_SIZE[1], max(240, screen_size[1] - 180))


def fit_image_rect(image_size, bounds):
    """将原图 (width,height) 等比例放入 (x,y,w,h)，返回居中整数矩形；不裁切。"""
    width, height = image_size
    x, y, available_w, available_h = bounds
    if min(width, height, available_w, available_h) <= 0:
        raise ValueError("图像和预览区域宽高必须为正。")
    scale = min(available_w / width, available_h / height)
    output_w = max(1, min(available_w, round(width * scale)))
    output_h = max(1, min(available_h, round(height * scale)))
    return x + (available_w - output_w) // 2, y + (available_h - output_h) // 2, output_w, output_h


def _intersects(first, second):
    x, y, w, h = first
    sx, sy, sw, sh = second
    return x < sx + sw and sx < x + w and y < sy + sh and sy < y + h


def label_layout(objects, image_size, reserved_top=0):
    """为 R#1 等短编号选择互不相交且不越界的位置，空间不足则省略该文字。

    极密画面无法容纳所有文字，完整编号/坐标仍在可翻页信息区和原 JSON 中，
    不通过强制挤进长坐标来破坏画面。返回按对象顺序排列的矩形或 None。
    """
    width, height = image_size
    used, layouts = [], []
    protected = [(obj["center_px"]["x"] - 9, obj["center_px"]["y"] - 9, 19, 19) for obj in objects]
    for obj in objects:
        text = f'{obj["color"][0].upper()}#{obj["id"]}'
        tw, th = cv2.getTextSize(text, FONT, 0.45, 1)[0]
        w, h = tw + 8, th + 9
        box = obj["bbox_xywh"]
        x, y, bw, bh = (box[key] for key in ("x", "y", "w", "h"))
        cx, cy = obj["center_px"]["x"], obj["center_px"]["y"]
        # 小目标的十字可能伸出框外，候选标签也需避开这段范围，不能只考虑框边缘。
        above = min(y - h - 3, cy - 9 - h - 3)
        below = max(y + bh + 3, cy + 9 + 3)
        choices = [(x, above), (x, below), (x + bw - w, above),
                   (max(x + bw + 3, cx + 12), y), (min(x - w - 3, cx - 12 - w), y),
                   (x, y + 3), (x + bw - w, y + bh - h)]
        selected = None
        if w <= width and h <= height - reserved_top:
            for lx, ly in choices:
                rect = (max(0, min(lx, width - w)), max(reserved_top, min(ly, height - h)), w, h)
                if not any(_intersects(rect, other) for other in used + protected):
                    selected = rect
                    used.append(rect)
                    break
        layouts.append(selected)
    return layouts


def draw_detections(frame, objects, reserved_top=0, source_size=None):
    """在副本上画原标注与旋转几何；所有输入 objects 都属于源图 pixel 空间。

    source_size=(源宽,源高)，仅预览传入；原尺寸 PNG 不传，比例为1。只为旧标注
    建本地缩放字典，几何直接从原字段生成绘图点，不改 center_mm 或任何嵌套字段。
    """
    output = frame.copy()
    height, width = output.shape[:2]
    sx, sy = (width / source_size[0], height / source_size[1]) if source_size else (1.0, 1.0)
    displayed = objects
    if source_size:
        displayed = []
        for obj in objects:
            box, center = obj["bbox_xywh"], obj["center_px"]
            displayed.append({**obj, "bbox_xywh": {"x": round(box["x"] * sx), "y": round(box["y"] * sy),
                                                    "w": max(1, round(box["w"] * sx)), "h": max(1, round(box["h"] * sy))},
                              "center_px": {"x": min(width - 1, round(center["x"] * sx)),
                                            "y": min(height - 1, round(center["y"] * sy))}})
    layouts = label_layout(displayed, (width, height), reserved_top)
    for original, obj in zip(objects, displayed):
        box = obj["bbox_xywh"]
        x, y, w, h = (box[key] for key in ("x", "y", "w", "h"))
        center = obj["center_px"]
        point = (center["x"], center["y"])
        cv2.rectangle(output, (x, y), (x + w - 1, y + h - 1), DRAW_COLORS[obj["color"]], 2)
        draw_rotated_geometry(output, original, (sx, sy))
        # 十字最后绘制；当两个中心重合时仍保留白色质心点，空心圆的周边仍可辨认。
        marker_size = max(5, min(16, min(w, h) // 2))
        cv2.drawMarker(output, point, (0, 0, 0), cv2.MARKER_CROSS, marker_size, 4)
        cv2.drawMarker(output, point, (255, 255, 255), cv2.MARKER_CROSS, marker_size, 2)
    # 最后画文字底板，保证白/黑背景均可读；避开中心标记防止覆盖质心。
    for obj, rect in zip(displayed, layouts):
        if rect is None:
            continue
        x, y, w, h = rect
        cv2.rectangle(output, (x, y), (x + w - 1, y + h - 1), (24, 28, 34), -1)
        cv2.putText(output, f'{obj["color"][0].upper()}#{obj["id"]}', (x + 4, y + h - 5),
                    FONT, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return output


def _text(canvas, text, x, y, max_width, color=(225, 231, 238), scale=0.45):
    """单行文字按像素宽度截断；固定信息区不让长设备描述越过边界。"""
    if max_width <= 10 or y >= canvas.shape[0] or y < 12:
        return
    original = text
    while text and cv2.getTextSize(text, FONT, scale, 1)[0][0] > max_width:
        text = text[:-1]
    if text != original:
        text = text[:-3] + "..." if len(text) > 3 else text
    cv2.putText(canvas, text, (x, y), FONT, scale, color, 1, cv2.LINE_AA)


def render_workbench(frame, objects, result, ui, canvas_size):
    """原始帧/Mask与原始坐标 → 指定尺寸工作台画布；只在显示副本中换算几何。

    断点查看 bounds、x/y/target_w/target_h 和 draw_detections 内的绘图副本；右侧可翻页。
    预览缩放绝不回写 objects，导出继续使用原图大小和原 JSON。
    """
    width, height = canvas_size
    canvas = np.full((height, width, 3), (22, 26, 32), dtype=np.uint8)
    sidebar_w = 270 if width >= 680 else 0
    header_h, footer_h = min(82, height // 4), min(62, height // 4)
    bounds = (8, header_h, max(1, width - sidebar_w - 16), max(1, height - header_h - footer_h))
    x, y, target_w, target_h = fit_image_rect((frame.shape[1], frame.shape[0]), bounds)
    interpolation = cv2.INTER_AREA if target_w < frame.shape[1] else cv2.INTER_LINEAR
    image = cv2.resize(frame, (target_w, target_h), interpolation=interpolation)
    if ui.get("view", "original") == "original":
        image = draw_detections(image, objects, source_size=(frame.shape[1], frame.shape[0]))
    # 图像区域黑底居中；信息区独立，始终避免拉伸或裁切。
    canvas[header_h:height - footer_h, :width - sidebar_w] = 0
    canvas[y:y + target_h, x:x + target_w] = image
    status = result.get("calibration", {}).get("status", "uncalibrated")
    calibration = "CALIBRATED" if status == "valid" else status.upper()
    fps = ui.get("fps")
    fps_text = "--" if fps is None else f"{fps:.1f}"
    state = " | PAUSED" if ui.get("paused") else ""
    title = f"CargoVision Mini   Objects {len(objects)}   FPS {fps_text}   {calibration}{state}"
    if width < 680:
        title = f"N {len(objects)} | FPS {fps_text} | {calibration}{state}"
    _text(canvas, title,
          12, 23, width - 24, scale=0.52)
    size = result.get("image_size", {"width": frame.shape[1], "height": frame.shape[0]})
    source = ui.get("source_label", result.get("source", "Image"))
    _text(canvas, f'{source} | Capture {size["width"]}x{size["height"]} | {result.get("pixel_frame", "raw")} | View {ui.get("view", "original").upper()}',
          12, 48, width - 24)
    _text(canvas, f'Min area {ui.get("min_area", 300)} px^2 | +/- fine adjust | D detail | [ ] target pages',
          12, 70, width - 24, color=(152, 169, 189), scale=0.4)
    if sidebar_w:
        left = width - sidebar_w + 10
        detail = ui.get("detail", False)
        stride = DETAIL_ROW_STRIDE if detail else 43
        last_offset = 6 * DETAIL_LINE_GAP if detail else 17
        room = height - footer_h - 12 - (header_h + 47) - last_offset
        capacity = 0 if room < 0 else 1 + room // stride
        pages = max(1, (len(objects) + capacity - 1) // capacity) if capacity else 1
        page = max(0, min(ui.get("page", 0), pages - 1))
        ui["page"] = page  # 目标数或窗口高度改变时同步分页，避免要按很多次上一页。
        title = f"TARGETS   {page + 1}/{pages}" + (" | px=Contour" if detail else "")
        _text(canvas, title, left, header_h + 22, sidebar_w - 20, color=(100, 202, 231))
        if not capacity:
            _text(canvas, "Enlarge height for target details", left, header_h + 47, sidebar_w - 20, scale=0.4)
        for offset, obj in enumerate(objects[page * capacity:(page + 1) * capacity]):
            row_y = header_h + 47 + offset * stride
            center = obj["center_px"]
            _text(canvas, f'{obj["color"][0].upper()}#{obj["id"]}  px ({center["x"]}, {center["y"]})', left, row_y, sidebar_w - 20)
            if "center_mm" in obj:
                mm = obj["center_mm"]
                line = f'mm ({mm["x"]:.2f}, {mm["y"]:.2f})'
            else:
                line = {"outside_roi": "OUTSIDE ROI", "invalid_transform": "INVALID MM"}.get(obj.get("mm_status"), "mm --")
            _text(canvas, line, left, row_y + 17, sidebar_w - 20, color=(152, 169, 189), scale=0.4)
            if detail:
                box = obj["bbox_xywh"]
                _text(canvas, f'{box["w"]}x{box["h"]} px  Area {obj["contour_area_px2"]:.0f}', left, row_y + 34, sidebar_w - 20, scale=0.4)
                geometry = geometry_for_display(obj)
                geometry = geometry or {"center": None, "long_side": None, "short_side": None, "aspect": None,
                                        "orientation_valid": False, "angle": None}
                center = geometry["center"]
                point_text = f'({center[0]:.1f}, {center[1]:.1f})' if center is not None else "N/A"
                long_text = f'{geometry["long_side"]:.1f}' if geometry["long_side"] is not None else "N/A"
                short_text = f'{geometry["short_side"]:.1f}' if geometry["short_side"] is not None else "N/A"
                aspect_text = f'{geometry["aspect"]:.3f}' if geometry["aspect"] is not None else "N/A"
                direction = f'Axis {geometry["angle"]:.2f} deg | VALID' if geometry["orientation_valid"] else "Axis N/A | NO VALID DIRECTION"
                for index, line in enumerate((f'Rect Cpx {point_text}', f'Long {long_text} px | Short {short_text} px',
                                              f'Aspect {aspect_text}', direction), start=3):
                    _text(canvas, line, left, row_y + index * DETAIL_LINE_GAP, sidebar_w - 20, scale=0.4)
    else:
        _text(canvas, "Enlarge window to show target coordinates", 12, height - footer_h - 8, width - 24, scale=0.4)
    legend = ("Cyan:RotRect | Magenta O:Rect center | Yellow:Axis | BW +:Contour" if ui.get("view", "original") == "original"
              else "Mask only - no target geometry overlay")
    _text(canvas, legend, 12, height - 52, width - 24, color=(152, 169, 189), scale=0.36)
    _text(canvas, "P pause  S save  Q/Esc quit | View slider: RGB / R / G / B", 12, height - 33, width - 24, scale=0.42)
    message = ui.get("message", "Ready - preview scaling does not change capture coordinates")
    color = (90, 150, 255) if "FAILED" in message else (106, 214, 161)
    _text(canvas, message, 12, height - 14, width - 24, color=color, scale=0.4)
    return canvas
