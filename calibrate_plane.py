"""OpenCV 四点点选工具：冻结同一帧、显式点序、撤销和覆盖确认。"""

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

from calibration import (CORNER_ORDER, create_plane_calibration, load_calibration,
                         positive_number, save_calibration, undistort_frame)
from config import PROJECT_DIR
from io_utils import read_image
from main import open_camera, window_is_open

PLANE_WINDOW = "CargoVision Plane Calibration"
HEADER_HEIGHT = 90


def display_to_pixel(x, y, image_size, display_size):
    """显示图内坐标 → 原图像素坐标（均不含标题栏）；使用 resize 的像素中心约定。

    比例由实际送给 imshow 的图片宽高确定；不是凭窗口外框尺寸猜测。
    标题/画面外点击返回 None，避免把提示栏误当标定角点。
    """
    width, height = image_size
    display_width, display_height = display_size
    if not (0 <= x < display_width and 0 <= y < display_height):
        return None
    px = np.clip((x + 0.5) * width / display_width - 0.5, 0, width - 1)
    py = np.clip((y + 0.5) * height / display_height - 0.5, 0, height - 1)
    return [float(px), float(py)]


def draw_selection(frame, points, frozen, pending_overwrite):
    """缩放预览并绘制编号；返回画布、显示图尺寸，原图不被修改。"""
    height, width = frame.shape[:2]
    scale = min(1.0, 1100 / width, 650 / height)
    display_size = (max(2, round(width * scale)), max(2, round(height * scale)))
    preview = cv2.resize(frame, display_size)
    canvas = np.zeros((display_size[1] + HEADER_HEIGHT, display_size[0], 3), dtype=np.uint8)
    canvas[HEADER_HEIGHT:] = preview
    lines = ["TL -> TR -> BR -> BL | X: TL->TR, Y: TL->BL", f'{"FROZEN" if frozen else "LIVE - press F first"} | Points: {len(points)}/4',
             "F freeze/live | U undo | R reset | S/Enter save | Esc/Q cancel"]
    if pending_overwrite:
        lines[2] = "FILE EXISTS: Y overwrite / N cancel overwrite"
    for index, line in enumerate(lines):
        cv2.putText(canvas, line, (8, 21 + index * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1, cv2.LINE_AA)
    displayed = []
    for index, (px, py) in enumerate(points):
        dx = round((px + 0.5) * display_size[0] / width - 0.5)
        dy = round((py + 0.5) * display_size[1] / height - 0.5) + HEADER_HEIGHT
        displayed.append((dx, dy))
        cv2.circle(canvas, (dx, dy), 5, (0, 255, 255), 2)
        cv2.putText(canvas, f"{index + 1} {CORNER_ORDER[index]}", (dx + 7, max(HEADER_HEIGHT + 14, dy - 7)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    if len(displayed) > 1:
        cv2.polylines(canvas, [np.array(displayed, dtype=np.int32)], len(displayed) == 4, (0, 255, 255), 1)
    return canvas, display_size


def select_plane(args, intrinsics=None):
    """读取图片或摄像头，交互创建平面 JSON；取消不写文件，异常确保释放资源。"""
    cap = None
    window_created = False
    state = {"points": [], "frozen": args.image is not None, "pending": None,
             "frame": None, "display_size": None}
    source = f"image:{args.image.resolve()}" if args.image else f"camera:{args.camera}"
    try:
        if args.image:
            state["frame"] = undistort_frame(read_image(args.image), intrinsics)
        else:
            cap = open_camera(args.camera)
            ok, raw = cap.read()
            if not ok or raw is None or raw.size == 0:
                raise RuntimeError("摄像头帧读取失败，无法进行平面标定。")
            state["frame"] = undistort_frame(raw, intrinsics)
        # AUTOSIZE 固定展示画布大小，禁止拖拽缩放；大图先自行 resize 再换算点击。
        cv2.namedWindow(PLANE_WINDOW, cv2.WINDOW_AUTOSIZE)
        window_created = True

        def on_mouse(event, x, y, flags, userdata):
            if not state["frozen"] or state["display_size"] is None:
                return
            if event == cv2.EVENT_RBUTTONDOWN:
                if state["points"]:
                    state["points"].pop()
                state["pending"] = None
            elif event == cv2.EVENT_LBUTTONDOWN and len(state["points"]) < 4:
                frame = state["frame"]
                point = display_to_pixel(x, y - HEADER_HEIGHT, (frame.shape[1], frame.shape[0]), state["display_size"])
                if point is not None:
                    state["points"].append(point)
                    state["pending"] = None

        cv2.setMouseCallback(PLANE_WINDOW, on_mouse)
        while True:
            if cap is not None and not state["frozen"]:
                ok, raw = cap.read()
                if not ok or raw is None or raw.size == 0:
                    raise RuntimeError("摄像头帧读取失败，请检查连接后重试。")
                state["frame"] = undistort_frame(raw, intrinsics)
            canvas, state["display_size"] = draw_selection(state["frame"], state["points"], state["frozen"], state["pending"] is not None)
            cv2.imshow(PLANE_WINDOW, canvas)
            key = cv2.waitKey(20) & 0xFF
            if key in (27, ord("q"), ord("Q")) or not window_is_open(PLANE_WINDOW):
                print("已取消平面标定，未写入配置。")
                return 0
            if key in (ord("r"), ord("R")):
                state["points"].clear()
                state["pending"] = None
            elif key in (8, ord("u"), ord("U")):
                if state["points"]:
                    state["points"].pop()
                state["pending"] = None
            elif key in (ord("f"), ord("F")) and cap is not None:
                state["frozen"] = not state["frozen"]
                state["points"].clear()
                state["pending"] = None
            elif key in (ord("n"), ord("N")):
                state["pending"] = None
            elif key in (ord("y"), ord("Y")) and state["pending"] is not None:
                save_calibration(args.output, state["pending"], overwrite=True)
                print(f"已确认覆盖平面标定：{args.output}")
                return 0
            elif key in (13, ord("s"), ord("S")):
                if not state["frozen"] or len(state["points"]) != 4:
                    print("请先按 F 冻结，再按 TL→TR→BR→BL 点选四角。")
                    continue
                height, width = state["frame"].shape[:2]
                try:
                    data = create_plane_calibration(state["points"], args.width_mm, args.height_mm,
                                                    {"width": width, "height": height}, source, intrinsics)
                except ValueError as exc:
                    print(f"四角无效：{exc} 请撤销或重选。", file=sys.stderr)
                    continue
                if args.output.exists():
                    state["pending"] = data
                    print("配置已存在；按 Y 确认覆盖，N 取消覆盖，Esc 取消标定。")
                else:
                    save_calibration(args.output, data)
                    print(f"已保存平面标定：{args.output}")
                    return 0
    except cv2.error:
        if window_created and not window_is_open(PLANE_WINDOW):
            print("标定窗口已关闭，未写入配置。")
            return 0
        raise
    finally:
        if cap is not None:
            cap.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass


def main(argv=None):
    """平面工具 CLI 入口；毫米尺寸必填（inspect 除外），取消返回 0、运行失败返回 1。"""
    parser = argparse.ArgumentParser(description="四点工作平面标定：TL→TR→BR→BL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--image", type=Path)
    group.add_argument("--camera", type=int)
    parser.add_argument("--width-mm", type=float, help="TL→TR 实测边长，毫米")
    parser.add_argument("--height-mm", type=float, help="TL→BL 实测边长，毫米")
    parser.add_argument("--intrinsics", type=Path, help="可选相机内参，先去畸变再点选四角")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "calibrations" / "workplane.json")
    parser.add_argument("--inspect", type=Path, help="只校验并打印已有平面配置，不打开窗口")
    args = parser.parse_args(argv)
    try:
        if args.inspect:
            print(json.dumps(load_calibration(args.inspect), ensure_ascii=False, indent=2))
            return 0
        if args.image is None and args.camera is None:
            parser.error("必须指定 --image 或 --camera；也可用 --inspect 检查配置。")
        if args.camera is not None and args.camera < 0:
            parser.error("摄像头编号不能为负数。")
        positive_number(args.width_mm, "width_mm")
        positive_number(args.height_mm, "height_mm")
        intrinsics = load_calibration(args.intrinsics, "camera_intrinsics") if args.intrinsics else None
        return select_plane(args, intrinsics)
    except (OSError, ValueError, RuntimeError, cv2.error) as exc:
        print(f"平面标定失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消平面标定。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
