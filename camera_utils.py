"""轻量摄像头管理：OpenCV 可用索引、本地偏好、采集设置及实际返回信息。

索引不是 USB 设备序列号。Python VideoCapture 不提供可靠的 Windows 设备路径映射，
本模块不猜测 PnP 列表与 OpenCV 枚举的对应关系，也不宣称索引永久绑定物理设备。
"""

import json
import math
import os
from pathlib import Path
import tempfile

import cv2

BACKENDS = {"DSHOW": cv2.CAP_DSHOW, "MSMF": cv2.CAP_MSMF, "ANY": cv2.CAP_ANY}


def open_camera(index, backend=None):
    """打开指定索引；首次自动尝试后端，已保存后端则只使用该后端，不换设备。

    返回由调用者负责 release 的 VideoCapture；全部失败抛中文 RuntimeError。
    此处不读取帧、不更改分辨率，保留原标定工具的调用方式。
    """
    choices = [BACKENDS[backend]] if backend else (
        [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if os.name == "nt" else [cv2.CAP_ANY])
    for api in choices:
        cap = cv2.VideoCapture()
        try:
            if cap.open(index, api) and cap.isOpened():
                return cap
        except cv2.error:
            pass
        cap.release()
    raise RuntimeError(f"无法打开摄像头 {index}（{backend or '自动后端'}）。请检查连接、占用和 Windows 权限；"
                       "运行 --list-cameras 后用 --camera N 重新选择，不会自动切换到其他编号。")


def load_camera_preference(path):
    """读取本机索引偏好；不存在返回 None，损坏时明确拒绝自动回退到摄像头 0。"""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("版本无效")
        if type(data.get("camera_index")) is not int or data["camera_index"] < 0:
            raise ValueError("camera_index 无效")
        if "backend" not in data or (data["backend"] is not None and data["backend"] not in BACKENDS):
            raise ValueError("backend 无效")
        size = data.get("capture_size")
        if not isinstance(size, dict) or any(type(size.get(key)) is not int or size[key] <= 0 for key in ("width", "height")):
            raise ValueError("capture_size 无效")
        return data
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError(f"本地摄像头偏好损坏：{path}。请用 --camera N 显式重新选择，或移走此配置后重试。") from exc


def choose_camera(explicit_index, preference=None, backend=None, size=None):
    """纯函数：CLI 优先于偏好；无偏好才使用 0。返回索引、后端、请求尺寸和来源。

    显式选择索引时不沿用另一台相机的后端/分辨率；隐式启动恢复已保存设置。
    """
    saved = explicit_index is None and preference is not None
    return {"index": preference["camera_index"] if saved else (explicit_index if explicit_index is not None else 0),
            "backend": backend or (preference["backend"] if saved else None),
            "size": size or (preference["capture_size"] if saved else None), "from_preference": saved}


def save_camera_preference(path, index, info):
    """成功读取并校验首帧后原子保存实际尺寸和后端；文件仅供本机使用。"""
    path = Path(path)
    data = {"version": 1, "identity_kind": "opencv_index_only", "camera_index": index,
            "backend": info["backend"] if info["backend"] in BACKENDS else None,
            "capture_size": {"width": info["width"], "height": info["height"]}}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def configure_capture(cap, size=None, plane=None, intrinsics=None):
    """可选请求采集宽高（pixel）；已有标定与请求尺寸不符时，在 set 前拒绝。

    set 返回成功不等于相机接受设置，调用者仍必须以实际 frame.shape 检查。
    不设置帧率、焦距或任何默认分辨率，不静默调整已有标定。
    """
    if size is None:
        return
    for calibration in (plane, intrinsics):
        if calibration is not None and calibration["image_size"] != size:
            raise ValueError("请求采集分辨率与已有标定不一致，未更改设备设置。请重新验证/标定，或使用原分辨率。")
    accepted_w = cap.set(cv2.CAP_PROP_FRAME_WIDTH, size["width"])
    accepted_h = cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size["height"])
    if not accepted_w or not accepted_h:
        print("提示：设备未确认接受分辨率设置，将检查实际返回的图像尺寸。")


def capture_info(cap, frame):
    """返回首帧真实宽高、实际视频后端及设备报告 FPS；未知帧率为 None，不伪造。

    CAP_PROP_FPS 是驱动报告值，不是实测循环 FPS；尺寸始终来自 frame.shape。
    """
    height, width = frame.shape[:2]
    try:
        backend = cap.getBackendName()
        if not isinstance(backend, str):
            backend = "UNKNOWN"
    except (cv2.error, AttributeError):
        backend = "UNKNOWN"
    try:
        reported_fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(reported_fps) or reported_fps <= 0:
            reported_fps = None
    except (cv2.error, TypeError, ValueError):
        reported_fps = None
    return {"width": width, "height": height, "backend": backend, "reported_fps": reported_fps}


def list_cameras(limit=5, backend=None):
    """依次探测 0..limit-1，只有成功读取图像才列为可用；所有探测句柄立即释放。

    不写偏好、不保存照片；编号可能因插拔或后端而变化，也可能因占用而暂不可用。
    """
    devices = []
    for index in range(limit):
        choices = [backend] if backend else (["DSHOW", "MSMF", "ANY"] if os.name == "nt" else ["ANY"])
        for api in choices:
            cap = None
            try:
                cap = open_camera(index, api)
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    devices.append({"index": index, **capture_info(cap, frame)})
                    break
            except (cv2.error, RuntimeError):
                continue
            finally:
                if cap is not None:
                    cap.release()
    return devices
