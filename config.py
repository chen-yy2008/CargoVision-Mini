"""集中管理 HSV 阈值和界面默认值；坐标、面积均为像素单位。"""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "outputs"
DEFAULT_MIN_AREA = 300
MAX_MIN_AREA = 100_000
MORPH_KERNEL_SIZE = 3

# OpenCV 的 H 范围为 0~179，S/V 范围为 0~255。
# 红色跨越色相两端，必须将两段 Mask 合并。
HSV_RANGES = {
    "red": (((0, 100, 70), (10, 255, 255)), ((170, 100, 70), (179, 255, 255))),
    "green": (((35, 80, 70), (85, 255, 255)),),
    "blue": (((95, 100, 70), (130, 255, 255)),),
}
DRAW_COLORS = {"red": (0, 0, 255), "green": (0, 255, 0), "blue": (255, 0, 0)}
PREVIEW_MODES = ("original", "red", "green", "blue")
WINDOW_NAME = "CargoVision Mini"
