"""启动器相机扫描/预览子进程；不保存照片，不执行识别或修改标定。

独立进程使驱动阻塞不会冻结 Tk，父窗口可以取消和限时回收设备。
"""

import json
from pathlib import Path
import sys
from time import monotonic

import cv2

from camera_utils import capture_info, configure_capture, list_cameras, open_camera
from launcher_config import validate_settings


def write_status(path, data):
    """以原子 JSON 报告状态，不含图像；父进程不会读到半个 JSON。"""
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def preview_camera(settings, result_path):
    """预览指定设备，C 确认、Q/Esc/关闭取消；真实宽高来自 frame.shape。

    只缩放显示副本，绝不将显示尺寸当成采集尺寸。返回 0，失败向外抛出。
    摄像头始终由 finally 释放；首次 ready 与每秒心跳供父窗口监测阻塞。
    """
    settings = validate_settings(settings)
    if settings["camera_index"] is None:
        raise ValueError("请填写摄像头编号。")
    backend = None if settings["backend"] == "auto" else settings["backend"].upper()
    cap = open_camera(settings["camera_index"], backend)
    window = "CargoVision Camera Preview - C confirm / Q cancel"
    window_created = False
    try:
        configure_capture(cap, {"width": settings["width"], "height": settings["height"]},
                          fourcc=None if settings["fourcc"] == "auto" else settings["fourcc"].upper(), fps=settings["fps"])
        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        window_created = True
        last_heartbeat = -float("inf")
        while True:
            ok, frame = cap.read()
            if not ok or frame is None or not frame.size:
                raise RuntimeError("摄像头读取失败，请检查连接、占用或采集模式；不会切换到其他编号。")
            info = capture_info(cap, frame)
            if monotonic() - last_heartbeat >= 1:
                write_status(result_path, {"status": "ready", "info": info})
                last_heartbeat = monotonic()
            h, w = frame.shape[:2]
            scale = min(1, 960 / w, 660 / h)
            canvas = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))))
            text = f'#{settings["camera_index"]} {info["backend"]} actual {w}x{h} | C confirm / Q cancel'
            cv2.putText(canvas, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(20) & 255
            try:
                visible = cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) >= 1
            except cv2.error:
                visible = False
            if not visible or key in (27, ord("q"), ord("Q")):
                write_status(result_path, {"status": "cancelled"})
                return 0
            if key in (ord("c"), ord("C")):
                write_status(result_path, {"status": "confirmed", "info": info})
                return 0
    except cv2.error:
        # 用户可能在查询前销毁原生窗口。只吞掉确实关闭的窗口错误，设备/绘制错误仍报告。
        if window_created:
            try:
                closed = cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1
            except cv2.error:
                closed = True
            if closed:
                write_status(result_path, {"status": "cancelled"})
                return 0
        raise
    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass


def main(argv=None):
    """内部入口：scan/preview + 请求 JSON + 状态 JSON；错误写中文诊断、返回 1。"""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3 or argv[0] not in ("scan", "preview"):
        print("此工具由启动器调用，请双击 Start_CargoVision.cmd。", file=sys.stderr)
        return 1
    action, request_path, result_path = argv
    try:
        if action == "scan":
            write_status(result_path, {"status": "scanned", "devices": list_cameras(5)})
            return 0
        return preview_camera(json.loads(Path(request_path).read_text(encoding="utf-8")), result_path)
    except (OSError, ValueError, RuntimeError, cv2.error) as exc:
        print(f"摄像头操作失败：{exc}", file=sys.stderr)
        write_status(result_path, {"status": "error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
