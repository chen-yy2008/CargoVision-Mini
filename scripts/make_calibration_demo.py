"""为 samples/demo.png 生成明确标为 synthetic 的平面配置，不是实际设备标定。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration import create_plane_calibration, save_calibration
from config import PROJECT_DIR


def make_demo_calibration():
    """固定 640×480 合成画面，ROI 内每像素约 0.5 mm；仅供离线演示/测试。"""
    data = create_plane_calibration([[20, 50], [600, 50], [600, 440], [20, 440]],
                                    290, 195, {"width": 640, "height": 480}, "synthetic:samples/demo.png")
    data.update(id="synthetic-demo-plane", created_at="2026-10-16T00:00:00+08:00", synthetic=True)
    return data


if __name__ == "__main__":
    path = PROJECT_DIR / "samples" / "workplane_demo.json"
    save_calibration(path, make_demo_calibration())
    print(f"已生成合成平面配置（不是真实标定）：{path}")
