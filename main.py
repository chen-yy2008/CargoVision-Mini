"""CargoVision Mini：保留像素工作流，可选接入同平面毫米标定和内参校正。"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from time import perf_counter

try:
    import cv2
    from calibration import (add_workplane_coordinates, load_calibration, undistort_frame)
    from config import (DEFAULT_MIN_AREA, MAX_MIN_AREA, PREVIEW_MODES, WINDOW_NAME)
    from io_utils import build_result, read_image, save_results
    from vision import annotate_frame, detect_objects
except ModuleNotFoundError as exc:
    raise SystemExit("缺少运行依赖，请使用项目 .venv 的 Python 执行："
                     "python -m pip install -r requirements.txt") from exc


def parse_args(argv=None):
    """解析 CLI 并保持旧命令兼容；面积为 px²，配置路径可选，参数错误退出码为 2。"""
    parser = argparse.ArgumentParser(description="CargoVision Mini：红绿蓝目标的像素定位")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--camera", type=int, help="摄像头编号，默认 0")
    group.add_argument("--image", type=Path, help="检测本地图片")
    parser.add_argument("--calibration", type=Path, help="四点工作平面标定 JSON；不提供时只输出像素")
    parser.add_argument("--intrinsics", type=Path, help="可选相机内参 JSON，先去畸变再检测")
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
    args.plane_data = None
    args.intrinsics_data = None
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


def window_is_open(window_name=WINDOW_NAME) -> bool:
    """关闭按钮可能直接销毁原生窗口；查询此窗口时也可能抛出 cv2.error。"""
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


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


def analyze_frame(frame, args, source, timestamp, fps=None, paused=False):
    """同一坐标空间的 BGR 帧 → 标注图、Mask、0.2 结果字典。

    输入 frame 已按需去畸变；先保留像素质心，再附加合法的工作平面毫米坐标。
    不在此处打开设备或写文件。分辨率/内参关联不符时抛 ValueError。
    断点依次查看 objects（含 center_px）、converted（含 mm_status/center_mm）。
    """
    objects, masks = detect_objects(frame, args.min_area)
    height, width = frame.shape[:2]
    converted = add_workplane_coordinates(objects, args.plane_data,
                                          {"width": width, "height": height}, args.intrinsics_data)
    pixel_frame = "undistorted" if args.intrinsics_data else "raw"
    status = ("CALIBRATED" if args.plane_data else "UNCALIBRATED") + f" | {pixel_frame}"
    annotated = annotate_frame(frame, converted, fps, paused, calibration_status=status)
    result = build_result(frame, converted, source, timestamp, args.plane_data, args.intrinsics_data)
    return annotated, masks, result


def run_image(args) -> int:
    """读取单张图片，按需校正后检测/显示/导出；返回退出码，输入或标定错误向外抛出。"""
    frame = read_image(args.image)
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    frame = undistort_frame(frame, args.intrinsics_data)
    source = f"image:{args.image.resolve()}"
    annotated, masks, result = analyze_frame(frame, args, source, timestamp)
    print(f'检测到 {len(result["objects"])} 个目标，标定状态：{result["calibration"]["status"]}。')
    if args.save or args.no_display:
        if not export_current(annotated, result):
            return 1
    if args.no_display:
        return 0
    create_window(args.min_area)
    last_area = args.min_area
    while window_is_open():
        try:
            min_area = max(1, cv2.getTrackbarPos("Min area", WINDOW_NAME))
            if min_area != last_area:
                args.min_area = min_area
                annotated, masks, result = analyze_frame(frame, args, source, timestamp)
                last_area = min_area
                print(f'检测到 {len(result["objects"])} 个目标，最小面积 {min_area} px^2。')
            show_preview(annotated, masks)
            key = cv2.waitKey(20) & 0xFF
        except cv2.error:
            # 处理查询后、绘制前用户恰好关闭窗口的情况；窗口仍在则保留真实错误。
            if window_is_open():
                raise
            break
        if key in (27, ord("q"), ord("Q")) or not window_is_open():
            break
        if key in (ord("s"), ord("S")):
            export_current(annotated, result)
    return 0


def run_camera(args) -> int:
    """处理摄像头帧和 P/S/Q 控制；暂停复用同一帧，任何退出路径都释放设备。"""
    cap = open_camera(args.camera)
    try:
        create_window(args.min_area)
        paused, frame, timestamp = False, None, None
        fps, previous_time = 0.0, None
        while window_is_open():
            if not paused or frame is None:
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError("摄像头帧读取失败，可能已断开、被占用或权限受限。请检查后重新启动。")
                timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                # 始终先校正新帧，再复用同一校正帧进行检测、标注和导出；暂停不重复校正。
                frame = undistort_frame(frame, args.intrinsics_data)
                now = perf_counter()
                if previous_time is not None:
                    fps = 1.0 / max(now - previous_time, 1e-9)
                previous_time = now
            try:
                min_area = max(1, cv2.getTrackbarPos("Min area", WINDOW_NAME))
                args.min_area = min_area
                # 即使预览的是 Mask，S 也保存同一坐标空间、同一帧的彩色图和毫米结果。
                annotated, masks, result = analyze_frame(frame, args, f"camera:{args.camera}", timestamp, fps, paused)
                show_preview(annotated, masks)
                key = cv2.waitKey(20) & 0xFF
            except cv2.error:
                if window_is_open():
                    raise
                break
            if key in (27, ord("q"), ord("Q")) or not window_is_open():
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
    """加载合法的可选标定配置后运行；失败打印中文原因，返回 1 并清理窗口。"""
    args = parse_args(argv)
    try:
        if args.calibration:
            args.plane_data = load_calibration(args.calibration)
        if args.intrinsics:
            args.intrinsics_data = load_calibration(args.intrinsics, "camera_intrinsics")
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
