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
FOURCC_CHOICES = ("MJPG", "YUY2")


def validate_capture_format(fourcc=None, fps=None):
    """校验可选格式与请求帧率（frame/s）；None 表示不设置，非法值抛 ValueError。"""
    if fourcc is not None and fourcc not in FOURCC_CHOICES:
        raise ValueError("采集格式只支持 MJPG / YUY2，或不指定。")
    if fps is not None and (type(fps) not in (int, float) or not math.isfinite(fps) or not 1 <= fps <= 240):
        raise ValueError("请求 FPS 必须是 1~240 之间的有限数值。")


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
        validate_capture_format(data.get("requested_fourcc"), data.get("requested_fps"))
        return data
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError(f"本地摄像头偏好损坏：{path}。请用 --camera N 显式重新选择，或移走此配置后重试。") from exc


def choose_camera(explicit_index, preference=None, backend=None, size=None, fourcc=None, fps=None):
    """纯函数：CLI 优先于偏好；无偏好才使用 0。返回索引、后端、请求尺寸和来源。

    显式选择索引时不沿用另一台相机的后端/分辨率；隐式启动恢复已保存设置。
    """
    saved = explicit_index is None and preference is not None
    choice = {"index": preference["camera_index"] if saved else (explicit_index if explicit_index is not None else 0),
            "backend": backend or (preference["backend"] if saved else None),
            "size": size or (preference["capture_size"] if saved else None), "from_preference": saved}
    for key, value in (("requested_fourcc", fourcc), ("requested_fps", fps)):
        value = value if value is not None else (preference.get(key) if saved else None)
        if value is not None:
            choice[key] = value
    return choice


def save_camera_preference(path, index, info):
    """成功读取并校验首帧后原子保存实际尺寸和后端；文件仅供本机使用。"""
    path = Path(path)
    data = {"version": 1, "identity_kind": "opencv_index_only", "camera_index": index,
            "backend": info["backend"] if info["backend"] in BACKENDS else None,
            "capture_size": {"width": info["width"], "height": info["height"]}}
    # 格式/FPS 保留“请求”语义，不把驱动属性读回值或测得的吞吐率伪装成设置。
    validate_capture_format(info.get("requested_fourcc"), info.get("requested_fps"))
    for key in ("requested_fourcc", "requested_fps"):
        if info.get(key) is not None:
            data[key] = info[key]
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


def configure_capture(cap, size=None, plane=None, intrinsics=None, fourcc=None, fps=None):
    """可选请求采集宽高（pixel）；已有标定与请求尺寸不符时，在 set 前拒绝。

    set 返回成功不等于相机接受设置，调用者仍必须以实际 frame.shape 检查。
    fourcc 为 MJPG/YUY2，fps 单位 frame/s；仅显式请求时设置。不改焦距/变焦。
    返回各属性 set 的布尔结果（只是驱动确认，不是实际能力证明）。
    """
    validate_capture_format(fourcc, fps)
    for calibration in (plane, intrinsics):
        if size is not None and calibration is not None and calibration["image_size"] != size:
            raise ValueError("请求采集分辨率与已有标定不一致，未更改设备设置。请重新验证/标定，或使用原分辨率。")
    if size is not None or fourcc is not None or fps is not None:
        print("提示：采集模式请求/恢复后，请核对视野、清晰度及独立验证点；模式改变可能需要重新标定。")
    settings = []
    if size is not None:
        settings.extend((("width", cv2.CAP_PROP_FRAME_WIDTH, size["width"]),
                         ("height", cv2.CAP_PROP_FRAME_HEIGHT, size["height"])))
    # DSHOW 可在宽高更新后按 FOURCC 重新协商媒体类型；全套设置后再读帧验收。
    # MSMF 可能返回转换后的格式，无法凭 FOURCC 属性证明 USB 链路的原生格式。
    if fourcc is not None:
        settings.append(("fourcc", cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc)))
    if fps is not None:
        settings.append(("fps", cv2.CAP_PROP_FPS, fps))
    accepted = {name: bool(cap.set(prop, value)) for name, prop, value in settings}
    if not all(accepted.values()):
        print("提示：设备未确认接受部分采集设置，将检查属性读回及实际返回的图像尺寸。")
    return accepted


def capture_properties(cap):
    """读取驱动属性（尺寸为 pixel，FPS 为 frame/s）；未知/非有限值返回 None。

    属性不是 frame.shape，也不是实测帧率；FOURCC 可能是后端转换后的输出格式。
    """
    values = {}
    for name, prop in (("width", cv2.CAP_PROP_FRAME_WIDTH), ("height", cv2.CAP_PROP_FRAME_HEIGHT),
                       ("fps", cv2.CAP_PROP_FPS), ("fourcc_code", cv2.CAP_PROP_FOURCC)):
        try:
            value = float(cap.get(prop))
            values[name] = value if math.isfinite(value) and value > 0 else None
        except (cv2.error, TypeError, ValueError):
            values[name] = None
    code = values["fourcc_code"]
    code = int(code) if code is not None and code <= 0xFFFFFFFF else 0
    chars = "".join(chr((code >> (8 * i)) & 255) for i in range(4))
    values["fourcc"] = chars if all(32 <= ord(c) <= 126 for c in chars) else None
    return values


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
    properties = capture_properties(cap)
    return {"width": width, "height": height, "backend": backend, "reported_fps": properties["fps"],
            "properties": properties}


def describe_capture(info, choice):
    """生成中文请求/属性/真实帧报告；不改输入，不将驱动 FPS 当成实测 FPS。"""
    props = info["properties"]
    return (f'请求采集：{choice.get("size") or "设备默认尺寸"}，'
            f'FOURCC {choice.get("requested_fourcc") or "不设置"}，FPS {choice.get("requested_fps") or "不设置"}；'
            f'属性读回：{props["width"]}×{props["height"]}，FOURCC {props["fourcc"] or "未知"}，FPS {props["fps"]}；'
            f'真实帧：{info["width"]}×{info["height"]}，后端 {info["backend"]}。'
            '属性读回不证明原生格式/FPS 已生效，纯采集实测请运行 scripts/probe_camera.py。')


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
