"""启动器的普通字典配置与命令组装；不修改检测、标定数学或导出 schema。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile

from calibration import check_frame_context, load_calibration
from camera_utils import load_camera_preference, validate_capture_format
from config import DEFAULT_MIN_AREA, MAX_MIN_AREA, PROJECT_DIR, CAMERA_PREFERENCE_PATH

SETTINGS_PATH = PROJECT_DIR / "local_settings" / "launcher.json"
DEFAULTS = {"version": 1, "camera_index": None, "backend": "auto", "width": 640, "height": 480,
            "fourcc": "auto", "fps": None, "min_area": DEFAULT_MIN_AREA,
            "width_mm": 210.0, "height_mm": 297.0, "calibration_path": "", "intrinsics_path": ""}


def validate_settings(data):
    """验证本机启动参数并返回副本；pixel、px²、mm 分开，不接受 NaN 或布尔整数。

    None 摄像头表示尚未选择；路径合法性在启动/保存时另用 calibration_state 检查。
    格式错误抛中文 ValueError，不默默替换损坏配置。
    """
    if not isinstance(data, dict) or set(data) != set(DEFAULTS) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("启动器配置结构或版本不正确，请在界面重新设置。")
    index = data["camera_index"]
    if index is not None and (type(index) is not int or index < 0):
        raise ValueError("摄像头编号必须是非负整数。")
    if data["backend"] not in ("auto", "dshow", "msmf") or data["fourcc"] not in ("auto", "mjpg", "yuy2"):
        raise ValueError("摄像头后端或采集格式无效。")
    validate_capture_format(None if data["fourcc"] == "auto" else data["fourcc"].upper(), data["fps"])
    for field, label in (("width", "采集宽度"), ("height", "采集高度")):
        if type(data[field]) is not int or not 2 <= data[field] <= 16384:
            raise ValueError(f"{label}必须是 2~16384 pixel 的整数。")
    if type(data["min_area"]) is not int or not 1 <= data["min_area"] <= MAX_MIN_AREA:
        raise ValueError(f"最小检测面积必须是 1~{MAX_MIN_AREA} px² 的整数。")
    for field, label in (("width_mm", "工作平面实测宽度"), ("height_mm", "工作平面实测高度")):
        value = data[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label}必须是正的有限数值，单位 mm。")
    if any(not isinstance(data[field], str) for field in ("calibration_path", "intrinsics_path")):
        raise ValueError("标定文件路径必须为文本。")
    return deepcopy(data)


def initial_settings(settings_path=SETTINGS_PATH, camera_path=CAMERA_PREFERENCE_PATH):
    """恢复启动器设置与上次实际相机信息，返回 (设置, 实际偏好, 错误列表)。

    首次只继承成功设备的编号/后端，采集请求保持 640×480，不自动继承较高模式。
    如果 CLI 后来选了另一设备，以成功偏好中的设备为准并回到 640×480。
    错误要由界面明确展示；不会把损坏配置当成可直接运行的设置。
    """
    settings, preference, errors = deepcopy(DEFAULTS), None, []
    if Path(settings_path).exists():
        try:
            settings = validate_settings(json.loads(Path(settings_path).read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"启动器本机配置无法读取：{exc}。原文件保留，请通过参数设置重新保存。")
    try:
        preference = load_camera_preference(camera_path)
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    if preference:
        backend = preference["backend"].lower() if preference["backend"] in ("DSHOW", "MSMF") else "auto"
        if settings["camera_index"] != preference["camera_index"]:
            settings.update(camera_index=preference["camera_index"], backend=backend, width=640, height=480,
                            fourcc="auto", fps=None)
            if preference["capture_size"] == {"width": 640, "height": 480}:
                settings.update(fourcc=(preference.get("requested_fourcc") or "auto").lower(),
                                fps=preference.get("requested_fps"))
        elif settings["backend"] == "auto":
            settings["backend"] = backend
    return settings, preference, errors


def save_settings(path, settings):
    """验证后原子写本机配置；失败保留原文件，不保存现场确认勾选状态。"""
    data = validate_settings(settings)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def camera_key(settings):
    """本次采集请求的会话键；只是参数组合，不是物理相机身份。"""
    return tuple(settings[key] for key in ("camera_index", "backend", "width", "height", "fourcc", "fps"))


def resolve_path(value, project=PROJECT_DIR):
    """相对标定路径按项目目录解析；保留带空格/中文路径，不交给 shell 解释。"""
    path = Path(value)
    return path if path.is_absolute() else Path(project) / path


def calibration_state(settings, project=PROJECT_DIR):
    """返回文件检查状态与现场确认指纹；不宣称能判断相机是否移动。

    文件、尺寸、raw/去畸变关联复用 V0.2 校验；文件内容或采集参数变化后指纹变化，
    旧勾选随之失效。实际帧尺寸仍由原程序再次检查，绝不缩放 H。
    """
    settings = validate_settings(settings)
    plane, intrinsics, fingerprints = None, None, []
    for field, kind in (("calibration_path", "workplane"), ("intrinsics_path", "camera_intrinsics")):
        if settings[field]:
            path = resolve_path(settings[field], project)
            before = path.read_bytes()
            data = load_calibration(path, kind)
            after = path.read_bytes()
            if before != after:
                raise ValueError("标定文件在检查期间被修改，请重新选择并确认。")
            fingerprints.append((str(path.resolve()), hashlib.sha256(after).hexdigest()))
            if kind == "workplane":
                plane = data
            else:
                intrinsics = data
    check_frame_context(plane, {"width": settings["width"], "height": settings["height"]}, intrinsics)
    if plane:
        message = (f'文件合法，待现场确认：{plane["image_size"]["width"]}×{plane["image_size"]["height"]} pixel，'
                   f'平面 {plane["width_mm"]:g}×{plane["height_mm"]:g} mm；{plane["pixel_frame"]}')
    else:
        message = "未加载平面标定：仅输出像素坐标" + ("（已选择内参去畸变）" if intrinsics else "")
    return {"plane": plane, "intrinsics": intrinsics, "message": message,
            "signature": (camera_key(settings), tuple(fingerprints))}


def build_command(settings, action, python, project=PROJECT_DIR, output=None, confirmed=None):
    """合法参数 → subprocess 的 argv 列表；拒绝未确认/失配的毫米标定。

    action=detect/plane；新标定的 width_mm/height_mm 是实物 mm，不是采集 pixel。
    confirmed 只存在当前 GUI 会话中，不能从本机配置恢复为自动信任。
    """
    settings = validate_settings(settings)
    if settings["camera_index"] is None:
        raise ValueError("请先选择摄像头，并预览确认画面。")
    if action not in ("detect", "plane"):
        raise ValueError("未知启动操作。")
    if action == "detect":
        state = calibration_state(settings, project)
        if (state["plane"] or state["intrinsics"]) and confirmed != state["signature"]:
            raise ValueError("请先确认相机、镜头、采集条件及工作平面与所选标定一致。")
    elif settings["intrinsics_path"]:
        intrinsics = load_calibration(resolve_path(settings["intrinsics_path"], project), "camera_intrinsics")
        check_frame_context(None, {"width": settings["width"], "height": settings["height"]}, intrinsics)
    command = [str(python), str(Path(project) / ("main.py" if action == "detect" else "calibrate_plane.py")),
               "--camera", str(settings["camera_index"]), "--backend", settings["backend"],
               "--width", str(settings["width"]), "--height", str(settings["height"]), "--fourcc", settings["fourcc"]]
    if settings["fps"] is not None:
        command += ["--fps", str(settings["fps"])]
    if settings["intrinsics_path"]:
        command += ["--intrinsics", str(resolve_path(settings["intrinsics_path"], project))]
    if action == "detect":
        command += ["--min-area", str(settings["min_area"])]
        if settings["calibration_path"]:
            command += ["--calibration", str(resolve_path(settings["calibration_path"], project))]
    else:
        if output is None:
            raise ValueError("请选择新标定文件的保存位置。")
        command += ["--width-mm", str(settings["width_mm"]), "--height-mm", str(settings["height_mm"]), "--output", str(output)]
    return command
