"""单元测试入口：固定 UTF-8 输出，阻止遗漏 Mock 时访问真实摄像头。"""

import sys

import cv2


def forbid_real_camera(*args, **kwargs):
    """真实设备构造器的测试哨兵；必须在调用位置显式替换为模拟设备。"""
    raise AssertionError("自动化测试禁止真实摄像头访问：请 Mock VideoCapture 或 open_camera。")


# discover -s tests 也会通过 tests.* 辅助模块导入此入口。
# 只影响测试进程，不修改生产代码，也不继承到普通检测子进程。
cv2.VideoCapture = forbid_real_camera
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="strict")
