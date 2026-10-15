"""CargoVision Mini V0.1：命令行入口、简单窗口和摄像头生命周期。"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from time import perf_counter

try:
    import cv2
    from config import (DEFAULT_MIN_AREA, MAX_MIN_AREA, PREVIEW_MODES, WINDOW_NAME)
    from io_utils import build_result, read_image, save_results
    from vision import annotate_frame, detect_objects
except ModuleNotFoundError as exc:
    raise SystemExit("缺少运行依赖，请使用项目 .venv 的 Python 执行："
                     "python -m pip install -r requirements.txt") from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="CargoVision Mini：红绿蓝目标的像素定位")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--camera", type=int, help="摄像头编号，默认 0")
    group.add_argument("--image", type=Path, help="检测本地图片")
    parser.add_argument("--min-area", type=int, default=DEFAULT_MIN_AREA,
                        help=f"最小轮廓面积，默认 {DEFAULT_MIN_AREA} px^2")
    parser.add_argument("--no-display", action="store_true", help="图片模式不打开窗口，并自动保存结果")
    parser.add_argument("--save", action="store_true", help="图片模式启动时保存一次结果")
    args = parser.parse_args(argv)
    if args.camera is not None and args.camera < 0:
        parser.error("摄像头编号必须大于等于 0。")
    if not 1 <= args.min_area <= MAX_MIN_AREA:
        parser.error(f"最小面积必须在 1~{MAX_MIN_AREA} 之间。")
    if (args.no_display or args.save) and args.image is None:
        parser.error("--no-display 和 --save 仅用于 --image 图片模式。")
    if args.camera is None:
        args.camera = 0
    return args


def open_camera(index: int):
    """Windows 依次尝试 DirectShow、MSMF 和默认后端，失败对象及时释放。"""
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if os.name == "nt" else [cv2.CAP_ANY]
    for backend in backends:
        cap = cv2.VideoCapture()
        try:
            if cap.open(index, backend) and cap.isOpened():
                return cap
        except cv2.error:
            cap.release()
            continue
        cap.release()
    raise RuntimeError(f"无法打开摄像头 {index}。请检查连接、编号、Windows 相机权限，"
                       "并关闭可能占用摄像头的程序；也可先用 --image 测试。")


def create_window(min_area: int):
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.createTrackbar("Min area", WINDOW_NAME, min_area, MAX_MIN_AREA, lambda value: None)
    cv2.createTrackbar("View 0=RGB 1=R 2=G 3=B", WINDOW_NAME, 0, 3, lambda value: None)


def show_preview(annotated, masks):
    mode = PREVIEW_MODES[cv2.getTrackbarPos("View 0=RGB 1=R 2=G 3=B", WINDOW_NAME)]
    if mode == "original":
        preview = annotated
    else:
        preview = cv2.cvtColor(masks[mode], cv2.COLOR_GRAY2BGR)
        cv2.putText(preview, f"{mode.upper()} MASK", (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow(WINDOW_NAME, preview)


def export_current(annotated, result):
    """保存失败不结束摄像头会话，便于修正输出目录权限后重试。"""
    try:
        image_path, json_path = save_results(annotated, result)
    except (OSError, ValueError, cv2.error) as exc:
        print(f"保存失败：{exc}", file=sys.stderr)
        return False
    print(f"已保存：{image_path}\n        {json_path}")
    return True


def run_image(args) -> int:
    frame = read_image(args.image)
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    source = f"image:{args.image.resolve()}"
    objects, masks = detect_objects(frame, args.min_area)
    annotated = annotate_frame(frame, objects)
    result = build_result(frame, objects, source, timestamp)
    print(f"检测到 {len(objects)} 个目标。")
    if args.save or args.no_display:
        if not export_current(annotated, result):
            return 1
    if args.no_display:
        return 0
    create_window(args.min_area)
    last_area = args.min_area
    while True:
        min_area = max(1, cv2.getTrackbarPos("Min area", WINDOW_NAME))
        if min_area != last_area:
            objects, masks = detect_objects(frame, min_area)
            annotated = annotate_frame(frame, objects)
            result = build_result(frame, objects, source, timestamp)
            last_area = min_area
            print(f"检测到 {len(objects)} 个目标，最小面积 {min_area} px^2。")
        show_preview(annotated, masks)
        key = cv2.waitKey(20) & 0xFF
        if key in (27, ord("q"), ord("Q")) or cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
            break
        if key in (ord("s"), ord("S")):
            export_current(annotated, result)
    return 0


def run_camera(args) -> int:
    cap = open_camera(args.camera)
    try:
        create_window(args.min_area)
        paused, frame, timestamp = False, None, None
        fps, previous_time = 0.0, None
        while True:
            if not paused or frame is None:
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError("摄像头帧读取失败，可能已断开、被占用或权限受限。请检查后重新启动。")
                timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                now = perf_counter()
                if previous_time is not None:
                    fps = 1.0 / max(now - previous_time, 1e-9)
                previous_time = now
            min_area = max(1, cv2.getTrackbarPos("Min area", WINDOW_NAME))
            objects, masks = detect_objects(frame, min_area)
            annotated = annotate_frame(frame, objects, fps, paused)
            # 即使预览的是 Mask，S 也保存同一帧的彩色标注图与 JSON。
            result = build_result(frame, objects, f"camera:{args.camera}", timestamp)
            show_preview(annotated, masks)
            key = cv2.waitKey(20) & 0xFF
            if key in (27, ord("q"), ord("Q")) or cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key in (ord("p"), ord("P")):
                paused = not paused
                previous_time = None  # 恢复时不要把暂停时长计入 FPS。
            if key in (ord("s"), ord("S")):
                export_current(annotated, result)
    finally:
        cap.release()
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run_image(args) if args.image is not None else run_camera(args)
    except (OSError, ValueError, RuntimeError, cv2.error) as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已停止。")
        return 0
    finally:
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
