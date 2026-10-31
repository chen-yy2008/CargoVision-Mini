"""限时、逐模式核对摄像头；只输出数值报告，不保存照片或修改本机偏好。

每个模式用独立子进程打开同一编号，避免驱动 read/open 卡住整个检测工具。
这是一组请求的验证，不是驱动支持列表枚举；高分辨率返回帧也不证明传感器原生像素。
"""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from camera_utils import (capture_info, capture_properties, configure_capture, load_camera_preference,
                          open_camera, validate_capture_format)
from config import CAMERA_PREFERENCE_PATH, OUTPUT_DIR

DEFAULT_SIZES = ("640x480", "1280x720", "1920x1080", "2560x1440", "3840x2160")


def measure_mode(spec):
    """请求一个模式并测量 read 吞吐率；spec 含 pixel 宽高、后端、格式、FPS 请求。

    返回请求、set 结果、属性读回、逐帧尺寸统计和实测 FPS（frame/s）。
    先丢弃 warmup 帧，再用帧完成时刻间隔 (N-1)/(t_last-t_first) 计算；
    不含 UI/检测，不等于传感器曝光 FPS，也不检测驱动是否重复了内容。
    断点看 requested / info / sizes / timestamps。错误保留已读样本且始终 release。
    超时由父进程负责；不要在 GUI 线程直接调用本函数。
    """
    result = {"requested": spec, "status": "error", "frames": 0, "measured_read_fps": None,
              "exact_resolution": False, "format_property_matches": None, "size_counts": {}}
    cap = None
    timestamps, sizes = [], Counter()
    try:
        cap = open_camera(spec["index"], spec["backend"])
        result["set_results"] = configure_capture(cap, spec["size"], fourcc=spec["fourcc"], fps=spec["fps"])
        result["properties_after_set"] = capture_properties(cap)
        for _ in range(spec["warmup"]):
            ok, frame = cap.read()
            if not ok or frame is None or not frame.size:
                raise RuntimeError("预热读帧失败，设备可能被占用/断开或不接受此模式。")
        started = perf_counter()
        while perf_counter() - started < spec["seconds"] and len(timestamps) < 1000:
            ok, frame = cap.read()
            if not ok or frame is None or not frame.size:
                raise RuntimeError("测量期间读帧失败。")
            timestamps.append(perf_counter())
            sizes[(frame.shape[1], frame.shape[0])] += 1
            if "actual" not in result:
                result["actual"] = capture_info(cap, frame)
        if not timestamps:
            raise RuntimeError("未取得测量帧。")
        # 末帧后再次读取属性，暴露协商或采集中属性变化；真实宽高仍以每帧 shape 为准。
        result["last_properties"] = capture_info(cap, frame)["properties"]
        expected = (spec["size"]["width"], spec["size"]["height"])
        result["exact_resolution"] = set(sizes) == {expected}
        observed_format = result["actual"]["properties"]["fourcc"]
        if spec["fourcc"] and observed_format:
            result["format_property_matches"] = observed_format == spec["fourcc"]
        result["status"] = "read_ok" if result["exact_resolution"] else "size_mismatch"
    except (OSError, ValueError, RuntimeError, cv2.error) as exc:
        result["error"] = str(exc)
    finally:
        if cap is not None:
            cap.release()
        result["frames"] = len(timestamps)
        result["size_counts"] = {f"{w}x{h}": count for (w, h), count in sizes.items()}
        if len(timestamps) >= 2 and timestamps[-1] > timestamps[0]:
            result["sample_seconds"] = timestamps[-1] - timestamps[0]
            result["measured_read_fps"] = (len(timestamps) - 1) / result["sample_seconds"]
    return result


def run_isolated(spec, timeout, directory):
    """用当前 Python 子进程测一个模式；超过 timeout 秒强制结束并回收句柄。

    结果用 UTF-8 JSON 传输，避免 Windows 驱动日志污染 stdout。超时不是“不支持”的证明。
    directory 为本次临时目录，函数不改写相机偏好或保存图像。
    """
    result_path = Path(directory) / f"{uuid4().hex}.json"
    command = [sys.executable, str(Path(__file__).resolve()), "--_worker", json.dumps(spec), str(result_path)]
    try:
        process = subprocess.run(command, timeout=timeout, capture_output=True)
        if process.returncode != 0 or not result_path.exists():
            return {"requested": spec, "status": "worker_error", "error": f"子进程退出码 {process.returncode}"}
        return json.loads(result_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return {"requested": spec, "status": "timeout", "error": f"超过 {timeout:g} 秒；不能据此断言设备不支持。"}
    except (OSError, ValueError) as exc:
        return {"requested": spec, "status": "worker_error", "error": f"子进程结果不可用：{exc}"}


def parse_args(argv=None):
    """验证工具参数；不隐式探测别的编号，不接受无上限的扫描组合。"""
    parser = argparse.ArgumentParser(description="摄像头采集模式检查：不保存画面/不改偏好，请先退出占用设备的软件。")
    parser.add_argument("--camera", type=int, help="设备编号；省略时使用已保存编号，无偏好则要求显式指定")
    parser.add_argument("--backends", nargs="+", choices=("dshow", "msmf"), default=["dshow", "msmf"])
    parser.add_argument("--formats", nargs="+", choices=("auto", "mjpg", "yuy2"), default=["auto", "mjpg", "yuy2"])
    parser.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES), help="请求列表，如 640x480 1280x720")
    parser.add_argument("--fps", type=float, help="可选请求 FPS 1~240；默认不设置设备帧率")
    parser.add_argument("--seconds", type=float, default=2, help="每模式测量秒数（0.2~15，默认 2）")
    parser.add_argument("--warmup", type=int, default=5, help="测量前丢弃帧数（0~60，默认 5）")
    parser.add_argument("--timeout", type=float, default=15, help="每模式进程总时限秒数（3~60，默认 15）")
    parser.add_argument("--output", type=Path, help="JSON 数值报告；默认 outputs 下唯一文件，不覆盖已有文件")
    args = parser.parse_args(argv)
    try:
        validate_capture_format(fps=args.fps)
        if args.camera is not None and args.camera < 0:
            raise ValueError("摄像头编号不能为负。")
        if not 0.2 <= args.seconds <= 15 or not 3 <= args.timeout <= 60 or args.timeout <= args.seconds:
            raise ValueError("seconds 必须在 0.2~15，timeout 在 3~60 且大于 seconds。")
        if not 0 <= args.warmup <= 60:
            raise ValueError("warmup 必须在 0~60。")
        sizes = []
        for item in dict.fromkeys(args.sizes):
            width, height = map(int, item.lower().split("x"))
            if not (1 <= width <= 16384 and 1 <= height <= 16384):
                raise ValueError("尺寸必须在 1~16384 pixel。")
            sizes.append({"width": width, "height": height})
        args.sizes = sizes
        args.backends = list(dict.fromkeys(args.backends))
        args.formats = list(dict.fromkeys(args.formats))
        if len(sizes) > 10 or len(sizes) * len(args.backends) * len(args.formats) > 60:
            raise ValueError("每次最多 10 种分辨率、60 个模式组合。")
    except ValueError as exc:
        parser.error(f"参数错误：{exc}")
    return args


def main(argv=None):
    """顺序验证模式并生成报告；至少一组精确尺寸可读返回 0，否则返回 1。

    成功退出不代表所有模式支持，也不是标定或 USB 身份验收；逐项查看 status。
    """
    args = parse_args(argv)
    try:
        if args.camera is None:
            preference = load_camera_preference(CAMERA_PREFERENCE_PATH)
            if preference is None:
                raise ValueError("没有已保存设备，请先 --list-cameras 核对画面，再给本工具 --camera N。")
            args.camera = preference["camera_index"]
        path = args.output or OUTPUT_DIR / f'camera_probe_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        # 独占创建，防止检测结束后才发现同名报告会覆盖已有实验数据。
        with path.open("x", encoding="utf-8") as stream:
            report = {"created_at": datetime.now().astimezone().isoformat(), "camera_index": args.camera,
                      "opencv_version": cv2.__version__, "results": [], "complete": False,
                      "notes": ["只核对指定编号，不保证不同后端编号对应同一物理设备。",
                                "真实尺寸来自 frame.shape；set 成功与属性读回都不是原生模式证明。",
                                "measured_read_fps 为预热后纯采集吞吐率，不是处理/UI或曝光帧率。",
                                "格式/FPS/视野变化后重新验证标定；未保存照片或设备偏好。"]}
            try:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="camera_probe_", dir=OUTPUT_DIR) as directory:
                    for backend in args.backends:
                        for fmt in args.formats:
                            for size in args.sizes:
                                print(f'检查 #{args.camera} {backend} {fmt} {size["width"]}x{size["height"]} ...', flush=True)
                                spec = {"index": args.camera, "backend": backend.upper(), "size": size,
                                        "fourcc": None if fmt == "auto" else fmt.upper(), "fps": args.fps,
                                        "seconds": args.seconds, "warmup": args.warmup}
                                result = run_isolated(spec, args.timeout, directory)
                                report["results"].append(result)
                                print(f'  {result["status"]} | 实际 {result.get("size_counts", {})} | '
                                      f'实测 read FPS {result.get("measured_read_fps")} | '
                                      f'属性 {result.get("actual", {}).get("properties", {})}', flush=True)
                report["complete"] = True
            except KeyboardInterrupt:
                report["interrupted"] = True
                print("已停止；保存已完成的模式报告。")
            finally:
                json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        print(f"数值报告：{path.resolve()}\n请逐项核对；检测不会修改 main.py 的本机偏好。")
        return 0 if any(row.get("status") == "read_ok" for row in report["results"]) else 1
    except (OSError, ValueError) as exc:
        print(f"检测失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--_worker":
        Path(sys.argv[3]).write_text(json.dumps(measure_mode(json.loads(sys.argv[2])),
                                              ensure_ascii=False, allow_nan=False), encoding="utf-8")
    else:
        raise SystemExit(main())
