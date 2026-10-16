"""兼容 Windows 中文路径的图片读写，以及同一帧结果导出。"""

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from config import OUTPUT_DIR
from calibration import calibration_metadata


def read_image(path: Path) -> np.ndarray:
    """用字节解码避免部分 Windows OpenCV 版本无法读取中文路径。"""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在或不是文件：{path}")
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if frame is None:
        raise ValueError(f"图片无法解码，请检查文件内容或格式：{path}")
    return frame


def build_result(frame: np.ndarray, objects: list[dict], source: str,
                 timestamp: str | None = None, plane=None, intrinsics=None) -> dict:
    """组装 0.2 JSON，保留既有像素字段；仅检测合法时对象中才有 center_mm。

    frame、objects 与标注图必须属于同一 raw/undistorted 空间；timestamp 为帧获取时间。
    """
    height, width = frame.shape[:2]
    return {
        "schema_version": "0.2",
        "coordinate_system": "image_pixel",
        "workplane_coordinate_system": "workplane_mm",
        "pixel_frame": "undistorted" if intrinsics else "raw",
        "calibration": calibration_metadata(plane, intrinsics),
        "image_size": {"width": width, "height": height},
        "source": source,
        "timestamp": timestamp or datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "objects": objects,
    }


def save_results(annotated: np.ndarray, result: dict,
                 output_dir: Path = OUTPUT_DIR) -> tuple[Path, Path]:
    """以相同文件名主干保存 PNG/JSON；独占创建，失败时清理本次半成品。"""
    height, width = annotated.shape[:2]
    if result["image_size"] != {"width": width, "height": height}:
        raise ValueError("导出图片尺寸与检测结果不一致。")
    ok, encoded = cv2.imencode(".png", annotated)
    if not ok:
        raise OSError("标注图片编码失败。")
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8]
    image_path, json_path = output_dir / f"{stem}.png", output_dir / f"{stem}.json"
    created = []
    try:
        for path, content in ((image_path, encoded.tobytes()),
                              (json_path, payload.encode("utf-8"))):
            with path.open("xb") as stream:
                created.append(path)
                stream.write(content)
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return image_path, json_path
