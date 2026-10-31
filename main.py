"""CargoVision Mini：保留像素工作流，可选接入同平面毫米标定和内参校正。"""

import argparse
from datetime import datetime
from pathlib import Path
import sys
from time import perf_counter

try:
    import cv2
    from calibration import (add_workplane_coordinates, load_calibration, undistort_frame)
    from camera_utils import (capture_info, choose_camera, configure_capture, list_cameras,
                              load_camera_preference, open_camera, save_camera_preference)
    from config import (AREA_SLIDER_MAX, CAMERA_PREFERENCE_PATH, DEFAULT_MIN_AREA, MAX_MIN_AREA,
                        PREVIEW_MODES, PREVIEW_SIZE, WINDOW_NAME)
    from display import initial_preview_size, render_workbench
    from io_utils import build_result, read_image, save_results
    from vision import annotate_frame, detect_objects
except ModuleNotFoundError as exc:
    raise SystemExit("缺少运行依赖，请使用项目 .venv 的 Python 执行："
                     "python -m pip install -r requirements.txt") from exc


def parse_args(argv=None):
    """解析 CLI 并保持旧命令兼容；面积为 px²，配置路径可选，参数错误退出码为 2。"""
    parser = argparse.ArgumentParser(description="CargoVision Mini：红绿蓝目标的像素定位")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--camera", type=int, help="显式选择并记住摄像头编号；优先于本机偏好")
    group.add_argument("--image", type=Path, help="检测本地图片")
    group.add_argument("--list-cameras", action="store_true", help="列出可读取图像的 OpenCV 摄像头编号")
    parser.add_argument("--scan-limit", type=int, default=5, help="枚举 0..N-1，默认 N=5，最大 20")
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), help="视频后端；默认沿用本机偏好或自动选择")
    parser.add_argument("--width", type=int, help="请求采集宽度 pixel，必须与 --height 一起使用")
    parser.add_argument("--height", type=int, help="请求采集高度 pixel；检查设备实际返回值")
    parser.add_argument("--calibration", type=Path, help="四点工作平面标定 JSON；不提供时只输出像素")
    parser.add_argument("--intrinsics", type=Path, help="可选相机内参 JSON，先去畸变再检测")
    parser.add_argument("--min-area", type=int, default=DEFAULT_MIN_AREA,
                        help=f"最小轮廓面积，默认 {DEFAULT_MIN_AREA} px^2")
    parser.add_argument("--no-display", action="store_true", help="图片模式不打开窗口，并自动保存结果")
    parser.add_argument("--save", action="store_true", help="图片模式启动时保存一次结果")
    parser.add_argument("--area-max", type=int, default=AREA_SLIDER_MAX, help="面积滑条上限，默认 5000 px²；初值更大时自动扩展")
    args = parser.parse_args(argv)
    if args.camera is not None and args.camera < 0:
        parser.error("摄像头编号必须大于等于 0。")
    if not 1 <= args.min_area <= MAX_MIN_AREA:
        parser.error(f"最小面积必须在 1~{MAX_MIN_AREA} 之间。")
    if not 1 <= args.area_max <= MAX_MIN_AREA:
        parser.error(f"面积滑条上限必须在 1~{MAX_MIN_AREA} 之间。")
    args.area_max = max(args.area_max, args.min_area)
    if not 1 <= args.scan_limit <= 20:
        parser.error("--scan-limit 必须在 1~20 之间。")
    if (args.width is None) != (args.height is None):
        parser.error("--width 和 --height 必须一起指定。")
    if args.width is not None and not (1 <= args.width <= 16384 and 1 <= args.height <= 16384):
        parser.error("采集宽高必须在 1~16384 pixel 之间。")
    if args.image is not None and (args.width is not None or args.backend is not None):
        parser.error("--width / --height / --backend 只用于摄像头。")
    if (args.no_display or args.save) and args.image is None:
        parser.error("--no-display 和 --save 仅用于 --image 图片模式。")
    args.camera_explicit = args.camera is not None
    args.ui = {"detail": False, "page": 0, "min_area": args.min_area}
    args.camera_choice = None
    args.plane_data = None
    args.intrinsics_data = None
    return args


def create_window(min_area: int, area_max=AREA_SLIDER_MAX):
    """只在初始化时设一次 960×720 图像区；后续尊重用户尺寸，不逐帧 resizeWindow。"""
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO)
    cv2.createTrackbar("Min area", WINDOW_NAME, min_area, max(min_area, area_max), lambda value: None)
    cv2.createTrackbar("View 0=RGB 1=R 2=G 3=B", WINDOW_NAME, 0, 3, lambda value: None)
    cv2.resizeWindow(WINDOW_NAME, *initial_preview_size())


def window_is_open(window_name=WINDOW_NAME) -> bool:
    """关闭按钮可能直接销毁原生窗口；查询此窗口时也可能抛出 cv2.error。"""
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def show_preview(annotated, masks, result=None, ui=None, raw_frame=None):
    """按当前窗口图像区尺寸生成画布；缩放仅用于预览，Mask 不改变原始数据。"""
    mode = PREVIEW_MODES[cv2.getTrackbarPos("View 0=RGB 1=R 2=G 3=B", WINDOW_NAME)]
    if mode == "original":
        preview = raw_frame if raw_frame is not None else annotated
    else:
        preview = cv2.cvtColor(masks[mode], cv2.COLOR_GRAY2BGR)
    _, _, width, height = cv2.getWindowImageRect(WINDOW_NAME)
    size = (width, height) if width > 16 and height > 16 else PREVIEW_SIZE
    state = ui if ui is not None else {}
    state["view"] = mode
    result = result or {"objects": []}
    canvas = render_workbench(preview, result["objects"], result, state, size)
    cv2.imshow(WINDOW_NAME, canvas)


def handle_view_key(key, args):
    """D 切换详细列表，[ ] 翻页，+/- 以 1 px² 精调；不触碰识别或标定结果。"""
    if key in (ord("d"), ord("D")):
        args.ui["detail"] = not args.ui["detail"]
    elif key in (ord("["), ord("]")):
        args.ui["page"] = max(0, args.ui["page"] + (1 if key == ord("]") else -1))
    elif key in (ord("+"), ord("="), ord("-")):
        area = max(1, min(args.area_max, args.min_area + (-1 if key == ord("-") else 1)))
        try:
            cv2.setTrackbarPos("Min area", WINDOW_NAME, area)
        except cv2.error:
            if window_is_open():
                raise


def prepare_camera_choice(args):
    """显式参数覆盖偏好；损坏偏好只允许通过显式 --camera 安全重新选择。"""
    preference = None if args.camera_explicit else load_camera_preference(CAMERA_PREFERENCE_PATH)
    backend = args.backend.upper() if args.backend and args.backend != "auto" else None
    requested_size = {"width": args.width, "height": args.height} if args.width is not None else None
    choice = choose_camera(args.camera if args.camera_explicit else None, preference, backend, requested_size)
    if args.backend == "auto":
        choice["backend"] = None
    args.camera = choice["index"]
    args.camera_choice = choice
    origin = "本机偏好" if choice["from_preference"] else ("命令行" if args.camera_explicit else "首次默认")
    print(f"摄像头选择：{args.camera}（{origin}，{choice['backend'] or '自动后端'}）。")
    print("注意：仅保存 OpenCV 索引和后端，不是物理设备绑定；插拔/重启后请核对画面，必要时 --list-cameras 并 --camera N 重选。")
    if args.plane_data is not None or args.intrinsics_data is not None:
        print("标定提醒：更换相机、采集尺寸、焦距或安装位置后必须重新验证/标定；尺寸相同也不代表同一设备。")


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
    args.ui.update(fps=fps, paused=paused, min_area=args.min_area)
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
    args.ui["source_label"] = "IMAGE"
    create_window(args.min_area, args.area_max)
    last_area = args.min_area
    while window_is_open():
        try:
            min_area = max(1, cv2.getTrackbarPos("Min area", WINDOW_NAME))
            args.ui["min_area"] = min_area
            if min_area != last_area:
                args.min_area = min_area
                annotated, masks, result = analyze_frame(frame, args, source, timestamp)
                last_area = min_area
                print(f'检测到 {len(result["objects"])} 个目标，最小面积 {min_area} px^2。')
            show_preview(annotated, masks, result, args.ui, frame)
            key = cv2.waitKey(20) & 0xFF
        except cv2.error:
            # 处理查询后、绘制前用户恰好关闭窗口的情况；窗口仍在则保留真实错误。
            if window_is_open():
                raise
            break
        if key in (27, ord("q"), ord("Q")) or not window_is_open():
            break
        handle_view_key(key, args)
        if key in (ord("s"), ord("S")):
            saved = export_current(annotated, result)
            args.ui["message"] = "Saved PNG + JSON (capture size)" if saved else "SAVE FAILED - see console"
    return 0


def run_camera(args) -> int:
    """处理摄像头帧和 P/S/Q 控制；暂停复用同一帧，任何退出路径都释放设备。"""
    if args.camera_choice is None:
        prepare_camera_choice(args)
    choice = args.camera_choice
    cap = open_camera(args.camera, choice["backend"]) if choice["backend"] else open_camera(args.camera)
    try:
        configure_capture(cap, choice["size"], args.plane_data, args.intrinsics_data)
        create_window(args.min_area, args.area_max)
        paused, frame, timestamp = False, None, None
        fps, previous_time = 0.0, None
        info, startup_complete = None, False
        while window_is_open():
            if not paused or frame is None:
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    raise RuntimeError(f"摄像头 {args.camera} 帧读取失败，可能已断开、被占用或权限受限。"
                                       "请检查后重新启动，或 --list-cameras / --camera N 重选；不会切换其他编号。")
                if info is None:
                    info = capture_info(cap, frame)
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
                if not startup_complete:
                    reported = f'{info["reported_fps"]:.1f}' if info["reported_fps"] is not None else "未知"
                    print(f'实际采集：{info["width"]}×{info["height"]}，后端 {info["backend"]}，设备报告 FPS {reported}（循环 FPS 见窗口）。')
                    if choice["size"] is not None and choice["size"] != {"width": info["width"], "height": info["height"]}:
                        print("提示：实际分辨率与请求不同；以实际帧为准，已有标定不匹配时程序会拒绝毫米输出。")
                    fps_label = reported if info["reported_fps"] is not None else "unknown"
                    args.ui["source_label"] = f'Camera {args.camera} | {info["backend"]} | Device FPS {fps_label}'
                    try:
                        save_camera_preference(CAMERA_PREFERENCE_PATH, args.camera, info)
                    except OSError as exc:
                        print(f"本机摄像头偏好保存失败：{exc}", file=sys.stderr)
                        args.ui["message"] = "PREFERENCE SAVE FAILED - see console"
                    startup_complete = True
                show_preview(annotated, masks, result, args.ui, frame)
                key = cv2.waitKey(20) & 0xFF
            except cv2.error:
                if window_is_open():
                    raise
                break
            if key in (27, ord("q"), ord("Q")) or not window_is_open():
                break
            handle_view_key(key, args)
            if key in (ord("p"), ord("P")):
                paused = not paused
                previous_time = None  # 恢复时不要把暂停时长计入 FPS。
            if key in (ord("s"), ord("S")):
                saved = export_current(annotated, result)
                args.ui["message"] = "Saved PNG + JSON (capture size)" if saved else "SAVE FAILED - see console"
    finally:
        cap.release()
    return 0


def main(argv=None) -> int:
    """加载合法的可选标定配置后运行；失败打印中文原因，返回 1 并清理窗口。"""
    args = parse_args(argv)
    try:
        if args.list_cameras:
            print(f"正在检测 0..{args.scan_limit - 1}，设备忙或权限不足也可能导致暂不可用。")
            backend = args.backend.upper() if args.backend and args.backend != "auto" else None
            devices = list_cameras(args.scan_limit, backend)
            for device in devices:
                fps = f'{device["reported_fps"]:.1f}' if device["reported_fps"] is not None else "未知"
                backend_option = f' --backend {device["backend"].lower()}' if device["backend"] in ("DSHOW", "MSMF") else ""
                print(f'--camera {device["index"]}{backend_option}: {device["width"]}×{device["height"]} | {device["backend"]} | 设备报告 FPS {fps}')
            print("请选择画面对应的设备：python main.py --camera N；成功读取后记住本机偏好。索引不是永久物理设备标识。")
            if not devices:
                print("未发现可读取设备，请检查连接/占用/权限，或增大 --scan-limit。", file=sys.stderr)
            return 0 if devices else 1
        if args.calibration:
            args.plane_data = load_calibration(args.calibration)
        if args.intrinsics:
            args.intrinsics_data = load_calibration(args.intrinsics, "camera_intrinsics")
        if args.image is None:
            prepare_camera_choice(args)
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
