"""独立验证点误差：不要把四个拟合角点的残差当作实际毫米测量精度。"""

import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibration import finite_array, load_calibration

FIELDS = ("true_x_mm", "true_y_mm", "predicted_x_mm", "predicted_y_mm")


def evaluate_measurements(measurements, plane=None):
    """输入至少三个不同独立位置的真值/预测值字典，输出逐点误差和 mm 统计。

    dx=预测X−尺量X，dy 同理；距离=sqrt(dx²+dy²)，RMSE=sqrt(mean(dx²+dy²))。
    若提供 plane，还会拒绝四个拟合角点和区域外真值；空/重复/非有限值拒绝。
    断点看 differences、distances，核对单位确为 mm，不是 pixel。
    """
    if len(measurements) < 3:
        raise ValueError("至少提供三个不同位置的独立验证点，不能只验证拟合角点。")
    values = []
    for row in measurements:
        if not isinstance(row, dict) or any(field not in row for field in FIELDS):
            raise ValueError(f"验证记录必须包含字段：{', '.join(FIELDS)}。")
        values.append(finite_array([row[field] for field in FIELDS], (4,), "验证点毫米值"))
    array = np.array(values)
    true_points = array[:, :2]
    if len(np.unique(true_points, axis=0)) != len(true_points):
        raise ValueError("验证点真实位置重复，请使用至少三个不同的独立位置。")
    if plane:
        width, height = plane["width_mm"], plane["height_mm"]
        corners = np.array([[0, 0], [width, 0], [width, height], [0, height]])
        for point in true_points:
            if (np.linalg.norm(corners - point, axis=1) < 1e-6).any():
                raise ValueError("验证记录包含用于拟合 H 的角点，请改用独立验证位置。")
            if not 0 <= point[0] <= width or not 0 <= point[1] <= height:
                raise ValueError("验证点超出已标定矩形，不能宣称区域外精度。")
    differences = array[:, 2:] - true_points
    distances = np.linalg.norm(differences, axis=1)
    if not np.isfinite(distances).all():
        raise ValueError("误差数值溢出，请检查输入单位和数值。")
    points = []
    for row, values_row, difference, distance in zip(measurements, array, differences, distances):
        points.append({"point_id": str(row.get("point_id", len(points) + 1)),
                       **dict(zip(FIELDS, values_row.tolist())),
                       "dx_mm": float(difference[0]), "dy_mm": float(difference[1]), "error_mm": float(distance)})
    return {"unit": "mm", "count": len(points), "points": points,
            "summary": {"mean_dx_mm": float(differences[:, 0].mean()), "mean_dy_mm": float(differences[:, 1].mean()),
                        "mean_error_mm": float(distances.mean()), "max_error_mm": float(distances.max()),
                        "rmse_mm": float(np.sqrt(np.mean(distances ** 2)))}}


def read_measurements(path):
    """读取可编辑 CSV（UTF-8/BOM）或 JSON 数组；返回数值字典列表，损坏数据明确报错。"""
    path = Path(path)
    if path.suffix.lower() == ".json":
        try:
            rows = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("验证 JSON 无法解析。") from exc
        if not isinstance(rows, list):
            raise ValueError("验证 JSON 须为记录数组。")
        return rows
    if path.suffix.lower() != ".csv":
        raise ValueError("验证点文件仅支持 .csv / .json。")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    converted = []
    for row in rows:
        try:
            converted.append({"point_id": row.get("point_id", ""), **{field: float(row[field]) for field in FIELDS}})
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("CSV 缺少指定字段或包含非数值内容。") from exc
    return converted


def main(argv=None):
    """误差统计 CLI；读取独立测量，打印或独占写入报告，失败返回 1，不覆盖旧报告。"""
    parser = argparse.ArgumentParser(description="独立验证点误差统计（毫米）")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, help="建议指定，排除拟合角点及 ROI 外真值")
    parser.add_argument("--output", type=Path, help="可选保存 JSON；默认打印，不覆盖已有文件")
    args = parser.parse_args(argv)
    try:
        plane = load_calibration(args.calibration) if args.calibration else None
        result = evaluate_measurements(read_measurements(args.input), plane)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(payload + "\n")
        print(payload)
        print("仅统计你提供的独立测量；合成样例或拟合残差不代表真实相机毫米精度。")
        return 0
    except (OSError, ValueError) as exc:
        print(f"误差统计失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
