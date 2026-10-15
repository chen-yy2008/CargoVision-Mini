"""生成固定 640x480 样图：红色两个、绿色一个、蓝色一个，另有小噪点。"""

from pathlib import Path
import sys

import cv2
import numpy as np

# 允许直接执行 python scripts/make_demo.py。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import PROJECT_DIR


def make_demo() -> np.ndarray:
    frame = np.full((480, 640, 3), 35, dtype=np.uint8)
    cv2.rectangle(frame, (60, 80), (160, 180), (0, 0, 255), -1)
    # 使用 H=175 的红色，确保第二个红色区间也参与检测。
    high_red = cv2.cvtColor(np.uint8([[[175, 255, 255]]]), cv2.COLOR_HSV2BGR)[0, 0]
    cv2.rectangle(frame, (240, 80), (340, 180), tuple(int(v) for v in high_red), -1)
    cv2.rectangle(frame, (420, 80), (540, 200), (0, 255, 0), -1)
    cv2.circle(frame, (180, 340), 50, (255, 0, 0), -1)
    for x, color in ((450, (0, 0, 255)), (480, (0, 255, 0)), (510, (255, 0, 0))):
        cv2.rectangle(frame, (x, 350), (x + 4, 354), color, -1)
    return frame


def main():
    path = PROJECT_DIR / "samples" / "demo.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"样图已存在，为避免覆盖未写入：{path}。如需重建，请先手动移走该文件。")
    ok, encoded = cv2.imencode(".png", make_demo())
    if not ok:
        raise SystemExit("样图编码失败。")
    with path.open("xb") as stream:
        stream.write(encoded.tobytes())
    print(f"已生成：{path}")


if __name__ == "__main__":
    main()
